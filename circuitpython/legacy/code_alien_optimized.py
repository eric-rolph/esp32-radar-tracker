# ESP32-S3 ProS3 - HLK-LD2450 Alien Motion Tracker
# OPTIMIZED for multiple targets with Rob's fade/pulse rendering
# No text - just beautiful blips!

import time, math
import board, busio, neopixel
import adafruit_ssd1306

# Hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=8192, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("Alien Motion Tracker - Multi-Target Optimized")

# Protocol
SYNC = b"\xAA\xFF\x03\x00"
FOOTER = b"\x55\xCC"
FRAME_SIZE = 30

def _s16_le(b0, b1):
    """Convert little-endian signed int16 per LD2450 protocol"""
    v = b0 | (b1 << 8)
    if v & 0x8000:
        return v - 0x8000  # Positive
    else:
        return -v if v != 0 else 0  # Negative

# Display - Full screen
CX, CY = 64, 63
RADII = [20, 40, 60]

# Target tracking with fade-out (Rob's technique)
class Target:
    def __init__(self, x, y, target_id):
        self.x = x
        self.y = y
        self.target_id = target_id
        self.birth_time = time.monotonic()
        self.last_seen = time.monotonic()
        self.active = True  # Recently detected
    
    def age(self):
        return time.monotonic() - self.birth_time
    
    def time_since_seen(self):
        return time.monotonic() - self.last_seen
    
    def update(self, x, y):
        self.x = x
        self.y = y
        self.last_seen = time.monotonic()
        self.active = True

targets = []
buffer = bytearray()
bytes_in = 0
frames_ok = 0

# Animation
pulse_start = 0
pulse_active = False

def map_xy(x_mm, y_mm):
    """Map radar coords to full screen"""
    sx = int(max(0, min(127, (x_mm + 3000) * 127 / 6000)))
    sy = int(max(0, min(63, 63 - (y_mm * 63 / 6000))))
    return sx, sy

def draw_dotted_circle(cx, cy, r, brightness=1.0):
    """Draw dotted circle with variable brightness"""
    if brightness < 0.1:
        return
    steps = int(r * 6.28)
    for i in range(0, steps, 3):
        a = (i / steps) * 2 * math.pi
        x = int(cx + r * math.cos(a))
        y = int(cy + r * math.sin(a))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_target_blip(sx, sy, radius, brightness):
    """Draw target blip with Rob's style - filled circle with glow"""
    if brightness < 0.1:
        return
    
    # Inner filled circle
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx*dx + dy*dy <= radius*radius:
                px, py = sx + dx, sy + dy
                if 0 <= px < 128 and 0 <= py < 64:
                    oled.pixel(px, py, 1)
    
    # Glow ring (partial)
    glow_radius = radius + 3
    steps = int(glow_radius * 6.28)
    for i in range(0, steps, 2):
        a = (i / steps) * 2 * math.pi
        x = int(sx + glow_radius * math.cos(a))
        y = int(sy + glow_radius * math.sin(a))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_sweep_lines():
    """Draw sweep lines to all active targets"""
    for target in targets:
        if not target.active or target.time_since_seen() > 0.5:
            continue
        
        # Calculate angle
        angle = math.atan2(-target.y, -target.x)
        angle_deg = math.degrees(angle) + 90
        
        if 0 <= angle_deg <= 180:
            # Draw thin line from center to target
            for r in range(0, RADII[-1] + 1, 3):
                a = math.radians(angle_deg - 90)
                x = int(CX + r * math.cos(a))
                y = int(CY + r * math.sin(a))
                if 0 <= x < 128 and 0 <= y < 64:
                    oled.pixel(x, y, 1)

def draw_display():
    """Draw complete radar with Rob's fade/pulse technique"""
    global pulse_active, pulse_start
    
    oled.fill(0)
    
    now = time.monotonic()
    
    # Calculate pulse animation (0.4 second cycle like Rob's)
    pulse_time = 0
    if pulse_active:
        pulse_time = now - pulse_start
        if pulse_time > 0.4:
            pulse_active = False
    
    # Draw grid (always visible)
    for r in RADII:
        draw_dotted_circle(CX, CY, r)
    oled.line(0, CY, 127, CY, 1)
    
    # Draw sweep lines to active targets
    draw_sweep_lines()
    
    # Draw targets with Rob's three-tier system
    active_count = 0
    
    for target in targets:
        age = target.age()
        time_since = target.time_since_seen()
        
        # Calculate brightness based on age and detection
        if time_since < 1.0:
            # ACTIVE - recently seen, full brightness with pulse
            brightness = 1.0
            active_count += 1
            
            # Pulse effect (radius varies with pulse_time)
            if pulse_active and pulse_time < 0.4:
                pulse_scale = math.sin((pulse_time / 0.4) * math.pi)
                radius = 4 + int(pulse_scale * 3)
            else:
                radius = 4
            
        elif time_since < 3.0:
            # FADING - not recently seen, fade out over 2 seconds
            fade_time = time_since - 1.0
            brightness = 1.0 - (fade_time / 2.0)
            radius = 3
        else:
            # TOO OLD - remove
            continue
        
        # Map to screen
        sx, sy = map_xy(target.x, target.y)
        
        # Draw the blip
        draw_target_blip(sx, sy, radius, brightness)
    
    # NeoPixel status
    if active_count > 0:
        pixel[0] = (50, 0, 0)  # Red when active targets
    else:
        # Rainbow fade when clear
        hue = (now * 50) % 126
        r = int((1 + math.sin(hue * 0.05)) * 25)
        g = int((1 + math.sin(hue * 0.05 + 2.1)) * 25)
        b = int((1 + math.sin(hue * 0.05 + 4.2)) * 25)
        pixel[0] = (r, g, b)
    
    oled.show()

def find_or_create_target(x, y, target_id):
    """Find existing target or create new one (with deduplication)"""
    # Check if this is close to an existing target
    for target in targets:
        dist = math.sqrt((target.x - x)**2 + (target.y - y)**2)
        if dist < 300:  # 300mm threshold (same as Rob's)
            target.update(x, y)
            return target
    
    # Create new target
    new_target = Target(x, y, target_id)
    targets.append(new_target)
    return new_target

def cleanup_old_targets():
    """Remove targets not seen in 3+ seconds (Rob's FADE_DURATION)"""
    global targets
    targets = [t for t in targets if t.time_since_seen() < 3.0]

last_draw = time.monotonic()
last_cleanup = time.monotonic()
last_stat = time.monotonic()

while True:
    # Read UART
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        if data:
            bytes_in += len(data)
            buffer.extend(data)
    
    # Parse Basic protocol frames
    while len(buffer) >= FRAME_SIZE:
        # Find sync pattern
        sync_idx = -1
        for i in range(len(buffer) - 3):
            if buffer[i:i+4] == SYNC:
                sync_idx = i
                break
        
        if sync_idx < 0:
            if len(buffer) > 100:
                buffer = buffer[-50:]
            break
        
        if sync_idx > 0:
            buffer = buffer[sync_idx:]
        
        if len(buffer) < FRAME_SIZE:
            break
        
        # Verify footer
        if buffer[28] == 0x55 and buffer[29] == 0xCC:
            frames_ok += 1
            frame = buffer[0:FRAME_SIZE]
            buffer = buffer[FRAME_SIZE:]
            
            # Parse 3 targets
            any_new = False
            for t_idx in range(3):
                offset = 4 + (t_idx * 8)
                
                x = _s16_le(frame[offset], frame[offset + 1])
                y = _s16_le(frame[offset + 2], frame[offset + 3])
                
                # Target exists if not all zeros
                if x != 0 or y != 0:
                    dist = int(math.sqrt(x * x + y * y))
                    # Filter reasonable range
                    if 100 < dist < 8000:
                        find_or_create_target(x, y, t_idx)
                        any_new = True
            
            # Trigger pulse animation when new targets detected
            if any_new:
                pulse_start = time.monotonic()
                pulse_active = True
            
            # Mark all targets as not active by default
            for target in targets:
                target.active = False
        else:
            buffer = buffer[2:]
    
    # Update display at 20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now
    
    # Cleanup old targets every second
    if now - last_cleanup > 1.0:
        cleanup_old_targets()
        last_cleanup = now
    
    # Status report
    if now - last_stat > 1.0:
        active = len([t for t in targets if t.time_since_seen() < 1.0])
        total = len(targets)
        print("RX {:5d} B/s | frames {:3d}/s | targets {:d}/{:d}".format(
            bytes_in, frames_ok, active, total))
        bytes_in = 0
        frames_ok = 0
        last_stat = now
    
    time.sleep(0.001)
