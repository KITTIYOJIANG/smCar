# Template for the recommended OpenART deployment path.
# This works with old OpenMV V4.3 tf runtime because it uses classifiers,
# not FOMO/object detection.
#
# Required files on board:
# - num.tflite: classifier for labels 00..09
# - char.tflite: classifier for character labels
#
# Tune NUM_ROI and CHAR_ROI to your camera image.

import sensor
import tf
import time

try:
    from pyb import UART
except ImportError:
    UART = None


NUM_MODEL = "num.tflite"
CHAR_MODEL = "char.tflite"
SCORE_THRESHOLD = 0.70
VOTE_FRAMES = 3

# QVGA frame coordinates after any windowing/rotation you use.
# Format: x, y, w, h
NUM_ROI = (0, 0, 120, 120)
CHAR_ROI = (120, 0, 120, 120)

NUM_LABELS = ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
CHAR_LABELS = [
    "mickey_mouse",
    "pikachu",
    "spongebob_squarepants",
    "pleasant_sheep",
    "donald_duck",
    "nezha",
    "big_head_son",
    "gg_bond",
    "calabash_brothers",
    "grey_wolf",
]

UART_ENABLE = False
UART_ID = 3
UART_BAUD = 115200


def load_model(path):
    return tf.load(path, load_to_fb=False)


def classify_roi(net, img, roi, labels):
    objs = tf.classify(
        net,
        img,
        roi=roi,
        min_scale=1.0,
        scale_mul=0.5,
        x_overlap=0.0,
        y_overlap=0.0,
    )
    if not objs:
        return "unknown", 0.0

    out = objs[0].output()
    best_i = 0
    best_s = 0.0
    for i, value in enumerate(out):
        score = value / 255.0 if value > 1.0 else value
        if score > best_s:
            best_i = i
            best_s = score

    if best_s < SCORE_THRESHOLD or best_i >= len(labels):
        return "unknown", best_s
    return labels[best_i], best_s


def stable_vote(history, value):
    history.append(value)
    if len(history) > VOTE_FRAMES:
        history.pop(0)
    if len(history) < VOTE_FRAMES:
        return "unknown"
    first = history[0]
    for item in history:
        if item != first:
            return "unknown"
    return first


def send_line(uart, line):
    print(line)
    if uart:
        uart.write(line + "\n")


sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

num_net = load_model(NUM_MODEL)
char_net = load_model(CHAR_MODEL)
print("DUAL_ROI_CLASSIFIER_READY")
print("num_model:", num_net)
print("char_model:", char_net)

uart = None
if UART_ENABLE and UART:
    uart = UART(UART_ID, UART_BAUD, timeout_char=1000)

num_hist = []
char_hist = []
last_line = ""
clock = time.clock()

while True:
    clock.tick()
    img = sensor.snapshot()

    img.draw_rectangle(NUM_ROI, color=(255, 0, 0))
    img.draw_rectangle(CHAR_ROI, color=(0, 255, 0))

    num_label, num_score = classify_roi(num_net, img, NUM_ROI, NUM_LABELS)
    char_label, char_score = classify_roi(char_net, img, CHAR_ROI, CHAR_LABELS)

    stable_num = stable_vote(num_hist, num_label)
    stable_char = stable_vote(char_hist, char_label)

    if stable_num != "unknown" or stable_char != "unknown":
        conf = min(num_score if stable_num != "unknown" else 1.0,
                   char_score if stable_char != "unknown" else 1.0)
        line = "NUM=%s,CHAR=%s,CONF=%.2f" % (stable_num, stable_char, conf)
        if line != last_line:
            send_line(uart, line)
            last_line = line

    print("fps %.2f" % clock.fps())
