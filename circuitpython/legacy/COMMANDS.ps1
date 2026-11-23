# Quick PowerShell Commands for ESP32 Radar Debugging

# View current code
Get-Content F:\code.py | Select-Object -First 20

# List all Python files
Get-ChildItem F:\ -Filter "*.py" | Select-Object Name, LastWriteTime

# Deploy diagnostic test
Copy-Item F:\test_radar_minimal.py F:\code.py -Force

# Deploy I2C scanner
Copy-Item F:\i2c_scan.py F:\code.py -Force

# Restore working code
Copy-Item F:\code.py.working F:\code.py -Force

# Deploy Alien tracker (dual protocol)
Copy-Item F:\code_dual_protocol.py F:\code.py -Force

# Deploy Alien tracker (basic protocol)
Copy-Item F:\code_alien_style.py F:\code.py -Force

# Backup current code
Copy-Item F:\code.py F:\code.py.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')

# View serial output (replace COM3 with your port)
# Get-Content -Path "\\.\COM3" -Encoding Byte -ReadCount 1
