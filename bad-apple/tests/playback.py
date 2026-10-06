#!/usr/bin/env python3
"""Check HTTP playback and chunk handoff against the encoded GIF in FuseX."""

import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import re
import functools
import http.server
import threading
import tempfile
import time

HERE = Path(__file__).resolve().parent
BUILD = None

class RegPair(ctypes.Union):
    _fields_ = [("word", ctypes.c_uint16), ("bytes", ctypes.c_uint8 * 2)]


class Processor(ctypes.Structure):
    _fields_ = [
        ("af", RegPair), ("bc", RegPair), ("de", RegPair), ("hl", RegPair),
        ("af_alt", RegPair), ("bc_alt", RegPair),
        ("de_alt", RegPair), ("hl_alt", RegPair),
        ("ix", RegPair), ("iy", RegPair),
        ("i", ctypes.c_uint8), ("r", ctypes.c_uint16), ("r7", ctypes.c_uint8),
        ("sp", RegPair), ("pc", RegPair), ("memptr", RegPair),
        ("iff2_read", ctypes.c_int), ("iff1", ctypes.c_uint8),
        ("iff2", ctypes.c_uint8), ("im", ctypes.c_uint8),
        ("halted", ctypes.c_int), ("clockl", ctypes.c_uint16),
        ("clockh", ctypes.c_uint16), ("q", ctypes.c_uint8),
        ("interrupts_enabled_at", ctypes.c_int32),
    ]


def screen_offset(y):
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)



def symbol_address(name):
    symbols = (BUILD / "badapple.map").read_text()
    match = re.search(rf"^{name}\s+= \$([0-9A-Fa-f]+)", symbols, re.MULTILINE)
    if not match:
        raise RuntimeError(f"missing linker symbol: {name}")
    return int(match.group(1), 16)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    requests = []

    def do_GET(self):
        self.requests.append(self.path)
        super().do_GET()

    def log_message(self, format, *args):
        pass


def main():
    global BUILD
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--startup", choices=("tape", "autoboot"), default="tape",
                        help="load SDK TAP on a nonzero mount, or boot the entire URL resource")
    parser.add_argument("--ticks", type=int, default=760)
    parser.add_argument("--expect-chunk", type=int, default=2)
    parser.add_argument("--protocol", choices=("http", "https", "xfs"), default="http")
    parser.add_argument("--host", help="external server; otherwise serve built media locally")
    parser.add_argument("--mount-path", default="/")
    parser.add_argument("--mount-index", type=int, choices=range(4), default=2)
    parser.add_argument("--check-music", action="store_true")
    parser.add_argument("--system-version",
                        help="test-only override of the version returned by the controller ROM")
    parser.add_argument("--expect-version-rejection", action="store_true",
                        help="verify the TAP returns without downloading or starting music")
    parser.add_argument("--hold-next-copy-ticks", type=int, default=0,
                        help="force the next copy to remain pending near chunk 1's end")
    parser.add_argument("--xfs-dir", type=Path,
                        help="XFS RAM directory to mount when using --protocol xfs")
    parser.add_argument("--intro-capture-dir", type=Path,
                        help="check intro timing and save credits/specification PPM images")
    args = parser.parse_args()
    if args.protocol == "xfs" and not args.xfs_dir:
        parser.error("--protocol xfs requires --xfs-dir")
    if args.startup == "autoboot":
        args.mount_index = 0
    BUILD = args.build_dir.resolve()
    media = BUILD / "media"
    server = None
    if args.protocol == "http" and not args.host:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
            functools.partial(QuietHandler, directory=str(media)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        args.host = f"127.0.0.1:{server.server_port}"
    elif args.protocol == "https" and not args.host:
        parser.error("HTTPS requires --host and optionally --mount-path")
    chunks = sorted(media.glob("badapple*.bin"),
                    key=lambda p: int(p.stem.removeprefix("badapple")))
    assert chunks, "build the HTTP chunks first"
    raw = b"".join(chunk.read_bytes() for chunk in chunks)
    reference = {raw[i:i + 3456]: i // 3456
                 for i in range(0, len(raw), 3456)}
    rows = [0x4000 + screen_offset(y + 24) + 4 for y in range(144)]
    chunk_addr = symbol_address("chunk_index")
    mount_addr = symbol_address("source_mount")
    music_ticks_addr = symbol_address("music_ticks")
    frames_left_addr = symbol_address("frames_left")
    banks_played_addr = symbol_address("banks_played")
    replay_wait_addr = symbol_address("replay_wait")

    lib = ctypes.CDLL(os.getenv("FUSEX_LIB", "/opt/fusex/lib/libfusex.so"))
    lib.fuse_init.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
    lib.fuse_init.restype = ctypes.c_int
    lib.fuse_end.restype = ctypes.c_int
    lib.spectrum_do_frame.argtypes = ()
    lib.readbyte.argtypes = (ctypes.c_uint16,)
    lib.readbyte.restype = ctypes.c_uint8
    lib.tape_open.argtypes = (ctypes.c_char_p, ctypes.c_int)
    lib.tape_open.restype = ctypes.c_int
    lib.spectranet_config_get_memory.restype = ctypes.POINTER(ctypes.c_uint8)
    lib.spectranet_config_set_string.argtypes = (ctypes.c_uint16, ctypes.c_uint8, ctypes.c_char_p)
    lib.spectranet_config_set_string.restype = ctypes.c_int
    lib.spectranet_config_set_byte.argtypes = (ctypes.c_uint16, ctypes.c_uint8, ctypes.c_uint8)
    lib.spectranet_config_set_byte.restype = ctypes.c_int
    lib.machine_reset.argtypes = (ctypes.c_int,)
    lib.keyboard_press.argtypes = (ctypes.c_int,)
    lib.keyboard_release.argtypes = (ctypes.c_int,)
    lib.xfs_handle_command.argtypes = (ctypes.c_void_p,)
    lib.spectranext_enginecall_dispatch.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p)
    lib.spectranext_enginecall_dispatch.restype = ctypes.c_int
    lib.spectranet_ram_page.argtypes = (ctypes.c_uint8,)
    lib.spectranet_ram_page.restype = ctypes.POINTER(ctypes.c_uint8)
    # Keep all RAMFS caches/configuration local to the test.
    temporary = tempfile.TemporaryDirectory(prefix="badapple-test-")
    os.environ["XDG_CONFIG_HOME"] = temporary.name
    options = [b"fusex", b"--machine=48", b"--spectranet",
               b"--no-spectranet-disable", b"--no-banner"]
    if args.check_music:
        options.append(b"--melodik")
        lib.ay_registerport_write.argtypes = (ctypes.c_uint16, ctypes.c_uint8)
        lib.ay_registerport_read.argtypes = (ctypes.c_uint16, ctypes.POINTER(ctypes.c_uint8))
        lib.ay_registerport_read.restype = ctypes.c_uint8
    argv = (ctypes.c_char_p * len(options))(*options)
    if lib.fuse_init(len(options), argv):
        raise RuntimeError("FuseX startup failed")
    try:
        source_hashes = None
        if args.protocol == "xfs":
            source_hashes = {chunk.name: hashlib.sha256((args.xfs_dir / chunk.name).read_bytes()).digest()
                             for chunk in chunks}
            xfs_path = (ctypes.c_char * 512).in_dll(lib, "xfs_base_path")
            encoded_path = str(args.xfs_dir.resolve()).encode()
            assert len(encoded_path) < len(xfs_path)
            xfs_path.value = encoded_path
            args.host = "ram"
            args.mount_path = "/"
        if args.startup == "tape":
            registers = (ctypes.c_uint8 * 4096).in_dll(lib, "xfs_registers")
            registers[:] = bytes(4096)
            registers[0] = 1  # XFS_CMD_MOUNT
            registers[6] = args.mount_index
            for offset, value, limit in ((8, args.protocol, 32),
                                         (40, args.host, 64),
                                         (104, args.mount_path, 128)):
                encoded = value.encode() + b"\0"
                assert len(encoded) <= limit
                registers[offset:offset + len(encoded)] = encoded
            lib.xfs_handle_command(ctypes.addressof(registers))
            assert registers[1] == 2, f"source mount failed: status={registers[1]}"
        if source_hashes is not None:
            original = args.xfs_dir / "badapple1.bin"
            assert lib.spectranext_enginecall_dispatch(
                f"{args.mount_index}:badapple1.bin".encode(), b"badapple1.bin", b"cp") < 0, \
                "same-file copy was not rejected"
            assert hashlib.sha256(original.read_bytes()).digest() == source_hashes["badapple1.bin"], \
                "same-file copy changed its source"
        def apply_version_fixture():
            if args.system_version is None:
                return
            page = (ctypes.c_uint8 * 4096).in_dll(lib, "spectranext_controller")
            # Follow the actual ROM's GET_VERSION dispatch and LD HL,string.
            # Only its version data changes; the SDK call still runs on Z80.
            if bytes(page[:3]) != b"\xfe\x0f\xca":
                return  # ROM has not been installed yet during startup.
            handler = (page[3] | page[4] << 8) - 0x2000
            assert bytes(page[handler:handler + 3]) == b"\xe5\xd1\x21"
            address = (page[handler + 3] | page[handler + 4] << 8) - 0x2000
            value = args.system_version.encode() + b"\0"
            assert len(value) <= 32 and 0 <= address < 2048 - len(value)
            assert len(value) <= bytes(page[address:address + 32]).index(0) + 1, \
                "version fixture exceeds ROM string storage"
            page[address:address + len(value)] = value

        def advance(count):
            for _ in range(count):
                apply_version_fixture()
                lib.spectrum_do_frame()

        def key(code, modifier=None):
            if modifier is not None:
                lib.keyboard_press(modifier)
            lib.keyboard_press(code)
            advance(12 if code == 0x100 else 3)
            lib.keyboard_release(code)
            if modifier is not None:
                lib.keyboard_release(modifier)
            advance(12)

        advance(300)
        key(ord("q"))
        key(0x100)
        advance(100)
        if args.startup == "autoboot":
            url = f"{args.protocol}://{args.host}{args.mount_path}"
            # Configure a fresh process-local device. The setter cannot grow
            # an existing shorter URL, so create a clean configuration page.
            configuration = lib.spectranet_config_get_memory()
            assert configuration
            ctypes.memset(configuration, 0xff, 4096)
            assert lib.spectranet_config_set_string(0x1ff, 0, url.encode()) == 0
            assert lib.spectranet_config_set_byte(0x1ff, 0x81, 1) == 0
            lib.machine_reset(0)
        else:
            # Actual SDK TAP and CRT through 48K BASIC, with a nonzero source
            # mount. No application bytes or entry-point jumps are injected.
            assert lib.tape_open(str(media / "badapple.tap").encode(), 0) == 0
            lib.spectranet_ram_page(0xC0)[0xF6F] = args.mount_index
            key(ord("j"))
            key(ord(" "))
            key(ord("p"), 0x102)
            key(ord("p"), 0x102)
            key(0x100)
        cpu = Processor.in_dll(lib, "z80")
        code = (BUILD / "badapple.bin").read_bytes()
        origin = symbol_address("__head")
        loaded = False
        tap_loaded = False
        matches = 0
        distinct = set()
        seen_chunks = set()
        samples = 0
        first_video_tick = None
        music_at_first_video = None
        last_end_tick = None
        loop_gap = None
        previous_chunk = 1
        loop_start_tick = None
        loop_music_start = None
        loop_music_lead = None
        audible = 0
        ay_states = set()
        copy_state = (ctypes.c_uint8 * 4096).in_dll(lib, "spectranext_controller")
        hold_start = None
        replay_music_start = None
        replay_music_end = None
        replay_images = set()
        intro_seen = set()
        for tick in range(args.ticks):
            apply_version_fixture()
            lib.spectrum_do_frame()
            if not tap_loaded:
                tap_loaded = bytes(lib.readbyte(origin + i) for i in range(32)) == code[:32]
            if not loaded:
                header = bytes(lib.readbyte(origin + i) for i in range(32))
                if header != code[:32] or not lib.readbyte(music_ticks_addr):
                    if tick % 25 == 0:
                        time.sleep(0.001)
                    continue
                assert lib.readbyte(mount_addr) == args.mount_index, "player selected wrong mount"
                loaded = True
            if (args.hold_next_copy_ticks and hold_start is not None and
                    lib.readbyte(chunk_addr) == 1):
                copy_state[0xffd] = (0xff if tick - hold_start < args.hold_next_copy_ticks else 0)
            if (args.hold_next_copy_ticks and hold_start is None and
                    lib.readbyte(chunk_addr) == 1 and
                    lib.readbyte(banks_played_addr) >= 31):
                hold_start = tick + 1
            if lib.readbyte(replay_wait_addr):
                replay_music_end = (lib.readbyte(music_ticks_addr) |
                                    (lib.readbyte(music_ticks_addr + 1) << 8))
                if replay_music_start is None:
                    replay_music_start = replay_music_end
            if first_video_tick is None and lib.readbyte(frames_left_addr):
                first_video_tick = tick
                music_at_first_video = (lib.readbyte(music_ticks_addr) |
                                        (lib.readbyte(music_ticks_addr + 1) << 8))
            current_chunk = lib.readbyte(chunk_addr)
            music_count = lib.readbyte(music_ticks_addr) | (lib.readbyte(music_ticks_addr + 1) << 8)
            if previous_chunk == len(chunks) and current_chunk == 1:
                loop_start_tick = tick
                loop_music_start = music_count
            if loop_music_start is not None and lib.readbyte(frames_left_addr) and loop_music_lead is None:
                loop_music_lead = music_count - loop_music_start
            previous_chunk = current_chunk
            seen_chunks.add(current_chunk)
            if args.intro_capture_dir:
                music_count = lib.readbyte(music_ticks_addr) | (lib.readbyte(music_ticks_addr + 1) << 8)
                targets = {100: "credits", 175: "blank-one", 275: "specifications", 375: "blank-two"}
                if music_count in targets and music_count not in intro_seen:
                    screen_data = bytes(lib.readbyte(0x4000 + i) for i in range(6912))
                    label = targets[music_count]
                    if label.startswith("blank"):
                        assert not any(screen_data[:6144]), f"{label} was not blank"
                    else:
                        assert any(screen_data[:6144]), f"{label} missing"
                        packed = (media / f"intro_{label}.bin").read_bytes()
                        expected = bytearray()
                        cursor = 0
                        while True:
                            value = packed[cursor]
                            cursor += 1
                            if value:
                                expected.append(value)
                            else:
                                count = packed[cursor]
                                cursor += 1
                                if not count:
                                    break
                                expected.extend(bytes(count))
                        assert screen_data[:6144] == expected, f"{label} bitmap differs from artwork"

                        assert set(screen_data[6144:]) == {0x47, 0x02}, f"{label} lost its restrained palette"
                        pixels = bytearray()
                        for y in range(192):
                            for x in range(256):
                                attribute = screen_data[6144 + (y // 8) * 32 + x // 8]
                                bit = screen_data[screen_offset(y) + x // 8] & (128 >> (x & 7))
                                colour = (attribute & 7) if bit else ((attribute >> 3) & 7)
                                intensity = 255 if attribute & 64 else 205
                                pixels.extend((intensity if colour & 2 else 0,
                                               intensity if colour & 4 else 0,
                                               intensity if colour & 1 else 0))
                        args.intro_capture_dir.mkdir(parents=True, exist_ok=True)
                        (args.intro_capture_dir / f"{label}.ppm").write_bytes(b"P6\n256 192\n255\n" + pixels)
                    intro_seen.add(music_count)

            if args.check_music:
                registers_now = []
                attached = ctypes.c_uint8()
                for number in (0, 1, 2, 3, 4, 5, 8, 9, 10):
                    lib.ay_registerport_write(0xfffd, number)
                    registers_now.append(lib.ay_registerport_read(0xfffd, ctypes.byref(attached)))
                ay_states.add(tuple(registers_now))
                if any(registers_now[-3:]):
                    audible += 1
            if first_video_tick is not None:
                samples += 1
                screen = b"".join(bytes(lib.readbyte(address + i) for i in range(24))
                                  for address in rows)
                if lib.readbyte(replay_wait_addr):
                    replay_images.add(screen)
                frame = reference.get(screen)
                if frame is not None:
                    matches += 1
                    distinct.add(frame)
                    if lib.readbyte(chunk_addr) == len(chunks) and frame >= 5400:
                        last_end_tick = tick
                    elif (last_end_tick is not None and lib.readbyte(chunk_addr) == 1 and
                          frame < 150 and loop_gap is None):
                        loop_gap = tick - last_end_tick
            if loaded:
                assert not 0x4000 <= cpu.pc.word < origin, "player executed screen RAM"
            # Background enginecalls are real host jobs; yield so the HTTP
            # server/downloader progress even with emulation running flat out.
            time.sleep(0.001)
        print(f"music lead: {first_video_tick} display ticks, "
              f"{music_at_first_video} music ticks; "
              f"exact snapshots: {matches}/{samples}; distinct frames: {len(distinct)}; "
              f"chunks: {sorted(seen_chunks)}; loop gap: {loop_gap} ticks; "
              f"final pc={cpu.pc.word:04x}")
        if server:
            print(f"HTTP requests: {QuietHandler.requests[:8]}")
            if args.startup == "autoboot":
                assert "/boot.zx" in QuietHandler.requests and "/badapple.tap" in QuietHandler.requests, \
                    "autoboot did not fetch the boot program and TAP"
        if args.expect_version_rejection:
            assert tap_loaded, "SDK TAP was not loaded"
            assert not loaded and not lib.readbyte(music_ticks_addr), "rejected version started music"
            assert not any(re.fullmatch(r"/badapple\d+\.bin", path)
                           for path in QuietHandler.requests), "rejected version downloaded a movie chunk"
            assert cpu.pc.word < origin, "rejected player did not return to BASIC"
            print("version rejected before any movie download or music; returned to BASIC")
            return
        if not loaded:
            (BUILD / "failed-boot.scr").write_bytes(bytes(lib.readbyte(0x4000 + i) for i in range(6912)))
        if args.check_music:
            music_ticks = lib.readbyte(music_ticks_addr) | (lib.readbyte(music_ticks_addr + 1) << 8)
            print(f"music ticks: {music_ticks}; AY states: {len(ay_states)}; "
                  f"audible display ticks: {audible}/{args.ticks}")
            assert music_ticks >= 50, "PT3 decoder did not advance"
            assert len(ay_states) >= 10 and audible >= 10, "AY registers did not play the tune"
        if args.hold_next_copy_ticks:
            assert hold_start is not None and replay_music_start is not None and replay_music_end is not None, \
                "forced copy wait did not reach the replay path"
            print(f"forced wait: {len(replay_images)} distinct screen images; "
                  f"music advanced {replay_music_end - replay_music_start} ticks")
            assert len(replay_images) >= 5 and replay_music_end - replay_music_start >= 50, \
                "screen or music stopped during forced copy wait"
        if args.intro_capture_dir:
            assert intro_seen == {100, 175, 275, 375}, f"intro stages missing: {intro_seen}"
            print("intro cards, blank intervals, colours and music timing verified")
        assert first_video_tick is not None and first_video_tick >= 390, \
            "video began before the music lead-in finished"
        assert music_at_first_video == 400, "video did not begin eight seconds after the music"
        assert matches >= samples * 3 // 10, "too few complete reference frames"
        assert len(distinct) >= 15, "player did not advance through the movie"
        assert args.expect_chunk in seen_chunks, "player did not reach expected HTTP chunk"
        if args.expect_chunk == len(chunks) and args.ticks >= 12000:
            assert loop_music_lead is not None and 399 <= loop_music_lead <= 401, \
                f"movie loop did not repeat the 400-tick music lead-in: {loop_music_lead}"
            assert len(distinct) >= 5000, "full movie lost too many reference frames"
            assert set(range(1, len(chunks) + 1)) <= seen_chunks, "movie skipped a chunk"
            movie_ticks = loop_start_tick - first_video_tick
            assert abs(movie_ticks - len(raw) // 3456 * 2) <= 100, \
                f"movie did not maintain 25 fps: {movie_ticks} display ticks"
            print(f"loop music lead-in: {loop_music_lead} ticks; movie duration: {movie_ticks} display ticks")
        if source_hashes is not None:
            for name, digest in source_hashes.items():
                assert hashlib.sha256((args.xfs_dir / name).read_bytes()).digest() == digest, \
                    f"source movie changed during playback: {name}"
    finally:
        lib.fuse_end()
        if server:
            server.shutdown()
            server.server_close()
        temporary.cleanup()


if __name__ == "__main__":
    main()
