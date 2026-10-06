; Static img2spec cards occupy the existing eight-second music lead-in.
intro_clear:
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
    ret

intro_credits:
    ld hl,intro_credits_data
    jr intro_card
intro_specs:
    ld hl,intro_specifications_data
intro_card:
    push hl
    call intro_clear
    pop hl
    ld de,$4000
; Nonzero bytes are literals; zero/count clears a run; zero/zero ends.
intro_unpack:
    ld a,(hl)
    inc hl
    or a
    jr z,intro_zero_run
    ld (de),a
    inc de
    jr intro_unpack
intro_zero_run:
    ld b,(hl)
    inc hl
    ld a,b
    or a
    jr z,intro_accent
    xor a
intro_zero_byte:
    ld (de),a
    inc de
    djnz intro_zero_byte
    jr intro_unpack
intro_accent:
    ; One muted red rule, aligned to complete attribute cells.
    ld hl,$59ce
    ld b,4
intro_accent_cell:
    ld (hl),$02
    inc hl
    djnz intro_accent_cell
    ret
include "intro_data.inc"
