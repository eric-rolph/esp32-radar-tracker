"""Unified ESP32-S3 + HLK-LD2450 Radar Tracker for CircuitPython 9.x.

Copy `code.py` and `ld2450.py` to your CIRCUITPY drive root.
Select your OLED display style via DISPLAY_MODE below:
  - "alien"      : Sci-fi motion tracker with dotted range arcs & pulsing blips
  - "sweep"      : Classic rotating radar sweep with distance readout
  - "minimal"    : Clean numeric target list (lowest CPU usage)
  - "diagnostic" : Serial debug telemetry only (works without an OLED attached)

Also streams compact JSON telemetry over USB serial at ~10 Hz so the live
Web Serial Radar Scope (https://eric-rolph.github.io/esp32-radar-tracker/)
plots all 3 targets in real time directly in Chrome/Edge.
"""

import json
import math
import time
import board
import busio
import adafruit_ssd1306

from ld2450 import extract_latest_targets

# --- User Configuration ---
DISPLAY_MODE = "alien"       # "alien" | "sweep" | "minimal" | "diagnostic"
MAX_RANGE_MM = 6000          # 6.0 meters display radius
STALE_TIMEOUT_S = 0.5        # Clear targets if radar UART goes quiet
UART_TX = board.IO43
UART_RX = board.IO44
UART_BAUD = 256000
STREAM_JSON_SERIAL = True    # Compatible with the Web Serial Live Radar Scope

# Optional onboard NeoPixel proximity indicator
try:
    import neopixel
    pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.25)
    pixel.fill((0, 12, 4))
except Exception:
    pixel = None

# Initialize OLED with automatic 0x3D -> 0x3C address fallback
oled = None
if DISPLAY_MODE != "diagnostic":
    i2c = board.STEMMA_I2C()
    for addr in (0x3D, 0x3C):
        try:
            oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=addr)
            print("OLED initialized at 0x{:02X}".format(addr))
            break
        except Exception:
            continue
    if oled is None:
        print("Warning: OLED not found at 0x3D/0x3C; continuing in serial-only mode.")

uart = busio.UART(UART_TX, UART_RX, baudrate=UART_BAUD, receiver_buffer_size=4096, timeout=0)

CX, CY = 64, 54
R_MAX = 48
buf = bytearray()
targets = []
last_frame_t = 0.0
sweep_deg = -60
last_draw = time.monotonic()
last_serial = 0.0


def _draw_arc(radius, step_deg=6):
    for deg in range(-60, 61, step_deg):
        rad = math.radians(deg)
        x = int(CX + radius * math.sin(rad))
        y = int(CY - radius * math.cos(rad))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)


def _draw_line(x0, y0, x1, y1):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for s in range(steps + 1):
        x = int(x0 + (x1 - x0) * s / steps)
        y = int(y0 + (y1 - y0) * s / steps)
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)


def _plot_target(t, idx):
    scale = R_MAX / float(MAX_RANGE_MM)
    px = int(CX + t["x_mm"] * scale)
    py = int(CY - t["y_mm"] * scale)
    if not (2 <= px < 126 and 2 <= py < 62):
        return
    if idx == 0:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx * dx + dy * dy <= 4:
                    oled.pixel(px + dx, py + dy, 1)
    elif idx == 1:
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            oled.pixel(px + dx, py + dy, 1)
    else:
        for d in range(-2, 3):
            oled.pixel(px + d, py, 1)
            oled.pixel(px, py + d, 1)


def render_oled():
    global sweep_deg
    if oled is None:
        return
    oled.fill(0)

    if DISPLAY_MODE == "minimal":
        oled.text("LD2450 TARGETS: {}".format(len(targets)), 0, 0, 1)
        for i, t in enumerate(targets[:3]):
            line = "T{}:{:.2f}m {:+d}cm/s".format(t["id"], t["distance_m"], t["speed_cm_s"])
            oled.text(line[:21], 0, 16 + i * 14, 1)
        if not targets:
            oled.text("Scanning +/-60 deg...", 0, 28, 1)
        oled.show()
        return

    # Cone edges (+/- 60 deg) and 2m / 4m / 6m range arcs
    for deg in (-60, 60):
        rad = math.radians(deg)
        _draw_line(CX, CY, int(CX + R_MAX * math.sin(rad)), int(CY - R_MAX * math.cos(rad)))
    for r in (16, 32, R_MAX):
        _draw_arc(r, step_deg=6 if DISPLAY_MODE == "alien" else 3)

    if DISPLAY_MODE == "sweep":
        rad = math.radians(sweep_deg)
        _draw_line(CX, CY, int(CX + R_MAX * math.sin(rad)), int(CY - R_MAX * math.cos(rad)))
        sweep_deg += 8
        if sweep_deg > 60:
            sweep_deg = -60

    for i, t in enumerate(targets):
        _plot_target(t, i)

    if targets:
        nearest = min(targets, key=lambda item: item["distance_m"])
        oled.text("{:.2f}m".format(nearest["distance_m"]), 0, 0, 1)
        oled.text("N={}".format(len(targets)), 104, 0, 1)
    else:
        oled.text("CLEAR", 0, 0, 1)
    oled.show()


print("ESP32-S3 HLK-LD2450 Tracker ready (mode={})".format(DISPLAY_MODE))

while True:
    now = time.monotonic()
    data = uart.read(256)
    if data:
        buf.extend(data)
        found, latest = extract_latest_targets(buf)
        if found:
            targets = latest
            last_frame_t = now

    if last_frame_t > 0.0 and (now - last_frame_t) > STALE_TIMEOUT_S:
        targets = []
        last_frame_t = 0.0

    if pixel is not None:
        if targets:
            d = min(t["distance_m"] for t in targets)
            if d < 1.2:
                pixel.fill((35, 0, 0))
            elif d < 2.8:
                pixel.fill((28, 16, 0))
            else:
                pixel.fill((0, 25, 10))
        else:
            pixel.fill((0, 6, 3))

    if STREAM_JSON_SERIAL and (now - last_serial) >= 0.1:
        last_serial = now
        payload = [[t["x_mm"], t["y_mm"], t["speed_cm_s"], round(t["distance_m"], 2)] for t in targets]
        print(json.dumps({"ld2450": payload}))

    if (now - last_draw) >= 0.066:
        last_draw = now
        render_oled()
    time.sleep(0.01)
