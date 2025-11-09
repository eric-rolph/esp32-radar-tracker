# I2C Scanner - Find OLED address
import board
import busio
import time

print("\n=== I2C Scanner ===")
print("Scanning for devices...")

i2c = board.STEMMA_I2C()

# Lock the I2C bus
while not i2c.try_lock():
    pass

print("\nFound devices at addresses:")
found = []
for addr in range(0x00, 0x80):
    if i2c.scan()[0:1]:
        pass
    try:
        # Try to communicate with this address
        i2c.writeto(addr, b'')
        found.append(addr)
        print(f"  0x{addr:02X} ({addr})")
    except:
        pass

i2c.unlock()

if len(found) == 0:
    print("  No devices found!")
    print("\nCheck:")
    print("  • SDA/SCL connections")
    print("  • Device power")
else:
    print(f"\nFound {len(found)} device(s)")
    if 0x3C in found:
        print("  ✓ OLED at 0x3C (common)")
    if 0x3D in found:
        print("  ✓ OLED at 0x3D (common)")

print("\nRebooting in 5 seconds...")
time.sleep(5)

import microcontroller
microcontroller.reset()
