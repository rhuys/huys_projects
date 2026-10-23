"""
Bit decoder tool

Decode a bitmap made by bitenc, with 3 x 3 blocks and an alternating
black/white block border. Locate the border using a grayscale threshold
of 128, infer the proportional grid spacing from its 322-block width,
and sample each block at its center. Remove the dotted border and read
the 320 data bits per row most significant first, left to right, then top
to bottom: 0 is black and 1 is white. Final-row zero padding is retained
because the original file length is not stored. Keep the complete border
in screenshots, without unrelated bright content outside it.
The earlier single-pixel format is not supported.
If no input filename is given, wait for a bitmap on the clipboard.
Press Ctrl+C to stop waiting.
Without -O, print ASCII to stdout, escaping non-ASCII bytes.
"""
import argparse
import sys
import time
from pathlib import Path

from PIL import Image, ImageGrab


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "filename", nargs="?", type=Path, help="input bitmap filename (default: clipboard)"
    )
    parser.add_argument(
        "-O", "--output", type=Path, help="output binary filename (default: ASCII stdout)"
    )
    args = parser.parse_args()

    try:
        if (
            args.filename is not None
            and args.output is not None
            and args.filename.resolve() == args.output.resolve()
        ):
            parser.error("output filename must be different from the input filename")
        if args.filename is not None:
            source = Image.open(args.filename)
        else:
            source = ImageGrab.grabclipboard()
            if not isinstance(source, Image.Image):
                print("waiting for bitmap on the clipboard", file=sys.stderr, flush=True)
            while not isinstance(source, Image.Image):
                time.sleep(0.5)
                source = ImageGrab.grabclipboard()
        with source as image:
            grayscale = image.convert("L")
            bounds = grayscale.point(lambda value: 255 if value >= 128 else 0).getbbox()
            if bounds is None:
                parser.error("no dotted bitmap border found")
            cropped = grayscale.crop(bounds)
            columns = 322
            rows = round(cropped.height * columns / cropped.width)
            if rows < 3 or cropped.width < columns or cropped.height < rows:
                parser.error("bitmap is too small to sample the dotted block grid")
            grid = cropped.resize((columns, rows), Image.Resampling.NEAREST)
            grid = grid.point(lambda value: 255 if value >= 128 else 0)
            perimeter = (
                [(column, 0) for column in range(columns)]
                + [(column, rows - 1) for column in range(columns)]
                + [(0, row) for row in range(1, rows - 1)]
                + [(columns - 1, row) for row in range(1, rows - 1)]
            )
            matches = sum(
                bool(grid.getpixel((column, row))) == ((column + row) % 2 == 0)
                for column, row in perimeter
            )
            if matches < len(perimeter) * 0.9:
                parser.error("dotted border does not match the expected sampling grid")
            pixels = grid.crop((1, 1, columns - 1, rows - 1)).tobytes()
        data = bytearray()
        for byte_start in range(0, len(pixels), 8):
            value = 0
            byte_pixels = pixels[byte_start:byte_start + 8]
            for pixel in byte_pixels:
                value = (value << 1) | int(pixel == 255)
            data.append(value << (8 - len(byte_pixels)))
        if args.output is not None:
            args.output.write_bytes(data)
        else:
            sys.stdout.write(data.decode("ascii", errors="backslashreplace"))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        parser.exit(130, "\n")


if __name__ == "__main__":
    main()