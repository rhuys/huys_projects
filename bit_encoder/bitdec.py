"""
Bit decoder tool

Decode a black-and-white bitmap of any size into bytes, removing all outer
all-black rows and columns. Bits are read most significant first, left to
right, then top to bottom: 0 is black and 1 is white. A partial final byte
is padded with zero bits. An all-black image produces no bytes.
All-zero data rows or columns at the edges cannot be distinguished from
the border and are also removed. The original file length is not stored.
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
            bounds = grayscale.getbbox()
            pixels = grayscale.crop(bounds).tobytes() if bounds is not None else b""
        if any(pixel not in (0, 255) for pixel in pixels):
            parser.error("input bitmap interior must contain only black and white pixels")
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