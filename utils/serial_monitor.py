"""
Serial Monitor for ESP32 Radar Tracker
Reads and displays radar data from the serial port
"""
import serial
import time
import sys

# Configuration
BAUD_RATE = 115200
TIMEOUT = 2

def find_serial_port():
    """Prompt user for COM port or auto-detect"""
    port = input("Enter COM port (e.g., COM5) or press Enter to use COM5: ").strip()
    return port if port else "COM5"

def monitor_serial(port):
    """Monitor serial output from ESP32"""
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT)
        print(f"Connected to {port} at {BAUD_RATE} baud")
        print("Reading radar data... (Press Ctrl+C to stop)\n")
        
        while True:
            if ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(line)
                    
    except serial.SerialException as e:
        print(f"Error: {e}")
        print("Make sure the device is connected and the COM port is correct.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        ser.close()
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    port = find_serial_port()
    monitor_serial(port)
