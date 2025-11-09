# ESP32-S3 ProS3 - HLK-LD2450 Alien Motion Tracker
# Fade & Pulse on Monochrome OLED using spatial dithering
# Inspired by RobSmithDev's alienmotiontracker rendering

import time, math
import board, busio, neopixel
import adafruit_ssd1306

# Hardware
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=8192, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("Alien Motion Tracker - Fade & Pulse Edition")

# Protocol
SYNC = b"\xAA\xFF\x03\x00"
FOOTER = b"\x55\xCC"
FRAME_SIZE = 30

def _s16_le(b0, b1):
    """Convert little-endian signed int16 per LD2450 protocol"""
    v = b0 | (b1 << 8)
    if v & 0x8000:
        return v - 0x8000
    else:
        return -v if v != 0 else 0

# Display
CX, CY = 64, 63
RADII = [20, 40, 60]

# Rob's fade timing
FADE_DURATION = 3.0  # 3 seconds total fade
PULSE_DURATION = 0.4  # 0.4 second pulse cycle

# Target tracking
class Target:
    def __init__(self, x, y, target_id):
        self.x = x
        self.y = y
        self.target_id = target_id
        self.birth_time = time.monotonic()
        self.last_seen = time.monotonic()
    
    def age(self):
        return time.monotonic() - self.birth_time
    
    def time_since_seen(self):
        return time.monotonic() - self.last_seen
    
    def update(self, x, y):
        self.x = x
        self.y = y
        self.last_seen = time.monotonic()
    
    def is_active(self):
        """Active if seen in last 1 second"""
        return self.time_since_seen() < 1.0
    
    def brightness(self):
        """Calculate brightness: 1.0 (full) down to 0.0 (gone)"""
        time_since = self.time_since_seen()
        if time_since < 1.0:
            return 1.0  # Full brightness
        elif time_since < FADE_DURATION:
            # Fade from 1.0 to 0.0 over next 2 seconds
            fade_progress = (time_since - 1.0) / (FADE_DURATION - 1.0)
            return max(0.0, 1.0 - fade_progress)
        else:
            return 0.0  # Dead

targets = []
buffer = bytearray()
bytes_in = 0
frames_ok = 0
pulse_start = 0

def map_xy(x_mm, y_mm):
    """Map radar coords to full screen"""
    sx = int(max(0, min(127, (x_mm + 3000) * 127 / 6000)))
    sy = int(max(0, min(63, 63 - (y_mm * 63 / 6000))))
    return sx, sy

def draw_dotted_circle(cx, cy, r):
    """Draw dotted circle"""
    steps = int(r * 6.28)
    for i in range(0, steps, 3):
        a = (i / steps) * 2 * math.pi
        x = int(cx + r * math.cos(a))
        y = int(cy + r * math.sin(a))
        if 0 <= x < 128 and 0 <= y < 64:
            oled.pixel(x, y, 1)

def draw_blip_with_fade(sx, sy, radius, brightness):
    """
    Draw blip with spatial dithering for brightness on monochrome OLED.
    Inspired by Rob's fade technique adapted for 1-bit display.
    
    Brightness 1.0 = solid filled circle
    Brightness 0.5 = checkerboard pattern  
    Brightness 0.25 = sparse pattern
    Brightness 0.0 = invisible
    """
    if brightness < 0.05:
        return
    
    # Dithering patterns for different brightness levels
    # Pattern determines which pixels to draw based on position
    def should_draw_pixel(dx, dy, brightness):
        """Spatial dithering: decide if pixel should be drawn"""
        if brightness >= 0.95:
            return True  # Solid
        elif brightness >= 0.75:
            # 75% coverage - skip 1 in 4
            return not ((dx + dy) % 2 == 0 and (dx % 2 == 0))
        elif brightness >= 0.5:
            # 50% coverage - checkerboard
            return (dx + dy) % 2 == 0
        elif brightness >= 0.25:
            # 25% coverage - sparse
            return (dx % 2 == 0 and dy % 2 == 0)
        else:
            # < 25% - very sparse
            return (dx % 3 == 0 and dy % 3 == 0)
    
    # Draw filled circle with dithering
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx*dx + dy*dy <= radius*radius:
                if should_draw_pixel(dx, dy, brightness):
                    px, py = sx + dx, sy + dy
                    if 0 <= px < 128 and 0 <= py < 64:
                        oled.pixel(px, py, 1)
    
    # Glow ring - always sparse for monochrome effect
    if brightness > 0.3:
        glow_radius = radius + 2
        steps = int(glow_radius * 6.28)
        for i in range(0, steps, 2):
            a = (i / steps) * 2 * math.pi
            x = int(sx + glow_radius * math.cos(a))
            y = int(sy + glow_radius * math.sin(a))
            if 0 <= x < 128 and 0 <= y < 64:
                oled.pixel(x, y, 1)

def draw_sweep_lines():
    """Draw sweep lines to active targets"""
    for target in targets:
        if not target.is_active():
            continue
        
        angle = math.atan2(-target.y, -target.x)
        angle_deg = math.degrees(angle) + 90
        
        if 0 <= angle_deg <= 180:
            # Thin line from center outward
            for r in range(0, RADII[-1] + 1, 4):
                a = math.radians(angle_deg - 90)
                x = int(CX + r * math.cos(a))
                y = int(CY + r * math.sin(a))
                if 0 <= x < 128 and 0 <= y < 64:
                    oled.pixel(x, y, 1)

def draw_display():
    """Render display with Rob's fade & pulse system"""
    global pulse_start
    
    oled.fill(0)
    now = time.monotonic()
    
    # Calculate pulse time for active targets
    pulse_time = now - pulse_start
    if pulse_time > PULSE_DURATION:
        pulse_time = 0  # Reset (will trigger on next detection)
    
    # Grid
    for r in RADII:
        draw_dotted_circle(CX, CY, r)
    oled.line(0, CY, 127, CY, 1)
    
    # Sweep lines
    draw_sweep_lines()
    
    # Draw targets with TWO-PHASE rendering (Rob's technique)
    active_count = 0
    
    # PHASE 1: Fading targets (> 1 second old)
    for target in targets:
        if target.time_since_seen() > 1.0:
            brightness = target.brightness()
            if brightness > 0:
                sx, sy = map_xy(target.x, target.y)
                radius = 3  # Fixed small radius for fading
                draw_blip_with_fade(sx, sy, radius, brightness)
    
    # PHASE 2: Active targets (< 1 second) with PULSE
    for target in targets:
        if target.is_active():
            active_count += 1
            brightness = 1.0  # Full brightness
            
            # PULSE ANIMATION - radius grows/shrinks with sin wave
            # Like Rob's: (defradius+5) - round(sin((timepos/1.2) * pi) * 6)
            base_radius = 4
            if pulse_time > 0 and pulse_time < PULSE_DURATION:
                pulse_scale = math.sin((pulse_time / PULSE_DURATION) * math.pi)
                radius = base_radius + int(pulse_scale * 3)  # Pulse from 4 to 7
            else:
                radius = base_radius
            
            sx, sy = map_xy(target.x, target.y)
            draw_blip_with_fade(sx, sy, radius, brightness)
    
    # NeoPixel status
    if active_count > 0:
        pixel[0] = (50, 0, 0)  # Red when tracking
    else:
        # Rainbow when clear
        hue = (now * 50) % 126
        r = int((1 + math.sin(hue * 0.05)) * 25)
        g = int((1 + math.sin(hue * 0.05 + 2.1)) * 25)
        b = int((1 + math.sin(hue * 0.05 + 4.2)) * 25)
        pixel[0] = (r, g, b)
    
    oled.show()

def find_or_create_target(x, y, target_id):
    """Find existing target or create new with 300mm deduplication"""
    for target in targets:
        dist = math.sqrt((target.x - x)**2 + (target.y - y)**2)
        if dist < 300:
            target.update(x, y)
            return target
    
    # New target - trigger pulse
    global pulse_start
    pulse_start = time.monotonic()
    
    new_target = Target(x, y, target_id)
    targets.append(new_target)
    return new_target

def cleanup_old_targets():
    """Remove dead targets (> 3s)"""
    global targets
    targets = [t for t in targets if t.brightness() > 0]

last_draw = time.monotonic()
last_cleanup = time.monotonic()
last_stat = time.monotonic()

print("Starting radar tracking...")

while True:
    # Read UART
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        if data:
            bytes_in += len(data)
            buffer.extend(data)
    
    # Parse frames
    while len(buffer) >= FRAME_SIZE:
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
            for t_idx in range(3):
                offset = 4 + (t_idx * 8)
                
                x = _s16_le(frame[offset], frame[offset + 1])
                y = _s16_le(frame[offset + 2], frame[offset + 3])
                
                if x != 0 or y != 0:
                    dist = int(math.sqrt(x * x + y * y))
                    if 100 < dist < 8000:
                        find_or_create_target(x, y, t_idx)
        else:
            buffer = buffer[2:]
    
    # Display update at 20 FPS
    now = time.monotonic()
    if now - last_draw > 0.05:
        draw_display()
        last_draw = now
    
    # Cleanup every second
    if now - last_cleanup > 1.0:
        cleanup_old_targets()
        last_cleanup = now
    
    # Stats
    if now - last_stat > 1.0:
        active = len([t for t in targets if t.is_active()])
        fading = len([t for t in targets if not t.is_active() and t.brightness() > 0])
        print("RX {:5d} B/s | frames {:3d}/s | active {:d} | fading {:d}".format(
            bytes_in, frames_ok, active, fading))
        bytes_in = 0
        frames_ok = 0
        last_stat = now
    
    time.sleep(0.001)
