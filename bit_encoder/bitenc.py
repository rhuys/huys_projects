"""
Bit encoder tool

Encode a file into a lossless 320 x 320 black-and-white PNG with an 8-pixel
black border. Bits are written most significant first, left to right,
then top to bottom: 0 is black and 1 is white. Unused pixels stay black.
The maximum input size is 11,552 bytes.
"""

import argparse
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("filename", type=Path, help="input file to encode")
    parser.add_argument(
        "-O", "--output", type=Path, help="output PNG filename (default: input stem.png)"
    )
    args = parser.parse_args()

    size = 320
    border = 8
    inner_size = size - 2 * border
    capacity = inner_size * inner_size // 8
    output = args.output if args.output is not None else args.filename.with_suffix(".png")

    try:
        if args.filename.resolve() == output.resolve():
            parser.error("output filename must be different from the input filename")
        with args.filename.open("rb") as source:
            data = source.read(capacity + 1)
        if len(data) > capacity:
            parser.error(f"input exceeds the bitmap capacity of {capacity:,} bytes")

        image = Image.new("1", (size, size), 0)
        for byte_index, byte in enumerate(data):
            for bit_index in range(8):
                pixel_index = byte_index * 8 + bit_index
                position = (
                    border + pixel_index % inner_size,
                    border + pixel_index // inner_size,
                )
                image.putpixel(position, 255 if byte & (1 << (7 - bit_index)) else 0)
        image.save(output, format="PNG")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()