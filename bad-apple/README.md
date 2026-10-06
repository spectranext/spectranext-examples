# Bad Apple streaming example

Play a 192×144 monochrome movie at 25 fps on a 48K Spectrum with Spectranext.
Requires **Spectranext 1.1 or newer**. The player reads the system version
before starting and displays an error on older or unsupported systems.
This example demonstrates copying files from the current HTTP(S) mount into
XFS RAM with the `cp` engine, then reading ahead into controller RAM while the
Z80 draws and plays an AY tune.

## What it does

1. Checks `spectranext_get_version()` and requires version 1.1 or newer.
2. Reads the current mount slot with `getmountpoint()`; it does not change volumes.
3. Copies the first movie chunk with the SDK `spectranext_enginecall()` API.
4. Shows two opening cards while the PT3 tune plays its eight-second lead-in.
5. Displays one nine-frame RAM bank while the controller fills the other.
6. Downloads the next chunk in the background, switches caches, and repeats.
7. Loops the movie and music. If a download is late, the last bank keeps
   playing with music until it is ready. Failed copies are retried.

A 48K machine needs an AY sound interface; enable **Melodik** in FuseX.
The video itself requires no 128K screen switching.

## Build

Use the Spectranext SDK environment, as for the other examples. Install
[Pillow](https://pillow.readthedocs.io/) for the Python interpreter used by
CMake and provide a host C++ compiler for the artwork converter.

```sh
cmake -S . -B build
cmake --build build
```

CMake converts `assets/bad-apple.gif` into `badapple1.bin` through
`badapple19.bin`, dithers the opening artwork, and builds the SDK application
and tokenized `boot.zx`. The complete resource is in **`build/media/`**.
All generated files stay in the build directory; building does not upload or
copy anything into a FuseX folder.

To install the resource into a chosen filesystem directory:

```sh
cmake --install build --prefix /path/to/xfs
```

The normal SDK `badapple_upload_tap` and `badapple_tap_autoboot` targets are
also available. They upload the player and boot file; the movie chunks must
be available on the mount from which the demo is launched.

## Run

Serve the generated resource locally:

```sh
python3 -m http.server 9001 --directory build/media --bind 0.0.0.0
```

On the Spectrum, mount that directory and run its boot program:

```basic
%mount "http://YOUR-HOST:9001/"
%load ""
```

Alternatively, select the resource URL in the launcher or enable autoboot
on the mounted resource. Its `boot.zx` executes `%tapein "badapple.tap"` and
`LOAD ""`. Plain `LOAD ""` alone does not execute `boot.zx`.

HTTPS works the same way. A copy must average more than **86.4 kB/s** to stay
ahead of the movie; a slower source causes bank replay at chunk boundaries.

## Enginecalls and buffering

A normal SDK program can copy a mounted source file with:

```c
#include <spectranext.h>

/* Mount slot 2 contains the source; the output is always in XFS RAM. */
int result = spectranext_enginecall("2:badapple1.bin", "ba-cache1.bin", "cp");
```

That function waits for completion. This example uses the equivalent
**second controller channel** in `controller.asm`: write the input,
output, and operation strings at `$2C00`, `$2C80`, and `$2D00`, then set
status `$2FFD` to `$FF` and submit ENGINECALL (command 6) at `$2FFC`.
Poll `$2FFD` while continuing playback: `$FF` means busy, `0` means success,
and `1` means error; the engine return code is at `$2E00`. Channel 0 retains
the existing SDK layout and uses command 8 to read cached ranges into RAM.
Both channels support every controller command. It uses the same
arguments and `cp` engine; the movie files are uncompressed.

| Storage | Contents |
|---|---|
| Current mount | Source `badappleN.bin` files |
| XFS RAM | Alternating `ba-cache1.bin` / `ba-cache2.bin`; a third cache for looping |
| Controller pages D0–D7 / D8–DF | Two alternating nine-frame banks |
| Spectrum RAM | SDK application, PT3 decoder, tune, and IM2 handler |

Each frame is 3,456 bytes: 144 rows of 24 bytes, most-significant pixel first.
Nine frames occupy 31,104 bytes. A full chunk contains 33 banks (1,026,432
bytes, below 1 MiB), so every chunk boundary is also a bank and frame boundary.
The final bank is padded with four opening frames. Cache names are different
from source names, so playback from an XFS folder preserves its movie files.

The player copies rows in visual order into the centred screen area, handling
Spectrum bitmap addressing and 4 KB source-page crossings. Two interrupts per
video frame provide the 25 fps pacing and 50 Hz PT3 ticks. Code starts at
`$6000`; `$C000–$C2C4` is reserved for IM2 and the stack starts at `$FF00`.

## Source layout

- `main.c` — version check, current mount detection, and the first `cp` enginecall.
- `player.asm` — playback, screen copying, bank switching, and music timing.
- `controller.asm` — background enginecalls, XFS reads, completion, and cache cleanup.
- `intro.asm` — opening card display.
- `music/` — attributed PT3 decoder and its licence.
- `assets/` — reference GIF, PT3 tune, and opening artwork.
- `tools/` — build-time media encoding and img2spec dither adaptation.
- `tests/playback.py` — loads the generated TAP through BASIC in libfusex.
- `tests/version.py` — checks accepted/rejected versions and prevents work on older systems.

## End-to-end verification

From the monorepo root, build the current headless emulator and run the test:

```sh
make -C aitest fuse
docker run --rm --entrypoint python3 -v "$PWD:/work" -w /work \
  spectranext/aitest-fuse:local examples/bad-apple/tests/playback.py \
  --build-dir examples/bad-apple/build --startup autoboot \
  --ticks 12500 --expect-chunk 19 \
  --check-music
```

The test serves the built resource over local HTTP, configures URL autoboot,
verifies retrieval of `boot.zx` and the SDK TAP, then checks exact movie frames,
all chunk transitions, AY register activity, and the repeated music lead-in.
Without `--startup autoboot`, it loads the SDK TAP through 48K BASIC with a
separately mounted source on slot 2, checking that the current mount is used.
On a host with a headless `FUSEX_LIB` configured, the same test is available
as `cmake --build build --target badapple_verify`.
Use `--intro-capture-dir build/intro` to check and save both title cards.
`--hold-next-copy-ticks 150` exercises playback during a delayed copy.
To test an external HTTPS resource, supply `--protocol https --host HOST`
and `--mount-path /path/`. Emulation verifies the program; real network
throughput and expansion-bus timing still depend on the hardware.
If the emulator ROM still reports an older build version, use
`--system-version 1.1` as a test fixture. To verify the version guard, use
`--system-version 1.0 --expect-version-rejection` instead. The installed
player always checks the real system version.

## Credits

- Animation: Anira and collaborators,
  [original Niconico video](https://www.nicovideo.jp/watch/sm8628149).
  The exact mirror used to prepare the reference GIF was not retained.
- PT3 cover: [Aki, Bad apple (2017)](https://zxart.ee/tune/191490).
- Original composition: ZUN; arrangement: Alstroemeria Records.
- Dithering: [Jari Komppa, img2spec](https://github.com/jarikomppa/img2spec);
  the adapted source retains its attribution notice.
- PT3 decoder: Sergey Bulba and Stefan Bylund,
  [vt_sound](https://github.com/stefanbylund/vt_sound), MIT (see `music/LICENSE`).
- Opening cards: generated apple artwork with native Spectrum font rendering.

### Hardware playback check

After flashing, serve the generated media and configure the device to autoboot
that HTTP URL. Run the snapshot check with the SDK's Python environment:

```sh
python3 tests/hardware_playback.py --media build/media \
  --seconds 260 --output build/hardware
```

It reads screen snapshots over USB without stopping the Z80, compares them with
the generated movie, estimates playback speed, and saves sample PNGs. Supply
`--http-log PATH` to also check that the server delivered every chunk and the
loop prefetch. `--port` selects a device explicitly; otherwise SPX discovers it.
Use `--expect-fps 25` to enforce the rate on a standard machine; accelerated
clones can run faster with the same interrupt-based player.
