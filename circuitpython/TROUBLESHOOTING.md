# 🔧 RADAR NOT WORKING - TROUBLESHOOTING GUIDE

## Problem: No radar data being received

Your HLK-LD2450 radar has **TWO different protocols**:

### Protocol Modes:
1. **Basic Mode** (0xAA 0xFF header) - Simple 30-byte frames
2. **Advanced Mode** (0xAA 0x55 header) - Variable length with checksums

## ✅ What I Just Did:

1. **Deployed dual-protocol code** → `F:\code.py`
   - Auto-detects which mode your radar is using
   - Shows "M314-B" for Basic or "M314-A" for Advanced on display
   - NeoPixel colors:
     - 🟡 Yellow = Searching for protocol
     - 🟢 Green = Protocol detected, no targets
     - 🔴 Red = Targets detected!

2. **Added diagnostic tool** → `F:\radar_diagnostic.py`

## 🔍 Debugging Steps:

### Step 1: Check Current Status
Connect to serial monitor (115200 baud) and look for:
```
Alien Motion Tracker - Dual Protocol
Auto-detecting radar protocol...
Status: 0 bytes/5s, 0 frames, Mode: None   ← BAD! No data
Status: 15000 bytes/5s, 30 frames, Mode: BASIC   ← GOOD!
```

### Step 2: If NO DATA (0 bytes/5s):

**Check Physical Connections:**
```
HLK-LD2450        ESP32-S3 ProS3
-----------       --------------
TX (Yellow)  -->  IO44 (RX)  ← Data FROM radar
RX (Green)   -->  IO43 (TX)  ← Data TO radar
VCC (Red)    -->  5V         ← Power
GND (Black)  -->  GND        ← Ground
```

**Common Issues:**
- ❌ TX/RX swapped (try IO43 ↔ IO44)
- ❌ No power to radar (check 5V connection)
- ❌ No GND connection
- ❌ Radar in wrong mode/needs reset

### Step 3: Run Diagnostic Tool

```powershell
# On your PC, copy diagnostic to code.py
Copy-Item F:\radar_diagnostic.py F:\code.py -Force
```

Wait 2 seconds, then check serial output for detailed connection info.

### Step 4: If BYTES but NO FRAMES:

The baudrate might be wrong. Try other rates:
- 256000 (default)
- 115200
- 9600

### Step 5: Check Radar Power LED

The HLK-LD2450 should have a power LED. If it's not lit:
- Not getting 5V power
- Bad connection
- Dead radar module

## 🔌 Wiring Reference

Your working code uses:
```python
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, ...)
```

This means:
- **IO43** = ESP32 TX → Radar RX (pin with GREEN wire)
- **IO44** = ESP32 RX ← Radar TX (pin with YELLOW wire)
- **5V** = Radar VCC (RED wire)
- **GND** = Radar GND (BLACK wire)

## 📊 Expected Behavior

Once working, you should see:
- **Serial Monitor**: `B-T1: 2.50m` or `A-T1: 2.50m`
- **OLED Display**: "M314-B" or "M314-A" in top left
- **NeoPixel**: Changes from yellow → green → red
- **Target blips** appear when you wave your hand

## 🔄 Quick Tests

### Test 1: Check if any UART data arrives
```python
# Minimal test - paste into code.py
import board, busio, time
uart = busio.UART(board.IO43, board.IO44, baudrate=256000, timeout=0)
while True:
    if uart.in_waiting:
        print(f"Got {uart.in_waiting} bytes!")
    time.sleep(0.5)
```

### Test 2: Try swapped pins
```python
# If no data, try swapping TX/RX
uart = busio.UART(board.IO44, board.IO43, baudrate=256000, timeout=0)
```

## 📝 Files on Your Device

- `F:\code.py` ← Active (dual-protocol)
- `F:\code.py.working` ← Your previous working code
- `F:\radar_diagnostic.py` ← Diagnostic tool
- `F:\uart_diagnostic.py` ← Another diagnostic
- `F:\code_alien_style.py` ← Single-protocol version

## 🎯 Next Steps

1. **Check serial output** for protocol detection
2. **Verify NeoPixel color** (should turn green when detected)
3. **Check OLED top-left** for "M314-B" or "M314-A"
4. If still nothing, **swap TX/RX wires** physically
5. If still nothing, **test radar power** (should have LED on)

## 📞 Status Indicators

| NeoPixel | Meaning |
|----------|---------|
| 🟡 Yellow | Searching for protocol |
| 🟢 Green | Protocol OK, no targets |
| 🔴 Red | Targets detected! |

| OLED | Meaning |
|------|---------|
| M314-? | Searching for protocol |
| M314-B | Basic mode (0xAA 0xFF) |
| M314-A | Advanced mode (0xAA 0x55) |

---

**The radar should work now!** The dual-protocol code will automatically detect whichever mode your radar is using. Check your serial monitor for status updates every 5 seconds.
