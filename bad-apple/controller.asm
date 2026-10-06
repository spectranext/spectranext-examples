; Raw Spectranext controller operations. Included by player.asm.
; Page B maps controller page $48 at $2000.
;
; Channel 0 retains the SDK workspace at $2800 and registers $2FFE/$2FFF.
; Channel 1 supports every command using the same payload layout at $2C00:
;   $2C00 input filename, $2C80 output filename, $2D00 operation string.
; Set $2FFD to $FF, then write command 6 (ENGINECALL) to $2FFC.
; $2FFD remains $FF until the result at $2E00 is ready: 0 success, 1 error.
; Channel 0 can continue XFS_READ requests while channel 1 is running.

; A is a one-based chunk number. HL is table base. Return HL=string pointer.
lookup_path:
    dec a
    add a,a
    ld e,a
    ld d,0
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ex de,hl
    ret

; Copy NUL-terminated string from HL to DE.
copy_z:
    ld a,(hl)
    ld (de),a
    inc hl
    inc de
    or a
    jr nz,copy_z
    ret

; Submit one asynchronous cp enginecall. A = source chunk (one-based).
queue_copy:
    ld (copy_index),a
    ld hl,remote_paths
    ld a,(copy_index)
    call lookup_path
    ld a,(source_mount)
    add a,'0'
    ld ($2c00),a
    ld a,':'
    ld ($2c01),a
    ld de,$2c02
    call copy_z
    ld a,(copy_index)
    ld hl,local_paths
    call lookup_path
    ld de,$2c80
    call copy_z
    ld hl,copy_operation
    ld de,$2d00
    call copy_z
    ld a,$ff
    ld ($2ffd),a
    ld a,ENGINECALL_CMD
    ld ($2ffc),a
    ld a,1
    ld (copy_pending),a
    ret

; Read nine complete frames to eight consecutive controller RAM pages.
; The 32-bit file offset advances only when a bank is queued.
queue_read:
    ld a,(chunk_index)
    cp 1
    jr nz,queue_read_path
    ld a,(wrap_active)
    or a
    jr z,queue_read_first
    ld a,CHUNK_COUNT+1
    jr queue_read_path
queue_read_first:
    ld a,1
queue_read_path:
    ld hl,read_paths
    call lookup_path
    ld de,$2800
    call copy_z
    ld hl,(source_offset)
    ld ($2880),hl
    ld bc,BANK_BYTES
    add hl,bc
    ld (source_offset),hl
    ld hl,(source_offset+2)
    ld ($2882),hl
    ld bc,0
    adc hl,bc
    ld (source_offset+2),hl
    ld a,(read_page)
    ld ($2884),a
    xor a
    ld ($2885),a
    ld ($2886),a
    ld ($2889),a
    ld ($288a),a
    ld hl,BANK_BYTES
    ld ($2887),hl
    ld a,1
    ld (pending_type),a
    ld a,$ff
    ld ($2fff),a
    ld a,READ_CMD
    ld ($2ffe),a
    ret

wait_pending:
    ld a,(pending_type)
    or a
    ret z
    call wait_command
    ld hl,($288b)
    ld de,BANK_BYTES
    or a
    sbc hl,de
    jp nz,read_error
    ld hl,($288d)
    ld a,h
    or l
    jp nz,read_error
    xor a
    ld (pending_type),a
    ret

wait_command:
    ld a,($2fff)
    cp $ff
    jr z,wait_command
    or a
    jp nz,read_error
    ret

wait_copy:
    ld a,(copy_pending)
    or a
    ret z
copy_wait:
    ld a,($2ffd)
    cp $ff
    jr z,copy_stall
    or a
    jr z,copy_complete
    ; A transient HTTP or RAMFS failure leaves a partial cache file. Reuse
    ; queue_copy so cp removes that file and starts the same transfer again.
    ld a,(replay_wait)
    or a
    jr z,copy_retry_halts
    ld b,3
copy_retry_replay:
    push bc
    call replay_bank
    pop bc
    djnz copy_retry_replay
    jr copy_retry_done
copy_retry_halts:
    ld b,50
copy_retry_delay:
    ei
    halt
    djnz copy_retry_delay
copy_retry_done:
    ld a,(copy_index)
    call queue_copy
    jr copy_wait
copy_stall:
    ld a,(replay_wait)
    or a
    jr z,copy_stall_blank
    call replay_bank
    jr copy_wait
copy_stall_blank:
    ei
    halt
    jr copy_wait
copy_complete:
    xor a
    ld (copy_pending),a
    ret

wait_copy_with_replay:
    ld a,1
    ld (replay_wait),a
    call wait_copy
    xor a
    ld (replay_wait),a
    ret

; Download the opening chunk to a third cache during the penultimate chunk.
; The short final chunk cannot hide a full download at the loop boundary.
maybe_wrap_prefetch:
    ld a,(chunk_index)
    cp CHUNK_COUNT-1
    ret nz
    ld a,(wrap_queued)
    or a
    ret nz
    ld a,($2ffd)
    or a
    ret nz
    xor a
    ld (copy_pending),a
    ld a,CHUNK_COUNT+1
    call queue_copy
    ld a,1
    ld (wrap_queued),a
    ret

; Discard cache files through the engine's internal RAM mount. The current
; Spectranet VFS mount may be HTTP, so its XFS unlink command is unsuitable.
cleanup_old_file:
    ld a,(chunk_index)
    cp CHUNK_COUNT
    jr nz,cleanup_wrap_file
    ld hl,old_slot_path
    jr unlink_local
cleanup_wrap_file:
    cp 2
    ret nz
    ld a,(wrap_active)
    or a
    ret z
    ld hl,wrap_slot_path
    call unlink_local
    xor a
    ld (wrap_active),a
    ret

unlink_local:
    ld de,$2800
    call copy_z
    xor a
    ld ($2880),a
    ld hl,remove_operation
    ld de,$2900
    call copy_z
    ld a,$ff
    ld ($2fff),a
    ld a,ENGINECALL_CMD
    ld ($2ffe),a
    call wait_command
    ret
