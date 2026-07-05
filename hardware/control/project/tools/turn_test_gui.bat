@echo off
cd /d "%~dp0"
python -c "import serial" >nul 2>nul
if errorlevel 1 (
    echo Missing pyserial. Installing...
    python -m pip install pyserial
)
python turn_test_gui.py
pause
