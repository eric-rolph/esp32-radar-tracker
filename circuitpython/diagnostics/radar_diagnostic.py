# Quick Radar Diagnostic for HLK-LD2450
# Copy this to F:\code.py to test radar connectivity

import board
import busio
import time
import neopixel

# Initialize hardware
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, receiver_buffer_size=4096, timeout=0)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

print("=" * 50)
print("HLK-LD2450 Radar Diagnostic")
print("=" * 50)
print("Testing UART on pins:")
print("  TX (ESP32) -> IO44 -> RX (Radar)")
print("  RX (ESP32) -> IO43 <- TX (Radar)")
print("  Baudrate: 256000")
print("=" * 50)

byte_count = 0
frame_count = 0
last_report = time.monotonic()
buffer = bytearray()

print("\nWaiting for data...")
print("(Wave hand in front of radar)\n")

while True:
    # Read any available data
    if uart.in_waiting:
        data = uart.read(uart.in_waiting)
        byte_count += len(data)
        buffer.extend(data)
        pixel.fill((0, 0, 50))  # Blue flash when data received
        
        # Look for valid frames
        while len(buffer) >= 30:
            try:
                idx = buffer.index(b'\xAA\xFF')
            except ValueError:
                buffer = bytearray()
                break
            
            if idx > 0:
                buffer = buffer[idx:]
            
            if len(buffer) < 30:
                break
            
            frame = buffer[0:30]
            buffer = buffer[30:]
            
            # Check frame validity
            if frame[2] == 0x03 and frame[3] == 0x00 and frame[28] == 0x55 and frame[29] == 0xCC:
                frame_count += 1
                pixel.fill((0, 50, 0))  # Green when valid frame
                
                # Parse targets
                for i, offset in enumerate([4, 12, 20]):
                    x = frame[offset] | (frame[offset+1] << 8)
                    y = frame[offset+2] | (frame[offset+3] << 8)
                    if x >= 32768: x -= 65536
                    if y >= 32768: y -= 65536
                    
                    if x != 0 or y != 0:
                        import math
                        dist = math.sqrt(x*x + y*y)
                        print(f"✓ Target {i+1}: {dist/1000:.2f}m  X:{x:5d} Y:{y:5d}")
            else:
                print(f"✗ Invalid frame: {frame[0:4].hex()} ... {frame[28:30].hex()}")
    else:
        pixel.fill((10, 0, 0))  # Red when no data
    
    # Report status every 2 seconds
    now = time.monotonic()
    if now - last_report > 2.0:
        print(f"\n--- Status (elapsed: {int(now)}s) ---")
        print(f"Bytes received: {byte_count}")
        print(f"Valid frames: {frame_count}")
        print(f"Rate: {byte_count/2:.1f} bytes/sec")
        
        if byte_count == 0:
            print("⚠ WARNING: NO DATA RECEIVED!")
            print("Check connections:")
            print("  • Radar TX -> ESP32 GPIO43 (IO43)")
            print("  • Radar RX -> ESP32 GPIO44 (IO44)")
            print("  • Radar VCC -> 5V")
            print("  • Radar GND -> GND")
        elif frame_count == 0:
            print("⚠ WARNING: Receiving bytes but no valid frames!")
            print("  • Baudrate might be wrong")
            print("  • Radar might not be powered properly")
        else:
            print("✓ Radar working correctly!")
        
        print()
        last_report = now
        byte_count = 0
        frame_count = 0
    
    time.sleep(0.01)
