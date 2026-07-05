# OpenART Plus mini-MIMXRT1170 / OpenMV V4.3
# Edge Impulse FOMO runtime adapted from ei_object_detection.py.
#
# This firmware has old tf, no ml. Do not run the generated ml script.
# Board root files:
# - main.py
# - trained.tflite
# - labels.txt

import gc
import math
import sensor
import tf
import time


SCRIPT_VERSION = "SMARTCAR_5CLASS_FOMO_EI_COMPAT_TF_V2_20260701"

MODEL_PATH = "trained.tflite"
LABELS_PATH = "labels.txt"

DEFAULT_LABELS = (
    "background",
    "big_head_son",
    "calabash_brothers",
    "donald_duck",
    "gg_bond",
    "pikachu",
)

# Match Edge Impulse generated ei_object_detection.py first.
MIN_CONFIDENCE = 0.50
SENSOR_WINDOW = (240, 240)
USE_SENSOR_WINDOWING = True
LOAD_TO_FB = False

VOTE_WINDOW = 5
VOTE_REQUIRED = 3

ORIENT_HMIRROR = False
ORIENT_VFLIP = False

COLORS = (
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


def normalize_score(value):
    if value < 0:
        value += 256
    score = value / 255.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def load_labels():
    labels = []
    try:
        handle = open(LABELS_PATH)
        try:
            for line in handle:
                label = line.strip()
                if label:
                    labels.append(label)
        finally:
            handle.close()
    except Exception as exc:
        print("LABEL_LOAD_FAIL_USE_DEFAULT:", exc)

    if len(labels) < 2:
        labels = list(DEFAULT_LABELS)
        print("LABEL_FALLBACK_USED")
    return labels


def label_at(labels, index):
    if index >= 0 and index < len(labels):
        return labels[index]
    if index >= 0 and index < len(DEFAULT_LABELS):
        return DEFAULT_LABELS[index]
    return "class_%d" % index


def mean_score(heatmap, rect):
    try:
        return normalize_score(heatmap.get_statistics(roi=rect).l_mean())
    except Exception:
        try:
            return normalize_score(heatmap.get_statistics(roi=rect).mean())
        except Exception:
            return 0.0


def max_score(heatmap):
    try:
        return normalize_score(heatmap.get_statistics().l_max())
    except Exception:
        try:
            return normalize_score(heatmap.get_statistics().max())
        except Exception:
            return 0.0


def push_top3(top3, label, score):
    item = (label, score)
    inserted = False
    out = []
    for old in top3:
        if (not inserted) and score > old[1]:
            out.append(item)
            inserted = True
        out.append(old)
    if not inserted:
        out.append(item)
    while len(out) > 3:
        out.pop()
    return out


def top3_text(top3):
    text = ""
    for label, score in top3:
        if text:
            text += ","
        text += "%s:%.2f" % (label, score)
    return text


def fomo_detect_tf(net, labels, img):
    heatmaps = tf.segment(net, img)
    img_w = img.width()
    img_h = img.height()
    detections = []
    top3 = []

    threshold = int(math.ceil(MIN_CONFIDENCE * 255))

    for class_id, heatmap in enumerate(heatmaps):
        label = label_at(labels, class_id)
        if class_id == 0 or label == "background":
            continue

        top3 = push_top3(top3, label, max_score(heatmap))

        try:
            map_w = heatmap.width()
            map_h = heatmap.height()
        except Exception:
            map_w = 10
            map_h = 10

        if map_w <= 0 or map_h <= 0:
            continue

        # This mirrors Edge Impulse fomo_post_process as closely as old tf allows.
        x_scale = img_w / map_w
        y_scale = img_h / map_h
        scale = min(x_scale, y_scale)
        x_offset = (img_w - (map_w * scale)) / 2
        y_offset = (img_h - (map_h * scale)) / 2

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

        for blob in blobs:
            rect = blob.rect()
            score = mean_score(heatmap, rect)
            if score < MIN_CONFIDENCE:
                continue

            x, y, w, h = rect
            out_x = int((x * scale) + x_offset)
            out_y = int((y * scale) + y_offset)
            out_w = max(10, int(w * scale))
            out_h = max(10, int(h * scale))
            detections.append((label, out_x, out_y, out_w, out_h, score))

    return detections, top3


def best_detection(detections):
    best = ("unknown", 0, 0, 0, 0, 0.0)
    for det in detections:
        if det[5] > best[5]:
            best = det
    return best


def vote(history, label, score):
    history.append((label, score))
    if len(history) > VOTE_WINDOW:
        history.pop(0)

    best_label = "unknown"
    best_count = 0
    best_total = 0.0
    for item_label, item_score in history:
        if item_label == "unknown":
            continue
        count = 0
        total = 0.0
        for other_label, other_score in history:
            if other_label == item_label:
                count += 1
                total += other_score
        if count > best_count or (count == best_count and total > best_total):
            best_label = item_label
            best_count = count
            best_total = total

    if best_count >= VOTE_REQUIRED:
        return best_label, best_total / best_count, 1
    return "unknown", 0.0, 0


def draw_detections(img, detections):
    for label, x, y, w, h, score in detections:
        color = COLORS[(len(label) + x + y) % len(COLORS)]
        cx = int(x + (w / 2))
        cy = int(y + (h / 2))
        img.draw_circle((cx, cy, 12), color=color)
        img.draw_rectangle((x, y, w, h), color=color, thickness=2)
        img.draw_string(max(0, x), max(0, y - 12), label, color=color)


def setup_camera():
    sensor.reset()
    try:
        sensor.set_hmirror(ORIENT_HMIRROR)
        print("hmirror:", ORIENT_HMIRROR)
    except Exception as exc:
        print("HMIRROR_FAIL:", exc)

    try:
        sensor.set_vflip(ORIENT_VFLIP)
        print("vflip:", ORIENT_VFLIP)
    except Exception as exc:
        print("VFLIP_FAIL:", exc)

    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)

    if USE_SENSOR_WINDOWING:
        try:
            sensor.set_windowing(SENSOR_WINDOW)
            print("sensor_windowing:", SENSOR_WINDOW)
        except Exception as exc:
            print("SENSOR_WINDOWING_FAIL:", exc)

    sensor.skip_frames(time=2000)


def main():
    print(SCRIPT_VERSION)
    print("runtime: old_tf_segment")
    print("ei_compat_window:", SENSOR_WINDOW)
    print("min_confidence:", MIN_CONFIDENCE)
    print("vote:", VOTE_REQUIRED, "/", VOTE_WINDOW)

    setup_camera()

    labels = load_labels()
    print("labels:", labels)

    try:
        net = tf.load(MODEL_PATH, load_to_fb=LOAD_TO_FB)
        print("MODEL_LOAD_OK:", net)
    except Exception as exc:
        print("MODEL_LOAD_FAIL:", exc)
        return

    clock = time.clock()
    history = []

    while True:
        clock.tick()
        img = sensor.snapshot()

        try:
            detections, top3 = fomo_detect_tf(net, labels, img)
        except Exception as exc:
            print("INFERENCE_FAIL:", exc)
            detections = []
            top3 = []

        draw_detections(img, detections)
        label, x, y, w, h, score = best_detection(detections)
        stable_label, stable_score, stable = vote(history, label, score)

        if stable:
            print("CHAR=%s,CONF=%.2f,STABLE=1,fps=%.1f" % (stable_label, stable_score, clock.fps()))
        elif label != "unknown":
            print(
                "CHAR=unknown,BEST=%s,CONF=%.2f,TOP3=%s,STABLE=0,fps=%.1f"
                % (label, score, top3_text(top3), clock.fps())
            )
        else:
            print(
                "CHAR=unknown,TOP3=%s,STABLE=0,fps=%.1f"
                % (top3_text(top3), clock.fps())
            )

        gc.collect()


try:
    main()
except Exception as exc:
    print("TOP_LEVEL_FAIL:", exc)
    while True:
        try:
            time.sleep(1)
        except Exception:
            pass
