#!/usr/bin/env python3
"""
CircuitPython Code Deployment Utility
Deploys CircuitPython code to ESP32 via serial REPL
"""
import serial
import time
import os
import sys

def list_circuitpython_files(base_dir):
    """List available CircuitPython code files"""
    cp_dir = os.path.join(base_dir, 'circuitpython')
    if not os.path.exists(cp_dir):
        print(f"Error: CircuitPython directory not found at {cp_dir}")
        return []
    
    files = [f for f in os.listdir(cp_dir) if f.endswith('.py')]
    return sorted(files)

def deploy_code(port, code_file_path, monitor_duration=10):
    """Deploy CircuitPython code to ESP32"""
    try:
        # Read the code file
        with open(code_file_path, 'r') as f:
            code_content = f.read()
        
        # Open serial connection
        ser = serial.Serial(port, 115200, timeout=2)
        print(f"Connected to {port}")
        print(f"Deploying: {os.path.basename(code_file_path)}")
        
        # Stop current program with Ctrl+C
        ser.write(b'\x03\r')
        time.sleep(0.5)
        
        # Clear input buffer
        while ser.in_waiting:
            ser.read(ser.in_waiting)
        
        print("Writing code to /code.py...")
        
        # Open file in REPL
        ser.write(b"with open('/code.py', 'w') as f:\r\n")
        time.sleep(0.2)
        
        # Write code line by line
        line_count = 0
        for line in code_content.split('\n'):
            # Escape backslashes and single quotes
            escaped = line.replace('\\', '\\\\').replace("'", "\\'")
            cmd = f"    f.write('{escaped}\\n')\r\n"
            ser.write(cmd.encode())
            time.sleep(0.02)  # Small delay to prevent buffer overflow
            line_count += 1
            
            # Progress indicator every 50 lines
            if line_count % 50 == 0:
                print(f"  Written {line_count} lines...")
        
        print(f"  Written {line_count} lines total")
        
        # Close the file writing block
        ser.write(b"\r\n")
        time.sleep(0.5)
        
        # Reload with Ctrl+D
        print("Reloading ESP32...")
        ser.write(b'\x04')
        time.sleep(3)
        
        # Monitor output
        print("\n" + "="*60)
        print("Radar Output (monitoring for {} seconds):".format(monitor_duration))
        print("="*60)
        
        start_time = time.time()
        while time.time() - start_time < monitor_duration:
            if ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(line)
        
        print("="*60)
        print("\n✓ Deployment complete!")
        print("Wave your hand in front of the radar to test detection")
        
        ser.close()
        return True
        
    except FileNotFoundError:
        print(f"Error: Code file not found at {code_file_path}")
        return False
    except serial.SerialException as e:
        print(f"Error: Serial connection failed - {e}")
        print("Check that:")
        print("  - The ESP32 is connected")
        print("  - The COM port is correct")
        print("  - No other program is using the port")
        return False
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main deployment workflow"""
    print("="*60)
    print("CircuitPython Deployment Tool")
    print("="*60)
    
    # Get base directory (one level up from utils)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    
    # List available code files
    files = list_circuitpython_files(base_dir)
    if not files:
        print("No CircuitPython files found!")
        return 1
    
    print("\nAvailable CircuitPython files:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f}")
    
    # Select file
    while True:
        try:
            choice = input(f"\nSelect file (1-{len(files)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                selected_file = files[idx]
                break
            print(f"Please enter a number between 1 and {len(files)}")
        except ValueError:
            print("Please enter a valid number")
        except KeyboardInterrupt:
            print("\n\nCancelled")
            return 0
    
    # Get COM port
    port = input("\nEnter COM port (e.g., COM5): ").strip().upper()
    if not port.startswith("COM"):
        port = "COM" + port
    
    # Get monitoring duration
    try:
        duration = input("\nMonitor duration in seconds (default: 10): ").strip()
        duration = int(duration) if duration else 10
    except ValueError:
        duration = 10
    
    # Deploy
    print()
    code_file_path = os.path.join(base_dir, 'circuitpython', selected_file)
    success = deploy_code(port, code_file_path, duration)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
