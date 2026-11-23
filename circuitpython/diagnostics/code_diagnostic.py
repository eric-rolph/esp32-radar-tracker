# ESP32-S3 ProS3 - HLK-LD2450 Radar DIAGNOSTIC
# Check if we're receiving ANY data and what protocol

import time
import board, busio, neopixel
import adafruit_ssd1306

# Hardware setup
i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)

uart = busio.UART(board.IO43, board.IO44, baudrate=256000,
                 receiver_buffer_size=8192, timeout=0)

pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("\n" + "="*50)
print("RADAR DIAGNOSTIC MODE")
print("="*50)

# Protocol signatures
SYNC_BASIC = b"\xAA\xFF"
SYNC_ADVANCED = b"\xAA\x55"

buffer = bytearray()
bytes_received = 0
basic_count = 0
advanced_count = 0
last_report = time.monotonic()
last_display = time.monotonic()

oled.fill(0)
oled.text("RADAR DIAG", 0, 0, 1)
oled.text("Waiting...", 0, 20, 1)
oled.show()

print("\nListening for radar data...")
print("Wave your hand in front of the radar!")
print()

while True:
    now = time.monotonic()
    
    # Read data
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        bytes_received += len(data)
        buffer.extend(data)
        pixel[0] = (0, 50, 0)  # Green flash when receiving
        
        # Keep buffer manageable
        if len(buffer) > 4096:
            buffer = buffer[-2048:]
    else:
        pixel[0] = (50, 0, 0)  # Red when no data
    
    # Check for protocol signatures
    if len(buffer) >= 2:
        # Scan for Basic protocol (0xAA 0xFF)
        try:
            idx = buffer.index(SYNC_BASIC)
            basic_count += 1
        except ValueError:
            pass
        
        # Scan for Advanced protocol (0xAA 0x55)
        try:
            idx = buffer.index(SYNC_ADVANCED)
            advanced_count += 1
        except ValueError:
            pass
    
    # Update display every 0.5 seconds
    if now - last_display > 0.5:
        oled.fill(0)
        oled.text("RADAR DIAG", 0, 0, 1)
        
        if bytes_received > 0:
            oled.text("RX: %d B/s" % (bytes_received * 2), 0, 12, 1)
            oled.text("Buf: %d" % len(buffer), 0, 24, 1)
            
            if basic_count > 0:
                oled.text("BASIC: %d" % basic_count, 0, 36, 1)
            if advanced_count > 0:
                oled.text("ADVANCED: %d" % advanced_count, 0, 48, 1)
            
            if basic_count == 0 and advanced_count == 0:
                oled.text("No sync!", 0, 36, 1)
        else:
            oled.text("NO DATA!", 0, 20, 1)
            oled.text("Check wiring", 0, 32, 1)
        
        oled.show()
        last_display = now
    
    # Print detailed report every second
    if now - last_report > 1.0:
        print("\n--- Status Report ---")
        print("Bytes/sec: %d" % bytes_received)
        print("Buffer size: %d" % len(buffer))
        print("Basic frames (0xAA 0xFF): %d" % basic_count)
        print("Advanced frames (0xAA 0x55): %d" % advanced_count)
        
        if bytes_received > 0:
            # Show first few bytes as hex
            preview = buffer[:20] if len(buffer) >= 20 else buffer
            hex_str = " ".join(["%02X" % b for b in preview])
            print("First bytes: %s" % hex_str)
            
            # Try to parse if we see Advanced protocol
            if advanced_count > 0 and len(buffer) >= 10:
                try:
                    idx = buffer.index(SYNC_ADVANCED)
                    if idx + 6 < len(buffer):
                        length = buffer[idx + 2] | (buffer[idx + 3] << 8)
                        cmd = buffer[idx + 4]
                        print("Frame: len=%d cmd=0x%02X" % (length, cmd))
                        
                        if idx + 7 < len(buffer):
                            count = buffer[idx + 6]
                            print("Target count: %d" % count)
                            
                            # Try to extract first target
                            if count > 0 and idx + 13 < len(buffer):
                                offset = idx + 7
                                x = buffer[offset] | (buffer[offset + 1] << 8)
                                y = buffer[offset + 2] | (buffer[offset + 3] << 8)
                                # Convert to signed
                                if x & 0x8000: x -= 0x10000
                                if y & 0x8000: y -= 0x10000
                                print("Target 1: X=%dmm Y=%dmm" % (x, y))
                except Exception as e:
                    print("Parse error: %s" % str(e))
        else:
            print("NO UART DATA - check connections!")
            print("  Radar TX -> ESP32 IO44")
            print("  Radar RX -> ESP32 IO43")
            print("  Radar powered? LED on?")
        
        # Reset counters
        bytes_received = 0
        basic_count = 0
        advanced_count = 0
        last_report = now
    
    time.sleep(0.01)
