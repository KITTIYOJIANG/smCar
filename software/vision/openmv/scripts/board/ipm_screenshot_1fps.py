# OpenART / OpenMV RT board script
# VGA 640x480 camera -> perspective correction -> save 1 JPG per second.
#
# Copy this file to OpenMV IDE and run it, or save it as main.py on the board.
# Saved files:
#   /sd/ipm_000.jpg
#   /sd/ipm_001.jpg
#   ...
#
# Source corner order from the raw 640x480 image:
#   LT = (197, 134)
#   RT = (462, 192)
#   LB = (206, 324)
#   RB = (461, 324)
#
# The old main.py used 180-degree corrected perspective:
#   corners = [RB, LB, LT, RT]

import gc
import os
import sensor
import time

try:
    from machine import UART
except Exception:
    UART = None


# -----------------------------
# Camera profile
# -----------------------------

FRAME_SIZE = sensor.VGA  # 640 x 480
PIX_FORMAT = sensor.RGB565

# Lighting parameters copied from your main.py.
MAIN_FIXED_EXPOSURE_US = 100
MAIN_GAIN_DB = 0
MAIN_BRIGHTNESS = -3
MAIN_CONTRAST = 0
MAIN_SATURATION = 0
MAIN_SHARPNESS = 2

# Active fixed profile. Keep these equal to main.py unless you intentionally
# want to test fixed exposure again.
FIXED_EXPOSURE_US = MAIN_FIXED_EXPOSURE_US
GAIN_DB = 0
BRIGHTNESS = MAIN_BRIGHTNESS
CONTRAST = MAIN_CONTRAST
SATURATION = MAIN_SATURATION
SHARPNESS = MAIN_SHARPNESS

# Your current screen is badly overexposed, so the default is the darker
# adaptive profile. Set this to False only when you want the exact main.py
# fixed exposure profile.
USE_ADAPTIVE_EXPOSURE = True

# Dark profile based on screenshot.py, adjusted for this IPM area.
EXPOSURE_US_START = 100
EXPOSURE_US_MIN = 40
EXPOSURE_US_MAX = 420

# Exposure statistics are measured before IPM on the source screen area.
# This is the bounding rectangle of:
# LT=(197,134), RT=(462,192), LB=(206,324), RB=(461,324)
SCREEN_ROI = (197, 134, 265, 190)

# OpenMV LAB L channel is about 0..100. Lower target means darker image.
TARGET_L_MEAN = 34
TARGET_L_UQ = 54
EXPOSURE_INTERVAL_MS = 500

DARKEN_STRONG = 0.75
DARKEN_SOFT = 0.88
BRIGHTEN_SOFT = 1.02
BRIGHTEN_STRONG = 1.04


# -----------------------------
# Perspective correction points
# -----------------------------

LT = (200, 138)
RT = (466, 138)
LB = (200, 324)
RB = (466, 324)

# 180-degree corrected inverse perspective, same idea as main.py.
CORNERS_ROT_180 = [RB, LB, LT, RT]


# -----------------------------
# Save settings
# -----------------------------

SAVE_DIR = "/sd/"
SAVE_PREFIX = "ipm"
SAVE_EXT = ".jpg"
JPEG_QUALITY = 85

AUTO_SAVE = True
AUTO_SAVE_INTERVAL_MS = 1000
AUTO_SAVE_MAX_SHOTS = 300

# Keep False for clean training images. Set True only when checking the corners.
DRAW_DEBUG_ON_PREVIEW = False

# Optional serial trigger. Send "s" or "S" to save immediately.
OPENART_UART_ID = 2
OPENART_UART_BAUDRATE = 115200


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


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


def get_uart():
    if UART is None:
        return None
    try:
        return UART(OPENART_UART_ID, baudrate=OPENART_UART_BAUDRATE)
    except Exception:
        return None


def set_camera_fixed():
    try:
        sensor.set_auto_gain(False, gain_db=GAIN_DB)
    except Exception:
        pass
    try:
        sensor.set_auto_whitebal(False)
    except Exception:
        pass
    try:
        sensor.set_auto_exposure(False, exposure_us=FIXED_EXPOSURE_US)
    except Exception:
        pass
    try:
        sensor.set_brightness(BRIGHTNESS)
    except Exception:
        pass
    try:
        sensor.set_contrast(CONTRAST)
    except Exception:
        pass
    try:
        sensor.set_saturation(SATURATION)
    except Exception:
        pass
    try:
        sensor.set_sharpness(SHARPNESS)
    except Exception:
        pass


def set_camera_adaptive(exposure_us):
    try:
        sensor.set_auto_gain(False, gain_db=GAIN_DB)
    except Exception:
        pass
    try:
        sensor.set_auto_whitebal(False)
    except Exception:
        pass
    try:
        sensor.set_auto_exposure(False, exposure_us=exposure_us)
    except Exception:
        pass
    try:
        sensor.set_brightness(-4)
    except Exception:
        pass
    try:
        sensor.set_contrast(1)
    except Exception:
        pass
    try:
        sensor.set_saturation(3)
    except Exception:
        pass


def trim_exposure_if_needed(img, exposure_us, now_ms, last_exposure_ms):
    if not USE_ADAPTIVE_EXPOSURE:
        return exposure_us, last_exposure_ms
    if time.ticks_diff(now_ms, last_exposure_ms) < EXPOSURE_INTERVAL_MS:
        return exposure_us, last_exposure_ms

    stats = img.get_statistics(roi=SCREEN_ROI)
    l_mean = stats.l_mean()
    l_uq = stats.l_uq()

    if l_uq > TARGET_L_UQ + 12 or l_mean > TARGET_L_MEAN + 14:
        exposure_us = scale_exposure(exposure_us, DARKEN_STRONG)
    elif l_uq > TARGET_L_UQ + 5 or l_mean > TARGET_L_MEAN + 7:
        exposure_us = scale_exposure(exposure_us, DARKEN_SOFT)
    elif l_mean < TARGET_L_MEAN - 12 and l_uq < TARGET_L_UQ - 15:
        exposure_us = scale_exposure(exposure_us, BRIGHTEN_STRONG)
    elif l_mean < TARGET_L_MEAN - 6 and l_uq < TARGET_L_UQ - 8:
        exposure_us = scale_exposure(exposure_us, BRIGHTEN_SOFT)

    try:
        sensor.set_auto_exposure(False, exposure_us=exposure_us)
    except Exception:
        pass
    return exposure_us, now_ms


def apply_ipm_180(img):
    # rotation_corr modifies the image shown/saved by OpenMV.
    img.rotation_corr(corners=CORNERS_ROT_180)
    return img


def draw_debug(img):
    # This is drawn after saving, so saved training images stay clean.
    try:
        img.draw_string(8, 8, "IPM 1FPS", color=(255, 0, 0), scale=2)
        img.draw_string(8, 34, "%d,%d" % LT, color=(255, 0, 0), scale=1)
        img.draw_string(8, 50, "%d,%d" % RT, color=(255, 0, 0), scale=1)
        img.draw_string(8, 66, "%d,%d" % LB, color=(255, 0, 0), scale=1)
        img.draw_string(8, 82, "%d,%d" % RB, color=(255, 0, 0), scale=1)
    except Exception:
        pass


sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)

if USE_ADAPTIVE_EXPOSURE:
    exposure_us = EXPOSURE_US_START
    set_camera_adaptive(exposure_us)
else:
    exposure_us = FIXED_EXPOSURE_US
    set_camera_fixed()

sensor.skip_frames(time=2000)

clock = time.clock()
uart = get_uart()
shot_index = find_start_index()
auto_shot_count = 0
last_save_ms = time.ticks_ms()
last_exposure_ms = time.ticks_ms()

print("IPM_SCREENSHOT_1FPS_START")
print("frame=640x480")
print("corners_rot_180=", CORNERS_ROT_180)
print("save_dir=", SAVE_DIR)
print("start_index=", shot_index)
print("adaptive_exposure=", USE_ADAPTIVE_EXPOSURE)

while True:
    clock.tick()
    img = sensor.snapshot()
    now_ms = time.ticks_ms()

    exposure_us, last_exposure_ms = trim_exposure_if_needed(
        img, exposure_us, now_ms, last_exposure_ms
    )

    img = apply_ipm_180(img)

    save_requested = False
    if AUTO_SAVE and auto_shot_count < AUTO_SAVE_MAX_SHOTS:
        if time.ticks_diff(now_ms, last_save_ms) >= AUTO_SAVE_INTERVAL_MS:
            save_requested = True
            last_save_ms = now_ms

    if uart is not None:
        try:
            if uart.any():
                data = uart.read(uart.any())
                if b"s" in data or b"S" in data:
                    save_requested = True
        except Exception:
            pass

    if save_requested:
        filename = next_filename(shot_index)
        try:
            img.save(filename, quality=JPEG_QUALITY)
            print(
                "saved=%s fps=%.1f exp_us=%d"
                % (filename, clock.fps(), exposure_us)
            )
            shot_index += 1
            if auto_shot_count < AUTO_SAVE_MAX_SHOTS:
                auto_shot_count += 1
        except Exception as err:
            print("save_failed:", err)

    if DRAW_DEBUG_ON_PREVIEW:
        draw_debug(img)

    gc.collect()
