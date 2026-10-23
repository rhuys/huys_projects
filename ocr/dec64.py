"""Decode files copied to the clipboard which were encoded with `ocr.enc64`.

This module provides functions to decode individual parts of a file from
base64-encoded clipboard text, validate metadata, track and assemble
ordered parts, and save the reconstructed file to disk.
"""

import base64
import binascii
import gzip
import hashlib
from pathlib import Path
import struct
import sys
import time
import zlib


MAGIC = b"B64F"
VERSION = 3
HEADER_FORMAT = ">4sBBIIQQ32sIH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
POLL_INTERVAL = 0.2


def decode_part(text: str) -> tuple[dict[str, str | bool | int], bytes] | None:
	"""Decode a clipboard frame, ignoring text that is not a valid package."""
	try:
		encoded = "".join(text.split()).encode("ascii")
		frame = base64.b64decode(encoded, validate=True)
	except (UnicodeEncodeError, binascii.Error, ValueError):
		return None

	if len(frame) < HEADER_SIZE:
		return None

	try:
		(
			magic,
			version,
			flags,
			part_number,
			part_count,
			payload_size,
			file_size,
			checksum,
			part_checksum,
			filename_length,
		) = struct.unpack_from(HEADER_FORMAT, frame)
	except struct.error:
		return None
	if magic != MAGIC or version != VERSION or flags & ~1:
		return None

	filename_start = HEADER_SIZE
	filename_end = filename_start + filename_length
	if filename_end > len(frame):
		return None

	try:
		filename = frame[filename_start:filename_end].decode("utf-8")
	except UnicodeDecodeError:
		return None
	metadata: dict[str, str | bool | int] = {
		"filename": filename,
		"zip_used": bool(flags & 1),
		"checksum_algorithm": "sha256",
		"checksum": checksum.hex(),
		"part_checksum": part_checksum,
		"payload_size": payload_size,
		"file_size": file_size,
		"part_number": part_number,
		"part_count": part_count,
	}
	if not _valid_metadata(metadata):
		return None

	return metadata, frame[filename_end:]


def _valid_metadata(metadata: dict) -> bool:
	filename = metadata.get("filename")
	checksum = metadata.get("checksum")
	part_checksum = metadata.get("part_checksum")
	part_number = metadata.get("part_number")
	part_count = metadata.get("part_count")
	return (
		isinstance(filename, str)
		and bool(filename)
		and isinstance(metadata.get("zip_used"), bool)
		and metadata.get("checksum_algorithm") == "sha256"
		and isinstance(checksum, str)
		and len(checksum) == 64
		and all(character in "0123456789abcdefABCDEF" for character in checksum)
		and isinstance(part_checksum, int)
		and not isinstance(part_checksum, bool)
		and 0 <= part_checksum <= 0xFFFFFFFF
		and isinstance(metadata.get("payload_size"), int)
		and not isinstance(metadata.get("payload_size"), bool)
		and metadata["payload_size"] >= 0
		and isinstance(metadata.get("file_size"), int)
		and not isinstance(metadata.get("file_size"), bool)
		and metadata["file_size"] >= 0
		and isinstance(part_count, int)
		and not isinstance(part_count, bool)
		and part_count > 0
		and isinstance(part_number, int)
		and not isinstance(part_number, bool)
		and 1 <= part_number <= part_count
	)


class PartReceiver:
	"""Track ordered parts and retain earlier parts when the latest fails."""

	def __init__(self) -> None:
		self.metadata: dict[str, str | bool | int] | None = None
		self.parts: list[bytes] = []

	def clear(self) -> None:
		self.metadata = None
		self.parts.clear()

	def receive(
		self, metadata: dict[str, str | bool | int], payload: bytes
	) -> tuple[dict[str, str | bool | int], bytes] | None:
		part_number = metadata["part_number"]
		assert isinstance(part_number, int)
		part_checksum = metadata.get("part_checksum")
		if not isinstance(part_checksum, int) or zlib.crc32(payload) & 0xFFFFFFFF != part_checksum:
			print("checksum failed, please retry")
			return None
		expected = len(self.parts) + 1

		if self.metadata is None:
			if part_number != 1:
				print(f"Expected part 1; ignoring part {part_number}.")
				return None
			self.metadata = metadata
		elif not self._same_file(metadata):
			if part_number != 1:
				print(f"Expected part 1; ignoring part {part_number}.")
				return None
			self.clear()
			self.metadata = metadata
		elif part_number == 1:
			self.clear()
			self.metadata = metadata
		elif part_number < expected:
			del self.parts[part_number - 1 :]
		elif part_number > expected:
			print(f"Expected part {expected}; ignoring part {part_number}.")
			return None

		self.parts.append(payload)
		part_count = metadata["part_count"]
		filename = metadata["filename"]
		assert isinstance(part_count, int) and isinstance(filename, str)
		print(f"received file {filename}, part {part_number} of {part_count}")

		if len(self.parts) < part_count:
			return None

		assembled = b"".join(self.parts)
		expected_size = metadata["payload_size"]
		expected_checksum = metadata["checksum"]
		assert isinstance(expected_size, int) and isinstance(expected_checksum, str)
		if (
			len(assembled) != expected_size
			or hashlib.sha256(assembled).hexdigest() != expected_checksum
		):
			self.parts.pop()
			print("checksum failed, please retry")
			return None

		return metadata, assembled

	def _same_file(self, metadata: dict[str, str | bool | int]) -> bool:
		if self.metadata is None:
			return False
		return all(
			self.metadata.get(key) == value
			for key, value in metadata.items()
			if key not in {"part_number", "part_count", "part_checksum"}
		) and self.metadata.get("part_count") == metadata.get("part_count")


def save_file(
	metadata: dict[str, str | bool | int],
	payload: bytes,
	input_fn=input,
) -> bool:
	"""Verify/decompress the payload and write it in the current directory."""
	filename = metadata["filename"]
	compressed = metadata["zip_used"]
	expected_size = metadata["file_size"]
	assert isinstance(filename, str)
	assert isinstance(compressed, bool)
	assert isinstance(expected_size, int)

	try:
		file_data = gzip.decompress(payload) if compressed else payload
	except (OSError, EOFError, zlib.error) as exc:
		print(f"Could not decode {filename}: {exc}")
		return False
	if len(file_data) != expected_size:
		print(f"Could not decode {filename}: file size does not match.")
		return False

	output_path = Path(filename).name
	if not output_path:
		print("Could not save file: invalid filename.")
		return False
	path = Path(output_path)
	if path.exists():
		answer = input_fn(
			f"File {path} already exists. Do you want to overwrite the file Y/n? "
		).strip().lower()
		if answer not in {"", "y", "yes"}:
			print(f"Skipped saving {path}.")
			return False

	try:
		path.write_bytes(file_data)
	except OSError as exc:
		print(f"Could not save {path}: {exc}")
		return False
	print(f"Saved {path} ({len(file_data)} bytes).")
	return True


def run() -> None:
	"""Wait for new clipboard frames and save complete files."""
	import pyperclip

	receiver = PartReceiver()
	previous_clipboard = None
	print("Waiting for encoded file data in the clipboard. Press Ctrl+C to stop.")
	while True:
		clipboard = pyperclip.paste()
		if clipboard != previous_clipboard:
			previous_clipboard = clipboard
			decoded = decode_part(clipboard)
			if decoded is not None:
				metadata, payload = decoded
				completed = receiver.receive(metadata, payload)
				if completed is not None:
					save_file(*completed)
					receiver.clear()
		time.sleep(POLL_INTERVAL)


def main() -> None:
	try:
		run()
	except KeyboardInterrupt:
		print("\nStopped.")
	except (OSError, RuntimeError) as exc:
		print(f"Clipboard error: {exc}", file=sys.stderr)


if __name__ == "__main__":
	main()

