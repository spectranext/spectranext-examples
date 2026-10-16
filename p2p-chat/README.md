# Peer-to-peer chat

A minimal C example using `p2p-chat@match.spx`. Both participants run the same
program: ordinary hostname lookup and TCP `connect()` bring up Spectranext's
system matchmaking menu. Choose each other there, then chat.

Once connected, the chat displays your matchmaking name and serial, the peer's
name and serial, and the match initiator's serial using
`spectranext_get_string(string_id, buffer, capacity)`. The example tolerates
unavailable metadata so older beta firmware can still exchange messages.

- Type up to 24 characters and press **Enter** to send.
- Use **Caps Shift + 0** to delete a character.
- Send **`/quit`** to leave locally (the command is not sent).
- Incoming messages appear even while you are typing.

The wire protocol is printable ASCII lines terminated by `\n`. The code handles
partial TCP writes and assembles received lines across reads. It needs no chat
server or application-level host/listener; Spectranext supplies matchmaking.

## Build

With the Spectranext SDK environment loaded, from this directory:

```sh
cmake -S . -B build
cmake --build build
```

This produces `build/p2p-chat.tap`. As in the other demos, the convenience
target below also generates/uploads the BASIC loader `build/boot.zx` and starts
the program on a connected device:

```sh
cmake --build build --target p2p-chat_tap_autoboot
```

Or copy the TAP to an XFS folder and load it from BASIC:

```basic
%tapein "p2p-chat.tap"
LOAD ""
```

Requires Spectranext firmware 1.2 or newer on both devices and a current SDK. For the
default public setup, test using different public IPs (for example a VPN on one
PC that permits UDP). Same-router public endpoints depend on NAT hairpinning.
For controlled LAN testing, configure a reachable local STUN server on both
endpoints. See the [matchmaking documentation](https://docs.spectranext.net/api/matchmaking).
