"""Decode files encoded with `ocr.enc64` from clipboard text or image files.

With no options, dec64 waits for encoded data in the clipboard. Use
``dec64 -i FILENAME`` to decode a packet from a .txt file or OCR an image file.
Use ``dec64 -h`` to show this description and the available options.
"""

import argparse
import base64
import binascii
import gzip
import hashlib
from functools import lru_cache
from pathlib import Path
import struct
import sys
import time
import zlib
import pyperclip
from PIL import Image, ImageGrab  # pip install Pillow

MAGIC = b"B64F"
VERSION = 3
HEADER_FORMAT = ">4sBBIIQQ32sIH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
POLL_INTERVAL = 0.2
BASE64_CHARACTERS = frozenset(
	"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)


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


def merge_same_line_results(result):
	"""Combine OCR detections that appear on the same visual line."""
	if not result:
		return []

	items = []
	for box, text, *_ in result:
		if not text:
			continue
		xs = [point[0] for point in box]
		ys = [point[1] for point in box]
		items.append((sum(ys) / len(ys), min(xs), text))

	items.sort(key=lambda item: (item[0], item[1]))
	lines = []
	for center_y, left, text in items:
		if not lines or abs(center_y - lines[-1]["y"]) > 12:
			lines.append({"y": center_y, "parts": [(left, text)]})
		else:
			lines[-1]["parts"].append((left, text))

	merged_lines = []
	for line in lines:
		line["parts"].sort(key=lambda entry: entry[0])
		merged_lines.append(" ".join(text for _, text in line["parts"]))
	return merged_lines


@lru_cache(maxsize=1)
def _ocr_engine():
	from rapidocr_onnxruntime import RapidOCR

	return RapidOCR(width_height_ratio=-1)


def recognize_image(img: Image.Image) -> str:
	"""Recognize and return text from an image without changing the clipboard."""
	import numpy as np

	result, _ = _ocr_engine()(np.array(img.convert("RGB")))
	return "\n".join(merge_same_line_results(result))


def print_ocr_result(text: str) -> None:
	print("OCR result:")
	print(text if text else "(no text recognized)")


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description=__doc__,
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	parser.add_argument(
		"-i",
		"--input",
		type=Path,
		metavar="FILENAME",
		help="decode a .txt packet file or OCR an image file instead of using the clipboard",
	)
	return parser


def _packet_blocks(text: str):
	lines = []
	for line in text.splitlines():
		candidate = "".join(line.split())
		if candidate and all(character in BASE64_CHARACTERS for character in candidate):
			lines.append(candidate)
		elif lines:
			yield "".join(lines)
			lines.clear()
	if lines:
		yield "".join(lines)


def _process_packet_text(
	text: str, receiver: PartReceiver
) -> bool:
	decoded = decode_part(text)
	if decoded is None:
		return False
	completed = receiver.receive(*decoded)
	if completed is not None:
		save_file(*completed)
		receiver.clear()
	return True


def decode_input_file(path: Path) -> None:
	"""Decode packets from a text file or OCR an image file."""
	if not path.is_file():
		raise FileNotFoundError(path)

	receiver = PartReceiver()
	if path.suffix.lower() == ".txt":
		text = path.read_text(encoding="utf-8-sig")
		valid_packets = sum(
			_process_packet_text(block, receiver) for block in _packet_blocks(text)
		)
	else:
		with Image.open(path) as image:
			print("running ocr... please wait", flush=True)
			text = recognize_image(image)
		print_ocr_result(text)
		valid_packets = int(_process_packet_text(text, receiver))

	if valid_packets == 0:
		print(f"No valid encoded packets found in {path}.")
	elif receiver.parts:
		part_count = receiver.metadata["part_count"]
		print(f"Received {len(receiver.parts)} of {part_count} parts; input ended before completion.")


def _clipboard_sequence_number() -> int | None:
	if sys.platform != "win32":
		return None
	try:
		import ctypes

		sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
	except (AttributeError, OSError):
		return None
	return sequence or None


def run() -> None:
	"""Wait for new clipboard frames and save complete files."""
	receiver = PartReceiver()
	previous_clipboard = None
	previous_sequence = None
	print("Waiting for encoded file data in the clipboard. Press Ctrl+C to stop.")
	while True:
		sequence = _clipboard_sequence_number()
		if sequence is not None:
			if sequence == previous_sequence:
				time.sleep(POLL_INTERVAL)
				continue
			previous_sequence = sequence

		try:
			clipboard_image = ImageGrab.grabclipboard()
		except (OSError, NotImplementedError):
			clipboard_image = None

		clipboard_text = None
		if isinstance(clipboard_image, Image.Image):
			clipboard_key = (
				"image",
				clipboard_image.size,
				clipboard_image.mode,
				hashlib.sha256(clipboard_image.tobytes()).digest(),
			)
			if clipboard_key != previous_clipboard:
				previous_clipboard = clipboard_key
				try:
					print("running ocr... please wait", flush=True)
					clipboard_text = recognize_image(clipboard_image)
					print_ocr_result(clipboard_text)
				except Exception as exc:
					print(f"OCR failed: {exc}", file=sys.stderr)
		else:
			clipboard = pyperclip.paste()
			clipboard_key = ("text", clipboard)
			if clipboard_key != previous_clipboard:
				previous_clipboard = clipboard_key
				clipboard_text = clipboard

		if clipboard_text:
			decoded = decode_part(clipboard_text)
			if decoded is not None:
				metadata, payload = decoded
				completed = receiver.receive(metadata, payload)
				if completed is not None:
					save_file(*completed)
					receiver.clear()
		time.sleep(POLL_INTERVAL)


def main() -> None:
	parser = build_parser()
	args = parser.parse_args()
	try:
		if args.input is None:
			run()
		else:
			decode_input_file(args.input)
	except KeyboardInterrupt:
		print("\nStopped.")
	except (OSError, RuntimeError, ValueError, zlib.error) as exc:
		parser.error(str(exc))


if __name__ == "__main__":
	main()

