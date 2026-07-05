# Preview the IPM source corners on the raw OpenART camera image.
#
# Run this from OpenMV IDE when tuning ipm_runtime_config.py. The yellow polygon
# should cover only the target character panel that will be stretched to the
# model input.

import sensor
import time

try:
    import ipm_runtime_config as ipm_config
except Exception:
    ipm_config = None


DEFAULT_CORNERS = ((108, 63), (204, 64), (204, 155), (104, 155))
IPM_CORNERS = DEFAULT_CORNERS

if ipm_config is not None:
    try:
        IPM_CORNERS = ipm_config.IPM_CORNERS
    except Exception:
        pass


def draw_corners(img, corners):
    color = (255, 255, 0)
    for index in range(4):
        x1, y1 = corners[index]
        x2, y2 = corners[(index + 1) % 4]
        img.draw_line((x1, y1, x2, y2), color=color, thickness=2)
        img.draw_circle((x1, y1, 4), color=(255, 0, 0), thickness=2)
        img.draw_string(x1 + 4, y1 + 4, str(index + 1), color=(255, 255, 255), scale=1)


sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1500)

print("IPM_CORNER_PREVIEW_READY")
print("corners:", IPM_CORNERS)
print("order: 1=top-left 2=top-right 3=bottom-right 4=bottom-left")

clock = time.clock()
while True:
    clock.tick()
    img = sensor.snapshot()
    draw_corners(img, IPM_CORNERS)
    img.draw_string(2, 2, "IPM corner preview", color=(255, 255, 0), scale=1)
    print("fps %.2f" % clock.fps())
