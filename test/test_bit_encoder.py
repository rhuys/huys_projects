import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from bit_encoder import bitdec, bitenc
from bit_encoder.bitdec import ChecksumError, unpack_file
from bit_encoder.bitenc import HEADER, MAGIC, pack_file


class DpiAwarenessTests(unittest.TestCase):
    def test_windows_enables_system_dpi_awareness(self):
        with patch.object(sys, "platform", "win32"), patch("ctypes.windll", create=True) as libraries:
            bitenc.enable_dpi_awareness()
        libraries.user32.SetProcessDPIAware.assert_called_once_with()

    def test_non_windows_does_not_call_windows_api(self):
        with patch.object(sys, "platform", "linux"), patch("ctypes.windll", create=True) as libraries:
            bitenc.enable_dpi_awareness()
        self.assertEqual(libraries.mock_calls, [])

    def test_screen_query_enables_dpi_awareness_before_tk(self):
        events = []
        window = Mock()
        window.winfo_screenwidth.return_value = 1920
        window.winfo_screenheight.return_value = 1200
        tkinter = Mock()
        tkinter.TclError = RuntimeError

        def create_window():
            events.append("Tk")
            return window

        tkinter.Tk.side_effect = create_window
        with (
            patch.dict(sys.modules, {"tkinter": tkinter}),
            patch.object(bitenc, "enable_dpi_awareness", side_effect=lambda: events.append("DPI")),
        ):
            self.assertEqual(bitenc.get_screen_size(), (1920, 1200))
        self.assertEqual(events, ["DPI", "Tk"])
        window.destroy.assert_called_once()


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

    def test_graphical_input_path_with_spaces(self):
        source = self.root / "OneDrive - imec" / "Doc1.docx"
        source.parent.mkdir()
        source.write_bytes(b"document data")
        with (
            patch.object(sys, "argv", ["bitenc", str(source)]),
            patch.object(bitenc, "get_screen_size", return_value=(1000, 800)),
            patch.object(bitenc, "display_image") as display,
        ):
            bitenc.main()
        receiver = bitdec.SectionReceiver()
        receiver.add_packet(bitdec.decode_image(display.call_args.args[0]))
        self.assertEqual(receiver.result(), ("Doc1.docx", b"document data"))

    def test_input_read_error_includes_path_and_operation(self):
        errors = StringIO()
        with (
            patch.object(sys, "argv", ["bitenc", str(self.source)]),
            patch.object(bitenc, "get_screen_size", return_value=(1000, 800)),
            patch.object(Path, "read_bytes", side_effect=OSError(22, "Invalid argument")),
            patch.object(bitenc, "display_image") as display,
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as caught,
        ):
            bitenc.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("cannot read input file", errors.getvalue())
        self.assertIn(repr(str(self.source)), errors.getvalue())
        self.assertIn("[Errno 22] Invalid argument", errors.getvalue())
        display.assert_not_called()

    def test_png_output_does_not_enable_dpi_awareness(self):
        with patch.object(bitenc, "enable_dpi_awareness") as enable:
            self.encode(b"PNG without GUI initialization")
        enable.assert_not_called()

    def test_explicit_output_message_names_original_and_destination(self):
        data = b"received bytes"
        self.encode(data)
        status = self.decode([str(self.bitmap), "-O", str(self.output)])
        self.assertEqual(status, f"saved example.bin to {self.output}\n")
        self.assertEqual(self.output.read_bytes(), data)

    def test_explicit_output_requires_overwrite_confirmation(self):
        data = b"replacement data"
        self.encode(data)
        for answers, overwrite in (
            (["n"], False), (["Y"], True), ([""], True),
            (["invalid", "n"], False), ([EOFError()], False),
        ):
            with self.subTest(answers=answers):
                self.output.write_bytes(b"keep existing data")
                with patch("builtins.input", side_effect=answers) as prompt:
                    status = self.decode([str(self.bitmap), "-O", str(self.output)])
                prompt.assert_called_with(f"Overwrite file {self.output}?  Y / n ")
                expected = data if overwrite else b"keep existing data"
                self.assertEqual(self.output.read_bytes(), expected)
                expected_status = f"saved example.bin to {self.output}\n" if overwrite else ""
                self.assertEqual(status, expected_status)

    def test_file_round_trip_and_status(self):
        for data in (b"", bytes(range(256)) + b"\x00\x00", b"large file " * 10000):
            with self.subTest(size=len(data)):
                self.encode(data)
                status = self.decode([str(self.bitmap), "-O", str(self.output)])
                self.assertEqual(self.output.read_bytes(), data)
                self.assertEqual(status, f"received file example.bin , {len(data)} bytes\n")

    def test_default_output_and_overwrite_confirmation(self):
        self.encode(b"received data")
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.decode([str(self.bitmap)])
            received = Path("example.bin")
            self.assertEqual(received.read_bytes(), b"received data")
            for answers, overwrite in (
                (["n"], False), (["N"], False), (["no"], False),
                (["Y"], True), (["yes"], True), ([""], True),
                (["invalid", "n"], False), ([EOFError()], False),
            ):
                with self.subTest(answers=answers):
                    received.write_bytes(b"keep existing data")
                    with patch("builtins.input", side_effect=answers) as prompt, redirect_stderr(StringIO()):
                        status = self.decode([str(self.bitmap)])
                    prompt.assert_called_with("Overwrite file example.bin?  Y / n ")
                    expected = b"received data" if overwrite else b"keep existing data"
                    self.assertEqual(received.read_bytes(), expected)
                    self.assertEqual(bool(status), overwrite)
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

    def test_standalone_scripts_without_sibling_modules(self):
        encoder_directory = self.root / "standalone_encoder"
        decoder_directory = self.root / "standalone_decoder"
        encoder_directory.mkdir()
        decoder_directory.mkdir()
        encoder = encoder_directory / "bitenc.py"
        decoder = decoder_directory / "bitdec.py"
        shutil.copyfile(bitenc.__file__, encoder)
        shutil.copyfile(bitdec.__file__, decoder)
        data = bytes(range(256)) + b"\x00\x00"
        self.source.write_bytes(data)
        for script, directory, options in (
            (encoder, encoder_directory, [str(self.source), "-O", str(self.bitmap)]),
            (decoder, decoder_directory, [str(self.bitmap), "-O", str(self.output)]),
        ):
            result = subprocess.run(
                [sys.executable, "-I", str(script), *options],
                cwd=directory, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), data)

    def encode_sections(self):
        data = random.Random(7).randbytes(1000)
        self.source.write_bytes(data)
        with patch.object(sys, "argv", [
            "bitenc", str(self.source), "-O", str(self.bitmap), "-w", "80", "-h", "80",
        ]):
            bitenc.main()
        return data, sorted(self.root.glob("encoded_*.png"))

    def test_numbered_sections_globs_reverse_order_and_duplicates(self):
        data, paths = self.encode_sections()
        self.assertGreater(len(paths), 1)
        self.assertFalse(self.bitmap.exists())
        self.assertEqual(paths[0].name, "encoded_01.png")
        self.assertEqual(paths[-1].name, f"encoded_{len(paths):02d}.png")
        for inputs in (
            [str(self.root / "encoded_*.png")],
            [str(path) for path in reversed(paths)] + [str(paths[0])],
        ):
            with self.subTest(inputs=inputs):
                status = self.decode([*inputs, "-O", str(self.output)])
                self.assertEqual(self.output.read_bytes(), data)
                self.assertEqual(status, "received file example.bin , 1000 bytes\n")

    def test_input_file_progress_uses_header_part_numbers(self):
        data = bytes(range(256))
        packets = bitenc.pack_sections("example.bin", data, 200)
        paths = []
        for number, packet in enumerate(packets, 1):
            path = self.root / f"test_{number:02d}.png"
            bitenc.make_image(packet, 40, 3).save(path)
            paths.append(path)
        progress = StringIO()
        with redirect_stderr(progress):
            status = self.decode([*map(str, reversed(paths)), "-O", str(self.output)])
        expected = "".join(
            f"test_{number:02d}.png : part {number} of {len(packets)}\n"
            for number in range(len(packets), 0, -1)
        )
        self.assertEqual(progress.getvalue(), expected)
        self.assertEqual(self.output.read_bytes(), data)
        self.assertEqual(status, "received file example.bin , 256 bytes\n")

    def test_missing_sections_does_not_modify_output(self):
        _, paths = self.encode_sections()
        self.output.write_bytes(b"keep existing data")
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            self.decode([str(paths[0]), "-O", str(self.output)])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(
            f"only received 1 of {len(paths)} sections, please provide all sections in the input files",
            errors.getvalue(),
        )
        self.assertEqual(self.output.read_bytes(), b"keep existing data")

    def test_bad_file_section_warns_and_accepts_good_retry(self):
        data, paths = self.encode_sections()
        with Image.open(paths[0]) as image:
            packet = bytearray(bitdec.decode_image(image))
        packet[bitenc.SECTION_HEADER.size - 1] ^= 1
        corrupt = self.root / "corrupt.png"
        bitenc.make_image(packet, 40, 3).save(corrupt)
        errors = StringIO()
        with redirect_stderr(errors):
            self.decode([str(corrupt), *map(str, paths), "-O", str(self.output)])
        self.assertIn("warning: section checksum failure; please retry this section", errors.getvalue())
        self.assertEqual(self.output.read_bytes(), data)

    def test_mixed_files_are_rejected_before_saving(self):
        _, paths = self.encode_sections()
        other = self.root / "other.png"
        packet = bitenc.pack_sections("other.bin", b"different file", 200)[0]
        bitenc.make_image(packet, 40, 3).save(other)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
            self.decode([*map(str, paths), str(other), "-O", str(self.output)])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_clipboard_retry_duplicates_and_out_of_order_sections(self):
        data = random.Random(9).randbytes(1000)
        packets = bitenc.pack_sections("example.bin", data, 200)
        corrupt = bytearray(packets[0])
        corrupt[-1] ^= 1
        sequence = [packets[-1], packets[-1], corrupt, packets[0], packets[0], *packets[1:-1]]
        images = [None] + [bitenc.make_image(packet, 40, 3) for packet in sequence]
        errors = StringIO()

        def check_not_saved_yet(interval):
            self.assertFalse(self.output.exists())

        with (
            patch.object(bitdec.ImageGrab, "grabclipboard", side_effect=images) as grab,
            patch.object(bitdec.time, "sleep", side_effect=check_not_saved_yet),
            redirect_stderr(errors),
        ):
            status = self.decode(["-O", str(self.output)])
        self.assertEqual(grab.call_count, len(images))
        self.assertEqual(self.output.read_bytes(), data)
        self.assertEqual(status, "received file example.bin , 1000 bytes\n")
        self.assertIn("warning: section checksum failure", errors.getvalue())
        self.assertIn(
            f"received file example.bin section {len(packets)} of {len(packets)}.  "
            "waiting for new bitmap on the clipboard",
            errors.getvalue(),
        )
        self.assertEqual(errors.getvalue().count("decoding clipboard..."), len(packets) + 1)

    def test_graphical_sections_are_rendered_on_demand(self):
        data = random.Random(11).randbytes(1000)
        self.source.write_bytes(data)
        with (
            patch.object(sys, "argv", ["bitenc", str(self.source), "-w", "80", "-h", "80"]),
            patch.object(bitenc, "get_screen_size", return_value=(1000, 800)),
            patch.object(bitenc, "display_image") as display,
        ):
            bitenc.main()
        receiver = bitdec.SectionReceiver()
        receiver.add_packet(bitdec.decode_image(display.call_args.args[0]))
        count = display.call_args.kwargs["section_count"]
        self.assertGreater(count, 1)
        render = display.call_args.kwargs["get_section"]
        for index in range(count - 1, 0, -1):
            receiver.add_packet(bitdec.decode_image(render(index)))
        self.assertEqual(receiver.result(), ("example.bin", data))

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


class SectionEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.data = random.Random(5).randbytes(1000)
        self.packets = bitenc.pack_sections("file.bin", self.data, 200)

    def test_packet_capacity_metadata_and_padding(self):
        for number, packet in enumerate(self.packets, 1):
            metadata, received_number, chunk = bitdec.unpack_section(packet + bytes(50))
            self.assertLessEqual(len(packet), 200)
            self.assertEqual(received_number, number)
            self.assertEqual(metadata[0:2], ("file.bin", len(self.data)))
            self.assertEqual(metadata[3], hashlib.sha256(self.data).digest())
            self.assertEqual(metadata[4], len(self.packets))
            self.assertGreater(len(chunk), 0)

    def test_out_of_order_duplicate_sections_and_final_checksum(self):
        receiver = bitdec.SectionReceiver()
        for packet in reversed(self.packets):
            self.assertTrue(receiver.add_packet(packet))
            self.assertFalse(receiver.add_packet(packet))
        self.assertEqual(receiver.result(), ("file.bin", self.data))

    def test_corrupt_metadata_or_payload_cannot_poison_receiver(self):
        for position in (10, bitenc.SECTION_HEADER.size - 1, bitenc.SECTION_HEADER.size, -1):
            with self.subTest(position=position):
                packet = bytearray(self.packets[0])
                packet[position] ^= 1
                receiver = bitdec.SectionReceiver()
                with self.assertRaises(bitdec.SectionChecksumError):
                    receiver.add_packet(packet)
                self.assertIsNone(receiver.metadata)
                self.assertEqual(receiver.sections, {})
                for valid in self.packets:
                    receiver.add_packet(valid)
                self.assertEqual(receiver.result(), ("file.bin", self.data))

    def test_file_checksum_checked_after_valid_section_checksums(self):
        receiver = bitdec.SectionReceiver()
        for packet in self.packets:
            fields = list(bitenc.SECTION_HEADER.unpack_from(packet))
            fields[4] = bytes(32)
            fields[-1] = 0
            tail = packet[bitenc.SECTION_HEADER.size:]
            fields[-1] = bitenc.zlib.crc32(bitenc.SECTION_HEADER.pack(*fields) + tail)
            receiver.add_packet(bitenc.SECTION_HEADER.pack(*fields) + tail)
        with self.assertRaises(ChecksumError):
            receiver.result()

    def test_capacity_must_fit_repeated_header(self):
        with self.assertRaisesRegex(ValueError, "capacity must fit"):
            bitenc.pack_sections("file.bin", self.data, bitenc.SECTION_HEADER.size)

    def test_compression_message_only_above_ten_megabytes(self):
        for size in (10_000_000, 10_000_001):
            with self.subTest(size=size):
                errors = StringIO()
                with redirect_stderr(errors), patch.object(bitenc.zlib, "compress", wraps=bitenc.zlib.compress) as compress:
                    bitenc.pack_sections("large.bin", bytes(size), 20000)
                compress.assert_called_once()
                expected = f"compressing file large.bin with size {size}...\n" if size > 10_000_000 else ""
                self.assertEqual(errors.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()