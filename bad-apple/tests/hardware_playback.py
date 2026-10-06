#!/usr/bin/env python3
"""Sample a running hardware demo over USB without stopping the Spectrum.

Run with the SDK's Python environment (pyserial is required). The SPX module
comes from that SDK. Serve build/media separately and autoboot its boot.zx.
"""
import argparse
import collections
import importlib.util
from pathlib import Path
import re
import shutil
import statistics
import struct
import time
import zlib


def screen_offset(y):
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)


def save_png(path, screen):
    palette = [(0, 0, 0), (0, 0, 205), (205, 0, 0), (205, 0, 205),
               (0, 205, 0), (0, 205, 205), (205, 205, 0), (205, 205, 205)]
    pixels = bytearray()
    for y in range(192):
        pixels.append(0)
        for x in range(256):
            attribute = screen[6144 + (y // 8) * 32 + x // 8]
            ink, paper = attribute & 7, (attribute >> 3) & 7
            color = palette[ink if screen[screen_offset(y) + x // 8] & (128 >> (x & 7)) else paper]
            pixels.extend(255 if value and attribute & 64 else value for value in color)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
        chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 192, 8, 2, 0, 0, 0)) +
        chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=260)
    parser.add_argument('--interval', type=float, default=.2)
    parser.add_argument('--expect-fps', type=float, help='optional target rate; accelerated machines may run faster')
    parser.add_argument('--port')
    parser.add_argument('--spx-module', type=Path)
    parser.add_argument('--http-log', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spx_path = args.spx_module or Path(shutil.which('spx')).with_name('spx.py')
    spec = importlib.util.spec_from_file_location('spx_client', spx_path)
    spx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spx)
    chunks = sorted(args.media.glob('badapple*.bin'), key=lambda p: int(p.stem[8:]))
    reference = collections.defaultdict(list)
    frame_index = 0
    for chunk in chunks:
        data = chunk.read_bytes()
        for offset in range(0, len(data), 3456):
            reference[data[offset:offset + 3456]].append(frame_index)
            frame_index += 1
    args.output.mkdir(parents=True, exist_ok=True)
    connection = spx.SPXConnection(args.port, show_progress=False)
    log = (args.output / 'console.log').open('w')
    connection.set_o_packet_callback(lambda text: (log.write(text), log.flush()))
    samples = []
    snapshots = changes = exact = 0
    previous = None
    started = time.monotonic()
    last_report = started
    try:
        while time.monotonic() - started < args.seconds:
            capture_time = time.monotonic() - started
            begin = connection._send_packet_with_response('vSpectranext:screen:begin', timeout=3)
            assert begin.startswith('S'), begin
            data = bytearray()
            for offset in range(0, 6912, 1024):
                count = min(1024, 6912 - offset)
                response = connection._send_packet_with_response(
                    f'vSpectranext:screen:read:{offset:x},{count:x}', timeout=3)
                assert len(response) == count * 2, response[:100]
                data.extend(bytes.fromhex(response))
            frame = b''.join(data[screen_offset(y + 24) + 4:screen_offset(y + 24) + 28] for y in range(144))
            snapshots += 1
            if frame != previous: changes += 1
            previous = frame
            indices = reference.get(frame, [])
            if indices:
                exact += 1
                if len(indices) == 1:
                    samples.append((capture_time, indices[0]))
                    if len(samples) == 1 or len(samples) % 100 == 0:
                        save_png(args.output / f'frame-{indices[0]:04d}.png', data)
            if time.monotonic() - last_report >= 20:
                print(f'{capture_time:.1f}s: snapshots={snapshots} changes={changes} exact={exact} '
                      f'last_unique_frame={samples[-1][1] if samples else None}', flush=True)
                last_report = time.monotonic()
            time.sleep(args.interval)
    finally:
        connection.close()
        log.close()
    # Use the longest monotonically advancing run to exclude the movie loop.
    runs = [[]]
    for sample in samples:
        if runs[-1] and sample[1] < runs[-1][-1][1]: runs.append([])
        runs[-1].append(sample)
    run = max(runs, key=len)
    assert len(run) >= 100, f'not enough unique reference frames: {len(run)}'
    times, indices = zip(*run)
    mean_time, mean_index = statistics.mean(times), statistics.mean(indices)
    fps = sum((t - mean_time) * (i - mean_index) for t, i in run) / sum((t - mean_time) ** 2 for t in times)
    print(f'Observed: {snapshots} snapshots, {exact} exact reference matches, '
          f'{changes} screen changes, measured {fps:.2f} fps, frames {min(indices)}..{max(indices)}', flush=True)
    if args.expect_fps is not None:
        assert abs(fps - args.expect_fps) <= 1, f'playback speed outside target: {fps:.2f}'
    assert max(indices) >= 5300, 'did not reach the end of the movie'
    assert len(runs) >= 2 and len(runs[-1]) >= 5, 'movie loop did not resume'
    print('PASS: full movie, loop and playback speed verified', flush=True)
    if args.http_log:
        requests = re.findall(r'GET /badapple(\d+)\.bin', args.http_log.read_text())
        assert set(map(int, requests)) >= set(range(1, len(chunks) + 1)), 'not all chunks downloaded'
        assert requests.count('1') >= 2, 'opening chunk was not prefetched for looping'
        print(f'PASS: server received every movie chunk and the loop prefetch ({len(requests)} requests)', flush=True)


if __name__ == '__main__': main()
