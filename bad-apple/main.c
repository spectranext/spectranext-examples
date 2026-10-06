/*
 * Stream a movie from the current mount through the cp engine into XFS RAM.
 *
 * Load the first chunk with the ordinary SDK call before music starts.
 * Playback submits subsequent enginecalls through controller channel 1
 * so music and drawing continue while the next chunk downloads.
 * See controller.asm for submission, completion polling, and XFS page reads.
 */
#include <stdio.h>
#include <limits.h>
#include <spectranext.h>
#include <spdos.h>

extern void badapple_play(unsigned int source_mount) __z88dk_fastcall;

/* Compare numeric components, accepting build suffixes such as 1.1-abcd. */
static int supported_version(const char *version)
{
    unsigned int parts[2];
    unsigned int value;
    unsigned char part;

    for (part = 0; part < 2; ++part) {
        if (*version < '0' || *version > '9')
            return 0;
        value = 0;
        while (*version >= '0' && *version <= '9') {
            unsigned int digit = *version++ - '0';
            if (value > (UINT_MAX - digit) / 10)
                return 0;
            value = value * 10 + digit;
        }
        parts[part] = value;
        if (part == 0 && *version++ != '.')
            return 0;
    }
    if (*version && *version != '.' && *version != '-' && *version != '+')
        return 0;
    return parts[0] > 1 || (parts[0] == 1 && parts[1] >= 1);
}

int main(void)
{
    char version[SPECTRANEXT_VERSION_SIZE];
    int source_mount;
    char input[] = "0:badapple1.bin";
    int result;

    if (spectranext_get_version(version) < 0) {
        printf("Spectranext 1.1 or newer required\nCannot read system version\n");
        return 1;
    }
    version[SPECTRANEXT_VERSION_SIZE - 1] = '\0';
    if (!supported_version(version)) {
        printf("Spectranext 1.1 or newer required\nSystem version: %s\n", version);
        return 1;
    }

    source_mount = getmountpoint();
    if (source_mount < 0 || source_mount > 3) {
        printf("No source mount selected\n");
        return 1;
    }

    /* Input is relative to the selected mount. Output always goes to RAM,
     * using a different name so an XFS source cannot overwrite itself. */
    input[0] += source_mount;
    result = spectranext_enginecall(input, "ba-cache1.bin", "cp");
    if (result < 0) {
        printf("Cannot copy first movie chunk: %d\n", result);
        return 1;
    }

    badapple_play(source_mount);
    return 0;
}
