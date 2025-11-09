# ESP32-S3 ProS3 - HLK-LD2450 Radar Tracker
# FULL SCREEN version - matches your working code layout
# Advanced protocol (0xAA 0x55)

import time, gc, math
import board, busio, neopixel
import adafruit_ssd1306

# ----------------- Hardware config -----------------
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)

uart = busio.UART(board.IO43, board.IO44, baudrate=256000,
                 receiver_buffer_size=8192, timeout=0)

pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("Full Screen Radar - Advanced Protocol")

# ----------------- Protocol -----------------
SYNC = b"\xAA\x55"

def _s16_le(b0, b1):
    v = b0 | (b1 << 8)
    return v - 0x10000 if v & 0x8000 else v

# ----------------- Display Config - FULL SCREEN -----------------
# Center at bottom of screen like your working code
CX = 64   # Center X
CY = 63   # Bottom of screen

# Range circles - full screen radii
RADII = [20, 40, 60]  # pixels (matches your working code)

# Mapping functions - FULL SCREEN
def map_xy(x_mm, y_mm):
    """Map radar coordinates to FULL screen
    X: -3000 to +3000mm -> 0 to 127 pixels (full width)
    Y: 0 to 6000mm -> 63 to 0 pixels (full height)
    """
    # X spans full 128 pixel width
    sx = int(max(0, min(127, (x_mm + 3000) * 127 / 6000)))
    
    # Y spans full 64 pixel height, inverted (0mm at bottom)
    sy = int(max(0, min(63, 63 - (y_mm * 63 / 6000))))
    
    return sx, sy

# Target tracking
targets = []
buffer = bytearray()
last_draw = time.monotonic()
frame_count = 0
bytes_in = 0
color_wheel = 0

def draw_dotted_circle(cx, cy, radius):
    """Draw dotted circle"""
    steps = int(radius * 6.28)  # More dots for larger circles
    for i in range(0, steps, 3):  # Every 3rd step
        angle = (i / steps) * 2 * math.pi
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_grid():
    """Draw full-screen grid with range circles"""
    # Draw dotted range circles from bottom center
    for r in RADII:
        draw_dotted_circle(CX, CY, r)
    
    # Draw horizontal baseline
    oled.line(0, CY, 127, CY, 1)

def draw_targets(target_list):
    """Draw targets using full screen coordinates"""
    for (x_mm, y_mm, age, idx) in target_list:
        if age > 10:
            continue
            
        # Map to FULL screen coordinates
        sx, sy = map_xy(x_mm, y_mm)
        
        # Draw target based on index
        if idx == 0:  # Primary - filled square
            oled.fill_rect(sx-2, sy-2, 5, 5, 1)
        elif idx == 1:  # Secondary - hollow square
            oled.rect(sx-2, sy-2, 5, 5, 1)
        else:  # Tertiary - cross
            oled.line(sx-2, sy, sx+2, sy, 1)
            oled.line(sx, sy-2, sx, sy+2, 1)

def wheel(n):
    """Color wheel for NeoPixel"""
    n %= 255
    if n < 85:   return (255-n*3, n*3, 0)
    if n < 170:  n-=85; return (0, 255-n*3, n*3)
    n-=170;      return (n*3, 0, 255-n*3)

def draw_display():
    """Draw complete full-screen radar"""
    global color_wheel
    
    # Clear screen
    oled.fill(0)
    
    # Draw grid
    draw_grid()
    
    # Draw targets
    active_count = 0
    closest_dist = 999.0
    
    for target_data in targets:
        x_mm, y_mm, age, idx = target_data
        
        if age < 5:
            dist = math.sqrt(x_mm * x_mm + y_mm * y_mm) / 1000.0
            if dist < closest_dist:
                closest_dist = dist
            active_count += 1
    
    draw_targets(targets)
    
    # Title
    oled.text("M314", 0, 0, 1)
    
    # Status at bottom
    if active_count > 0:
        # Show distance and count
        status = "%.1fm [%d]" % (closest_dist, active_count)
        oled.text(status, 70, 56, 1)
        pixel[0] = (50, 0, 0)  # Red when targets
    else:
        pixel[0] = wheel(color_wheel)
        color_wheel = (color_wheel + 3) % 255
    
    oled.show()

# Main loop
last_stat = time.monotonic()
frames_ok = 0

while True:
    # Read UART
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        bytes_in += len(data)
        buffer.extend(data)

    # Process frames - Advanced protocol (0xAA 0x55)
    while len(buffer) >= 10:
        try:
            idx = buffer.index(SYNC)
        except ValueError:
            buffer = bytearray()
            break

        if idx > 0:
            buffer = buffer[idx:]

        if len(buffer) < 6:
            break

        # Get frame length
        length = buffer[2] | (buffer[3] << 8)

        if length < 10 or length > 512:
            buffer = buffer[2:]
            continue

        if len(buffer) < length:
            break

        frame = buffer[0:length]
        buffer = buffer[length:]

        # Parse frame for targets
        frames_ok += 1
        new_targets = []

        # Extract targets from payload (starts at byte 6)
        # First byte is count, then x,y,v triplets (6 bytes each)
        if len(frame) > 7:
            count = min(3, frame[6])
            offset = 7
            
            for target_idx in range(count):
                if offset + 6 <= len(frame) - 2:
                    x = _s16_le(frame[offset], frame[offset + 1])
                    y = _s16_le(frame[offset + 2], frame[offset + 3])
                    # v = _s16_le(frame[offset + 4], frame[offset + 5])  # velocity not used
                    
                    # Filter valid targets
                    dist = int(math.sqrt(x * x + y * y))
                    if 100 < dist < 8000:  # 0.1m to 8m range
                        new_targets.append((x, y, 0, target_idx))
                    
                    offset += 6

        # Age existing targets and merge
        aged_targets = [(x, y, age + 1, idx) for x, y, age, idx in targets if age < 15]
        
        # Merge: keep new targets, add aged ones not overlapping
        targets = new_targets[:]
        for old_target in aged_targets:
            ox, oy, oage, oidx = old_target
            # Check if this old target is close to any new target
            is_duplicate = False
            for nx, ny, _, _ in new_targets:
                dist = math.sqrt((ox - nx)**2 + (oy - ny)**2)
                if dist < 300:  # 300mm threshold
                    is_duplicate = True
                    break
            if not is_duplicate:
                targets.append(old_target)
        
        targets = targets[:10]  # Limit to 10 targets max

    # Update display at 20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now

    # Status report every second
    if now - last_stat > 1.0:
        print("RX {:5d} B/s  frames {:3d}/s".format(bytes_in, frames_ok))
        bytes_in = 0
        frames_ok = 0
        last_stat = now

    time.sleep(0.001)
