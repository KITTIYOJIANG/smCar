# Edge Impulse FOMO runner for old OpenMV tf API.
# This uses tf.classify() and manually decodes the FOMO output tensor.
# Model checked on PC: input 96x96x3, output 12x12x21.

import math
import sensor
import tf
import time

try:
    from pyb import UART
except ImportError:
    UART = None


MODEL_PATH = "trained.tflite"
SCORE_THRESHOLD = 0.70
VOTE_FRAMES = 3
GRID_W = 12
GRID_H = 12

UART_ENABLE = False
UART_ID = 3
UART_BAUD = 115200

LABELS = [
    "background",
    "00",
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "big_head_son",
    "calabash_brothers",
    "donald_duck",
    "gg_bond",
    "grey_wolf",
    "mickey_mouse",
    "nezha",
    "pikachu",
    "pleasant_sheep",
    "spongebob_squarepants",
]

NUM_LABELS = {"00", "01", "02", "03", "04", "05", "06", "07", "08", "09"}
CHAR_LABELS = {
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
}


def label_at(class_id):
    if class_id < len(LABELS):
        return LABELS[class_id]
    return "class_%d" % class_id


def load_model(path):
    try:
        return tf.load(path, load_to_fb=False)
    except Exception as exc:
        raise Exception("tf.load failed: " + str(exc))


def score_value(v):
    # Some old firmwares return floats, others return 0..255-like values.
    if v > 1.0:
        return v / 255.0
    return v


def decode_fomo_flat(output, rect):
    detections = []
    channels = len(LABELS)
    expected = GRID_W * GRID_H * channels

    # If this unexpectedly behaves like a classifier, still print a useful top result.
    if len(output) == channels:
        best_id = 0
        best_score = 0.0
        for i in range(1, channels):
            score = score_value(output[i])
            if score > best_score:
                best_score = score
                best_id = i
        if best_score >= SCORE_THRESHOLD:
            x, y, w, h = rect
            detections.append((label_at(best_id), x, y, w, h, best_score))
        return detections

    if len(output) < expected:
        print("UNEXPECTED_OUTPUT_LEN", len(output), "expected", expected)
        return detections

    rx, ry, rw, rh = rect
    cell_w = rw / GRID_W
    cell_h = rh / GRID_H

    for gy in range(GRID_H):
        for gx in range(GRID_W):
            base = ((gy * GRID_W) + gx) * channels
            best_id = 0
            best_score = 0.0
            for class_id in range(1, channels):
                score = score_value(output[base + class_id])
                if score > best_score:
                    best_score = score
                    best_id = class_id
            if best_score >= SCORE_THRESHOLD:
                cx = int(rx + ((gx + 0.5) * cell_w))
                cy = int(ry + ((gy + 0.5) * cell_h))
                box_w = int(cell_w * 1.6)
                box_h = int(cell_h * 1.6)
                detections.append(
                    (
                        label_at(best_id),
                        int(cx - box_w / 2),
                        int(cy - box_h / 2),
                        box_w,
                        box_h,
                        best_score,
                    )
                )
    return detections


def run_fomo(net, img):
    detections = []
    try:
        objs = tf.classify(
            net,
            img,
            min_scale=1.0,
            # Old OpenMV V4.3 tf.classify requires 0 <= scale_mul < 1.
            # 0.5 keeps the call valid; with min_scale=1.0 it still tests the
            # full window first, which is what this FOMO model needs.
            scale_mul=0.5,
            x_overlap=0.0,
            y_overlap=0.0,
        )
    except Exception as exc:
        raise Exception("tf.classify failed: " + str(exc))

    for obj in objs:
        detections += decode_fomo_flat(obj.output(), obj.rect())
    return detections


def best_by_group(detections):
    best_num = ("unknown", 0.0)
    best_char = ("unknown", 0.0)
    for label, x, y, w, h, score in detections:
        if label in NUM_LABELS and score > best_num[1]:
            best_num = (label, score)
        elif label in CHAR_LABELS and score > best_char[1]:
            best_char = (label, score)
    return best_num, best_char


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
        try:
            uart.write(line + "\n")
        except Exception as exc:
            print("UART_WRITE_ERROR", exc)


sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.set_windowing((240, 240))
sensor.skip_frames(time=2000)

net = load_model(MODEL_PATH)
print("TF_CLASSIFY_FOMO_READY")
print("model:", net)
print("labels:", LABELS)
print("grid:", GRID_W, GRID_H, "classes:", len(LABELS), "threshold:", SCORE_THRESHOLD)

uart = None
if UART_ENABLE and UART:
    try:
        uart = UART(UART_ID, UART_BAUD, timeout_char=1000)
        print("UART_READY")
    except Exception as exc:
        print("UART_INIT_ERROR", exc)

num_history = []
char_history = []
last_line = ""
clock = time.clock()

while True:
    clock.tick()
    img = sensor.snapshot()
    detections = run_fomo(net, img)

    for label, x, y, w, h, score in detections:
        cx = math.floor(x + (w / 2))
        cy = math.floor(y + (h / 2))
        img.draw_circle((cx, cy, 10), color=(0, 255, 0))
        img.draw_string(max(0, x), max(0, y - 12), label, color=(255, 255, 255))
        print("%s x=%d y=%d score=%.2f" % (label, cx, cy, score))

    (num_label, num_score), (char_label, char_score) = best_by_group(detections)
    stable_num = stable_vote(num_history, num_label)
    stable_char = stable_vote(char_history, char_label)

    if stable_num != "unknown" or stable_char != "unknown":
        if stable_num != "unknown" and stable_char != "unknown":
            conf = min(num_score, char_score)
        elif stable_num != "unknown":
            conf = num_score
        else:
            conf = char_score
        line = "NUM=%s,CHAR=%s,CONF=%.2f" % (stable_num, stable_char, conf)
        if line != last_line:
            send_line(uart, line)
            last_line = line

    print("fps %.2f" % clock.fps())
