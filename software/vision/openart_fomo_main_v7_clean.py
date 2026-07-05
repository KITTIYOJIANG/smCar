# Clean OpenART/OpenMV V4.3 FOMO runner for Edge Impulse OpenMV Library export.
#
# Board files required at root:
# - trained.tflite
# - labels.txt
#
# This board has old OpenMV V4.3 tf, not the new ml module. Edge Impulse's
# generated ei_object_detection.py imports ml, so do not run it on this firmware.

import gc
import math
import sensor
import tf
import time


MODEL_PATH = "trained.tflite"
LABELS_PATH = "labels.txt"

SCRIPT_VERSION = "SMARTCAR_FOMO_MAIN_V17_TRAINING_COMPAT_RAW_20260630"
MIN_CONFIDENCE = 0.40
NUM_MIN_CONFIDENCE = 0.32
CHAR_MIN_CONFIDENCE = 0.46
VOTE_FRAMES = 3

# Use the same full camera view that Edge Impulse saw during labeling.
# This is dynamic detection, not a fixed ROI classifier.
USE_CENTER_240 = False

# Match the orientation of the Edge Impulse training images. Human-upright is
# not necessarily model-upright; the model must see the same direction it saw
# during data collection.
ORIENT_HMIRROR = False
ORIENT_VFLIP = False

# Perspective correction is intentionally off in V16. V15 warped the image too
# aggressively; first make the live frame direction correct, then tune IPM.
USE_IPM = False
IPM_CORNERS = ((92, 70), (256, 72), (258, 187), (88, 185))
IPM_FAIL_CLOSED = False

# This is not a fixed object ROI. It is the fixed game first-person window on
# the projected screen. FOMO still detects the target dynamically inside it.
USE_INFER_ROI = False
INFER_ROI = (95, 74, 145, 105)

# The number target is a high-contrast black digit on a white card. The current
# FOMO number classes are polluted by placeholder boxes, so use CV as a
# reliable fallback while the 160 model is retraining.
NUM_CV_ENABLE = False
NUM_CV_ROI = (95, 74, 145, 92)
NUM_CV_DARK_LUMA = 100
NUM_CV_STEP = 2
NUM_CV_MIN_DARK_PIXELS = 28
NUM_CV_MIN_BOX_W = 10
NUM_CV_MIN_BOX_H = 22
NUM_CV_MIN_SCORE = 0.56
NUM_CV_CELL_DARK_PERCENT = 16

# These reject impossible heatmap peaks after FOMO has detected dynamically.
# Format: x, y, w, h on the inference image, not always the full frame.
FILTER_VALID_AREAS = True
CHAR_VALID_ROI = (0, 0, 320, 240)
NUM_VALID_ROI = (0, 0, 320, 240)
CHAR_DRAW_SIZE = 52
NUM_DRAW_SIZE = 32

UART_ENABLE = False
UART_ID = 3
UART_BAUD = 115200

NUM_LABELS = ("00", "01", "02", "03", "04", "05", "06", "07", "08", "09")
CHAR_LABELS = (
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
)

DEFAULT_LABELS = (
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
)

COLORS = (
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


try:
    from pyb import UART
except Exception:
    UART = None


def apply_sensor_orientation():
    try:
        sensor.set_hmirror(ORIENT_HMIRROR)
        print("orient_hmirror:", ORIENT_HMIRROR)
    except Exception as exc:
        print("orient_hmirror_FAIL:", exc)
    try:
        sensor.set_vflip(ORIENT_VFLIP)
        print("orient_vflip:", ORIENT_VFLIP)
    except Exception as exc:
        print("orient_vflip_FAIL:", exc)


IPM_WARNED = False


def apply_ipm(img):
    global IPM_WARNED

    if not USE_IPM:
        return img
    try:
        corrected = img.rotation_corr(corners=IPM_CORNERS)
        if corrected is not None:
            return corrected
    except Exception as exc:
        if not IPM_WARNED:
            print("IPM_FAIL:", exc)
            IPM_WARNED = True
        if IPM_FAIL_CLOSED:
            raise
    return img


def load_labels(path):
    labels = []
    try:
        handle = open(path)
        try:
            for line in handle:
                label = line.strip()
                if label:
                    labels.append(label)
        finally:
            handle.close()
    except Exception as exc:
        print("LABEL_LOAD_FAIL:", exc)

    if len(labels) == 0:
        labels = list(DEFAULT_LABELS)
        print("LABEL_FALLBACK_USED")
    return labels


def label_at(labels, index):
    if index >= 0 and index < len(labels):
        return labels[index]
    if index >= 0 and index < len(DEFAULT_LABELS):
        return DEFAULT_LABELS[index]
    return "class_%d" % index


def threshold_for(label):
    if label in NUM_LABELS:
        return NUM_MIN_CONFIDENCE
    if label in CHAR_LABELS:
        return CHAR_MIN_CONFIDENCE
    return MIN_CONFIDENCE


def normalize_heat_value(value):
    if value < 0:
        value += 256
    score = value / 255.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def heatmap_score(heatmap, rect, threshold_value):
    try:
        return normalize_heat_value(heatmap.get_statistics(roi=rect).l_max())
    except Exception:
        try:
            return normalize_heat_value(heatmap.get_statistics(roi=rect).l_max())
        except Exception:
            return 0.0


def point_in_roi(x, y, roi):
    rx, ry, rw, rh = roi
    return x >= rx and x <= (rx + rw) and y >= ry and y <= (ry + rh)


def clip_rect(cx, cy, size, img_w, img_h):
    half = int(size / 2)
    x = max(0, cx - half)
    y = max(0, cy - half)
    w = min(size, img_w - x)
    h = min(size, img_h - y)
    return x, y, w, h


def find_fomo_detections(net, labels, img, offset_x, offset_y):
    heatmaps = tf.segment(net, img)
    img_w = img.width()
    img_h = img.height()
    best_by_label = {}

    for class_id, heatmap in enumerate(heatmaps):
        if class_id == 0:
            continue

        label = label_at(labels, class_id)
        threshold = int(math.ceil(threshold_for(label) * 255))

        try:
            map_w = heatmap.width()
            map_h = heatmap.height()
        except Exception:
            map_w = 12
            map_h = 12

        if map_w <= 0 or map_h <= 0:
            continue

        try:
            blobs = heatmap.find_blobs(
                [(threshold, 255)],
                x_stride=1,
                y_stride=1,
                area_threshold=1,
                pixels_threshold=1,
            )
        except Exception:
            blobs = []

        x_scale = img_w / map_w
        y_scale = img_h / map_h

        for blob in blobs:
            bx, by, bw, bh = blob.rect()
            score = heatmap_score(heatmap, blob.rect(), threshold_for(label))
            if score < threshold_for(label):
                continue

            cx = int((bx + (bw / 2)) * x_scale)
            cy = int((by + (bh / 2)) * y_scale)

            if FILTER_VALID_AREAS:
                if label in CHAR_LABELS and not point_in_roi(cx, cy, CHAR_VALID_ROI):
                    continue
                if label in NUM_LABELS and not point_in_roi(cx, cy, NUM_VALID_ROI):
                    continue

            box_size = CHAR_DRAW_SIZE
            if label in NUM_LABELS:
                box_size = NUM_DRAW_SIZE
            x, y, w, h = clip_rect(cx, cy, box_size, img_w, img_h)

            previous = best_by_label.get(label)
            if previous is None or score > previous[5]:
                best_by_label[label] = (label, x + offset_x, y + offset_y, w, h, score)

    detections = []
    for label in best_by_label:
        detections.append(best_by_label[label])
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


DIGIT_TEMPLATES = (
    ("00", ("11111", "10001", "10001", "10001", "10001", "10001", "11111")),
    ("01", ("00100", "01100", "00100", "00100", "00100", "00100", "01110")),
    ("02", ("11110", "00001", "00001", "11110", "10000", "10000", "11111")),
    ("03", ("11110", "00001", "00001", "01110", "00001", "00001", "11110")),
    ("04", ("10010", "10010", "10010", "11111", "00010", "00010", "00010")),
    ("05", ("11111", "10000", "10000", "11110", "00001", "00001", "11110")),
    ("06", ("01111", "10000", "10000", "11110", "10001", "10001", "01110")),
    ("07", ("11111", "00001", "00010", "00100", "01000", "01000", "01000")),
    ("08", ("01110", "10001", "10001", "01110", "10001", "10001", "01110")),
    ("09", ("01110", "10001", "10001", "01111", "00001", "00001", "11110")),
)


def pixel_luma(pixel):
    try:
        return int((pixel[0] * 30 + pixel[1] * 59 + pixel[2] * 11) // 100)
    except Exception:
        return int(pixel)


def find_digit_dark_box(img):
    rx, ry, rw, rh = NUM_CV_ROI
    x0 = rx + 8
    y0 = ry + 4
    x1 = rx + rw - 8
    y1 = ry + rh - 4

    min_x = 9999
    min_y = 9999
    max_x = -1
    max_y = -1
    dark_pixels = 0

    for y in range(y0, y1, NUM_CV_STEP):
        for x in range(x0, x1, NUM_CV_STEP):
            if pixel_luma(img.get_pixel(x, y)) <= NUM_CV_DARK_LUMA:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                dark_pixels += 1

    if dark_pixels < NUM_CV_MIN_DARK_PIXELS:
        return None

    w = max_x - min_x + 1
    h = max_y - min_y + 1
    if w < NUM_CV_MIN_BOX_W or h < NUM_CV_MIN_BOX_H:
        return None
    return min_x, min_y, w, h, dark_pixels


def digit_bits_from_box(img, rect):
    x0, y0, w, h, dark_pixels = rect
    dark = [0] * 35
    total = [0] * 35

    if w <= 0 or h <= 0:
        return None

    for y in range(y0, y0 + h, NUM_CV_STEP):
        row = int(((y - y0) * 7) // h)
        if row < 0:
            row = 0
        if row > 6:
            row = 6
        for x in range(x0, x0 + w, NUM_CV_STEP):
            col = int(((x - x0) * 5) // w)
            if col < 0:
                col = 0
            if col > 4:
                col = 4
            idx = row * 5 + col
            total[idx] += 1
            if pixel_luma(img.get_pixel(x, y)) <= NUM_CV_DARK_LUMA:
                dark[idx] += 1

    bits = [0] * 35
    for idx in range(35):
        if total[idx] > 0 and (dark[idx] * 100) >= (total[idx] * NUM_CV_CELL_DARK_PERCENT):
            bits[idx] = 1
    return bits


def score_digit_template(bits, template):
    score = 0
    possible = 0
    for row in range(7):
        line = template[row]
        for col in range(5):
            idx = row * 5 + col
            expected = 0
            if line[col] == "1":
                expected = 1
            if expected:
                possible += 2
                if bits[idx]:
                    score += 2
            else:
                possible += 1
                if not bits[idx]:
                    score += 1
    if possible <= 0:
        return 0.0
    return score / possible


def detect_num_cv(img):
    if not NUM_CV_ENABLE:
        return "unknown", 0.0, None

    rect = find_digit_dark_box(img)
    if rect is None:
        return "unknown", 0.0, None

    bits = digit_bits_from_box(img, rect)
    if bits is None:
        return "unknown", 0.0, rect

    best_label = "unknown"
    best_score = 0.0
    second_score = 0.0
    for label, template in DIGIT_TEMPLATES:
        score = score_digit_template(bits, template)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_label = label
        elif score > second_score:
            second_score = score

    if best_score < NUM_CV_MIN_SCORE:
        return "unknown", best_score, rect
    return best_label, best_score, rect


def draw_num_cv(img, label, score, rect):
    if not NUM_CV_ENABLE:
        return
    img.draw_rectangle(NUM_CV_ROI, color=(0, 255, 255), thickness=1)
    if rect is not None:
        x, y, w, h, count = rect
        color = (0, 255, 0)
        if label == "unknown":
            color = (255, 255, 0)
        img.draw_rectangle((x, y, w, h), color=color, thickness=2)
        img.draw_string(max(0, x), max(0, y - 12), "numcv %s %.2f" % (label, score), color=color)


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


def init_uart():
    if not UART_ENABLE or UART is None:
        return None
    try:
        return UART(UART_ID, UART_BAUD, timeout_char=1000)
    except Exception as exc:
        print("UART_INIT_FAIL:", exc)
        return None


def send_line(uart, line):
    print(line)
    if uart:
        try:
            uart.write(line + "\n")
        except Exception as exc:
            print("UART_WRITE_FAIL:", exc)


def draw_detections(img, detections):
    if USE_INFER_ROI and not USE_IPM:
        img.draw_rectangle(INFER_ROI, color=(255, 255, 0), thickness=1)
    for label, x, y, w, h, score in detections:
        cx = int(x + (w / 2))
        cy = int(y + (h / 2))
        color = COLORS[(len(label) + x + y) % len(COLORS)]
        img.draw_rectangle((x, y, w, h), color=color, thickness=2)
        img.draw_cross(cx, cy, color=color, size=8)
        img.draw_string(max(0, x), max(0, y - 12), label, color=color)


sensor.reset()
apply_sensor_orientation()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
if USE_CENTER_240:
    sensor.set_windowing((240, 240))
sensor.skip_frames(time=2000)

print(SCRIPT_VERSION)
print("use_center_240:", USE_CENTER_240)
print("orientation hmirror=%s,vflip=%s" % (ORIENT_HMIRROR, ORIENT_VFLIP))
print("use_ipm:", USE_IPM)
print("ipm_corners:", IPM_CORNERS)
print("use_infer_roi:", USE_INFER_ROI)
print("infer_roi:", INFER_ROI)
print("num_cv_enable:", NUM_CV_ENABLE)
print("num_cv_roi:", NUM_CV_ROI)
print("thresholds: global=%.2f,num=%.2f,char=%.2f" % (MIN_CONFIDENCE, NUM_MIN_CONFIDENCE, CHAR_MIN_CONFIDENCE))
print("filter_valid_areas:", FILTER_VALID_AREAS)
print("char_valid_roi:", CHAR_VALID_ROI)

net = tf.load(MODEL_PATH, load_to_fb=False)
labels = load_labels(LABELS_PATH)
print("MODEL_LOAD_OK:", net)
print("labels:", labels)

uart = init_uart()
clock = time.clock()
num_history = []
char_history = []
last_line = ""

while True:
    clock.tick()
    raw_img = sensor.snapshot()
    img = apply_ipm(raw_img)
    infer_img = img
    offset_x = 0
    offset_y = 0
    if USE_INFER_ROI:
        infer_img = img.copy(roi=INFER_ROI)
        offset_x = INFER_ROI[0]
        offset_y = INFER_ROI[1]

    detections = find_fomo_detections(net, labels, infer_img, offset_x, offset_y)
    draw_detections(img, detections)

    (num_label, num_score), (char_label, char_score) = best_by_group(detections)
    cv_num_label, cv_num_score, cv_num_rect = detect_num_cv(img)
    draw_num_cv(img, cv_num_label, cv_num_score, cv_num_rect)
    if cv_num_label != "unknown":
        num_label = cv_num_label
        num_score = cv_num_score

    stable_num = stable_vote(num_history, num_label)
    stable_char = stable_vote(char_history, char_label)

    if stable_num == "unknown" and stable_char == "unknown":
        print("NUM=unknown,CHAR=unknown,fps=%.1f" % clock.fps())
    else:
        conf = 0.0
        if stable_num != "unknown" and stable_char != "unknown":
            conf = min(num_score, char_score)
        elif stable_num != "unknown":
            conf = num_score
        else:
            conf = char_score

        line = "NUM=%s,CHAR=%s,CONF=%.2f,fps=%.1f" % (stable_num, stable_char, conf, clock.fps())
        if line != last_line:
            send_line(uart, line)
            last_line = line

    gc.collect()
