# ESP32-S3 ProS3 - HLK-LD2450 Radar Tracker - DUAL PROTOCOL
# Works with BOTH Basic (0xAA 0xFF) and Advanced (0xAA 0x55) modes
# Alien Motion Tracker Style

import board
import busio
import time
import adafruit_ssd1306
import neopixel
import math

# Initialize hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=8192, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

def s16(b0, b1):
    """Convert two bytes to signed 16-bit integer"""
    v = b0 | (b1 << 8)
    return v - 65536 if v >= 32768 else v

# Display configuration - Alien Tracker style
CX, CY = 64, 35
MAX_RANGE = 6000  # 6 meters
R_MAX = 28
R_RINGS = [9, 18, 28]

# Target tracking
targets = []
buffer = bytearray()
frame_count = 0
last_draw = time.monotonic()
sweep_angle = 0
protocol_mode = None  # Will auto-detect

print("Alien Motion Tracker - Dual Protocol")
print("Auto-detecting radar protocol...")
pixel.fill((10, 10, 0))  # Yellow = detecting

def draw_dotted_circle(cx, cy, radius):
    for angle_deg in range(0, 181, 4):
        rad = math.radians(angle_deg - 90)
        x = int(cx + radius * math.cos(rad))
        y = int(cy + radius * math.sin(rad))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_angle_markers(cx, cy):
    for angle_deg in [0, 45, 90, 135, 180]:
        rad = math.radians(angle_deg - 90)
        for r in range(R_MAX - 4, R_MAX + 1):
            x = int(cx + r * math.cos(rad))
            y = int(cy + r * math.sin(rad))
            if 0 <= x < 128 and 0 <= y < 64:
                oled.pixel(x, y, 1)

def draw_target(x, y, target_idx, age):
    if not (0 <= x < 128 and 0 <= y < 64):
        return
    
    brightness = max(0, min(1, (10 - age) / 10))
    if brightness < 0.3:
        return
    
    if target_idx == 0:  # Primary - filled circle with glow
        for angle in range(0, 360, 30):
            rad = math.radians(angle)
            gx = int(x + 4 * math.cos(rad))
            gy = int(y + 4 * math.sin(rad))
            if 0 <= gx < 128 and 0 <= gy < 64:
                oled.pixel(gx, gy, 1)
        
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx*dx + dy*dy <= 4:
                    bx, by = x + dx, y + dy
                    if 0 <= bx < 128 and 0 <= by < 64:
                        oled.pixel(bx, by, 1)
    
    elif target_idx == 1:  # Secondary - hollow circle
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            gx = int(x + 2 * math.cos(rad))
            gy = int(y + 2 * math.sin(rad))
            if 0 <= gx < 128 and 0 <= gy < 64:
                oled.pixel(gx, gy, 1)
    
    else:  # Tertiary - cross
        for i in range(-2, 3):
            if 0 <= x + i < 128 and 0 <= y < 64:
                oled.pixel(x + i, y, 1)
            if 0 <= x < 128 and 0 <= y + i < 64:
                oled.pixel(x, y + i, 1)

def draw_radar_screen():
    global sweep_angle, targets, protocol_mode
    
    oled.fill(0)
    
    # Draw dotted range rings
    for r in R_RINGS:
        draw_dotted_circle(CX, CY, r)
    
    # Draw angle markers
    draw_angle_markers(CX, CY)
    
    # Draw center dot
    oled.pixel(CX, CY, 1)
    
    # Draw rotating sweep line
    sweep_angle = (sweep_angle + 8) % 180
    rad = math.radians(sweep_angle - 90)
    for r in range(0, R_MAX + 1, 2):
        x = int(CX + r * math.cos(rad))
        y = int(CY + r * math.sin(rad))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)
    
    # Draw all targets
    active_targets = 0
    closest_dist = 999.0
    
    for target_data in targets:
        x_mm, y_mm, age, t_idx = target_data
        
        dist_mm = int(math.sqrt(x_mm * x_mm + y_mm * y_mm))
        dist_m = dist_mm / 1000.0
        
        if dist_m < closest_dist and age < 5:
            closest_dist = dist_m
        
        if dist_mm <= MAX_RANGE:
            active_targets += 1
            
            angle_rad = math.atan2(-y_mm, -x_mm)
            angle_deg = math.degrees(angle_rad) + 90
            
            if 0 <= angle_deg <= 180:
                r = int((dist_mm / MAX_RANGE) * R_MAX)
                
                screen_rad = math.radians(angle_deg - 90)
                px = int(CX + r * math.cos(screen_rad))
                py = int(CY + r * math.sin(screen_rad))
                
                draw_target(px, py, t_idx, age)
    
    # Draw text info at bottom
    oled.fill_rect(0, 56, 128, 8, 0)
    
    if active_targets == 0:
        oled.text("NO CONTACT", 25, 56, 1)
    else:
        oled.text("%.1fm [%d]" % (closest_dist, active_targets), 40, 56, 1)
    
    # Show protocol mode (top left)
    if protocol_mode == "BASIC":
        oled.text("M314-B", 0, 0, 1)
    elif protocol_mode == "ADV":
        oled.text("M314-A", 0, 0, 1)
    else:
        oled.text("M314-?", 0, 0, 1)
    
    oled.show()

def parse_basic_frame(frame):
    """Parse Basic Mode frame (0xAA 0xFF format - 30 bytes)"""
    global targets, protocol_mode
    
    if len(frame) != 30:
        return False
    
    # Verify frame markers
    if frame[2] != 0x03 or frame[3] != 0x00:
        return False
    if frame[28] != 0x55 or frame[29] != 0xCC:
        return False
    
    protocol_mode = "BASIC"
    
    # Parse 3 targets
    new_targets = []
    for i, offset in enumerate([4, 12, 20]):
        x = s16(frame[offset], frame[offset + 1])
        y = s16(frame[offset + 2], frame[offset + 3])
        
        if x != 0 or y != 0:
            dist = int(math.sqrt(x * x + y * y))
            if 500 < dist < 10000:
                new_targets.append((x, y, 0, i))
                print(f"B-T{i+1}: {dist/1000:.2f}m")
    
    # Age existing targets
    aged_targets = [(x, y, age + 1, t_idx) for x, y, age, t_idx in targets if age < 15]
    targets = new_targets + aged_targets
    targets = targets[:10]
    
    return True

def parse_advanced_frame(frame):
    """Parse Advanced Mode frame (0xAA 0x55 format - variable length)"""
    global targets, protocol_mode
    
    if len(frame) < 10:
        return False
    
    # frame[0:2] = 0xAA 0x55
    # frame[2:4] = length (little endian)
    length = frame[2] | (frame[3] << 8)
    
    if len(frame) < length:
        return False
    
    protocol_mode = "ADV"
    
    # Advanced mode payload starts at byte 6
    # Typically contains target data in payload
    # For now, try to extract targets from common payload format
    new_targets = []
    
    # Look for target data patterns in payload
    offset = 6
    target_idx = 0
    
    while offset + 8 <= len(frame) - 2 and target_idx < 3:
        x = s16(frame[offset], frame[offset + 1])
        y = s16(frame[offset + 2], frame[offset + 3])
        
        if x != 0 or y != 0:
            dist = int(math.sqrt(x * x + y * y))
            if 500 < dist < 10000:
                new_targets.append((x, y, 0, target_idx))
                print(f"A-T{target_idx+1}: {dist/1000:.2f}m")
                target_idx += 1
        
        offset += 8
    
    aged_targets = [(x, y, age + 1, t_idx) for x, y, age, t_idx in targets if age < 15]
    targets = new_targets + aged_targets
    targets = targets[:10]
    
    return True

# Main loop
last_status = time.monotonic()
bytes_received = 0

while True:
    # Read UART data
    if uart.in_waiting:
        new_data = uart.read(uart.in_waiting)
        buffer.extend(new_data)
        bytes_received += len(new_data)
    
    # Try to find and parse frames
    while len(buffer) >= 10:
        found_frame = False
        
        # Try Basic Mode (0xAA 0xFF)
        try:
            idx = buffer.index(b'\xAA\xFF')
            if idx >= 0:
                if idx > 0:
                    buffer = buffer[idx:]
                
                if len(buffer) >= 30:
                    frame = buffer[0:30]
                    if parse_basic_frame(frame):
                        buffer = buffer[30:]
                        frame_count += 1
                        found_frame = True
                        break
        except ValueError:
            pass
        
        # Try Advanced Mode (0xAA 0x55)
        if not found_frame:
            try:
                idx = buffer.index(b'\xAA\x55')
                if idx >= 0:
                    if idx > 0:
                        buffer = buffer[idx:]
                    
                    if len(buffer) >= 6:
                        length = buffer[2] | (buffer[3] << 8)
                        if len(buffer) >= length:
                            frame = buffer[0:length]
                            if parse_advanced_frame(frame):
                                buffer = buffer[length:]
                                frame_count += 1
                                found_frame = True
                                break
            except ValueError:
                pass
        
        # No sync found, discard first byte
        if not found_frame:
            buffer = buffer[1:]
            if len(buffer) < 10:
                break
    
    # Update display at ~20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_radar_screen()
        last_draw = now
        
        # Update NeoPixel status
        if len([t for t in targets if t[2] < 5]) > 0:
            pixel.fill((50, 0, 0))  # Red when targets detected
        elif protocol_mode:
            pixel.fill((0, 50, 0))  # Green when protocol detected
        else:
            pixel.fill((10, 10, 0))  # Yellow when searching
    
    # Status report
    if now - last_status > 5.0:
        print(f"Status: {bytes_received} bytes/5s, {frame_count} frames, Mode: {protocol_mode}")
        last_status = now
        bytes_received = 0
        frame_count = 0
    
    time.sleep(0.001)
