"""Pure-Python HLK-LD2450 24GHz mmWave radar protocol parser.

Compatible with both CircuitPython 9.x on ESP32-S3 and desktop Python 3 for unit tests.
Decodes 30-byte multi-target frames using the HLK-LD2450 sign-magnitude encoding
(bit 15 = 1 for positive values, bit 15 = 0 for negative values).
"""

import math

HEADER = b"\xAA\xFF\x03\x00"
TAIL = b"\x55\xCC"
FRAME_SIZE = 30
NUM_TARGETS = 3


def decode_signed16(lo, hi):
    """Decode HLK-LD2450 16-bit sign-magnitude field."""
    raw = (hi << 8) | lo
    if raw & 0x8000:
        return raw - 0x8000
    return 0 if raw == 0 else -raw


def parse_frame(frame):
    """Parse a single 30-byte HLK-LD2450 frame into a list of target dicts.

    Returns None if the frame header or tail markers are invalid.
    """
    if len(frame) != FRAME_SIZE:
        return None
    if frame[:4] != HEADER or frame[28:30] != TAIL:
        return None

    targets = []
    for i in range(NUM_TARGETS):
        off = 4 + i * 8
        x_mm = decode_signed16(frame[off], frame[off + 1])
        y_mm = decode_signed16(frame[off + 2], frame[off + 3])
        speed_cm_s = decode_signed16(frame[off + 4], frame[off + 5])
        resolution_mm = (frame[off + 7] << 8) | frame[off + 6]
        if x_mm == 0 and y_mm == 0:
            continue
        dist_m = math.sqrt(float(x_mm) * float(x_mm) + float(y_mm) * float(y_mm)) / 1000.0
        angle_deg = math.degrees(math.atan2(float(x_mm), float(y_mm)))
        targets.append({
            "id": i + 1,
            "x_mm": x_mm,
            "y_mm": y_mm,
            "speed_cm_s": speed_cm_s,
            "resolution_mm": resolution_mm,
            "distance_m": dist_m,
            "angle_deg": angle_deg,
        })
    return targets


def extract_latest_targets(buf):
    """Consume complete frames from bytearray `buf` in-place.

    Returns (found_frame, latest_targets_list).
    """
    found = False
    latest = []
    while True:
        idx = buf.find(HEADER)
        if idx < 0:
            if len(buf) > 3:
                del buf[:-3]
            break
        if idx > 0:
            del buf[:idx]
        if len(buf) < FRAME_SIZE:
            break
        frame = bytes(buf[:FRAME_SIZE])
        parsed = parse_frame(frame)
        if parsed is not None:
            found = True
            latest = parsed
            del buf[:FRAME_SIZE]
        else:
            del buf[:1]
    return found, latest
