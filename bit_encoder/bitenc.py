"""
Bit encoder tool

Encode a file into a lossless black-and-white PNG, with 320 bits per row.
Each bit is a solid 3 x 3 pixel block: 0 is black and 1 is white.
An alternating black/white block border surrounds the data, followed by
a 9-pixel black margin, giving a total width of 984 pixels.
Bits are written most significant first, left to
right, then top to bottom. The height follows the file length; unused bits
in the last row stay black. The maximum input size is 11,552 bytes.
This format is not compatible with the earlier single-pixel format.
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

    columns = 320
    block_size = 3
    margin = 9
    capacity = 11552
    output = args.output if args.output is not None else args.filename.with_suffix(".png")

    try:
        if args.filename.resolve() == output.resolve():
            parser.error("output filename must be different from the input filename")
        with args.filename.open("rb") as source:
            data = source.read(capacity + 1)
        if len(data) > capacity:
            parser.error(f"input exceeds the bitmap capacity of {capacity:,} bytes")

        rows = max(1, (len(data) * 8 + columns - 1) // columns)
        grid = Image.new("1", (columns + 2, rows + 2), 0)
        for column in range(columns + 2):
            grid.putpixel((column, 0), 255 if column % 2 == 0 else 0)
            grid.putpixel((column, rows + 1), 255 if (column + rows + 1) % 2 == 0 else 0)
        for row in range(rows + 2):
            grid.putpixel((0, row), 255 if row % 2 == 0 else 0)
            grid.putpixel((columns + 1, row), 255 if (columns + 1 + row) % 2 == 0 else 0)
        for byte_index, byte in enumerate(data):
            for bit_index in range(8):
                pixel_index = byte_index * 8 + bit_index
                position = (
                    1 + pixel_index % columns,
                    1 + pixel_index // columns,
                )
                grid.putpixel(position, 255 if byte & (1 << (7 - bit_index)) else 0)
        enlarged = grid.resize(
            (grid.width * block_size, grid.height * block_size),
            Image.Resampling.NEAREST,
        )
        image = Image.new("1", (enlarged.width + 2 * margin, enlarged.height + 2 * margin), 0)
        image.paste(enlarged, (margin, margin))
        image.save(output, format="PNG")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()