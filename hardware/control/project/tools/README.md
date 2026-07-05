# Project Tools

PC-side helpers for the RT1064 firmware under `../user/src/main.c`.

## Chassis Serial Control

Use `chassis_serial_control.py` for direct car commands over USB CDC:

```powershell
python .\chassis_serial_control.py ports
python .\chassis_serial_control.py --port COM13 status
python .\chassis_serial_control.py --port COM13 forward --speed 200 --duration 1.0 --yes
python .\chassis_serial_control.py --port COM13 drive --vx 0 --vy 200 --wz 0 --duration 1.0 --yes
python .\chassis_serial_control.py --port COM13 turn 90 --read-duration 8 --yes
python .\chassis_serial_control.py --port COM13 monitor
```

Velocity command units match the firmware:

```text
vx: right-positive, mm/s
vy: forward-positive, mm/s
wz: CCW-positive, deg/s
```

Timed velocity commands auto-send `s` when the duration ends unless `--no-stop` is passed.

## PI Serial Tuner

Use `pid_serial_tuner.py` for single-wheel PI tuning, bounded sweeps, and raw feedback checks.

## Turn Test GUI

Use `turn_test_gui.py` for click-to-send turn tests:

```powershell
python .\turn_test_gui.py
```

Or double-click `turn_test_gui.bat` on Windows.

Typical flow:

```text
1. Select COM port and click connect.
2. Click IMU 静止校准 while the car is still.
3. Click 应用参数 to send turn max/min and translation compensation.
4. Click 左转 90° / 右转 90° / 左转 180° / 右转 180°.
5. Use 停止 for emergency stop.
```

Turn compensation uses firmware body-frame units:

```text
vx: right-positive, mm/s
vy: forward-positive, mm/s
```

Current floor-tested defaults:

```text
turn max = 150
turn min = 120
left  turn: lvx = -10, lvy = 10
right turn: rvx = -25, rvy = 0
```
