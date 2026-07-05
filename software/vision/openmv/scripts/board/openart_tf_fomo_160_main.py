# OpenART Plus mini-MIMXRT1170 / OpenMV V4.3 FOMO runner.
#
# Required files on board root:
# - trained.tflite
# - labels.txt
#
# This script is for old OpenMV V4.3 firmware. It uses the legacy tf runtime
# and avoids the newer Edge Impulse generated ML runtime.

import gc
import image
import math
import sensor
import sys
import tf
import time


MODEL_PATH = "trained.tflite"
LABELS_PATH = "labels.txt"
SCRIPT_VERSION = "OPENART_TF_FOMO_160_BOX_CROP_V2_20260701"

CONFIDENCE = 0.40
VOTE_WINDOW = 5
VOTE_REQUIRED = 3
LOAD_TO_FB = False

FRAME_SIZE = sensor.QVGA
PIX_FORMAT = sensor.RGB565

# Keep the already verified live-image direction.
ORIENT_HMIRROR = False
ORIENT_VFLIP = False

# Crop the live OpenMV frame to the first-person box/target area before FOMO.
# Coordinates are on the QVGA 320x240 camera image. Tune this rectangle in
# OpenMV IDE until the frame buffer shows only the box and a little margin.
USE_INFER_ROI = True
SHOW_CROP_ONLY = True
INFER_ROI = (72, 30, 150, 135)

DRAW_BOX_SIZE = 44
BACKGROUND_LABEL = "background"

COLORS = (
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


def print_exception(prefix, exc):
    print(prefix, exc)
    try:
        sys.print_exception(exc)
    except Exception:
        pass


def normalize_score(value):
    if value < 0:
        value += 256
    score = value / 255.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def load_labels(path):
    labels = []
    handle = open(path)
    try:
        for line in handle:
            label = line.strip()
            if label:
                labels.append(label)
    finally:
        handle.close()
    return labels


def label_at(labels, index):
    if index >= 0 and index < len(labels):
        return labels[index]
    return "class_%d" % index


def clip_rect(cx, cy, size, img_w, img_h):
    half = int(size / 2)
    x = max(0, cx - half)
    y = max(0, cy - half)
    w = min(size, img_w - x)
    h = min(size, img_h - y)
    return x, y, w, h


def heatmap_score(heatmap, rect):
    try:
        return normalize_score(heatmap.get_statistics(roi=rect).l_max())
    except Exception:
        return 0.0


def find_detections(net, labels, img, offset_x, offset_y):
    heatmaps = tf.segment(net, img)
    img_w = img.width()
    img_h = img.height()
    detections = []

    for class_id, heatmap in enumerate(heatmaps):
        label = label_at(labels, class_id)
        if class_id == 0 or label == BACKGROUND_LABEL:
            continue

        threshold = int(math.ceil(CONFIDENCE * 255))
        try:
            map_w = heatmap.width()
            map_h = heatmap.height()
        except Exception:
            map_w = 20
            map_h = 20

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

        best = None
        for blob in blobs:
            bx, by, bw, bh = blob.rect()
            score = heatmap_score(heatmap, blob.rect())
            if score < CONFIDENCE:
                continue

            cx = int((bx + (bw / 2)) * x_scale)
            cy = int((by + (bh / 2)) * y_scale)
            x, y, w, h = clip_rect(cx, cy, DRAW_BOX_SIZE, img_w, img_h)
            det = (label, x + offset_x, y + offset_y, w, h, score)
            if best is None or score > best[5]:
                best = det

        if best is not None:
            detections.append(best)

    return detections


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
    best_score = 0.0

    for item_label, item_score in history:
        if item_label == "unknown":
            continue
        count = 0
        total = 0.0
        for other_label, other_score in history:
            if other_label == item_label and other_score >= CONFIDENCE:
                count += 1
                total += other_score
        avg = total / count if count else 0.0
        if count > best_count or (count == best_count and avg > best_score):
            best_label = item_label
            best_count = count
            best_score = avg

    if best_count >= VOTE_REQUIRED:
        return best_label, best_score, 1
    return "unknown", 0.0, 0


def draw_detections(img, detections):
    for label, x, y, w, h, score in detections:
        color = COLORS[(len(label) + x + y) % len(COLORS)]
        img.draw_rectangle((x, y, w, h), color=color, thickness=2)
        img.draw_cross(int(x + w / 2), int(y + h / 2), color=color, size=7)
        img.draw_string(max(0, x), max(0, y - 12), label, color=color)


def setup_camera():
    sensor.reset()
    try:
        sensor.set_hmirror(ORIENT_HMIRROR)
        print("hmirror:", ORIENT_HMIRROR)
    except Exception as exc:
        print_exception("HMIRROR_SET_FAIL:", exc)
    try:
        sensor.set_vflip(ORIENT_VFLIP)
        print("vflip:", ORIENT_VFLIP)
    except Exception as exc:
        print_exception("VFLIP_SET_FAIL:", exc)
    sensor.set_pixformat(PIX_FORMAT)
    sensor.set_framesize(FRAME_SIZE)
    sensor.skip_frames(time=2000)


def main():
    print(SCRIPT_VERSION)
    print("runtime: import_tf_only")
    print("confidence:", CONFIDENCE)
    print("vote_window:", VOTE_WINDOW)
    print("vote_required:", VOTE_REQUIRED)
    print("load_to_fb:", LOAD_TO_FB)
    print("use_infer_roi:", USE_INFER_ROI)
    print("show_crop_only:", SHOW_CROP_ONLY)
    print("infer_roi:", INFER_ROI)

    setup_camera()

    try:
        labels = load_labels(LABELS_PATH)
        print("labels:", labels)
    except Exception as exc:
        print_exception("LABEL_LOAD_FAIL:", exc)
        return

    try:
        net = tf.load(MODEL_PATH, load_to_fb=LOAD_TO_FB)
        print("MODEL_LOAD_OK:", net)
    except Exception as exc:
        print_exception("MODEL_LOAD_FAIL:", exc)
        return

    clock = time.clock()
    history = []

    while True:
        clock.tick()
        full_img = sensor.snapshot()
        img = full_img
        infer_img = full_img
        offset_x = 0
        offset_y = 0

        if USE_INFER_ROI:
            crop_img = full_img.copy(roi=INFER_ROI)
            infer_img = crop_img
            if SHOW_CROP_ONLY:
                img = crop_img
                offset_x = 0
                offset_y = 0
            else:
                img = full_img
                offset_x = INFER_ROI[0]
                offset_y = INFER_ROI[1]
                img.draw_rectangle(INFER_ROI, color=(255, 255, 0), thickness=1)

        try:
            detections = find_detections(net, labels, infer_img, offset_x, offset_y)
        except Exception as exc:
            print_exception("INFERENCE_FAIL:", exc)
            detections = []

        draw_detections(img, detections)
        label, x, y, w, h, score = best_detection(detections)
        stable_label, stable_score, stable = vote(history, label, score)

        if stable:
            print("CHAR=%s,CONF=%.2f,STABLE=1,fps=%.1f" % (stable_label, stable_score, clock.fps()))
        else:
            if label != "unknown":
                print("CHAR=unknown,BEST=%s,CONF=%.2f,STABLE=0,fps=%.1f" % (label, score, clock.fps()))
            else:
                print("CHAR=unknown,STABLE=0,fps=%.1f" % clock.fps())

        gc.collect()


try:
    main()
except Exception as exc:
    print_exception("TOP_LEVEL_FAIL:", exc)
    while True:
        try:
            time.sleep(1)
        except Exception:
            pass
