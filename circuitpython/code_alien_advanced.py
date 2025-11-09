# ESP32-S3 ProS3 - HLK-LD2450 Radar Tracker
# Alien Motion Tracker Style - MATCHED TO YOUR WORKING CODE
# Uses YOUR EXACT initialization and Advanced protocol (0xAA 0x55)

import time, gc, math
import board, busio, neopixel
import adafruit_ssd1306

# ----------------- Hardware config (EXACT MATCH to your code) -----------------
# OLED on STEMMA QT (SDA=IO7, SCL=IO9)
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)

# LD2450 UART on IO43/IO44 (ProS3 silk TX/RX header)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000,
                 receiver_buffer_size=8192, timeout=0)

# Onboard NeoPixel (status)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("Alien Motion Tracker - Advanced Protocol")
print("Using YOUR initialization settings")

# ----------------- Protocol (Advanced mode 0xAA 0x55) -----------------
SYNC = b"\xAA\x55"

def _s16_le(b0, b1):
    v = b0 | (b1 << 8)
    return v - 0x10000 if v & 0x8000 else v

# Display config - Alien style
CX, CY = 64, 35
MAX_RANGE = 6000  # 6 meters
R_MAX = 28
R_RINGS = [9, 18, 28]

# Target tracking
targets = []
buffer = bytearray()
sweep_angle = 0
last_draw = time.monotonic()
frame_count = 0
bytes_in = 0

def draw_dotted_circle(cx, cy, radius):
    """Draw dotted circle for range rings"""
    for angle_deg in range(0, 181, 4):
        rad = math.radians(angle_deg - 90)
        x = int(cx + radius * math.cos(rad))
        y = int(cy + radius * math.sin(rad))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_angle_markers(cx, cy):
    """Draw angle markers every 45 degrees"""
    for angle_deg in [0, 45, 90, 135, 180]:
        rad = math.radians(angle_deg - 90)
        for r in range(R_MAX - 4, R_MAX + 1):
            x = int(cx + r * math.cos(rad))
            y = int(cy + r * math.sin(rad))
            if 0 <= x < 128 and 0 <= y < 64:
                oled.pixel(x, y, 1)

def draw_target(x, y, target_idx, age):
    """Draw target blip with Alien style"""
    if not (0 <= x < 128 and 0 <= y < 64):
        return
    
    brightness = max(0, min(1, (10 - age) / 10))
    if brightness < 0.3:
        return
    
    if target_idx == 0:  # Primary - filled circle with glow
        # Glow ring
        for angle in range(0, 360, 30):
            rad = math.radians(angle)
            gx = int(x + 4 * math.cos(rad))
            gy = int(y + 4 * math.sin(rad))
            if 0 <= gx < 128 and 0 <= gy < 64:
                oled.pixel(gx, gy, 1)
        
        # Filled center
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

def draw_display():
    """Draw complete Alien-style radar screen"""
    global sweep_angle, targets
    
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
            
            # Calculate angle
            angle_rad = math.atan2(-y_mm, -x_mm)
            angle_deg = math.degrees(angle_rad) + 90
            
            if 0 <= angle_deg <= 180:
                r = int((dist_mm / MAX_RANGE) * R_MAX)
                
                screen_rad = math.radians(angle_deg - 90)
                px = int(CX + r * math.cos(screen_rad))
                py = int(CY + r * math.sin(screen_rad))
                
                draw_target(px, py, t_idx, age)
    
    # Draw text info
    oled.fill_rect(0, 56, 128, 8, 0)
    
    if active_targets == 0:
        oled.text("NO CONTACT", 25, 56, 1)
    else:
        oled.text("%.1fm [%d]" % (closest_dist, active_targets), 40, 56, 1)
    
    # Title
    oled.text("M314-A", 0, 0, 1)
    
    oled.show()

# Main loop (using your working code's pattern)
last_stat = time.monotonic()
frames_ok = 0

while True:
    # Read UART (like your code does)
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        bytes_in += len(data)
        buffer.extend(data)
    
    # Process frames - look for Advanced protocol (0xAA 0x55)
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
        
        if len(buffer) < length:
            break
        
        frame = buffer[0:length]
        buffer = buffer[length:]
        
        # Parse frame for targets
        frames_ok += 1
        new_targets = []
        
        # Try to extract targets from payload (starts at byte 6)
        offset = 6
        target_idx = 0
        
        while offset + 8 <= len(frame) - 2 and target_idx < 3:
            try:
                x = _s16_le(frame[offset], frame[offset + 1])
                y = _s16_le(frame[offset + 2], frame[offset + 3])
                
                if x != 0 or y != 0:
                    dist = int(math.sqrt(x * x + y * y))
                    if 500 < dist < 10000:
                        new_targets.append((x, y, 0, target_idx))
                        target_idx += 1
            except:
                pass
            
            offset += 8
        
        # Age existing targets
        aged_targets = [(x, y, age + 1, t_idx) for x, y, age, t_idx in targets if age < 15]
        targets = new_targets + aged_targets
        targets = targets[:10]
    
    # Update display every 50ms (20 FPS)
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now
        
        # Update NeoPixel
        if len([t for t in targets if t[2] < 5]) > 0:
            pixel.fill((50, 0, 0))  # Red = targets
        else:
            pixel.fill((0, 10, 0))  # Green = clear
    
    # Status report (like your code)
    if now - last_stat > 1.0:
        print("RX {:5d} B/s  frames {:3d}/s".format(bytes_in, frames_ok))
        bytes_in = 0
        frames_ok = 0
        last_stat = now
    
    time.sleep(0.001)
