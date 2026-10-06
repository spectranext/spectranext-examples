#!/usr/bin/env python3
"""Convert source artwork and GIF to movie chunks and assembler includes."""

import argparse
from pathlib import Path
import subprocess

from PIL import Image

FRAME_BYTES = 3456
FRAMES_PER_BANK = 9
BANK_BYTES = FRAME_BYTES * FRAMES_PER_BANK
BANKS_PER_CHUNK = (1024 * 1024) // BANK_BYTES


def spectrum_offset(y):
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)


def build_intro(assets, output, converter):
    # Static artwork is dithered by our headless img2spec adaptation, then
    # encoded as zero runs in Spectrum bitmap order. No runtime font needed.
    lines = []
    for name in ("credits", "specifications"):
        source = Image.open(assets / f"{name}.png").convert("L")
        pixels = subprocess.run([str(converter), "256", "192"], input=source.tobytes(),
                                stdout=subprocess.PIPE, check=True).stdout
        bitmap = bytearray(6144)
        for y in range(192):
            for x in range(256):
                if pixels[y * 256 + x]:
                    bitmap[spectrum_offset(y) + x // 8] |= 128 >> (x & 7)
        packed = bytearray()
        i = 0
        while i < len(bitmap):
            if bitmap[i]:
                packed.append(bitmap[i])
                i += 1
            else:
                end = i + 1
                while end < len(bitmap) and not bitmap[end] and end - i < 255:
                    end += 1
                packed.extend((0, end - i))
                i = end
        packed.extend((0, 0))
        (output / f"intro_{name}.bin").write_bytes(packed)
        lines.append(f'intro_{name}_data: binary "{output / f"intro_{name}.bin"}"')
        print(f"intro {name}: {len(packed)} bytes")
    (output / "intro_data.inc").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    args = parser.parse_args()
    assets = args.assets.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    gif = Image.open(assets / "bad-apple.gif")
    if gif.size != (192, 144):
        parser.error("movie must be 192x144")
    frame_count = gif.n_frames
    # Remove stale chunks when the input movie becomes shorter.
    for old in output.glob("badapple*.bin"):
        old.unlink()

    chunk_banks = []
    first = []
    current = None
    for index in range(frame_count):
        bank = index // FRAMES_PER_BANK
        chunk = bank // BANKS_PER_CHUNK + 1
        if len(chunk_banks) < chunk:
            if current:
                current.close()
            current = (output / f"badapple{chunk}.bin").open("wb")
            chunk_banks.append(0)
        gif.seek(index)
        if gif.info.get("duration") != 40:
            raise ValueError(f"frame {index} must last 40 ms (25 fps)")
        frame = gif.convert("1", dither=Image.Dither.NONE).tobytes()
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"frame {index} has {len(frame)} bytes")
        current.write(frame)
        if index < FRAMES_PER_BANK:
            first.append(frame)
        if index % FRAMES_PER_BANK == FRAMES_PER_BANK - 1:
            chunk_banks[-1] += 1
    padding = (-frame_count) % FRAMES_PER_BANK
    for index in range(padding):
        current.write(first[index])
    if padding:
        chunk_banks[-1] += 1
    current.close()

    if len(chunk_banks) > 255 or any(b < 2 for b in chunk_banks):
        raise ValueError("each chunk needs two 32 KB banks")
    lines = [
        f"CHUNK_COUNT equ {len(chunk_banks)}",
        f"BANK_BYTES equ {BANK_BYTES}",
        "chunk_bank_counts:",
        "    defb " + ",".join(map(str, chunk_banks)),
        "remote_paths:",
        *[f"    defw remote_{i}" for i in range(1, len(chunk_banks) + 1)],
        "    defw remote_wrap",
        "local_paths:",
        *[f"    defw local_{i}" for i in range(1, len(chunk_banks) + 1)],
        "    defw local_wrap",
        "read_paths:",
        *[f"    defw read_{i}" for i in range(1, len(chunk_banks) + 1)],
        "    defw read_wrap",
    ]
    suffix = "bin"
    for i in range(1, len(chunk_banks) + 1):
        local_slot = (i - 1) % 2 + 1
        lines += [
            f'remote_{i}: defm "badapple{i}.{suffix}"',
            "    defb 0",
            f'local_{i}: defm "ba-cache{local_slot}.bin"',
            "    defb 0",
            f'read_{i}: defm "/ba-cache{local_slot}.bin"',
            "    defb 0",
        ]
    lines += [
        f'old_slot_path: defm "/ba-cache{(len(chunk_banks) - 2) % 2 + 1}.bin"',
        "    defb 0",
        f'remote_wrap: defm "badapple1.{suffix}"',
        "    defb 0",
        'local_wrap: defm "ba-cache3.bin"',
        "    defb 0",
        'read_wrap: defm "/ba-cache3.bin"',
        "    defb 0",
    ]
    build_intro(assets, output, args.converter.resolve())
    (output / "connection.inc").write_text(
        'REFRESH_HZ equ 50\ncopy_operation: defm "cp"\n    defb 0\n')
    (output / "media.inc").write_text("\n".join(lines) + "\n")
    (output / "copy_row.inc").write_text("    ldi\n" * 24)
    (output / "copy16.inc").write_text("    ldi\n" * 16)
    (output / "copy8.inc").write_text("    ldi\n" * 8)
    (output / "row_addresses.inc").write_text(
        "\n".join(f"    defw ${0x4000 + spectrum_offset(y + 24) + 4:04x}"
                  for y in range(144)) + "\n")
    (output / "music_data.inc").write_text(f'binary "{assets / "music.pt3"}"\n')
    (output / "media.stamp").write_text(f"{frame_count} frames, {padding} padding frames, {len(chunk_banks)} chunks\n")
    print(f"{frame_count} frames + {padding} wrap frames; "
          f"{len(chunk_banks)} chunks, bank counts: {chunk_banks}")


if __name__ == "__main__":
    main()
