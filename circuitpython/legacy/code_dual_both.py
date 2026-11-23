# ESP32-S3 ProS3 - DUAL PROTOCOL radar with full screen
# Tries BOTH Basic (0xAA 0xFF) AND Advanced (0xAA 0x55)

import time, math
import board, busio, neopixel
import adafruit_ssd1306

# Hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=8192, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("Dual Protocol Radar")

# Protocols
SYNC_BASIC = b"\xAA\xFF"
SYNC_ADV = b"\xAA\x55"

def _s16_le(b0, b1):
    v = b0 | (b1 << 8)
    return v - 0x10000 if v & 0x8000 else v

# Display
CX, CY = 64, 63
RADII = [20, 40, 60]

def map_xy(x_mm, y_mm):
    sx = int(max(0, min(127, (x_mm + 3000) * 127 / 6000)))
    sy = int(max(0, min(63, 63 - (y_mm * 63 / 6000))))
    return sx, sy

targets = []
buffer = bytearray()
last_draw = time.monotonic()
bytes_in = 0
frames_basic = 0
frames_adv = 0

def draw_dotted_circle(cx, cy, r):
    steps = int(r * 6.28)
    for i in range(0, steps, 3):
        a = (i / steps) * 2 * math.pi
        x = int(cx + r * math.cos(a))
        y = int(cy + r * math.sin(a))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_display():
    oled.fill(0)
    
    # Grid
    for r in RADII:
        draw_dotted_circle(CX, CY, r)
    oled.line(0, CY, 127, CY, 1)
    
    # Targets
    active = 0
    closest = 999.0
    
    for x_mm, y_mm, age, idx in targets:
        if age > 10:
            continue
        
        dist = math.sqrt(x_mm * x_mm + y_mm * y_mm) / 1000.0
        if dist < closest:
            closest = dist
        active += 1
        
        # Draw sweep line to target
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
        
        # Draw target
        sx, sy = map_xy(x_mm, y_mm)
        if idx == 0:
            oled.fill_rect(sx-2, sy-2, 5, 5, 1)
        elif idx == 1:
            oled.rect(sx-2, sy-2, 5, 5, 1)
        else:
            oled.line(sx-2, sy, sx+2, sy, 1)
            oled.line(sx, sy-2, sx, sy+2, 1)
    
    # Status
    if active > 0:
        oled.text("%.1fm [%d]" % (closest, active), 70, 56, 1)
        pixel[0] = (50, 0, 0)
    else:
        pixel[0] = (0, 10, 0)
    
    oled.show()

last_stat = time.monotonic()

while True:
    # Read
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        bytes_in += len(data)
        buffer.extend(data)
    
    # Try BASIC protocol (0xAA 0xFF 0x03 0x00 ... 0x55 0xCC)
    while len(buffer) >= 30:
        try:
            idx = buffer.index(SYNC_BASIC)
        except ValueError:
            break
        
        if idx > 0:
            buffer = buffer[idx:]
        
        if len(buffer) < 30:
            break
        
        # Check for valid Basic frame
        if (buffer[0] == 0xAA and buffer[1] == 0xFF and 
            buffer[2] == 0x03 and buffer[3] == 0x00 and
            buffer[28] == 0x55 and buffer[29] == 0xCC):
            
            frames_basic += 1
            frame = buffer[0:30]
            buffer = buffer[30:]
            
            # Parse targets
            new_targets = []
            for t_idx in range(3):
                offset = 4 + (t_idx * 8)
                x = _s16_le(frame[offset], frame[offset + 1])
                y = _s16_le(frame[offset + 2], frame[offset + 3])
                
                if x != 0 or y != 0:
                    dist = int(math.sqrt(x * x + y * y))
                    if 100 < dist < 8000:
                        new_targets.append((x, y, 0, t_idx))
            
            # Update targets
            aged = [(x, y, age + 1, i) for x, y, age, i in targets if age < 15]
            targets = new_targets[:]
            for old in aged:
                ox, oy, oa, oi = old
                dup = False
                for nx, ny, _, _ in new_targets:
                    if math.sqrt((ox - nx)**2 + (oy - ny)**2) < 300:
                        dup = True
                        break
                if not dup:
                    targets.append(old)
            targets = targets[:10]
        else:
            buffer = buffer[2:]
    
    # Try Advanced protocol (0xAA 0x55)
    while len(buffer) >= 10:
        try:
            idx = buffer.index(SYNC_ADV)
        except ValueError:
            break
        
        if idx > 0:
            buffer = buffer[idx:]
        
        if len(buffer) < 6:
            break
        
        length = buffer[2] | (buffer[3] << 8)
        if length < 10 or length > 512:
            buffer = buffer[2:]
            continue
        
        if len(buffer) < length:
            break
        
        frames_adv += 1
        frame = buffer[0:length]
        buffer = buffer[length:]
        
        # Parse Advanced
        if len(frame) > 7:
            count = min(3, frame[6])
            offset = 7
            new_targets = []
            
            for t_idx in range(count):
                if offset + 6 <= len(frame) - 2:
                    x = _s16_le(frame[offset], frame[offset + 1])
                    y = _s16_le(frame[offset + 2], frame[offset + 3])
                    dist = int(math.sqrt(x * x + y * y))
                    if 100 < dist < 8000:
                        new_targets.append((x, y, 0, t_idx))
                    offset += 6
            
            # Update
            aged = [(x, y, age + 1, i) for x, y, age, i in targets if age < 15]
            targets = new_targets[:]
            for old in aged:
                ox, oy, oa, oi = old
                dup = False
                for nx, ny, _, _ in new_targets:
                    if math.sqrt((ox - nx)**2 + (oy - ny)**2) < 300:
                        dup = True
                        break
                if not dup:
                    targets.append(old)
            targets = targets[:10]
    
    # Display at 20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now
    
    # Status
    if now - last_stat > 1.0:
        print("RX %5d B/s | Basic %3d/s | Adv %3d/s" % (bytes_in, frames_basic, frames_adv))
        bytes_in = 0
        frames_basic = 0
        frames_adv = 0
        last_stat = now
    
    time.sleep(0.001)
