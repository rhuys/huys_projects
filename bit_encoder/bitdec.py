"""
Bit decoder tool

Decode a bitmap made by bitenc, with configurable pixel blocks and an alternating
black/white block border. Locate the border using a grayscale threshold
of 128, count its white peaks to discover the grid width and height,
and sample each block at its center. Remove the dotted border and read
the data bits most significant first, left to right, then top
to bottom: 0 is black and 1 is white. Read the binary file header, decompress
the zlib payload and verify the original size and SHA-256 checksum before
saving. The header lengths exclude final-row padding. Keep the complete border
in screenshots, without unrelated bright content outside it.
The earlier single-pixel format is not supported.
If no input filename is given, wait for a bitmap on the clipboard.
Press Ctrl+C to stop waiting.
Without -O, save to the received filename in the current directory without
overwriting an existing file. Use -O to choose a different output filename.
"""
import argparse
import sys
import time
from itertools import groupby
from pathlib import Path

from PIL import Image, ImageGrab

if __package__:
    from .bitformat import ChecksumError, unpack_file
else:
    from bitformat import ChecksumError, unpack_file


def border_runs(values):
    """Return (is_white, pixel_count) runs along a dotted border scan line."""
    return [
        (white, sum(1 for _ in pixels))
        for white, pixels in groupby(values, key=lambda value: value >= 128)
    ]


def count_border_cells(values):
    """Count white peaks and their separating black cells, including endpoints."""
    runs = border_runs(values)
    peaks = sum(white for white, length in runs)
    if peaks < 1:
        raise ValueError("dotted border must contain a white peak")
    # There is one black cell between consecutive white peaks. A black cell
    # at either endpoint adds one more, so odd and even cell counts both work.
    return 2 * peaks - 1 + int(not runs[0][0]) + int(not runs[-1][0])


def first_peak_center(values):
    """Find the first white block's center, skipping a blurred dark endpoint."""
    offset = 0
    for white, length in border_runs(values):
        if white:
            return offset + length // 2
        offset += length
    raise ValueError("no white peak found on the dotted border")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "filename", nargs="?", type=Path, help="input bitmap filename (default: clipboard)"
    )
    parser.add_argument(
        "-O", "--output", type=Path, help="output filename (default: received filename)"
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
            # Clipboard text and file lists are not image pixels. Wait until
            # Pillow returns an image, keeping status messages off data stdout.
            source = ImageGrab.grabclipboard()
            if not isinstance(source, Image.Image):
                print("waiting for bitmap on the clipboard", file=sys.stderr, flush=True)
            while not isinstance(source, Image.Image):
                time.sleep(0.5)
                source = ImageGrab.grabclipboard()
            print("decoding clipboard...", file=sys.stderr, flush=True)
        with source as image:
            grayscale = image.convert("L")
            # Use a thresholded copy only to find the bright frame's bounds;
            # faint screenshot noise in the black margin should not enlarge it.
            # Keep the original grayscale pixels for the actual sampling.
            bounds = grayscale.point(lambda value: 255 if value >= 128 else 0).getbbox()
            if bounds is None:
                parser.error("no dotted bitmap border found")
            cropped = grayscale.crop(bounds)
            # The top-left block is white, but its extreme corner pixel can
            # be darkened by screenshot interpolation. Find the first white
            # run on each axis, allowing a short dark lead-in at that corner.
            # Scan through the middle of that thickness, not its blurred edge.
            center_column = first_peak_center(
                cropped.crop((0, 0, cropped.width, 1)).tobytes()
            )
            center_row = first_peak_center(
                cropped.crop((0, 0, 1, cropped.height)).tobytes()
            )
            # Count peaks on all four edges. Opposite edges must agree, and
            # independent X/Y counts also allow different horizontal/vertical
            # screenshot scale factors. No encoded data width is assumed.
            top = cropped.crop((0, center_row, cropped.width, center_row + 1))
            bottom_row = cropped.height - 1 - center_row
            bottom = cropped.crop((0, bottom_row, cropped.width, bottom_row + 1))
            left = cropped.crop((center_column, 0, center_column + 1, cropped.height))
            right_column = cropped.width - 1 - center_column
            right = cropped.crop((right_column, 0, right_column + 1, cropped.height))
            columns = count_border_cells(top.tobytes())
            rows = count_border_cells(left.tobytes())
            if (
                count_border_cells(bottom.tobytes()) != columns
                or count_border_cells(right.tobytes()) != rows
            ):
                parser.error("opposite dotted borders disagree on the grid dimensions")
            if columns < 3 or rows < 3 or cropped.width < columns or cropped.height < rows:
                parser.error("bitmap is too small to sample the dotted block grid")
            # Resizing to one pixel per cell samples near each cell's center:
            # source column = floor((column + 0.5) * cropped.width / columns),
            # source row = floor((row + 0.5) * cropped.height / rows).
            # For an unscaled 3 x 3 block this selects its middle pixel.
            # NEAREST does not average neighboring cells; threshold the sampled
            # grayscale values afterward to recover black/white bits.
            grid = cropped.resize((columns, rows), Image.Resampling.NEAREST)
            grid = grid.point(lambda value: 255 if value >= 128 else 0)
            # Check every frame cell once against the encoder's alternating
            # pattern. At least 90% must match: this checks alignment but does
            # not correct data errors or guarantee the payload is intact.
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
            # Discard the frame only after sampling and validation. The inferred
            # data width is preserved even if its edge bits are all black.
            pixels = grid.crop((1, 1, columns - 1, rows - 1)).tobytes()
        data = bytearray()
        # Pixels are row-major: shift each group of eight bits into a byte,
        # most-significant bit first, reversing the encoder's bit order.
        # The file envelope's compressed length excludes final-row padding.
        for byte_start in range(0, len(pixels), 8):
            value = 0
            byte_pixels = pixels[byte_start:byte_start + 8]
            for pixel in byte_pixels:
                value = (value << 1) | int(pixel == 255)
            data.append(value << (8 - len(byte_pixels)))
        filename, received_data = unpack_file(data)
        output = args.output if args.output is not None else Path(filename)
        if args.filename is not None and args.filename.resolve() == output.resolve():
            parser.error("output filename must be different from the input bitmap filename")
        if args.output is None:
            with output.open("xb") as destination:
                destination.write(received_data)
        else:
            output.write_bytes(received_data)
        print(f"received file {filename} , {len(received_data)} bytes")
    except ChecksumError:
        parser.exit(1, "checksum failure, please try again\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        parser.exit(130, "\n")


if __name__ == "__main__":
    main()