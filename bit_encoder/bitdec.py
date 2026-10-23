"""
Bit decoder tool

Decode a lossless 320 x 320 black-and-white PNG with an 8-pixel black border
into bytes. Bits are read most significant first, left to right,
then top to bottom: 0 is black and 1 is white. Trailing zero padding is
retained because the image does not store the original file length.
The output size is 11,552 bytes. If no input filename is given, read the
image from stdin. Without -O, print ASCII to stdout, escaping non-ASCII bytes.
"""
import argparse
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "filename", nargs="?", type=Path, help="input bitmap filename (default: stdin)"
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
        source = (
            args.filename
            if args.filename is not None
            else BytesIO(sys.stdin.buffer.read())
        )
        with Image.open(source) as image:
            if image.size != (320, 320):
                parser.error("input bitmap must be 320 x 320 pixels")
            pixels = image.convert("L").crop((8, 8, 312, 312)).tobytes()
        if any(pixel not in (0, 255) for pixel in pixels):
            parser.error("input bitmap interior must contain only black and white pixels")
        data = bytearray()
        for byte_start in range(0, len(pixels), 8):
            value = 0
            for pixel in pixels[byte_start:byte_start + 8]:
                value = (value << 1) | int(pixel == 255)
            data.append(value)
        if args.output is not None:
            args.output.write_bytes(data)
        else:
            sys.stdout.write(data.decode("ascii", errors="backslashreplace"))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()