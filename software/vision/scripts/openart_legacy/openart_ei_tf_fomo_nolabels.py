# Edge Impulse FOMO runner for OpenART Plus firmware with old OpenMV tf module.
# This version does not read labels.txt at all. It embeds labels to avoid
# OpenART filesystem read errors such as "Failed to load labels.txt: -1".

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


def read_model(path):
    try:
        # This OpenART firmware can return -1 for uos.stat/read even when
        # tf.load() can load the model successfully.
        return tf.load(path, load_to_fb=False)
    except Exception as exc:
        raise Exception("Failed to load trained.tflite: " + str(exc))


def label_at(class_id):
    if class_id < len(LABELS):
        return LABELS[class_id]
    return "class_%d" % class_id


def fomo_segment_detect(net, img):
    outputs = net.segment(img)
    oc = len(outputs)
    ow = outputs[0].width()
    oh = outputs[0].height()

    x_scale = img.width() / ow
    y_scale = img.height() / oh
    scale = min(x_scale, y_scale)
    x_offset = (img.width() - (ow * scale)) / 2
    y_offset = (img.height() - (oh * scale)) / 2

    threshold_list = [(math.ceil(SCORE_THRESHOLD * 255), 255)]
    detections = []

    for class_id in range(min(oc, len(outputs))):
        if class_id == 0:
            continue
        out_img = outputs[class_id]
        blobs = out_img.find_blobs(
            threshold_list,
            x_stride=1,
            y_stride=1,
            area_threshold=1,
            pixels_threshold=1,
        )
        for blob in blobs:
            x, y, w, h = blob.rect()
            score = out_img.get_statistics(thresholds=threshold_list, roi=blob.rect()).l_mean() / 255.0
            x = int((x * scale) + x_offset)
            y = int((y * scale) + y_offset)
            w = int(w * scale)
            h = int(h * scale)
            detections.append((label_at(class_id), x, y, w, h, score))
    return detections


def best_by_group(detections):
    best_num = ("unknown", 0.0)
    best_char = ("unknown", 0.0)
    for label, x, y, w, h, score in detections:
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

net = read_model(MODEL_PATH)
print("TF_FOMO_NOLABELS_READY")
print("labels:", LABELS)
print("model:", net)

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
    detections = fomo_segment_detect(net, img)

    for label, x, y, w, h, score in detections:
        cx = math.floor(x + (w / 2))
        cy = math.floor(y + (h / 2))
        img.draw_circle((cx, cy, 10), color=(0, 255, 0))
        img.draw_string(max(0, cx - 35), max(0, cy - 18), label, color=(255, 255, 255))
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
