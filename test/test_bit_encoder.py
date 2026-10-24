import hashlib
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from bit_encoder import bitdec, bitenc
from bit_encoder.bitformat import HEADER, MAGIC, ChecksumError, pack_file, unpack_file


class FileEnvelopeTests(unittest.TestCase):
    def test_header_and_exact_round_trip_with_padding(self):
        filename = "caf\u00e9.bin"
        for data in (b"", b"hello\x00\x00", bytes(range(256))):
            with self.subTest(data_size=len(data)):
                packet = pack_file(filename, data)
                magic, name_size, size, compressed_size, checksum = HEADER.unpack_from(packet)
                self.assertEqual(magic, MAGIC)
                self.assertEqual(name_size, len(filename.encode("utf-8")))
                self.assertEqual(size, len(data))
                self.assertEqual(compressed_size, len(packet) - HEADER.size - name_size)
                self.assertEqual(checksum, hashlib.sha256(data).digest())
                self.assertEqual(unpack_file(packet + bytes(50)), (filename, data))

    def test_compresses_repeated_data(self):
        data = b"repeated data " * 10000
        packet = pack_file("large.bin", data)
        self.assertLess(len(packet), len(data) // 10)
        self.assertEqual(unpack_file(packet), ("large.bin", data))

    def test_rejects_corrupt_checksum_and_compressed_data(self):
        packet = pack_file("file.bin", b"payload")
        for position in (HEADER.size - 1, len(packet) - 1):
            with self.subTest(position=position):
                corrupt = bytearray(packet)
                corrupt[position] ^= 1
                with self.assertRaises(ChecksumError):
                    unpack_file(corrupt)

    def test_rejects_truncated_or_unsupported_packets(self):
        packet = pack_file("file.bin", b"payload")
        for corrupt in (b"", packet[:HEADER.size - 1], packet[:-1], b"INVALID!" + packet[8:]):
            with self.subTest(packet_size=len(corrupt)):
                with self.assertRaises(ChecksumError):
                    unpack_file(corrupt)

    def test_rejects_incorrect_original_size(self):
        packet = pack_file("file.bin", b"payload")
        magic, name_size, size, compressed_size, checksum = HEADER.unpack_from(packet)
        for incorrect_size in (size - 1, size + 1):
            corrupt = HEADER.pack(magic, name_size, incorrect_size, compressed_size, checksum)
            with self.assertRaises(ChecksumError):
                unpack_file(corrupt + packet[HEADER.size:])

    def test_rejects_received_paths(self):
        for filename in ("../file.bin", "/tmp/file.bin", "..\\file.bin", "C:\\file.bin", ".", "..", "bad\x00.bin"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    unpack_file(pack_file(filename, b"payload"))


class BitmapTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source" / "example.bin"
        self.source.parent.mkdir()
        self.bitmap = self.root / "encoded.png"
        self.output = self.root / "restored.bin"

    def encode(self, data):
        self.source.write_bytes(data)
        with patch.object(sys, "argv", ["bitenc", str(self.source), "-O", str(self.bitmap)]):
            bitenc.main()

    def decode(self, options):
        status = StringIO()
        with patch.object(sys, "argv", ["bitdec", *options]), redirect_stdout(status):
            bitdec.main()
        return status.getvalue()

    def test_file_round_trip_and_status(self):
        for data in (b"", bytes(range(256)) + b"\x00\x00", b"large file " * 10000):
            with self.subTest(size=len(data)):
                self.encode(data)
                status = self.decode([str(self.bitmap), "-O", str(self.output)])
                self.assertEqual(self.output.read_bytes(), data)
                self.assertEqual(status, f"received file example.bin , {len(data)} bytes\n")

    def test_default_output_and_existing_file_protection(self):
        self.encode(b"received data")
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.decode([str(self.bitmap)])
            received = Path("example.bin")
            self.assertEqual(received.read_bytes(), b"received data")
            received.write_bytes(b"keep existing data")
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
                self.decode([str(self.bitmap)])
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(received.read_bytes(), b"keep existing data")
        finally:
            os.chdir(previous)

    def test_checksum_failure_does_not_modify_output(self):
        packet = bytearray(pack_file("example.bin", b"received data"))
        packet[HEADER.size - 1] ^= 1
        bitenc.make_image(packet, 80, 3).save(self.bitmap)
        self.output.write_bytes(b"keep existing data")
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            self.decode([str(self.bitmap), "-O", str(self.output)])
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(errors.getvalue(), "checksum failure, please try again\n")
        self.assertEqual(self.output.read_bytes(), b"keep existing data")

    def test_scaled_clipboard_round_trip(self):
        data = bytes(range(256))
        packet = pack_file("example.bin", data)
        image = bitenc.make_image(packet, 80, 3).convert("L")
        image = image.resize((round(image.width * 1.5), round(image.height * 1.5)), Image.Resampling.BILINEAR)
        with patch.object(bitdec.ImageGrab, "grabclipboard", return_value=image):
            status = self.decode(["-O", str(self.output)])
        self.assertEqual(self.output.read_bytes(), data)
        self.assertEqual(status, "received file example.bin , 256 bytes\n")

    def test_graphical_layout_uses_compressed_packet(self):
        data = b"compressible data " * 10000
        self.source.write_bytes(data)
        with (
            patch.object(sys, "argv", ["bitenc", str(self.source)]),
            patch.object(bitenc, "get_screen_size", return_value=(1000, 800)),
            patch.object(bitenc, "display_image") as display,
        ):
            bitenc.main()
        display.call_args.args[0].save(self.bitmap)
        self.decode([str(self.bitmap), "-O", str(self.output)])
        self.assertEqual(self.output.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()