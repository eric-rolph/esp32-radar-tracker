# ESP32-S3 ProS3 - HLK-LD2450 Radar Tracker
# CORRECT PROTOCOL - Basic mode (AA FF 03 00 ... 55 CC)
# Full screen display with data-driven sweep

import time, math
import board, busio, neopixel
import adafruit_ssd1306

# Hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=8192, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("HLK-LD2450 Radar - Basic Protocol")

# Protocol - Basic mode per official spec
SYNC = b"\xAA\xFF\x03\x00"
FOOTER = b"\x55\xCC"
FRAME_SIZE = 30

def _s16_le(b0, b1):
    """Convert little-endian signed int16 per LD2450 protocol
    Protocol spec: highest bit 1=positive, 0=negative (inverted from standard)
    """
    v = b0 | (b1 << 8)
    # Per protocol: if highest bit is 1, value is positive
    # If highest bit is 0, negate the value
    if v & 0x8000:
        return v - 0x8000  # Positive: remove sign bit
    else:
        return -v if v != 0 else 0  # Negative: negate the value

# Display - Full screen
CX, CY = 64, 63
RADII = [20, 40, 60]

def map_xy(x_mm, y_mm):
    """Map radar coords to full screen"""
    sx = int(max(0, min(127, (x_mm + 3000) * 127 / 6000)))
    sy = int(max(0, min(63, 63 - (y_mm * 63 / 6000))))
    return sx, sy

targets = []
buffer = bytearray()
last_draw = time.monotonic()
bytes_in = 0
frames_ok = 0
color_wheel = 0

def draw_dotted_circle(cx, cy, r):
    steps = int(r * 6.28)
    for i in range(0, steps, 3):
        a = (i / steps) * 2 * math.pi
        x = int(cx + r * math.cos(a))
        y = int(cy + r * math.sin(a))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_display():
    global color_wheel
    
    oled.fill(0)
    
    # Draw grid
    for r in RADII:
        draw_dotted_circle(CX, CY, r)
    oled.line(0, CY, 127, CY, 1)
    
    # Count active targets
    active = 0
    closest = 999.0
    
    for x_mm, y_mm, age, idx in targets:
        if age > 10:
            continue
        
        dist = math.sqrt(x_mm * x_mm + y_mm * y_mm) / 1000.0
        if dist < closest:
            closest = dist
        active += 1
        
        # Draw sweep line to target (if recent)
        if age < 3:
            angle = math.atan2(-y_mm, -x_mm)
            angle_deg = math.degrees(angle) + 90
            if 0 <= angle_deg <= 180:
                for r in range(0, RADII[-1] + 1, 2):
                    a = math.radians(angle_deg - 90)
                    x = int(CX + r * math.cos(a))
                    y = int(CY + r * math.sin(a))
                    if 0 <= x < 128 and 0 <= y < 64:
                        oled.pixel(x, y, 1)
        
        # Draw target marker
        sx, sy = map_xy(x_mm, y_mm)
        if idx == 0:  # Primary - filled square
            oled.fill_rect(sx-2, sy-2, 5, 5, 1)
        elif idx == 1:  # Secondary - hollow square
            oled.rect(sx-2, sy-2, 5, 5, 1)
        else:  # Tertiary - cross
            oled.line(sx-2, sy, sx+2, sy, 1)
            oled.line(sx, sy-2, sx, sy+2, 1)
    
    # Status (no title text)
    if active > 0:
        oled.text("%.1fm [%d]" % (closest, active), 70, 56, 1)
        pixel[0] = (50, 0, 0)  # Red
    else:
        # Rainbow color wheel when no targets
        r = int((1 + math.sin(color_wheel * 0.05)) * 25)
        g = int((1 + math.sin(color_wheel * 0.05 + 2.1)) * 25)
        b = int((1 + math.sin(color_wheel * 0.05 + 4.2)) * 25)
        pixel[0] = (r, g, b)
        color_wheel = (color_wheel + 1) % 126
    
    oled.show()

last_stat = time.monotonic()

while True:
    # Read UART
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        if data:
            bytes_in += len(data)
            buffer.extend(data)
    
    # Parse Basic protocol frames (AA FF 03 00 ... 55 CC)
    while len(buffer) >= FRAME_SIZE:
        # Find sync pattern
        sync_idx = -1
        for i in range(len(buffer) - 3):
            if buffer[i:i+4] == SYNC:
                sync_idx = i
                break
        
        if sync_idx < 0:
            # No sync found, keep last few bytes
            if len(buffer) > 100:
                buffer = buffer[-50:]
            break
        
        # Align to sync
        if sync_idx > 0:
            buffer = buffer[sync_idx:]
        
        if len(buffer) < FRAME_SIZE:
            break
        
        # Verify footer
        if buffer[28] == 0x55 and buffer[29] == 0xCC:
            frames_ok += 1
            frame = buffer[0:FRAME_SIZE]
            buffer = buffer[FRAME_SIZE:]
            
            # Parse 3 targets (8 bytes each, starting at offset 4)
            new_targets = []
            for t_idx in range(3):
                offset = 4 + (t_idx * 8)
                
                # Per protocol spec:
                # Bytes 0-1: X coordinate (signed int16, little-endian)
                # Bytes 2-3: Y coordinate (signed int16, little-endian)
                # Bytes 4-5: Speed (signed int16, little-endian)
                # Bytes 6-7: Distance resolution (uint16, little-endian)
                
                x = _s16_le(frame[offset], frame[offset + 1])
                y = _s16_le(frame[offset + 2], frame[offset + 3])
                # speed = _s16_le(frame[offset + 4], frame[offset + 5])  # Not used for display
                # resolution = frame[offset + 6] | (frame[offset + 7] << 8)
                
                # Target exists if not all zeros
                if x != 0 or y != 0:
                    dist = int(math.sqrt(x * x + y * y))
                    # Filter reasonable range (10cm to 8m)
                    if 100 < dist < 8000:
                        new_targets.append((x, y, 0, t_idx))
            
            # Age existing targets
            aged = [(x, y, age + 1, i) for x, y, age, i in targets if age < 15]
            
            # Merge: keep new, add non-duplicate aged
            targets = new_targets[:]
            for old in aged:
                ox, oy, oa, oi = old
                dup = False
                for nx, ny, _, _ in new_targets:
                    if math.sqrt((ox - nx)**2 + (oy - ny)**2) < 300:  # 300mm threshold
                        dup = True
                        break
                if not dup:
                    targets.append(old)
            
            targets = targets[:10]  # Max 10 targets
        else:
            # Invalid footer, skip 2 bytes and resync
            buffer = buffer[2:]
    
    # Update display at 20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now
    
    # Status report every second
    if now - last_stat > 1.0:
        print("RX {:5d} B/s  frames {:3d}/s  targets {:d}".format(
            bytes_in, frames_ok, len([t for t in targets if t[2] < 5])))
        bytes_in = 0
        frames_ok = 0
        last_stat = now
    
    time.sleep(0.001)
