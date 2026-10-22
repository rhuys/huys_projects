"""Print a file as a wrapped Base64 text block."""

import argparse
import binascii
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib


MAGIC = b"B64F\x01"
MAX_HEADER_SIZE = 1024 * 1024


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
        description=(
            "Encode files with metadata or decode and verify previously encoded files."
        )
    )
    parser.add_argument(
        "file",
        type=Path,
        nargs="?",
        help="file to encode, or Base64 input file when decoding (default: stdin)",
    )
    parser.add_argument(
        "-d", "--decode", action="store_true", help="decode and verify Base64 input"
    )
    parser.add_argument(
        "-O",
        "--output",
        type=Path,
        metavar="FILE",
        help="output filename when decoding (default: filename from header)",
    )
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
        metavar="N",
        help="maximum number of lines to print (default: all)",
    )
    parser.add_argument(
        "-z",
        "--zip",
        action="store_true",
        help="gzip-compress the file before Base64 encoding",
    )
    parser.add_argument(
        "-p",
        "--print-summary",
        dest="print_summary",
        action="store_true",
        help="print a summary instead of Base64 output; with --decode, print it after decoding",
    )
    return parser


def print_base64(
    path: Path,
    width: int,
    max_lines: int | None,
    compress: bool = False,
    summary_only: bool = False,
) -> dict[str, str | bool | int]:
    """Frame file data with metadata, then Base64-encode it incrementally."""
    lines_printed = 0
    pending = ""
    base64_carry = b""
    bytes_per_chunk = 3 * 8192
    original_size = 0

    def print_encoded(data: bytes) -> None:
        nonlocal pending, lines_printed
        if summary_only:
            return
        pending += data.decode("ascii")
        while len(pending) >= width and (
            max_lines is None or lines_printed < max_lines
        ):
            print(pending[:width])
            pending = pending[width:]
            lines_printed += 1

    def encode_bytes(data: bytes, final: bool = False) -> None:
        nonlocal base64_carry
        data = base64_carry + data
        complete_length = len(data) if final else len(data) - len(data) % 3
        if complete_length:
            print_encoded(binascii.b2a_base64(data[:complete_length], newline=False))
        base64_carry = data[complete_length:]

    with tempfile.TemporaryFile() as payload:
        checksum = hashlib.sha256()
        payload_size = 0
        compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16) if compress else None

        with path.open("rb") as source:
            chunk = source.read(bytes_per_chunk)
            while chunk:
                original_size += len(chunk)
                encoded_input = compressor.compress(chunk) if compressor else chunk
                if encoded_input:
                    payload.write(encoded_input)
                    checksum.update(encoded_input)
                    payload_size += len(encoded_input)
                chunk = source.read(bytes_per_chunk)

        if compressor:
            final_data = compressor.flush()
            payload.write(final_data)
            checksum.update(final_data)
            payload_size += len(final_data)

        metadata = {
            "filename": path.name,
            "zip_used": compress,
            "checksum_algorithm": "sha256",
            "checksum": checksum.hexdigest(),
            "payload_size": payload_size,
            "file_size": original_size,
        }
        metadata_bytes = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        binary_header = MAGIC + struct.pack(">I", len(metadata_bytes)) + metadata_bytes

        encode_bytes(binary_header)
        if not summary_only:
            payload.seek(0)
            while max_lines is None or lines_printed < max_lines:
                chunk = payload.read(bytes_per_chunk)
                if not chunk:
                    break
                encode_bytes(chunk)
            encode_bytes(b"", final=True)

    if not summary_only and pending and (
        max_lines is None or lines_printed < max_lines
    ):
        print(pending)
    return metadata


def decode_to_file(
    source: io.BufferedReader, output_path: Path | None
) -> dict[str, str | bool | int]:
    """Decode a framed Base64 stream, verify it, then write its payload."""
    with tempfile.TemporaryFile() as decoded:
        carry = b""
        while True:
            chunk = source.read(64 * 1024)
            if not chunk:
                break
            compact = bytes(byte for byte in chunk if byte not in b" \t\r\n\v\f")
            data = carry + compact
            complete_length = len(data) - len(data) % 4
            if complete_length:
                decoded.write(binascii.a2b_base64(data[:complete_length], strict_mode=True))
            carry = data[complete_length:]

        if carry:
            decoded.write(binascii.a2b_base64(carry, strict_mode=True))

        decoded.seek(0)
        prefix = decoded.read(len(MAGIC) + 4)
        if len(prefix) != len(MAGIC) + 4 or prefix[:len(MAGIC)] != MAGIC:
            raise ValueError("input does not contain a supported encoded file")
        header_length = struct.unpack(">I", prefix[len(MAGIC):])[0]
        if header_length > MAX_HEADER_SIZE:
            raise ValueError("encoded metadata header is too large")

        header_bytes = decoded.read(header_length)
        if len(header_bytes) != header_length:
            raise ValueError("encoded metadata header is incomplete")
        metadata = json.loads(header_bytes)
        if not isinstance(metadata, dict):
            raise ValueError("encoded metadata must be a JSON object")

        filename = metadata.get("filename")
        zip_used = metadata.get("zip_used")
        checksum_algorithm = metadata.get("checksum_algorithm")
        checksum = metadata.get("checksum")
        payload_size = metadata.get("payload_size")
        if not isinstance(filename, str) or not filename:
            raise ValueError("encoded metadata has no valid filename")
        if not isinstance(zip_used, bool):
            raise ValueError("encoded metadata has no valid compression flag")
        if checksum_algorithm != "sha256":
            raise ValueError("unsupported checksum algorithm")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError("encoded metadata has no valid SHA-256 checksum")
        if not isinstance(payload_size, int) or isinstance(payload_size, bool) or payload_size < 0:
            raise ValueError("encoded metadata has an invalid payload size")

        payload_start = decoded.tell()
        payload_hash = hashlib.sha256()
        actual_size = 0
        while chunk := decoded.read(64 * 1024):
            payload_hash.update(chunk)
            actual_size += len(chunk)
        if actual_size != payload_size:
            raise ValueError("payload size does not match the metadata")
        if not hmac.compare_digest(payload_hash.hexdigest(), checksum):
            raise ValueError("payload checksum verification failed")

        decoded.seek(payload_start)
        payload_prefix = decoded.read(2)
        if zip_used != (payload_prefix == b"\x1f\x8b"):
            raise ValueError("compression flag does not match the payload")

        file_size = metadata.get("file_size")
        if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
            file_size = None

        safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if safe_filename in {"", ".", ".."}:
            raise ValueError("encoded metadata has an unsafe filename")
        destination = output_path or Path(safe_filename)
        temporary_path: Path | None = None
        actual_file_size = 0
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
            ) as output:
                temporary_path = Path(output.name)
                decoded.seek(payload_start)
                if zip_used:
                    decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
                    while chunk := decoded.read(64 * 1024):
                        file_chunk = decompressor.decompress(chunk)
                        output.write(file_chunk)
                        actual_file_size += len(file_chunk)
                    final_chunk = decompressor.flush()
                    output.write(final_chunk)
                    actual_file_size += len(final_chunk)
                    if not decompressor.eof or decompressor.unused_data:
                        raise ValueError("invalid gzip payload")
                else:
                    while chunk := decoded.read(64 * 1024):
                        output.write(chunk)
                        actual_file_size += len(chunk)
                if file_size is not None and file_size != actual_file_size:
                    raise ValueError("file size does not match the metadata")
            os.replace(temporary_path, destination)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return {
            "filename": filename,
            "zip_used": zip_used,
            "file_size": actual_file_size,
            "checksum": checksum,
        }


def print_summary(summary: dict[str, str | bool | int]) -> None:
    """Print the file metadata in a readable form."""
    print(f"Filename: {summary['filename']}")
    print(f"Compressed: {'yes' if summary['zip_used'] else 'no'}")
    print(f"File size: {summary['file_size']} bytes")
    print(f"SHA-256: {summary['checksum']}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.decode:
            if args.zip:
                parser.error("-z/--zip cannot be used with -d/--decode")
            if args.file is None or str(args.file) == "-":
                summary = decode_to_file(sys.stdin.buffer, args.output)
            else:
                with args.file.open("rb") as source:
                    summary = decode_to_file(source, args.output)
            if args.print_summary:
                print_summary(summary)
        else:
            if args.file is None:
                parser.error("a file is required when encoding")
            if args.output is not None:
                parser.error("-O/--output can only be used with -d/--decode")
            width = args.width or shutil.get_terminal_size(fallback=(80, 24)).columns - 3
            if not args.print_summary:
                print()
            summary = print_base64(
                args.file, width, args.lines, args.zip, args.print_summary
            )
            if args.print_summary:
                print_summary(summary)
            else:
                print()
    except OSError as exc:
        parser.error(str(exc))
    except (ValueError, binascii.Error, zlib.error, json.JSONDecodeError) as exc:
        parser.error(f"could not decode input: {exc}")


if __name__ == "__main__":
    main()