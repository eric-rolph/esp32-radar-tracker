# ESP32 Radar Tracker Utilities

Python utility scripts for working with the ESP32 Radar Tracker.

## Requirements

```bash
pip install pyserial
```

## Scripts

### serial_monitor.py

Monitor real-time radar data from the ESP32:

```bash
python utils/serial_monitor.py
```

You'll be prompted to enter your COM port (or press Enter for default COM5).

### deploy_circuitpython.py

Deploy CircuitPython code to your device:

```bash
python utils/deploy_circuitpython.py
```

This script will:
1. Prompt for your COM port
2. Stop the running program
3. Upload the CircuitPython code
4. Restart the device

## Configuration

If you have a consistent COM port, you can modify the default in each script:

```python
DEFAULT_PORT = "COM5"  # Change to your port
```

## Troubleshooting

**Can't find COM port:**
- Windows: Check Device Manager → Ports (COM & LPT)
- List all ports: `python -m serial.tools.list_ports`

**Permission denied:**
- Close Arduino IDE or other serial monitors
- Only one program can access the port at a time

**No data received:**
- Check baud rate (should be 115200)
- Verify ESP32 is powered and programmed
- Check USB cable (must support data transfer)
