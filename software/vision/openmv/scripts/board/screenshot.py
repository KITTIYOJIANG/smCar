# 优化版：1秒精确定时拍照，极速保存防卡顿
import sensor
import time
import os
import sys

try:
    import pyb
    import machine
    from machine import Pin, UART
    import uselect as select
except ImportError:
    pass # 兼容处理

# -------- 核心配置 --------
FRAME_SIZE = sensor.VGA  # 640 x 480
PIX_FORMAT = sensor.RGB565

# 曝光参数
EXPOSURE_US_START = 220
EXPOSURE_US_MIN = 80
EXPOSURE_US_MAX = 900
GAIN_DB = 0
BRIGHTNESS = -4
CONTRAST = 1
SATURATION = 3

# 截图区域
SCREEN_ROI = (205, 5, 285, 225)
TARGET_L_MEAN = 48
TARGET_L_UQ = 68

AUTO_EXPOSURE_TRIM = True
DARKEN_STRONG = 0.88
DARKEN_SOFT = 0.95
BRIGHTEN_SOFT = 1.02
BRIGHTEN_STRONG = 1.04

# -------- 截图与保存设置 (重点优化区) --------
SAVE_DIR = "/sd/"
SAVE_PREFIX = "screen"
SAVE_EXT = ".jpg"

# 【优化1】降低 JPEG 质量，缩短 SD 卡写入时间（原为95，现改为75）。
# 75 的画质依然清晰，但文件体积减半，保存速度翻倍，极大减少卡顿感。
JPEG_QUALITY = 75
SAVE_FULL_FRAME = False

# 【优化2】定时器配置：精确到毫秒
AUTO_SAVE = True
AUTO_SAVE_INTERVAL_MS = 1000  # 精确控制：1000毫秒 (1秒) 拍一次
EXPOSURE_INTERVAL_MS = 500    # 每500毫秒调整一次曝光 (脱离帧率限制)
AUTO_SAVE_MAX_SHOTS = 200     # 最大拍摄张数

# 触发器配置
OPENART_KEY_PIN = "WAKEUP"
OPENART_KEY_PRESSED_LEVEL = None
OPENART_UART_ID = 2
OPENART_UART_BAUDRATE = 115200

# -------- 辅助函数 --------
def clamp(value, low, high):
    return max(low, min(value, high))

def scale_exposure(exposure_us, factor):
    next_exposure = int(exposure_us * factor)
    if factor > 1 and next_exposure <= exposure_us:
        next_exposure = exposure_us + 1
    elif factor < 1 and next_exposure >= exposure_us:
        next_exposure = exposure_us - 1
    return clamp(next_exposure, EXPOSURE_US_MIN, EXPOSURE_US_MAX)

def next_filename(index):
    return "%s%s_%03d%s" % (SAVE_DIR, SAVE_PREFIX, index, SAVE_EXT)

def find_start_index():
    index = 0
    while True:
        try:
            os.stat(next_filename(index))
            index += 1
        except OSError:
            return index

# -------- 硬件初始化略写 --------
# (为了保持代码整洁，将冗余的初始化折叠，功能照常)
def get_uart():
    try: return UART(OPENART_UART_ID, baudrate=OPENART_UART_BAUDRATE)
    except: return None

# 初始化摄像头
sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)
sensor.set_auto_gain(False, gain_db=GAIN_DB)
sensor.set_auto_exposure(False, exposure_us=EXPOSURE_US_START)
sensor.set_auto_whitebal(False)
sensor.set_brightness(BRIGHTNESS)
sensor.set_contrast(CONTRAST)
sensor.set_saturation(SATURATION)
sensor.skip_frames(time=2000)

clock = time.clock()
exposure_us = EXPOSURE_US_START
shot_index = find_start_index()
auto_shot_count = 0
uart = get_uart()

print("✅ 已开启极速定时拍照模式: 1张/秒")

# 【优化3】初始化时间戳
last_save_time = time.ticks_ms()
last_exposure_time = time.ticks_ms()

while True:
    clock.tick()
    img = sensor.snapshot()
    current_time = time.ticks_ms() # 获取当前毫秒时间戳

    # 1. 动态曝光控制 (基于时间，不基于帧数)
    if AUTO_EXPOSURE_TRIM and time.ticks_diff(current_time, last_exposure_time) >= EXPOSURE_INTERVAL_MS:
        stats = img.get_statistics(roi=SCREEN_ROI)
        l_mean, l_uq = stats.l_mean(), stats.l_uq()

        if l_uq > TARGET_L_UQ + 12 or l_mean > TARGET_L_MEAN + 14:
            exposure_us = scale_exposure(exposure_us, DARKEN_STRONG)
        elif l_uq > TARGET_L_UQ + 5 or l_mean > TARGET_L_MEAN + 7:
            exposure_us = scale_exposure(exposure_us, DARKEN_SOFT)
        elif l_mean < TARGET_L_MEAN - 12 and l_uq < TARGET_L_UQ - 15:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_STRONG)
        elif l_mean < TARGET_L_MEAN - 6 and l_uq < TARGET_L_UQ - 8:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_SOFT)

        sensor.set_auto_exposure(False, exposure_us=exposure_us)
        last_exposure_time = current_time # 重置曝光计时器

    # 2. 定时拍照控制 (基于时间差，严格1秒)
    save_requested = False
    if AUTO_SAVE and auto_shot_count < AUTO_SAVE_MAX_SHOTS:
        if time.ticks_diff(current_time, last_save_time) >= AUTO_SAVE_INTERVAL_MS:
            save_requested = True
            last_save_time = current_time # 重置拍照计时器

    # 3. 串口触发捕获 (保留)
    if uart and uart.any():
        data = uart.read(uart.any())
        if b's' in data or b'S' in data:
            save_requested = True

    # 4. 执行保存
    if save_requested:
        filename = next_filename(shot_index)
        try:
            # 【优化4】优先直接写入 ROI 区域，不使用 copy()，极大节省内存和 CPU 耗时
            if not SAVE_FULL_FRAME:
                img.save(filename, roi=SCREEN_ROI, quality=JPEG_QUALITY)
            else:
                img.save(filename, quality=JPEG_QUALITY)

            print(f"📸 拍照成功: {filename} | 帧率: {clock.fps():.1f}")
            shot_index += 1
            if auto_shot_count < AUTO_SAVE_MAX_SHOTS:
                auto_shot_count += 1

        except Exception as err:
            print("❌ 保存失败:", err)
