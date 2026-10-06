; 48K Bad Apple player. HTTP chunk copies and XFS reads use raw controller
; requests, so the Z80 can display one 32 KB bank while a request is active.
SECTION code_user
PUBLIC _badapple_play
PUBLIC chunk_index, source_mount, music_ticks, frames_left
PUBLIC banks_played, replay_wait

PAGEIN       equ $3ff9
SETPAGEA     equ $3e33
SETPAGEB     equ $3e36
READ_CMD     equ 8
ENGINECALL_CMD equ 6

_badapple_play:
    ; __z88dk_fastcall: main.c passes the selected source slot in HL.
    ld a,l
    ld (source_mount),a
    call PAGEIN
    di
    xor a
    out ($fe),a
    ld hl,$4000
    ld de,$4001
    ld bc,6143
    ld (hl),0
    ldir
    ld hl,$5800
    ld de,$5801
    ld bc,767
    ld (hl),$47
    ldir

    ld a,$48
    call SETPAGEB
    ; Keep IM2 above the application and embedded PT3 module.
    ld hl,$c000
    ld de,$c001
    ld bc,256
    ld (hl),$c2
    ldir
    ld hl,im2_handler
    ld de,$c2c2
    ld bc,3
    ldir
    ld a,$c0
    ld i,a
    im 2
    ld a,1
    ld (chunk_index),a

    ; main.c has already copied chunk 1 through the synchronous SDK API.
start_chunk:
    xor a
    ld (source_offset),a
    ld (source_offset+1),a
    ld (source_offset+2),a
    ld (source_offset+3),a
    ld (banks_played),a
    ld a,2
    ld (banks_loaded),a
    ld a,(chunk_index)
    ld hl,chunk_bank_counts-1
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    ld (banks_total),a

    ld a,$d0
    ld (read_page),a
    call queue_read
    call wait_pending
    ld a,$d8
    ld (read_page),a
    call queue_read
    call wait_pending
    call cleanup_old_file
    ld a,$d0
    ld (display_bank),a

    ; Prefetch the next HTTP chunk while XFS_READ keeps the page banks full.
    ld a,(chunk_index)
    inc a
    cp CHUNK_COUNT+1
    jr z,start_music_if_first_chunk
    call queue_copy

start_music_if_first_chunk:
    ld a,(chunk_index)
    cp 1
    jr nz,play_bank
    ; Show the title cards during the eight-second music lead-in,
    ; including when the movie loops.
    ld hl,$4000
    ld de,$4001
    ld bc,6143
    ld (hl),0
    ldir
    ld hl,music_module
    call VT_START+3
    call music_lead

play_bank:
    ld a,(display_bank)
    ld (display_page),a
    call SETPAGEA
    ld hl,$1000
    ld (source_ptr),hl
    ld a,9
    ld (frames_left),a

play_frame:
    call draw_frame
    ld a,(frames_left)
    dec a
    ld (frames_left),a
    jp nz,play_frame

    ld a,(banks_played)
    inc a
    ld (banks_played),a
    ld b,a
    ld a,(banks_total)
    cp b
    jp z,chunk_done

    ; The consumed bank is available for the next read. The background copy
    ; writes XFS RAM concurrently and never occupies the controller command.
    call wait_pending
    call maybe_wrap_prefetch
    ld a,(banks_loaded)
    ld b,a
    ld a,(banks_total)
    cp b
    jr z,switch_bank
    ld a,(display_bank)
    ld (read_page),a
    call queue_read
    ld a,(banks_loaded)
    inc a
    ld (banks_loaded),a
switch_bank:
    ld a,(display_bank)
    xor 8
    ld (display_bank),a
    jp play_bank

; Draw one frame and tick the tune twice. The boundary wait can reuse this
; without advancing the movie's bank or chunk counters.
draw_frame:
    di
    ld a,(display_page)
    call SETPAGEA
    ld hl,(source_ptr)
    ld ix,row_addresses
    ld a,144
copy_row:
    push af
    ld e,(ix+0)
    ld d,(ix+1)
    ; 4096 mod 24 cycles through 16, 8, and 0 bytes. Handle both split
    ; rows and the case where the boundary falls exactly between rows.
    ld a,h
    cp $20
    jr z,page_at_row
    cp $1f
    jr nz,whole_row
    ld a,l
    cp $f0
    jr z,split_16
    cp $f8
    jr z,split_8
    jr whole_row
page_at_row:
    call next_page
    jr whole_row
split_16:
include "copy16.inc"
    call next_page
include "copy8.inc"
    jr row_done
split_8:
include "copy8.inc"
    call next_page
include "copy16.inc"
    jr row_done
whole_row:
include "copy_row.inc"
row_done:
    inc ix
    inc ix
    pop af
    dec a
    jp nz,copy_row
    ld (source_ptr),hl
    call music_tick
    call pace_wait
    call music_tick
    ret

; The final nine frames remain in display_bank at a chunk boundary. Repeat
; them while HTTP catches up, without changing movie position.
replay_bank:
    ld a,(display_bank)
    ld (display_page),a
    call SETPAGEA
    ld hl,$1000
    ld (source_ptr),hl
    ld a,9
    ld (frames_left),a
replay_frame:
    call draw_frame
    ld a,(frames_left)
    dec a
    ld (frames_left),a
    jr nz,replay_frame
    ret

next_page:
    ld a,(display_page)
    inc a
    ld (display_page),a
    call SETPAGEA
    ld hl,$1000
    ret

chunk_done:
    call wait_pending
    ; The penultimate chunk normally starts this while playing. If the short successor took
    ; unexpectedly long to download, complete both copies before proceeding.
    ld a,(chunk_index)
    cp CHUNK_COUNT-1
    jr nz,chunk_done_copy
    call maybe_wrap_prefetch
    ld a,(wrap_queued)
    or a
    jr nz,chunk_done_copy
    call wait_copy_with_replay
    ld a,CHUNK_COUNT+1
    call queue_copy
    ld a,1
    ld (wrap_queued),a
chunk_done_copy:
    call wait_copy_with_replay
    ld a,(chunk_index)
    inc a
    cp CHUNK_COUNT+1
    jr nz,next_chunk
    ld a,1
    ld (chunk_index),a
    ld (wrap_active),a
    xor a
    ld (wrap_queued),a
    jp start_chunk
next_chunk:
    ld (chunk_index),a
    jp start_chunk

include "controller.asm"

; 60 Hz: five 25 fps frames span 12 host display periods.
pace_wait:
    ld a,(pace_phase)
    inc a
    cp 5
    jr nz,pace_store
    xor a
pace_store:
    ld (pace_phase),a
    ei
    halt
    ld a,REFRESH_HZ
    cp 50
    ret z
    ld a,(pace_phase)
    cp 2
    jr z,pace_extra
    cp 4
    ret nz
pace_extra:
    halt
    ret

; Tick the 50 Hz PT3 tune for eight seconds before drawing the first frame.
; A 60 Hz machine needs one extra display interrupt for every five music ticks.
music_lead:
    xor a
    ld (lead_phase),a
    call intro_credits
    ld bc,150
    call music_lead_wait
    call intro_clear
    ld bc,50
    call music_lead_wait
    call intro_specs
    ld bc,150
    call music_lead_wait
    call intro_clear
    ld bc,50
    jp music_lead_wait

music_lead_wait:
music_lead_tick:
    push bc
    call music_tick
    ei
    halt
    ld a,REFRESH_HZ
    cp 60
    jr nz,music_lead_next
    ld a,(lead_phase)
    inc a
    cp 5
    jr nz,music_lead_store
    xor a
music_lead_store:
    ld (lead_phase),a
    or a
    jr nz,music_lead_next
    halt
music_lead_next:
    pop bc
    dec bc
    ld a,b
    or c
    jr nz,music_lead_tick
    ret

include "intro.asm"

music_tick:
    call VT_START+5
    ld hl,(music_ticks)
    inc hl
    ld (music_ticks),hl
    ret

read_error:
    ld a,2
    out ($fe),a
error_loop:
    ei
    halt
    jr error_loop

chunk_index:   defb 1
source_mount:  defb 0
copy_index:    defb 1
pending_type:  defb 0
copy_pending:  defb 0
replay_wait:   defb 0
wrap_queued:   defb 0
wrap_active:   defb 0
banks_total:   defb 0
banks_loaded:  defb 0
banks_played:  defb 0
read_page:     defb $d0
display_bank:  defb $d0
display_page:  defb $d0
frames_left:   defb 0
pace_phase:    defb 0
lead_phase:    defb 0
music_ticks:   defw 0
source_ptr:    defw $1000
source_offset: defw 0,0
include "connection.inc"
wrap_slot_path: defm "/ba-cache3.bin"
    defb 0
remove_operation: defm "rm"
    defb 0

include "media.inc"
row_addresses:
include "row_addresses.inc"
im2_handler:
    ei
    reti

; The PT3 decoder and tune live with the player in ordinary 48K RAM.
include "music/pt3_player.asm"
music_module:
include "music_data.inc"
