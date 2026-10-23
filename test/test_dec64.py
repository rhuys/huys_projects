import base64
import hashlib
import os
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from ocr.dec64 import PartReceiver, decode_part, run, save_file
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
            patch.dict("sys.modules", {"pyperclip": clipboard}),
            patch("ocr.dec64.save_file") as save_file_mock,
            patch("ocr.dec64.time.sleep", side_effect=KeyboardInterrupt),
            redirect_stdout(StringIO()),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run()

        save_file_mock.assert_called_once_with(metadata, payload)


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