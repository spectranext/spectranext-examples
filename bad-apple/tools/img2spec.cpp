/*
 * Headless monochrome stream converter adapted from img2spec's ordered
 * dither modifier: https://github.com/jarikomppa/img2spec
 * This is an altered version, not the original program.
 *
 * Copyright (c) 2015-2016 Jari Komppa, http://iki.fi/sol
 * The original source allows use, modification, and redistribution provided
 * its origin is not misrepresented, alterations are marked, and this notice
 * is preserved.
 */
#include <array>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <vector>

// Matrix values and ordering from src/ordereddithermodifier.h.
static constexpr std::array<int, 16> matrix = {
     1,  9,  3, 11,
    13,  5, 15,  7,
     4, 12,  2, 10,
    16,  8, 14,  6
};

int main(int argc, char **argv) {
    const int width = argc > 1 ? std::atoi(argv[1]) : 192;
    const int height = argc > 2 ? std::atoi(argv[2]) : 144;
    if (width <= 0 || height <= 0) {
        std::cerr << "invalid dimensions\n";
        return 1;
    }
    const int pixels = width * height;
    std::vector<uint8_t> input(pixels), output(pixels);
    unsigned long frames = 0;
    while (true) {
        const size_t count = std::fread(input.data(), 1, pixels, stdin);
        if (count == 0 && std::feof(stdin)) break;
        if (count != pixels) {
            std::cerr << "short input frame at " << frames << '\n';
            return 1;
        }
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const int index = y * width + x;
                const int dither = matrix[(y & 3) * 4 + (x & 3)];
                // Retain crisp silhouettes; dither only antialiased edges.
                const int threshold = 128 + (dither - 8) * 3;
                output[index] = input[index] >= threshold ? 255 : 0;
            }
        }
        if (std::fwrite(output.data(), 1, pixels, stdout) != pixels) {
            std::cerr << "output write failed\n";
            return 1;
        }
        ++frames;
    }
    std::cerr << "converted " << frames << " frames\n";
    return 0;
}
