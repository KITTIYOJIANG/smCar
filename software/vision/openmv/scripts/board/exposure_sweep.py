# OpenMV exposure sweep for projected SmartCar VR screen.
#
# Use this when the screen is still overexposed at the lowest physical
# brightness. It cycles through very short exposure values and prints LAB
# statistics for the screen ROI. Choose the lowest exposure that still keeps
# colors visible without washing white/blue/cyan together.

import sensor
import time


FRAME_SIZE = sensor.VGA
PIX_FORMAT = sensor.RGB565

GAIN_DB = 0
BRIGHTNESS = -4
CONTRAST = 1
SATURATION = 3

# Adjust this red box so it covers the screen/game area only.
SCREEN_ROI = (205, 5, 285, 225)

EXPOSURES_US = [80, 120, 160, 220, 300, 420, 600, 850, 1200]
FRAMES_PER_EXPOSURE = 45
PRINT_EVERY_N_FRAMES = 15


def apply_camera(exposure_us):
    sensor.set_auto_gain(False, gain_db=GAIN_DB)
    sensor.set_auto_exposure(False, exposure_us=exposure_us)
    sensor.set_auto_whitebal(False)
    sensor.set_brightness(BRIGHTNESS)
    sensor.set_contrast(CONTRAST)
    sensor.set_saturation(SATURATION)


sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)
apply_camera(EXPOSURES_US[0])
sensor.skip_frames(time=1500)

clock = time.clock()
frame_count = 0
exposure_index = 0

while True:
    clock.tick()

    if frame_count % FRAMES_PER_EXPOSURE == 0:
        exposure_us = EXPOSURES_US[exposure_index]
        apply_camera(exposure_us)
        exposure_index = (exposure_index + 1) % len(EXPOSURES_US)
        # Give the sensor a few frames after switching exposure.
        sensor.skip_frames(n=3)

    img = sensor.snapshot()
    frame_count += 1
    stats = img.get_statistics(roi=SCREEN_ROI)

    img.draw_rectangle(SCREEN_ROI, color=(255, 0, 0), thickness=2)

    if frame_count % PRINT_EVERY_N_FRAMES == 0:
        print(
            "fps=%.1f exp_us=%d Lmean=%d Luq=%d Amin=%d Amean=%d Amax=%d Bmin=%d Bmean=%d Bmax=%d"
            % (
                clock.fps(),
                exposure_us,
                stats.l_mean(),
                stats.l_uq(),
                stats.a_min(),
                stats.a_mean(),
                stats.a_max(),
                stats.b_min(),
                stats.b_mean(),
                stats.b_max(),
            )
        )
