"""
Bit encoder tool

Encode a file into a lossless black-and-white PNG, with 320 bits per row.
Each bit is a solid P x P pixel block: 0 is black and 1 is white.
Set P with -p / --pixel-size (default: 3).
An alternating black/white block border surrounds the data, followed by
a 9-pixel black margin, giving a total width of 322 * P + 18 pixels.
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
    parser.add_argument(
        "-p", "--pixel-size", type=int, default=3, metavar="P",
        help="pixels per bit along each axis; positive integer (default: 3)",
    )
    args = parser.parse_args()
    if args.pixel_size < 1:
        parser.error("pixel size must be a positive integer")

    columns = 320
    block_size = args.pixel_size
    margin = 9
    capacity = 11552
    output = args.output if args.output is not None else args.filename.with_suffix(".png")

    try:
        if args.filename.resolve() == output.resolve():
            parser.error("output filename must be different from the input filename")
        # Read one extra byte so oversized files are rejected, not silently truncated.
        with args.filename.open("rb") as source:
            data = source.read(capacity + 1)
        if len(data) > capacity:
            parser.error(f"input exceeds the bitmap capacity of {capacity:,} bytes")

        # Build a logical grid first: one pixel per bit, plus one border cell
        # on each side. Round up to a full row; even an empty file gets one row.
        rows = max(1, (len(data) * 8 + columns - 1) // columns)
        grid = Image.new("1", (columns + 2, rows + 2), 0)
        # White cells have even (column + row) parity around the entire frame.
        # These dots establish the bounds independently of the data, including
        # data rows or columns that are entirely black.
        for column in range(columns + 2):
            grid.putpixel((column, 0), 255 if column % 2 == 0 else 0)
            grid.putpixel((column, rows + 1), 255 if (column + rows + 1) % 2 == 0 else 0)
        for row in range(rows + 2):
            grid.putpixel((0, row), 255 if row % 2 == 0 else 0)
            grid.putpixel((columns + 1, row), 255 if (columns + 1 + row) % 2 == 0 else 0)
        # Write each byte most-significant bit first. Modulo selects its data
        # column, integer division selects its row, and +1 skips the frame.
        # Cells after the last input bit remain black padding.
        for byte_index, byte in enumerate(data):
            for bit_index in range(8):
                pixel_index = byte_index * 8 + bit_index
                position = (
                    1 + pixel_index % columns,
                    1 + pixel_index // columns,
                )
                grid.putpixel(position, 255 if byte & (1 << (7 - bit_index)) else 0)
        # Nearest-neighbor enlargement repeats each logical cell as a solid
        # P x P square without introducing gray values at the block edges.
        enlarged = grid.resize(
            (grid.width * block_size, grid.height * block_size),
            Image.Resampling.NEAREST,
        )
        # Add the black quiet margin outside the dotted frame, then save a
        # lossless, one-bit PNG. Width: (320 + 2) * P + 2 * 9 pixels.
        image = Image.new("1", (enlarged.width + 2 * margin, enlarged.height + 2 * margin), 0)
        image.paste(enlarged, (margin, margin))
        image.save(output, format="PNG")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()