"""Versioned file envelope shared by the bitmap encoder and decoder."""

import hashlib
import struct
import zlib


MAGIC = b"BITENC01"
HEADER = struct.Struct(">8sHQQ32s")


class ChecksumError(ValueError):
    """The received file envelope is incomplete, corrupt or unsupported."""


def pack_file(filename, data):
    """Prefix zlib-compressed data with a binary header and UTF-8 basename."""
    name = filename.encode("utf-8")
    if not name or len(name) > 65535:
        raise ValueError("filename must contain between 1 and 65535 UTF-8 bytes")
    compressed = zlib.compress(data, level=9)
    # Network byte order: magic/version, name length, original byte count,
    # compressed byte count, SHA-256 of the original file, then name and data.
    return (
        HEADER.pack(MAGIC, len(name), len(data), len(compressed), hashlib.sha256(data).digest())
        + name
        + compressed
    )


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