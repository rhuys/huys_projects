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
Input filenames may be a list or glob patterns for one original file.
Sections may arrive in any order; duplicates are ignored and bad sections
produce retry warnings. All sections are required before verifying and saving.
If no input filename is given, wait for new bitmaps on the clipboard until
all sections arrive, retaining valid sections across retries.
Press Ctrl+C to stop waiting.
Without -O, save to the received filename in the current directory, asking
before overwriting an existing file. Enter accepts; n cancels the save.
Use -O to choose a different output filename; existing files still require confirmation.
"""
import argparse
import glob
import hashlib
import struct
import sys
import time
import zlib
from itertools import groupby
from pathlib import Path

from PIL import Image, ImageGrab

MAGIC = b"BITENC01"
HEADER = struct.Struct(">8sHQQ32s")
SECTION_MAGIC = b"BITENC02"
SECTION_HEADER = struct.Struct(">8sHQQ32sIIQI")


class ChecksumError(ValueError):
    """The received file envelope is incomplete, corrupt or unsupported."""


class SectionChecksumError(ChecksumError):
    """A damaged section can be discarded and received again."""


def unpack_section(packet):
    """Validate a section CRC before trusting its metadata or payload."""
    if bytes(packet[:8]) == MAGIC:
        filename, data = unpack_file(packet)
        _, name_size, size, compressed_size, checksum = HEADER.unpack_from(packet)
        start = HEADER.size + name_size
        return (filename, size, compressed_size, checksum, 1), 1, bytes(packet[start:start + compressed_size])
    if len(packet) < SECTION_HEADER.size:
        raise SectionChecksumError("truncated section header")
    fields = SECTION_HEADER.unpack_from(packet)
    magic, name_size, size, compressed_size, checksum, number, count, chunk_size, crc = fields
    start = SECTION_HEADER.size + name_size
    end = start + chunk_size
    if magic != SECTION_MAGIC or not name_size or not chunk_size or end > len(packet):
        raise SectionChecksumError("invalid or truncated section")
    protected = SECTION_HEADER.pack(*fields[:-1], 0) + bytes(packet[SECTION_HEADER.size:end])
    if zlib.crc32(protected) != crc:
        raise SectionChecksumError("section checksum failure")
    if not 1 <= number <= count <= compressed_size or chunk_size > compressed_size:
        raise SectionChecksumError("invalid section numbering or size")
    try:
        filename = bytes(packet[SECTION_HEADER.size:start]).decode("utf-8")
    except UnicodeError as error:
        raise SectionChecksumError("invalid filename") from error
    if filename in (".", "..") or any(character in filename for character in ("/", "\\", ":", "\x00")):
        raise ValueError("received filename must be a basename without path components")
    return (filename, size, compressed_size, checksum, count), number, bytes(packet[start:end])


class SectionReceiver:
    """Collect one file in any order; never retain a section with a bad CRC."""

    def __init__(self):
        self.metadata = None
        self.sections = {}

    @property
    def complete(self):
        return self.metadata is not None and len(self.sections) == self.metadata[4]

    def add_packet(self, packet):
        metadata, number, payload = unpack_section(packet)
        if self.metadata is not None and metadata != self.metadata:
            raise ValueError("sections belong to different files; receive only one file at a time")
        if number in self.sections:
            if self.sections[number] != payload:
                raise SectionChecksumError("conflicting duplicate section; retry this section")
            return False
        if sum(map(len, self.sections.values())) + len(payload) > metadata[2]:
            raise SectionChecksumError("section payloads exceed the compressed file size")
        self.metadata = metadata
        self.sections[number] = payload
        return True

    def result(self):
        if self.metadata is None:
            raise ValueError("no valid file sections received")
        filename, size, compressed_size, checksum, count = self.metadata
        if not self.complete:
            raise ValueError(
                f"only received {len(self.sections)} of {count} sections, "
                "please provide all sections in the input files"
            )
        compressed = b"".join(self.sections[number] for number in range(1, count + 1))
        if len(compressed) != compressed_size:
            raise ChecksumError("compressed file size mismatch")
        name = filename.encode("utf-8")
        # Reuse the original envelope verifier for bounded decompression,
        # exact file size and the final SHA-256 check after reassembly.
        packet = HEADER.pack(MAGIC, len(name), size, compressed_size, checksum) + name + compressed
        return unpack_file(packet)


def unpack_file(packet):
    """Validate and decompress an envelope, ignoring bitmap row padding."""
    if len(packet) < HEADER.size:
        raise ChecksumError("truncated file header")
    magic, name_size, original_size, compressed_size, checksum = HEADER.unpack_from(packet)
    payload_start = HEADER.size + name_size
    payload_end = payload_start + compressed_size
    if magic != MAGIC or not name_size or payload_end > len(packet):
        raise ChecksumError("invalid or truncated file envelope")
    try:
        filename = bytes(packet[HEADER.size:payload_start]).decode("utf-8")
        # Bound decompression to the advertised file size plus one byte so
        # an incorrect size cannot silently truncate or expand the result.
        decompressor = zlib.decompressobj()
        data = decompressor.decompress(bytes(packet[payload_start:payload_end]), original_size + 1)
    except (UnicodeError, zlib.error, OverflowError) as error:
        raise ChecksumError("invalid filename or compressed payload") from error
    if (
        len(data) != original_size
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or hashlib.sha256(data).digest() != checksum
    ):
        raise ChecksumError("file size or checksum mismatch")
    # Embedded names must never select an absolute path or escape the current
    # directory, including paths interpreted differently on Windows and Linux.
    if filename in (".", "..") or any(character in filename for character in ("/", "\\", ":", "\x00")):
        raise ValueError("received filename must be a basename without path components")
    return filename, data


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


def decode_image(image):
    """Sample one dotted bitmap into packet bytes, retaining row padding."""
    grayscale = image.convert("L")
    # Threshold only for locating the frame; retain grayscale for sampling.
    bounds = grayscale.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None:
        raise ValueError("no dotted bitmap border found")
    cropped = grayscale.crop(bounds)
    # Scan through the first white block's center, not its blurred corner.
    center_column = first_peak_center(cropped.crop((0, 0, cropped.width, 1)).tobytes())
    center_row = first_peak_center(cropped.crop((0, 0, 1, cropped.height)).tobytes())
    top = cropped.crop((0, center_row, cropped.width, center_row + 1))
    bottom_row = cropped.height - 1 - center_row
    bottom = cropped.crop((0, bottom_row, cropped.width, bottom_row + 1))
    left = cropped.crop((center_column, 0, center_column + 1, cropped.height))
    right_column = cropped.width - 1 - center_column
    right = cropped.crop((right_column, 0, right_column + 1, cropped.height))
    # Independent peak counts discover unknown width/height and allow unequal
    # X/Y scaling. The opposite edges must describe the same cell grid.
    columns = count_border_cells(top.tobytes())
    rows = count_border_cells(left.tobytes())
    if count_border_cells(bottom.tobytes()) != columns or count_border_cells(right.tobytes()) != rows:
        raise ValueError("opposite dotted borders disagree on the grid dimensions")
    if columns < 3 or rows < 3 or cropped.width < columns or cropped.height < rows:
        raise ValueError("bitmap is too small to sample the dotted block grid")
    # One output pixel per cell samples source coordinates near
    # ((column + 0.5) * width / columns, (row + 0.5) * height / rows).
    # NEAREST selects the center instead of averaging adjacent data blocks.
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
        raise ValueError("dotted border does not match the expected sampling grid")
    pixels = grid.crop((1, 1, columns - 1, rows - 1)).tobytes()
    data = bytearray()
    # Read row-major bits most-significant first. Header lengths discard the
    # padding only after this sampled byte stream has passed its checksum.
    for byte_start in range(0, len(pixels), 8):
        value = 0
        byte_pixels = pixels[byte_start:byte_start + 8]
        for pixel in byte_pixels:
            value = (value << 1) | int(pixel == 255)
        data.append(value << (8 - len(byte_pixels)))
    return bytes(data)


def expand_input_files(patterns):
    """Expand quoted Windows globs as well as shell-expanded Linux paths."""
    paths = []
    for pattern in patterns:
        matches = [pattern] if Path(pattern).is_file() else sorted(glob.glob(pattern))
        if not matches:
            raise ValueError(f"no input files match {pattern}")
        paths.extend(Path(match) for match in matches)
    return list(dict.fromkeys(path.resolve() for path in paths))


def warn_section(error):
    print(f"warning: {error}; please retry this section", file=sys.stderr, flush=True)


def receive_clipboard(receiver):
    """Wait for new bitmap contents; keep good sections across retries."""
    last_signature = None
    announced = False
    while not receiver.complete:
        image = ImageGrab.grabclipboard()
        if isinstance(image, Image.Image):
            with image:
                signature = (image.mode, image.size, hashlib.sha256(image.tobytes()).digest())
                if signature != last_signature:
                    last_signature = signature
                    announced = True
                    print("decoding clipboard...", file=sys.stderr, flush=True)
                    try:
                        packet = decode_image(image)
                        added = receiver.add_packet(packet)
                    except (ChecksumError, ValueError) as error:
                        warn_section(error)
                    else:
                        if added and not receiver.complete:
                            filename, _, _, _, count = receiver.metadata
                            _, number, _ = unpack_section(packet)
                            print(
                                f"received file {filename} section {number} of {count}.  "
                                "waiting for new bitmap on the clipboard",
                                file=sys.stderr, flush=True,
                            )
        elif not announced:
            print("waiting for bitmap on the clipboard", file=sys.stderr, flush=True)
            announced = True
        if not receiver.complete:
            time.sleep(0.5)


def confirm_overwrite(path):
    """Ask before replacing an output file; EOF safely cancels the save."""
    while True:
        try:
            answer = input(f"Overwrite file {path}?  Y / n ").strip().casefold()
        except EOFError:
            return False
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "filename", nargs="*", help="input bitmap filenames or glob patterns (default: clipboard)"
    )
    parser.add_argument(
        "-O", "--output", type=Path, help="output filename (default: received filename)"
    )
    args = parser.parse_args()

    try:
        paths = expand_input_files(args.filename)
        if args.output is not None and args.output.resolve() in paths:
            parser.error("output filename must be different from the input filename")
        receiver = SectionReceiver()
        if paths:
            for path in paths:
                try:
                    with Image.open(path) as image:
                        packet = decode_image(image)
                except ValueError as error:
                    warn_section(error)
                    continue
                try:
                    receiver.add_packet(packet)
                except SectionChecksumError as error:
                    warn_section(error)
                else:
                    metadata, number, _ = unpack_section(packet)
                    print(f"{path.name} : part {number} of {metadata[4]}", file=sys.stderr, flush=True)
        else:
            receive_clipboard(receiver)
        filename, received_data = receiver.result()
        output = args.output if args.output is not None else Path(filename)
        if output.resolve() in paths:
            parser.error("output filename must be different from the input bitmap filename")
        try:
            with output.open("xb") as destination:
                destination.write(received_data)
        except FileExistsError:
            if not confirm_overwrite(output):
                return
            output.write_bytes(received_data)
        if args.output is None:
            print(f"saved to file {filename} , {len(received_data)} bytes")
        else:
            print(f"saved {filename} to {output}")
    except ChecksumError:
        parser.exit(1, "checksum failure, please try again\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        parser.exit(130, "\n")


if __name__ == "__main__":
    main()