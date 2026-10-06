#!/usr/bin/env python3
"""Exercise the real C entry point with SDK calls stubbed on the host."""

from pathlib import Path
import subprocess
import tempfile


def main():
    source = Path(__file__).resolve().parents[1] / "main.c"
    with tempfile.TemporaryDirectory(prefix="badapple-version-") as directory:
        work = Path(directory)
        (work / "spectranext.h").write_text("""
#define SPECTRANEXT_VERSION_SIZE 32
#define __z88dk_fastcall
int spectranext_get_version(char *version);
int spectranext_enginecall(char *input, char *output, char *operation);
""")
        (work / "spdos.h").write_text("int getmountpoint(void);\n")
        test = work / "test.c"
        test.write_text("""
#include <assert.h>
#include <string.h>
#define main demo_main
#include """ + f'"{source}"' + """
#undef main

static const char *system_version;
static int mount_calls, copy_calls, play_calls;
int spectranext_get_version(char *version)
{
    if (!system_version) return -1;
    strcpy(version, system_version);
    return 0;
}
int getmountpoint(void) { ++mount_calls; return 2; }
int spectranext_enginecall(char *input, char *output, char *operation)
{
    ++copy_calls;
    assert(!strcmp(input, "2:badapple1.bin"));
    assert(!strcmp(output, "ba-cache1.bin"));
    assert(!strcmp(operation, "cp"));
    return 0;
}
void badapple_play(unsigned int mount) { assert(mount == 2); ++play_calls; }
int main(void)
{
    static const struct { const char *version; int accepted; } cases[] = {
        {0, 0}, {"", 0}, {"garbage", 0}, {"1", 0}, {"1.", 0},
        {"1.x", 0}, {"1.1garbage", 0}, {"0.99", 0}, {"1.0", 0},
        {"1.0-88b77c01", 0}, {"1.1", 1}, {"1.1-abcd", 1},
        {"1.1.0", 1}, {"1.1+build", 1}, {"1.10", 1}, {"2.0", 1},
        {"99999999999999999999.1", 0}
    };
    unsigned int i;
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        system_version = cases[i].version;
        mount_calls = copy_calls = play_calls = 0;
        assert(demo_main() == !cases[i].accepted);
        assert(mount_calls == cases[i].accepted);
        assert(copy_calls == cases[i].accepted);
        assert(play_calls == cases[i].accepted);
    }
    puts("17 version cases passed; rejected systems never mounted/copied/played");
    return 0;
}
""")
        subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-I", str(work), str(test), "-o", str(work / "test")], check=True)
        subprocess.run([str(work / "test")], check=True)


if __name__ == "__main__":
    main()
