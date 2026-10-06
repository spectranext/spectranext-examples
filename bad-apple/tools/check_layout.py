"""Reject an application that would overwrite the player's IM2 region."""

from pathlib import Path
import re
import sys

binary, map_file = map(Path, sys.argv[1:])
symbols = {name: int(value, 16) for name, value in
           re.findall(r"^(\w+)\s+= \$([0-9A-Fa-f]+)", map_file.read_text(), re.MULTILINE)}
origin = symbols["__head"]
end = max(origin + binary.stat().st_size, symbols["__BSS_END_tail"])
if origin != 0x6000 or end > 0xC000:
    raise SystemExit(f"Application overlaps reserved memory: ${origin:04X}-${end:04X}")
print(f"Application RAM: ${origin:04X}-${end - 1:04X}; IM2 starts at $C000")
