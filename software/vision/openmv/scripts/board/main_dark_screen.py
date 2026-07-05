# OpenMV screen camera tuning script.
#
# Goal:
#   Keep the projected SmartCar VR screen readable for recognition.
#   Gain and white-balance are locked, while exposure is adjusted gently so
#   changing room/screen brightness does not destroy the color thresholds.
#
# Usage:
#   1. Copy this file to OpenMV IDE and run it, or save it as main.py.
#   2. Aim the camera at the screen.
#   3. Adjust SCREEN_ROI so the red rectangle covers only the bright game screen.
#   4. If the image still pumps too much, increase TRIM_EVERY_N_FRAMES.
#      If it adapts too slowly, decrease TRIM_EVERY_N_FRAMES a little.

import sensor
import time


# -------- Camera profile --------

FRAME_SIZE = sensor.VGA  # 640 x 480
PIX_FORMAT = sensor.RGB565

# Ultra-dark adaptive profile for over-bright projected screens.
# If colors are still clipped at the minimum physical screen brightness, the
# camera must run far below 500 us before color thresholds will separate.
EXPOSURE_US_START = 220
EXPOSURE_US_MIN = 80
EXPOSURE_US_MAX = 900
GAIN_DB = 0

BRIGHTNESS = -4
CONTRAST = 1
SATURATION = 3

# Screen region in a 640x480 image: (x, y, w, h).
# Tune this in OpenMV IDE so the red box covers only the bright game screen.
# The old ROI included dark screen bezel/bottom area, which kept the LCD too bright.
SCREEN_ROI = (205, 5, 285, 225)

# LAB L-channel targets in OpenMV scale: L is about 0..100.
# Lower target for color recognition. The previous 72/85 target looked okay to
# humans, but white borders and colored tiles were still too close to clipping.
TARGET_L_MEAN = 48
TARGET_L_UQ = 68

AUTO_EXPOSURE_TRIM = True
TRIM_EVERY_N_FRAMES = 20
PRINT_EVERY_N_FRAMES = 20

# Small steps avoid visible exposure jumps.
DARKEN_STRONG = 0.88
DARKEN_SOFT = 0.95
BRIGHTEN_SOFT = 1.02
BRIGHTEN_STRONG = 1.04


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


def set_manual_camera(exposure_us):
    sensor.set_auto_gain(False, gain_db=GAIN_DB)
    sensor.set_auto_exposure(False, exposure_us=exposure_us)
    sensor.set_auto_whitebal(False)
    sensor.set_brightness(BRIGHTNESS)
    sensor.set_contrast(CONTRAST)
    sensor.set_saturation(SATURATION)


sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)
set_manual_camera(EXPOSURE_US_START)
sensor.skip_frames(time=2000)

clock = time.clock()
exposure_us = EXPOSURE_US_START
frame_count = 0

while True:
    clock.tick()
    img = sensor.snapshot()
    frame_count += 1

    stats = img.get_statistics(roi=SCREEN_ROI)
    l_mean = stats.l_mean()
    l_uq = stats.l_uq()

    if AUTO_EXPOSURE_TRIM and (frame_count % TRIM_EVERY_N_FRAMES == 0):
        # Brightness deadband: do nothing when already close enough.
        if l_uq > TARGET_L_UQ + 12 or l_mean > TARGET_L_MEAN + 14:
            exposure_us = scale_exposure(exposure_us, DARKEN_STRONG)
        elif l_uq > TARGET_L_UQ + 5 or l_mean > TARGET_L_MEAN + 7:
            exposure_us = scale_exposure(exposure_us, DARKEN_SOFT)
        elif l_mean < TARGET_L_MEAN - 12 and l_uq < TARGET_L_UQ - 15:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_STRONG)
        elif l_mean < TARGET_L_MEAN - 6 and l_uq < TARGET_L_UQ - 8:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_SOFT)

        sensor.set_auto_exposure(False, exposure_us=exposure_us)

    # Draw debug ROI after statistics so the rectangle does not affect tuning.
    img.draw_rectangle(SCREEN_ROI, color=(255, 0, 0), thickness=2)

    if frame_count % PRINT_EVERY_N_FRAMES == 0:
        print(
            "fps=%.1f exp_us=%d Lmean=%d Luq=%d"
            % (clock.fps(), exposure_us, l_mean, l_uq)
        )
