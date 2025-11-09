# MINIMAL RADAR TEST - Shows exactly what's happening
import board
import busio
import time
import neopixel

print("\n" + "="*60)
print("RADAR DIAGNOSTIC - Minimal Test")
print("="*60)

# Initialize UART
try:
    uart = busio.UART(board.IO43, board.IO44, baudrate=256000, 
                     receiver_buffer_size=8192, timeout=0)
    print("✓ UART initialized: IO43(TX) / IO44(RX) @ 256000 baud")
except Exception as e:
    print(f"✗ UART FAILED: {e}")
    while True: time.sleep(1)

# Initialize NeoPixel
try:
    pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.5)
    pixel.fill((10, 10, 0))  # Yellow = starting
    print("✓ NeoPixel initialized")
except Exception as e:
    print(f"✗ NeoPixel FAILED: {e}")

print("\n" + "-"*60)
print("Listening for radar data...")
print("Wave your hand in front of the radar sensor!")
print("-"*60 + "\n")

# Counters
start_time = time.monotonic()
total_bytes = 0
last_bytes = 0
basic_frames = 0  # 0xAA 0xFF
adv_frames = 0    # 0xAA 0x55
buffer = bytearray()

# Status display
last_status = time.monotonic()
check_count = 0

while True:
    now = time.monotonic()
    
    # Read available data
    available = uart.in_waiting
    if available > 0:
        data = uart.read(available)
        total_bytes += len(data)
        buffer.extend(data)
        
        # Flash blue when receiving data
        pixel.fill((0, 0, 50))
        time.sleep(0.01)
        pixel.fill((10, 10, 0))
        
        # Look for frame headers
        hex_data = data.hex().upper()
        if 'AAFF' in hex_data:
            basic_frames += 1
            print(f"  ► BASIC frame detected! (0xAA 0xFF) - Total: {basic_frames}")
            # Show first 32 bytes
            preview = ' '.join(f'{b:02X}' for b in data[:min(32, len(data))])
            print(f"    Data: {preview}")
            pixel.fill((0, 50, 0))  # Green flash
        
        if 'AA55' in hex_data:
            adv_frames += 1
            print(f"  ► ADVANCED frame detected! (0xAA 0x55) - Total: {adv_frames}")
            # Show first 32 bytes
            preview = ' '.join(f'{b:02X}' for b in data[:min(32, len(data))])
            print(f"    Data: {preview}")
            pixel.fill((0, 50, 0))  # Green flash
    
    # Print status every 3 seconds
    if now - last_status >= 3.0:
        check_count += 1
        elapsed = now - start_time
        bytes_this_period = total_bytes - last_bytes
        last_bytes = total_bytes
        
        print(f"\n[Check #{check_count} @ {elapsed:.1f}s]")
        print(f"  Total bytes: {total_bytes}")
        print(f"  Last 3s: {bytes_this_period} bytes ({bytes_this_period/3:.1f} bytes/sec)")
        print(f"  Basic frames (0xAA 0xFF): {basic_frames}")
        print(f"  Advanced frames (0xAA 0x55): {adv_frames}")
        print(f"  Buffer size: {len(buffer)} bytes")
        
        if total_bytes == 0:
            print("\n  ⚠️  WARNING: NO DATA RECEIVED!")
            print("  Check these connections:")
            print("    • Radar TX (Yellow) → ESP32 IO44")
            print("    • Radar RX (Green)  → ESP32 IO43")
            print("    • Radar VCC (Red)   → 5V")
            print("    • Radar GND (Black) → GND")
            print("  Try:")
            print("    1. Swap TX/RX wires (IO43 ↔ IO44)")
            print("    2. Check radar has power LED on")
            print("    3. Move hand 1-2m in front of radar")
            pixel.fill((50, 0, 0))  # Red = no data
        elif basic_frames + adv_frames == 0:
            print("\n  ⚠️  Bytes received but NO valid frames!")
            print("  This might mean:")
            print("    • Wrong baudrate (try 115200?)")
            print("    • Radar in different mode")
            print("    • Corrupted data")
            # Show some raw bytes
            if len(buffer) > 0:
                preview = ' '.join(f'{buffer[i]:02X}' for i in range(min(32, len(buffer))))
                print(f"  Raw buffer: {preview}")
            pixel.fill((50, 25, 0))  # Orange = wrong protocol
        else:
            print(f"\n  ✓ Radar is WORKING!")
            if basic_frames > 0:
                print(f"    Mode: BASIC (0xAA 0xFF)")
            if adv_frames > 0:
                print(f"    Mode: ADVANCED (0xAA 0x55)")
            pixel.fill((0, 50, 0))  # Green = working
        
        print("-"*60)
        last_status = now
        
        # Keep buffer reasonable size
        if len(buffer) > 1000:
            buffer = buffer[-500:]
    
    time.sleep(0.05)
