# Edge Impulse OpenMV Library runner for OpenART Plus / OpenMV RT1062.
# Copy this file, trained.tflite, and labels.txt to the board drive.

import image
import math
import sensor
import time
import ml
from ml.utils import NMS

try:
    from pyb import UART
except ImportError:
    UART = None


MODEL_PATH = "trained.tflite"
LABELS_PATH = "labels.txt"
SCORE_THRESHOLD = 0.70
VOTE_FRAMES = 3
UART_ENABLE = False
UART_ID = 3
UART_BAUD = 115200

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


def load_labels(path):
    labels = []
    try:
        with open(path) as f:
            labels = [line.strip() for line in f if line.strip()]
    except OSError:
        labels = []
    return labels


def labels_for_model(model, labels):
    # FOMO has a background output at class index 0. Some exports include it in
    # labels.txt, some do not, so align conservatively with output channels.
    oc = model.output_shape[0][3]
    if len(labels) == oc:
        return labels
    if len(labels) == oc - 1:
        return ["background"] + labels
    if len(labels) < oc:
        return ["background"] + labels + ["class_%d" % i for i in range(len(labels) + 1, oc)]
    return labels[:oc]


def fomo_post_process(model, inputs, outputs):
    n, oh, ow, oc = model.output_shape[0]
    nms = NMS(ow, oh, inputs[0].roi)
    threshold_list = [(math.ceil(SCORE_THRESHOLD * 255), 255)]
    for i in range(oc):
        img = image.Image(outputs[0][0, :, :, i] * 255)
        blobs = img.find_blobs(
            threshold_list,
            x_stride=1,
            area_threshold=1,
            pixels_threshold=1,
        )
        for b in blobs:
            x, y, w, h = b.rect()
            score = img.get_statistics(thresholds=threshold_list, roi=b.rect()).l_mean() / 255.0
            nms.add_bounding_box(x, y, x + w, y + h, score, i)
    return nms.get_bounding_boxes()


def best_by_group(detections, labels):
    best_num = ("unknown", 0.0)
    best_char = ("unknown", 0.0)
    for class_id, detection_list in enumerate(detections):
        if class_id == 0 or class_id >= len(labels):
            continue
        label = labels[class_id]
        for rect, score in detection_list:
            if score < SCORE_THRESHOLD:
                continue
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


def uart_write(uart, text):
    print(text)
    if uart:
        try:
            uart.write(text + "\n")
        except Exception as exc:
            print("UART_WRITE_ERROR", exc)


sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

model = ml.Model(MODEL_PATH, load_to_fb=True)
labels = labels_for_model(model, load_labels(LABELS_PATH))
print(model)
print(labels)

uart = None
if UART_ENABLE and UART:
    try:
        uart = UART(UART_ID, UART_BAUD, timeout_char=1000)
    except Exception as exc:
        print("UART_INIT_ERROR", exc)

num_history = []
char_history = []
last_line = ""
clock = time.clock()

while True:
    clock.tick()
    img = sensor.snapshot()
    detections = model.predict([img], callback=fomo_post_process)

    for class_id, detection_list in enumerate(detections):
        if class_id == 0 or class_id >= len(labels):
            continue
        label = labels[class_id]
        for (x, y, w, h), score in detection_list:
            if score < SCORE_THRESHOLD:
                continue
            cx = math.floor(x + w / 2)
            cy = math.floor(y + h / 2)
            img.draw_circle((cx, cy, 10), color=(0, 255, 0))
            img.draw_string(max(0, cx - 20), max(0, cy - 18), label, color=(255, 255, 255))

    (num_label, num_score), (char_label, char_score) = best_by_group(detections, labels)
    stable_num = stable_vote(num_history, num_label)
    stable_char = stable_vote(char_history, char_label)
    conf = min(num_score if stable_num != "unknown" else 0.0, char_score if stable_char != "unknown" else 0.0)

    if stable_num != "unknown" or stable_char != "unknown":
        line = "NUM=%s,CHAR=%s,CONF=%.2f" % (stable_num, stable_char, conf)
        if line != last_line:
            uart_write(uart, line)
            last_line = line

    print("fps", clock.fps())
