"""Encode files as wrapped, metadata-bearing Base64 parts."""

import argparse
import binascii
import hashlib
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib


MAGIC = b"B64F"
VERSION = 3
HEADER_FORMAT = ">4sBBIIQQ32sIH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
BYTES_PER_CHUNK = 3 * 8192


def positive_int(value: str) -> int:
    """Parse an argparse integer that must be greater than zero."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", type=Path, help="file to encode")
    parser.add_argument(
        "-w",
        "--width",
        type=positive_int,
        default=None,
        metavar="N",
        help="maximum characters per line (default: terminal width, or 80 if unavailable)",
    )
    parser.add_argument(
        "-l",
        "--lines",
        type=positive_int,
        default=None,
        metavar="N",
        help="maximum lines per part, including the continuation prompt",
    )
    parser.add_argument(
        "-p",
        "--print-summary",
        action="store_true",
        help="print file metadata instead of the encoded parts",
    )
    return parser


def make_header(metadata: dict[str, str | bool | int]) -> bytes:
    filename = metadata["filename"]
    checksum = metadata["checksum"]
    part_checksum = metadata["part_checksum"]
    assert isinstance(filename, str)
    assert isinstance(checksum, str)
    assert isinstance(part_checksum, int)
    filename_bytes = filename.encode("utf-8")
    if len(filename_bytes) > 0xFFFF:
        raise ValueError("filename is too long for the packet header")

    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        VERSION,
        int(metadata["zip_used"]),
        metadata["part_number"],
        metadata["part_count"],
        metadata["payload_size"],
        metadata["file_size"],
        bytes.fromhex(checksum),
        part_checksum,
        len(filename_bytes),
    )
    return header + filename_bytes


def payload_capacity(
    metadata: dict[str, str | bool | int], width: int, max_lines: int
) -> int:
    header = make_header(metadata)
    encoded_capacity = width * max_lines
    binary_capacity = (encoded_capacity // 4) * 3
    return binary_capacity - len(header)


def choose_parts(
    metadata: dict[str, str | bool | int], width: int, max_lines: int | None
) -> tuple[int, int | None]:
    payload_size = metadata["payload_size"]
    assert isinstance(payload_size, int)

    if max_lines is None:
        return 1, None

    one_part_metadata = {
        **metadata,
        "part_number": 1,
        "part_count": 1,
        "part_checksum": 0,
    }
    one_part_capacity = payload_capacity(one_part_metadata, width, max_lines)
    if one_part_capacity < 0:
        raise ValueError("terminal line limit is too small to hold the package header")
    if payload_size <= one_part_capacity:
        return 1, one_part_capacity

    if max_lines < 2:
        raise ValueError("at least two lines per part are needed to show the prompt")

    part_count = 2
    while True:
        last_part_metadata = {
            **metadata,
            "part_number": part_count,
            "part_count": part_count,
            "part_checksum": 0,
        }
        part_capacity = payload_capacity(last_part_metadata, width, max_lines - 1)
        if part_capacity <= 0:
            raise ValueError("terminal line limit is too small to hold the package header")
        needed_parts = max(1, (payload_size + part_capacity - 1) // part_capacity)
        if needed_parts <= part_count:
            return part_count, part_capacity
        part_count = needed_parts


def print_frame(
    header: bytes, payload, payload_length: int, width: int
) -> None:
    carry = b""
    pending = ""

    def emit(data: bytes, final: bool = False) -> None:
        nonlocal carry, pending
        combined = carry + data
        complete_length = (
            len(combined) if final else len(combined) - len(combined) % 3
        )
        if complete_length:
            pending += binascii.b2a_base64(
                combined[:complete_length], newline=False
            ).decode("ascii")
        carry = combined[complete_length:]
        while len(pending) >= width:
            print(pending[:width])
            pending = pending[width:]

    emit(header)
    remaining = payload_length
    while remaining:
        chunk = payload.read(min(BYTES_PER_CHUNK, remaining))
        if not chunk:
            raise OSError("temporary payload ended unexpectedly")
        emit(chunk)
        remaining -= len(chunk)
    emit(b"", final=True)
    if pending:
        print(pending)


def checksum_part(payload, payload_length: int) -> int:
    """Calculate a CRC-32 for the next part without changing stream position."""
    position = payload.tell()
    checksum = 0
    remaining = payload_length
    try:
        while remaining:
            chunk = payload.read(min(BYTES_PER_CHUNK, remaining))
            if not chunk:
                raise OSError("temporary payload ended unexpectedly")
            checksum = zlib.crc32(chunk, checksum)
            remaining -= len(chunk)
    finally:
        payload.seek(position)
    return checksum & 0xFFFFFFFF


def wait_for_key(part_number: int, part_count: int) -> None:
    print(f"part {part_number} of {part_count}, press anykey to continue", flush=True)
    if not sys.stdin.isatty():
        return

    if sys.platform == "win32":
        import msvcrt

        if msvcrt.getch() == b"\x03":
            raise KeyboardInterrupt
    else:
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        previous_settings = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            if sys.stdin.read(1) == "\x03":
                raise KeyboardInterrupt
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous_settings)
    print()


def encode_file(
    path: Path,
    width: int,
    max_lines: int | None,
    compress: bool = False,
    summary_only: bool = False,
) -> dict[str, str | bool | int]:
    """Encode a file into one or more independently framed Base64 parts."""
    original_size = 0
    payload_size = 0
    checksum = hashlib.sha256()
    compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16) if compress else None

    with tempfile.TemporaryFile() as payload:
        with path.open("rb") as source:
            while chunk := source.read(BYTES_PER_CHUNK):
                original_size += len(chunk)
                encoded_input = compressor.compress(chunk) if compressor else chunk
                if encoded_input:
                    payload.write(encoded_input)
                    checksum.update(encoded_input)
                    payload_size += len(encoded_input)

        if compressor:
            final_data = compressor.flush()
            payload.write(final_data)
            checksum.update(final_data)
            payload_size += len(final_data)

        metadata: dict[str, str | bool | int] = {
            "filename": path.name,
            "zip_used": compress,
            "checksum_algorithm": "sha256",
            "checksum": checksum.hexdigest(),
            "payload_size": payload_size,
            "file_size": original_size,
        }
        part_count, part_capacity = choose_parts(metadata, width, max_lines)
        summary = {**metadata, "part_count": part_count}

        if not summary_only:
            payload.seek(0)
            remaining = payload_size
            for part_number in range(1, part_count + 1):
                part_size = remaining if part_capacity is None else min(remaining, part_capacity)
                part_metadata = {
                    **metadata,
                    "part_number": part_number,
                    "part_count": part_count,
                    "part_checksum": checksum_part(payload, part_size),
                }
                print()
                print_frame(make_header(part_metadata), payload, part_size, width)
                print()
                remaining -= part_size
                if part_count > 1 and part_number < part_count:
                    wait_for_key(part_number, part_count)

        return summary


def print_summary(summary: dict[str, str | bool | int]) -> None:
    print(f"Filename: {summary['filename']}")
    print(f"Compressed: {'yes' if summary['zip_used'] else 'no'}")
    print(f"File size: {summary['file_size']} bytes")
    print(f"SHA-256: {summary['checksum']}")
    print(f"Parts: {summary['part_count']}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    width = args.width or max(
        1, shutil.get_terminal_size(fallback=(80, 24)).columns - 3
    )
    lines = args.lines or max(1, shutil.get_terminal_size(fallback=(80, 24)).lines - 3)
    try:
        summary = encode_file(
            args.file, width, lines, True, args.print_summary
        )
        if args.print_summary:
            print_summary(summary)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
    except (OSError, ValueError, zlib.error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()