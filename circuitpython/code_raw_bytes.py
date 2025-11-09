# ESP32-S3 ProS3 - Raw byte inspector
# Show exactly what the radar is sending

import time
import board, busio, neopixel
import adafruit_ssd1306

i2c = board.STEMMA_I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)

uart = busio.UART(board.IO43, board.IO44, baudrate=256000,
                 receiver_buffer_size=8192, timeout=0)

pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

print("\n" + "="*60)
print("RAW BYTE INSPECTOR")
print("="*60)

buffer = bytearray()
last_print = time.monotonic()
bytes_total = 0

while True:
    # Read data
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        buffer.extend(data)
        bytes_total += len(data)
        pixel[0] = (0, 50, 0)
    
    now = time.monotonic()
    if now - last_print > 2.0:
        print("\n--- Bytes received: %d ---" % bytes_total)
        
        if len(buffer) > 0:
            # Show first 60 bytes as hex
            preview = buffer[:60] if len(buffer) >= 60 else buffer
            
            print("HEX dump (first 60 bytes):")
            for i in range(0, len(preview), 16):
                chunk = preview[i:i+16]
                hex_str = " ".join(["%02X" % b for b in chunk])
                ascii_str = "".join([chr(b) if 32 <= b < 127 else "." for b in chunk])
                print("%04d: %-48s  %s" % (i, hex_str, ascii_str))
            
            # Look for common patterns
            print("\nSearching for sync patterns...")
            if b"\xAA\xFF" in buffer:
                idx = buffer.index(b"\xAA\xFF")
                print("  Found 0xAA 0xFF (BASIC) at byte %d" % idx)
            if b"\xAA\x55" in buffer:
                idx = buffer.index(b"\xAA\x55")
                print("  Found 0xAA 0x55 (ADVANCED) at byte %d" % idx)
            if b"\xF4\xF3\xF2\xF1" in buffer:
                idx = buffer.index(b"\xF4\xF3\xF2\xF1")
                print("  Found 0xF4 0xF3 0xF2 0xF1 (ALT) at byte %d" % idx)
            
            # Keep reasonable buffer size
            if len(buffer) > 500:
                buffer = buffer[-200:]
        else:
            print("NO DATA in buffer!")
        
        bytes_total = 0
        last_print = now
        pixel[0] = (50, 0, 0)
    
    time.sleep(0.01)
