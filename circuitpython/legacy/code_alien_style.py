# ESP32-S3 ProS3 - HLK-LD2450 Radar Tracker
# Alien Motion Tracker Style - Enhanced Version
# For CircuitPython 9.x

import board
import busio
import time
import adafruit_ssd1306
import neopixel
import math

# Initialize hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=4096, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

def s16(b0, b1):
    """Convert two bytes to signed 16-bit integer"""
    v = b0 | (b1 << 8)
    return v - 65536 if v >= 32768 else v

# Display configuration - Alien Tracker style
CX, CY = 64, 35  # Center positioned for text area at bottom
MAX_RANGE = 6000  # 6 meters max display range
R_MAX = 28  # Maximum radius on screen
R_RINGS = [9, 18, 28]  # Ring radii for 2m, 4m, 6m

# Target tracking
targets = []
buffer = bytearray()
frame_count = 0
last_draw = time.monotonic()
sweep_angle = 0

print("Alien Motion Tracker - Ready")
print("Tracking up to 3 targets")
pixel.fill((0, 10, 0))  # Green = ready

def draw_dotted_circle(cx, cy, radius):
    """Draw a dotted circle for range rings"""
    for angle_deg in range(0, 181, 4):  # Every 4 degrees for dotted effect
        rad = math.radians(angle_deg - 90)
        x = int(cx + radius * math.cos(rad))
        y = int(cy + radius * math.sin(rad))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_angle_markers(cx, cy):
    """Draw angle marker lines every 45 degrees"""
    for angle_deg in [0, 45, 90, 135, 180]:
        rad = math.radians(angle_deg - 90)
        # Draw line from inner to outer
        for r in range(R_MAX - 4, R_MAX + 1):
            x = int(cx + r * math.cos(rad))
            y = int(cy + r * math.sin(rad))
            if 0 <= x < 128 and 0 <= y < 64:
                oled.pixel(x, y, 1)

def draw_target(x, y, target_idx, age):
    """Draw a target blip with different styles"""
    if not (0 <= x < 128 and 0 <= y < 64):
        return
    
    # Brightness based on age (fade out over time)
    brightness = max(0, min(1, (10 - age) / 10))
    
    if brightness < 0.3:
        return
    
    # Different marker styles for different targets
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

def draw_radar_screen():
    """Draw the complete Alien-style radar display"""
    global sweep_angle, targets
    
    oled.fill(0)
    
    # Draw dotted range rings
    for r in R_RINGS:
        draw_dotted_circle(CX, CY, r)
    
    # Draw angle markers
    draw_angle_markers(CX, CY)
    
    # Draw center dot
    oled.pixel(CX, CY, 1)
    
    # Draw rotating sweep line (Alien style)
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
        
        # Calculate polar coordinates
        dist_mm = int(math.sqrt(x_mm * x_mm + y_mm * y_mm))
        dist_m = dist_mm / 1000.0
        
        if dist_m < closest_dist and age < 5:
            closest_dist = dist_m
        
        # Only draw if in range
        if dist_mm <= MAX_RANGE:
            active_targets += 1
            
            # Calculate angle (0° = up, clockwise)
            angle_rad = math.atan2(-y_mm, -x_mm)
            angle_deg = math.degrees(angle_rad) + 90
            
            # Only draw if in front hemisphere
            if 0 <= angle_deg <= 180:
                # Map distance to screen radius
                r = int((dist_mm / MAX_RANGE) * R_MAX)
                
                # Calculate screen position
                screen_rad = math.radians(angle_deg - 90)
                px = int(CX + r * math.cos(screen_rad))
                py = int(CY + r * math.sin(screen_rad))
                
                # Draw the target
                draw_target(px, py, t_idx, age)
    
    # Draw text info at bottom
    oled.fill_rect(0, 56, 128, 8, 0)  # Clear text area
    
    if active_targets == 0:
        oled.text("NO CONTACT", 25, 56, 1)
    else:
        # Show closest target distance
        oled.text("%.1fm [%d]" % (closest_dist, active_targets), 40, 56, 1)
    
    # Frame counter (top left)
    oled.text("M314", 0, 0, 1)
    
    oled.show()

def process_radar_frame(frame):
    """Parse HLK-LD2450 frame and extract targets"""
    global targets
    
    # Verify frame integrity
    if frame[2] != 0x03 or frame[3] != 0x00:
        return
    if frame[28] != 0x55 or frame[29] != 0xCC:
        return
    
    # Parse 3 targets (8 bytes each, starting at byte 4)
    new_targets = []
    for i, offset in enumerate([4, 12, 20]):
        x = s16(frame[offset], frame[offset + 1])
        y = s16(frame[offset + 2], frame[offset + 3])
        speed = s16(frame[offset + 4], frame[offset + 5])
        
        # Only add if valid (non-zero)
        if x != 0 or y != 0:
            dist = int(math.sqrt(x * x + y * y))
            
            # Only track reasonable ranges (0.5m to 10m)
            if 500 < dist < 10000:
                new_targets.append((x, y, 0, i))
                
                # Debug print
                print("T%d: %.2fm X:%d Y:%d Spd:%d" % (i + 1, dist / 1000.0, x, y, speed))
    
    # Merge new targets with existing (age existing targets)
    aged_targets = []
    for x, y, age, t_idx in targets:
        if age < 15:  # Keep targets for ~1.5 seconds
            aged_targets.append((x, y, age + 1, t_idx))
    
    # Add new targets
    targets = new_targets + aged_targets
    
    # Limit to most recent 10 targets
    targets = targets[:10]

# Main loop
while True:
    # Read UART data
    if uart.in_waiting:
        buffer.extend(uart.read(uart.in_waiting))
    
    # Process complete frames
    while len(buffer) >= 30:
        try:
            idx = buffer.index(b'\xAA\xFF')
        except ValueError:
            buffer = bytearray()
            break
        
        # Align to header
        if idx > 0:
            buffer = buffer[idx:]
        
        if len(buffer) < 30:
            break
        
        # Extract frame
        frame = buffer[0:30]
        buffer = buffer[30:]
        
        # Process the frame
        process_radar_frame(frame)
        frame_count += 1
    
    # Update display at ~20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_radar_screen()
        last_draw = now
        
        # Update NeoPixel status
        if len([t for t in targets if t[2] < 5]) > 0:
            pixel.fill((50, 0, 0))  # Red when targets detected
        else:
            pixel.fill((0, 10, 0))  # Green when clear
    
    time.sleep(0.001)
