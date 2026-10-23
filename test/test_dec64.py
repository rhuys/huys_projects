import base64
import hashlib
import os
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from ocr.dec64 import (
    PartReceiver,
    build_parser,
    decode_input_file,
    decode_part,
    recognize_image,
    run,
    save_file,
)
from ocr.enc64 import make_header


def make_part(metadata: dict, payload: bytes) -> str:
    frame = make_header(metadata) + payload
    return base64.b64encode(frame).decode("ascii")


class DecodePartTests(unittest.TestCase):
    def test_decodes_valid_package_and_ignores_other_clipboard_data(self):
        payload = b"file data"
        metadata = {
            "filename": "example.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(payload).hexdigest(),
            "part_checksum": zlib.crc32(payload) & 0xFFFFFFFF,
            "payload_size": len(payload),
            "file_size": len(payload),
            "part_number": 1,
            "part_count": 1,
        }

        self.assertEqual(decode_part(make_part(metadata, payload)), (metadata, payload))
        self.assertIsNone(decode_part("ordinary clipboard text"))

    def test_recognize_image_merges_detections_in_reading_order(self):
        detections = [
            ([[20, 0], [30, 0], [30, 10], [20, 10]], "second", 0.9),
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "first", 0.9),
            ([[0, 30], [10, 30], [10, 40], [0, 40]], "next line", 0.9),
        ]
        engine = Mock(return_value=(detections, None))
        with patch("ocr.dec64._ocr_engine", return_value=engine):
            text = recognize_image(Image.new("RGB", (32, 42), "white"))

        self.assertEqual(text, "first second\nnext line")


class DirectInputTests(unittest.TestCase):
    def test_help_includes_module_docstring_and_input_option(self):
        help_text = build_parser().format_help()
        self.assertIn("Decode files encoded with `ocr.enc64`", help_text)
        self.assertIn("-i FILENAME", help_text)

    def test_txt_file_can_contain_multiple_packets_and_encoder_prompts(self):
        payload = b"abcdef"
        base_metadata = {
            "filename": "direct.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(payload).hexdigest(),
            "payload_size": len(payload),
            "file_size": len(payload),
            "part_count": 2,
        }
        packet_text = []
        for part_number, part_payload in enumerate((b"ab", b"cdef"), 1):
            metadata = {
                **base_metadata,
                "part_number": part_number,
                "part_checksum": zlib.crc32(part_payload) & 0xFFFFFFFF,
            }
            encoded = base64.b64encode(make_header(metadata) + part_payload).decode("ascii")
            packet_text.append("\n".join(encoded[index:index + 40] for index in range(0, len(encoded), 40)))
        content = f"{packet_text[0]}\n\npart 1 of 2, press anykey to continue\n\n{packet_text[1]}\n"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packets.txt"
            path.write_text(content, encoding="utf-8")
            with patch("ocr.dec64.save_file") as save_file_mock:
                with redirect_stdout(StringIO()):
                    decode_input_file(path)

        save_file_mock.assert_called_once()
        self.assertEqual(save_file_mock.call_args.args[1], payload)

    def test_image_file_is_recognized_then_decoded(self):
        payload = b"image packet"
        metadata = {
            "filename": "image.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(payload).hexdigest(),
            "part_checksum": zlib.crc32(payload) & 0xFFFFFFFF,
            "payload_size": len(payload),
            "file_size": len(payload),
            "part_number": 1,
            "part_count": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet.png"
            Image.new("RGB", (2, 2), "white").save(path)
            output = StringIO()
            with (
                patch("ocr.dec64.recognize_image", return_value=make_part(metadata, payload)) as ocr_mock,
                patch("ocr.dec64.save_file") as save_file_mock,
                redirect_stdout(output),
            ):
                decode_input_file(path)

        ocr_mock.assert_called_once()
        save_file_mock.assert_called_once_with(metadata, payload)
        self.assertIn("OCR result:", output.getvalue())
        self.assertIn(make_part(metadata, payload), output.getvalue())


class PartReceiverTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"abcdef"
        self.metadata = {
            "filename": "example.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(self.payload).hexdigest(),
            "payload_size": len(self.payload),
            "file_size": len(self.payload),
            "part_count": 3,
        }
        self.receiver = PartReceiver()

    def receive(
        self, number: int, payload: bytes, checksum_payload: bytes | None = None
    ):
        checksum_payload = payload if checksum_payload is None else checksum_payload
        metadata = {
            **self.metadata,
            "part_number": number,
            "part_checksum": zlib.crc32(checksum_payload) & 0xFFFFFFFF,
        }
        with redirect_stdout(StringIO()):
            return self.receiver.receive(metadata, payload)

    def test_out_of_order_part_is_ignored_and_failed_part_can_be_retried(self):
        self.assertIsNone(self.receive(1, b"ab"))
        self.assertIsNone(self.receive(3, b"ef"))
        self.assertEqual(self.receiver.parts, [b"ab"])
        self.assertIsNone(self.receive(2, b"cd"))
        self.assertIsNone(self.receive(3, b"XX", b"ef"))
        self.assertEqual(self.receiver.parts, [b"ab", b"cd"])

        completed = self.receive(3, b"ef")
        self.assertEqual(
            completed,
            (
                self.metadata
                | {
                    "part_number": 3,
                    "part_checksum": zlib.crc32(b"ef") & 0xFFFFFFFF,
                },
                self.payload,
            ),
        )

    def test_restarting_from_older_part_discards_later_parts(self):
        self.receive(1, b"ab")
        self.receive(2, b"cd")
        self.assertIsNone(self.receive(2, b"cd"))
        self.assertEqual(self.receiver.parts, [b"ab", b"cd"])
        self.assertEqual(self.receive(3, b"ef")[1], self.payload)

    def test_receiving_part_one_resets_the_buffer(self):
        self.receive(1, b"ab")
        self.receive(2, b"cd")
        self.assertIsNone(self.receive(1, b"ab"))
        self.assertEqual(self.receiver.parts, [b"ab"])


class ClipboardStartupTests(unittest.TestCase):
    def test_processes_valid_clipboard_data_present_at_startup(self):
        payload = b"startup file"
        metadata = {
            "filename": "startup.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(payload).hexdigest(),
            "part_checksum": zlib.crc32(payload) & 0xFFFFFFFF,
            "payload_size": len(payload),
            "file_size": len(payload),
            "part_number": 1,
            "part_count": 1,
        }
        clipboard = Mock()
        clipboard.paste.return_value = make_part(metadata, payload)

        with (
            patch("ocr.dec64.pyperclip", clipboard),
            patch("ocr.dec64._clipboard_sequence_number", return_value=None),
            patch("PIL.ImageGrab.grabclipboard", return_value=None),
            patch("ocr.dec64.save_file") as save_file_mock,
            patch("ocr.dec64.time.sleep", side_effect=KeyboardInterrupt),
            redirect_stdout(StringIO()),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run()

        save_file_mock.assert_called_once_with(metadata, payload)

    def test_recognizes_new_bitmap_clipboard_content_once(self):
        payload = b"bitmap packet"
        metadata = {
            "filename": "bitmap.bin",
            "zip_used": False,
            "checksum_algorithm": "sha256",
            "checksum": hashlib.sha256(payload).hexdigest(),
            "part_checksum": zlib.crc32(payload) & 0xFFFFFFFF,
            "payload_size": len(payload),
            "file_size": len(payload),
            "part_number": 1,
            "part_count": 1,
        }
        image = Image.new("RGB", (2, 2), "white")
        clipboard = Mock()
        recognized_text = make_part(metadata, payload)
        output = StringIO()

        with (
            patch("ocr.dec64.pyperclip", clipboard),
            patch("ocr.dec64._clipboard_sequence_number", side_effect=[1, 1]),
            patch("PIL.ImageGrab.grabclipboard", return_value=image) as image_grab_mock,
            patch("ocr.dec64.recognize_image", return_value=recognized_text) as recognize_mock,
            patch("ocr.dec64.save_file") as save_file_mock,
            patch("ocr.dec64.time.sleep", side_effect=[None, KeyboardInterrupt]),
            redirect_stdout(output),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run()

        recognize_mock.assert_called_once_with(image)
        image_grab_mock.assert_called_once_with()
        save_file_mock.assert_called_once_with(metadata, payload)
        clipboard.paste.assert_not_called()
        self.assertIn("running ocr... please wait", output.getvalue())


class SaveFileTests(unittest.TestCase):
    def test_existing_file_requires_overwrite_confirmation(self):
        metadata = {"filename": "result.bin", "zip_used": False, "file_size": 3}
        original_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with open("result.bin", "wb") as output:
                    output.write(b"old")
                prompts = []

                def confirm(prompt: str) -> str:
                    prompts.append(prompt)
                    return "n"

                with redirect_stdout(StringIO()):
                    self.assertFalse(save_file(metadata, b"new", confirm))
                with open("result.bin", "rb") as output:
                    self.assertEqual(output.read(), b"old")
                self.assertEqual(
                    prompts,
                    ["File result.bin already exists. Do you want to overwrite the file Y/n? "],
                )

                with redirect_stdout(StringIO()):
                    self.assertTrue(save_file(metadata, b"new", Mock(return_value="Y")))
                with open("result.bin", "rb") as output:
                    self.assertEqual(output.read(), b"new")
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()