"""Bounded validation of browser-generated PNG evidence, without extra runtime dependencies."""
import struct
import zlib
from app_config import AppError

MAX_PNG_BYTES = 32 * 1024 * 1024


def validate_png(data):
    if len(data) > MAX_PNG_BYTES or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise AppError('Expected a PNG of at most 32 MiB.')
    pos, width, height, has_data = 8, 0, 0, False
    while pos + 12 <= len(data):
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 8 + size
        if end + 4 > len(data) or zlib.crc32(data[pos + 4:end]) & 0xffffffff != struct.unpack('>I', data[end:end + 4])[0]:
            raise AppError('Incomplete or corrupt PNG.')
        if pos == 8:
            if kind != b'IHDR' or size != 13: raise AppError('Missing PNG header.')
            width, height = struct.unpack('>II', data[pos + 8:pos + 16])
            if not 1 <= width <= 8192 or not 1 <= height <= 65535 or width * height > 100_000_000:
                raise AppError('PNG dimensions exceed the evidence limit.')
        if kind == b'IDAT': has_data = True
        if kind == b'IEND':
            if size or end + 4 != len(data) or not has_data: raise AppError('Invalid PNG end.')
            return width, height
        pos = end + 4
    raise AppError('Incomplete PNG.')
