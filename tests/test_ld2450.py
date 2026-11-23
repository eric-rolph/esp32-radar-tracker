"""Unit tests for the pure-Python HLK-LD2450 radar protocol parser."""
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "circuitpython"))

from ld2450 import HEADER, TAIL, decode_signed16, extract_latest_targets, parse_frame


def _enc_sm16(val: int) -> bytes:
    """Encode signed int into HLK-LD2450 sign-magnitude 16-bit LE."""
    if val >= 0:
        raw = 0x8000 | val
    else:
        raw = abs(val)
    return struct.pack("<H", raw)


def _build_frame(targets):
    body = bytearray()
    for i in range(3):
        if i < len(targets):
            x, y, spd, res = targets[i]
        else:
            x = y = spd = res = 0
        body.extend(_enc_sm16(x))
        body.extend(_enc_sm16(y))
        body.extend(_enc_sm16(spd))
        body.extend(struct.pack("<H", res))
    return HEADER + bytes(body) + TAIL


def test_decode_signed16_sign_magnitude():
    assert decode_signed16(0x00, 0x00) == 0
    assert decode_signed16(0xE8, 0x83) == 1000   # +1000 mm (0x83E8)
    assert decode_signed16(0xE8, 0x03) == -1000  # -1000 mm (0x03E8)
    assert decode_signed16(0x32, 0x80) == 50     # +50 cm/s
    assert decode_signed16(0x32, 0x00) == -50    # -50 cm/s


def test_parse_multi_target_frame():
    frame = _build_frame([
        (-1200, 1600, -45, 360),
        (2000, 3000, 25, 360),
    ])
    targets = parse_frame(frame)
    assert targets is not None
    assert len(targets) == 2

    t1, t2 = targets
    assert t1["x_mm"] == -1200
    assert t1["y_mm"] == 1600
    assert t1["speed_cm_s"] == -45
    assert math.isclose(t1["distance_m"], 2.0, rel_tol=1e-4)
    assert t1["angle_deg"] < 0

    assert t2["x_mm"] == 2000
    assert t2["y_mm"] == 3000
    assert t2["speed_cm_s"] == 25
    assert math.isclose(t2["distance_m"], math.sqrt(2.0**2 + 3.0**2), rel_tol=1e-4)


def test_extract_latest_targets_resyncs_over_noise():
    f1 = _build_frame([(500, 1000, 10, 360)])
    f2 = _build_frame([(-300, 2400, -20, 360)])
    buf = bytearray(b"\x00\x99\xAA\x01" + f1 + b"\xDE\xAD" + f2 + b"\xAA\xFF")
    found, latest = extract_latest_targets(buf)
    assert found is True
    assert len(latest) == 1
    assert latest[0]["x_mm"] == -300
    assert latest[0]["y_mm"] == 2400
    # Trailing partial header retained cleanly for next read
    assert bytes(buf) == b"\xAA\xFF"
