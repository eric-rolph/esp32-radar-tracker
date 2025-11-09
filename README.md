# ESP32 Radar Tracker with HLK-LD2450

Real-time radar tracking system using the HLK-LD2450 24GHz mmWave radar sensor with OLED display visualization. Features both Arduino and CircuitPython implementations for the ESP32-S3.

## 🎯 Features

- **Multi-Target Tracking**: Simultaneously tracks up to 3 targets with X/Y coordinates
- **Real-time Visualization**: OLED display with animated radar sweep and target positions
- **Dual Platform Support**: 
  - Arduino C++ with optimized performance
  - CircuitPython with multiple visualization modes
- **Multiple Visualization Modes**:
  - Classic radar sweep display
  - Alien-style animated tracking
  - Diagnostic data output
  - Raw protocol debugging

## 📡 Hardware Requirements

- **ESP32-S3** (tested on ProS3 board)
- **HLK-LD2450** 24GHz mmWave Radar Sensor
- **0.96" OLED Display** (128x64, I2C, SSD1306)
- USB-C cable for programming and power

### Wiring Diagram

**Radar to ESP32:**
- TX → RX (GPIO 44)
- RX → TX (GPIO 43)
- VCC → 5V
- GND → GND

**OLED to ESP32:**
- SDA → GPIO 8
- SCL → GPIO 9
- VCC → 3.3V
- GND → GND

## 🚀 Quick Start

### Arduino Setup

1. Install Arduino IDE with ESP32 support
2. Install required libraries:
   - Adafruit SSD1306
   - Adafruit GFX Library
3. Open `arduino/ESP32_Radar_Tracker.ino`
4. Select board: **ESP32-S3 Dev Module**
5. Upload to your ESP32

### CircuitPython Setup

1. Install CircuitPython 9.x on your ESP32-S3
2. Install required libraries on device:
   - adafruit_displayio_ssd1306
   - adafruit_display_text
3. Choose a visualization mode from `circuitpython/` folder
4. Deploy using the utility tool:

```powershell
python utils/deploy_circuitpython.py
```

Available CircuitPython modes:
- `code_correct_protocol.py` - Standard radar sweep display
- `code_alien_style.py` - Sci-fi animated tracking
- `code_dual_both.py` - Dual protocol support
- `code_diagnostic.py` - Debug output
- `code_realtime_sweep.py` - Fast refresh radar sweep

## 🛠️ Utilities

### Serial Monitor
Monitor ESP32 serial output in real-time:
```powershell
python utils/serial_monitor.py
```

### Code Deployment
Deploy CircuitPython code to ESP32:
```powershell
python utils/deploy_circuitpython.py
```

See [utils/README.md](utils/README.md) for detailed utility documentation.

## 📊 HLK-LD2450 Sensor Details

- **Detection Range**: 0-6 meters
- **Angle Coverage**: ±60°
- **Maximum Targets**: 3 simultaneous
- **Protocol**: UART (115200 baud)
- **Update Rate**: ~10 Hz
- **Technology**: 24GHz FMCW radar

## 🎨 Visualization Modes

### Arduino Version
- Clean radar sweep with target markers
- Distance and position text overlay
- 128x64 optimized graphics

### CircuitPython Versions

**Standard Mode** (`code_correct_protocol.py`)
- Classic radar sweep animation
- Target position markers
- Distance labels

**Alien Style** (`code_alien_style.py`)
- Animated target tracking
- Fade effects
- Sci-fi aesthetic

**Diagnostic Mode** (`code_diagnostic.py`)
- Raw data output
- Protocol debugging
- Sensor status monitoring

## 🔧 Troubleshooting

### No Radar Data
1. Check UART wiring (TX/RX)
2. Verify sensor power (5V)
3. Run diagnostic mode to check protocol

### Display Not Working
1. Verify I2C address (0x3C default)
2. Check SDA/SCL wiring
3. Run `i2c_scan.py` to detect display

### COM Port Issues
- Windows: Check Device Manager for COM port
- Linux/Mac: Use `ls /dev/tty*` to find port
- Ensure no other program is using the port

## �� Project Structure

```
esp32-radar-tracker/
├── arduino/              # Arduino C++ implementation
│   ├── ESP32_Radar_Tracker.ino
│   ├── HLK_LD2450.h     # Radar protocol parser
│   └── RadarDisplay.h   # OLED graphics
├── circuitpython/       # Multiple CircuitPython versions
│   ├── code_correct_protocol.py
│   ├── code_alien_style.py
│   ├── code_diagnostic.py
│   └── ...              # Various visualization modes
├── utils/               # Deployment and monitoring tools
│   ├── deploy_circuitpython.py
│   ├── serial_monitor.py
│   └── README.md
├── docs/                # Additional documentation
├── requirements.txt     # Python dependencies
└── README.md
```

## 🤝 Contributing

Contributions welcome! Areas for improvement:
- Additional visualization modes
- Enhanced target tracking algorithms
- Multi-sensor support
- Data logging features

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Adafruit**: Display libraries and CircuitPython support
- **Hi-Link**: HLK-LD2450 sensor and protocol documentation
- **ESP32 Community**: Hardware support and examples

## 📚 Resources

- [HLK-LD2450 Datasheet](https://www.hlktech.net/index.php?id=1163)
- [CircuitPython Documentation](https://circuitpython.org/)
- [ESP32-S3 Technical Reference](https://www.espressif.com/en/products/socs/esp32-s3)
- [Adafruit SSD1306 Guide](https://learn.adafruit.com/monochrome-oled-breakouts)

---

**Status**: ✅ Fully functional - tested with ESP32-S3 ProS3 and HLK-LD2450
