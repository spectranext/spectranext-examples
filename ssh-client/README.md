# SSH client example

Interactive SSH terminal client for the ZX Spectrum with Spectranext. Enter a server hostname, connect on port 22, and use a remote shell. Output is echoed by the SSH server; input is sent from the Spectrum keyboard.

Spectranext handles SSH on port 22 transparently (like TLS on 443). The Z80 program uses the normal socket API (`socket`, `connect`, `send`, `recv`, `poll_fd`); the co-processor performs the SSH handshake and encryption.

## What it does

1. Prompts for a server (`user@host` is supported, e.g. `demo@test.rebex.net`).
2. Resolves the hostname with `gethostbyname()`.
3. Opens a TCP socket and connects to port **22**.
4. Runs an interactive loop that polls the socket and reads the keyboard.
5. Handles SSH authentication prompts from the co-processor (`TRUST?`, `USER?`, `PASSWORD?`).
6. After `CONNECTED`, forwards keystrokes to the remote shell and prints received data.
7. On disconnect, returns to the hostname prompt so you can connect again.

## Controls

| Key | Action |
|-----|--------|
| Type normally | Send input to the remote shell (echo from server) |
| DELETE | Send backspace (byte 127) to the server |
| **SYM + X** | Disconnect current session |
| Empty hostname at prompt | Quit the program |

During local prompts (hostname, trust, username, password), use **Enter** to confirm. A blinking `_` cursor marks the input position.

## Prerequisites

- Spectranext SDK installed and `SPECTRANEXT_SDK_PATH` set (see [SDK setup](https://docs.spectranext.net/development/sdk))
- Spectranext hardware with Wi-Fi configured
- An SSH server reachable from the device

Public test server (optional): `demo@test.rebex.net` with password `password`.

## Build

From this directory:

```bash
cmake -B build
cmake --build build
```

Outputs in `build/`:

- `ssh_client.bin` — raw binary
- `ssh_client.tap` — Spectrum tape file

## Upload and run

```bash
cmake --build build --target ssh_client_tap_autoboot
```

Or upload `ssh_client.tap` manually and load it on the Spectrum.

## Authentication flow

While connecting, the co-processor may send control lines on the socket:

| Message | Meaning |
|---------|---------|
| `TRUST? SHA256:…` | Unknown host key — answer `yes` or `no` |
| `USER?` | Username required |
| `PASSWORD?` | Password required |
| `CONNECTED` | Shell session ready |
| `ERROR …` | Connection or auth failed |

The example prints the trust fingerprint and prompts locally for your answers.

## How it works

- **CMake** — Same pattern as `https-example`: imports the Spectranext SDK, links `-llibspectranet` and `-llibsocket`.
- **Memory** — Calls `pagein()` / `pageout()` around network use.
- **Polling** — Uses `struct pollfd` and `poll_fd()` to read socket data without blocking keyboard input.
- **Keyboard** — Debounced input via `in_WaitForNoKey()` so symbol-shift combinations (e.g. SYM+M for `.`) do not produce a second key on release.
- **Echo** — No local echo in connected mode; the SSH endpoint prints characters as you type.

## Libraries

| Library | Purpose |
|---------|---------|
| `libsocket` | `socket`, `connect`, `send`, `recv`, `poll_fd`, `gethostbyname` |
| `libspectranet` | `pagein`, `pageout`, Spectranext integration |

## See also

- [Socket APIs](https://docs.spectranext.net/development/socket-apis)
- [https-example](../https-example/) — HTTPS request using a similar CMake layout
