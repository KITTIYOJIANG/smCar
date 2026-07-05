# SmartCar OpenART Edge Impulse FOMO safe runner.
#
# This script intentionally does NOT use a fixed ROI. It runs on the whole
# sensor window and first detects which OpenMV ML API is actually available.
#
# Runtime paths:
#   1. New OpenMV firmware: import ml, ml.Model(...), net.predict(...).
#   2. OpenART/OpenMV V4.3 module API: tf.segment("trained.tflite", img)
#      then manual FOMO heatmap post-processing.
#   3. Older OpenMV module API: tf.detect("trained.tflite", img, ...).
#   4. Older EI/OpenMV model API: tf.load(...), net.detect(...).
#   4. Unsupported firmware: print a clear message and keep camera live.
#
# All fatal errors are caught and printed. OpenMV IDE should not show exception
# popups when this file is used.

import gc
import image
import math
import sensor
import time

try:
    import uos
except Exception:
    uos = None

try:
    import ml
except Exception:
    ml = None

try:
    import tf
except Exception:
    tf = None

try:
    from pyb import UART
except Exception:
    UART = None


MODEL_PATH = "trained.tflite"
# Low global threshold is only for finding candidate blobs in the 12x12 heatmaps.
# Per-class thresholds below decide which detections are trusted.
MIN_CONFIDENCE = 0.25
NUM_MIN_CONFIDENCE = 0.35
CHAR_MIN_CONFIDENCE = 0.82
VOTE_FRAMES = 3

TUNE_MODE = False

# Classes that are currently weak on the real OpenART camera feed. Keep them
# visible in debug logs and require one extra stable frame before final output.
WEAK_CHAR_LABELS = (
    "pikachu",
    "nezha",
    "donald_duck",
    "mickey_mouse",
    "gg_bond",
    "grey_wolf",
)

CLASS_THRESHOLDS = {
    "calabash_brothers": 0.78,
    "pleasant_sheep": 0.78,
    "pikachu": 0.86,
    "nezha": 0.86,
    "donald_duck": 0.86,
    "mickey_mouse": 0.86,
    "gg_bond": 0.86,
    "grey_wolf": 0.86,
}

# Temporary tuning helpers. FOMO is still full-frame; this only rejects detections
# close to the camera frame border where the monitor bezel/wall often causes
# false positives.
USE_VALID_CENTER_FILTER = True
VALID_CENTER_X_MIN = 0.04
VALID_CENTER_X_MAX = 0.88
VALID_CENTER_Y_MIN = 0.04
VALID_CENTER_Y_MAX = 0.94

DEBUG_TOP_HEATMAPS = True
DEBUG_TOP_EVERY_N_FRAMES = 10
DEBUG_NUM_HEATMAPS = True
DEBUG_NUM_EVERY_N_FRAMES = 5
DEBUG_FILTERED = False
INFER_FRAME_COUNT = 0

# Number debug mode: full QVGA proves whether the red number area is inside
# the model input. If character recognition gets worse, set this False again.
USE_FULL_QVGA = True

# Optional target-area inverse perspective mapping. When enabled, these four
# source corners are stretched to the whole model input so the network only sees
# the character/number area instead of the full camera scene.
USE_IPM = False
IPM_CORNERS = ((108, 63), (204, 64), (204, 155), (104, 155))
IPM_FAIL_CLOSED = False

try:
    import ipm_runtime_config as ipm_config

    USE_IPM = bool(getattr(ipm_config, "USE_IPM", USE_IPM))
    IPM_CORNERS = getattr(ipm_config, "IPM_CORNERS", IPM_CORNERS)
    IPM_FAIL_CLOSED = bool(getattr(ipm_config, "IPM_FAIL_CLOSED", IPM_FAIL_CLOSED))
except Exception:
    pass

if TUNE_MODE:
    MIN_CONFIDENCE = 0.08
    NUM_MIN_CONFIDENCE = 0.12
    CHAR_MIN_CONFIDENCE = 0.12
    VOTE_FRAMES = 1
    USE_VALID_CENTER_FILTER = False
    DEBUG_TOP_EVERY_N_FRAMES = 1
    DEBUG_NUM_EVERY_N_FRAMES = 1
    DEBUG_FILTERED = True
    for _label in CLASS_THRESHOLDS:
        CLASS_THRESHOLDS[_label] = 0.12

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

COLORS = (
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)

THRESHOLD_LIST = [(int(math.ceil(MIN_CONFIDENCE * 255)), 255)]
IPM_RUNTIME_ENABLED = USE_IPM
IPM_WARNED = False


def safe_dir(obj):
    try:
        return dir(obj)
    except Exception:
        return []


def has_method(obj, name):
    try:
        getattr(obj, name)
        return True
    except Exception:
        pass
    try:
        return name in dir(obj)
    except Exception:
        return False


def apply_inverse_perspective(img):
    global IPM_RUNTIME_ENABLED
    global IPM_WARNED

    if not IPM_RUNTIME_ENABLED:
        return img

    try:
        corrected = img.rotation_corr(corners=IPM_CORNERS)
        if corrected is not None:
            return corrected
        return img
    except Exception as exc:
        if not IPM_WARNED:
            print("IPM_DISABLED:", exc)
            IPM_WARNED = True
        IPM_RUNTIME_ENABLED = False
        if IPM_FAIL_CLOSED:
            raise
        return img


def label_at(class_id):
    if class_id >= 0 and class_id < len(LABELS):
        return LABELS[class_id]
    return "class_%d" % class_id


def label_threshold(label):
    if label in CLASS_THRESHOLDS:
        return CLASS_THRESHOLDS[label]
    if label in NUM_LABELS:
        return NUM_MIN_CONFIDENCE
    if label in CHAR_LABELS:
        return CHAR_MIN_CONFIDENCE
    return MIN_CONFIDENCE


def should_keep_detection(label, x, y, w, h, score, img_w, img_h):
    need = label_threshold(label)
    if score < need:
        if DEBUG_FILTERED:
            print("FILTER_LOW_CONF %s score=%.2f need=%.2f" % (label, score, need))
        return False

    if USE_VALID_CENTER_FILTER:
        cx = x + (w / 2)
        cy = y + (h / 2)
        if (
            cx < (img_w * VALID_CENTER_X_MIN)
            or cx > (img_w * VALID_CENTER_X_MAX)
            or cy < (img_h * VALID_CENTER_Y_MIN)
            or cy > (img_h * VALID_CENTER_Y_MAX)
        ):
            if DEBUG_FILTERED:
                print("FILTER_OUTSIDE %s x=%d y=%d score=%.2f" % (label, int(cx), int(cy), score))
            return False

    return True


def heatmap_peak(heatmap):
    try:
        return heatmap.get_statistics().l_max() / 255.0
    except Exception:
        pass
    try:
        return heatmap.get_statistics().max() / 255.0
    except Exception:
        return 0.0


def debug_top_heatmaps(heatmaps):
    top = []
    for class_id, heatmap in enumerate(heatmaps):
        if class_id == 0:
            continue
        top.append((heatmap_peak(heatmap), label_at(class_id)))

    # Small list, so insertion sort is simple and MicroPython-friendly.
    for i in range(1, len(top)):
        item = top[i]
        j = i - 1
        while j >= 0 and top[j][0] < item[0]:
            top[j + 1] = top[j]
            j -= 1
        top[j + 1] = item

    msg = "TOP_HEATMAPS"
    limit = 5
    if len(top) < limit:
        limit = len(top)
    for i in range(limit):
        msg += " %s=%.2f" % (top[i][1], top[i][0])
    print(msg)


def debug_num_heatmaps(heatmaps):
    msg = "NUM_HEATMAPS"
    for class_id in range(1, 11):
        if class_id < len(heatmaps):
            msg += " %s=%.2f" % (label_at(class_id), heatmap_peak(heatmaps[class_id]))
    print(msg)


def init_camera():
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    if USE_FULL_QVGA:
        print("CAMERA_WINDOW: full QVGA 320x240")
    else:
        sensor.set_windowing((240, 240))
        print("CAMERA_WINDOW: centered 240x240")
    sensor.skip_frames(time=2000)
    print("CAMERA_READY")


def load_model():
    if ml is not None:
        try:
            print("TRY_RUNTIME: ml.Model")
            net = ml.Model(MODEL_PATH, load_to_fb=False)
            print("ML_MODEL_LOAD_OK:", net)
            return ("ml_predict", net)
        except Exception as exc:
            print("ML_MODEL_LOAD_FAIL:", exc)

    if tf is not None:
        try:
            print("TRY_RUNTIME: tf.load")
            net = tf.load(MODEL_PATH, load_to_fb=False)
            print("TF_MODEL_LOAD_OK:", net)
            print("TF_DIR:", safe_dir(tf))
            print("NET_DIR:", safe_dir(net))
            if has_method(net, "detect"):
                print("SELECT_RUNTIME: tf_net_detect")
                return ("tf_net_detect", net)
            if has_method(net, "predict"):
                print("SELECT_RUNTIME: tf_net_predict")
                return ("tf_net_predict", net)
            if has_method(tf, "segment"):
                print("SELECT_RUNTIME: tf_module_segment")
                return ("tf_module_segment", net)
            if has_method(tf, "detect"):
                print("SELECT_RUNTIME: tf_module_detect_path")
                return ("tf_module_detect_path", MODEL_PATH)
            print("NO_SUPPORTED_FOMO_METHOD_ON_TF_MODEL")
            return ("unsupported", net)
        except Exception as exc:
            print("TF_MODEL_LOAD_FAIL:", exc)

        if has_method(tf, "segment"):
            print("SELECT_RUNTIME: tf_module_segment_without_preload")
            return ("tf_module_segment", MODEL_PATH)
        if has_method(tf, "detect"):
            print("SELECT_RUNTIME: tf_module_detect_path_without_preload")
            return ("tf_module_detect_path", MODEL_PATH)

    return ("no_model", None)


def fomo_post_process(model, inputs, outputs):
    ob, oh, ow, oc = model.output_shape[0]

    x_scale = inputs[0].roi[2] / ow
    y_scale = inputs[0].roi[3] / oh
    scale = min(x_scale, y_scale)

    x_offset = ((inputs[0].roi[2] - (ow * scale)) / 2) + inputs[0].roi[0]
    y_offset = ((inputs[0].roi[3] - (oh * scale)) / 2) + inputs[0].roi[1]

    result = [[] for i in range(oc)]

    for i in range(oc):
        heatmap = image.Image(outputs[0][0, :, :, i] * 255)
        blobs = heatmap.find_blobs(
            THRESHOLD_LIST,
            x_stride=1,
            y_stride=1,
            area_threshold=1,
            pixels_threshold=1,
        )
        for b in blobs:
            rect = b.rect()
            x, y, w, h = rect
            score = heatmap.get_statistics(thresholds=THRESHOLD_LIST, roi=rect).l_mean() / 255.0
            x = int((x * scale) + x_offset)
            y = int((y * scale) + y_offset)
            w = int(w * scale)
            h = int(h * scale)
            result[i].append((x, y, w, h, score))

    return result


def rect_from_detection(det):
    try:
        return det.rect()
    except Exception:
        pass
    try:
        return (det.x(), det.y(), det.w(), det.h())
    except Exception:
        pass
    try:
        values = tuple(det)
        if len(values) >= 4:
            return (values[0], values[1], values[2], values[3])
    except Exception:
        return (0, 0, 0, 0)
    return (0, 0, 0, 0)


def score_from_detection(det):
    try:
        values = tuple(det)
        if len(values) >= 5:
            value = values[4]
            if value > 1.0:
                value = value / 255.0
            return value
    except Exception:
        pass
    for method in ("score", "value", "confidence", "probability"):
        try:
            value = getattr(det, method)()
            if value > 1.0:
                value = value / 255.0
            return value
        except Exception:
            pass
    return MIN_CONFIDENCE


def infer(runtime, net, img):
    global INFER_FRAME_COUNT
    INFER_FRAME_COUNT += 1
    detections = []
    img_w = img.width()
    img_h = img.height()

    if runtime == "ml_predict":
        per_class = net.predict([img], callback=fomo_post_process)
        for class_id, detection_list in enumerate(per_class):
            if class_id == 0 or not detection_list:
                continue
            label = label_at(class_id)
            for x, y, w, h, score in detection_list:
                x = int(x)
                y = int(y)
                w = int(w)
                h = int(h)
                if should_keep_detection(label, x, y, w, h, score, img_w, img_h):
                    detections.append((label, x, y, w, h, score))
        return detections

    if runtime == "tf_net_predict":
        per_class = net.predict([img], callback=fomo_post_process)
        for class_id, detection_list in enumerate(per_class):
            if class_id == 0 or not detection_list:
                continue
            label = label_at(class_id)
            for x, y, w, h, score in detection_list:
                x = int(x)
                y = int(y)
                w = int(w)
                h = int(h)
                if should_keep_detection(label, x, y, w, h, score, img_w, img_h):
                    detections.append((label, x, y, w, h, score))
        return detections

    if runtime == "tf_net_detect":
        per_class = net.detect(img, thresholds=THRESHOLD_LIST)
        for class_id, detection_list in enumerate(per_class):
            if class_id == 0 or not detection_list:
                continue
            label = label_at(class_id)
            for det in detection_list:
                x, y, w, h = rect_from_detection(det)
                x = int(x)
                y = int(y)
                w = int(w)
                h = int(h)
                score = score_from_detection(det)
                if should_keep_detection(label, x, y, w, h, score, img_w, img_h):
                    detections.append((label, x, y, w, h, score))
        return detections

    if runtime == "tf_module_segment":
        # This firmware exposes FOMO as a list of 12x12 grayscale heatmaps.
        # Each output image is one class channel. We find hot blobs manually.
        heatmaps = tf.segment(net, img)
        if DEBUG_TOP_HEATMAPS and (INFER_FRAME_COUNT % DEBUG_TOP_EVERY_N_FRAMES == 0):
            debug_top_heatmaps(heatmaps)
        if DEBUG_NUM_HEATMAPS and (INFER_FRAME_COUNT % DEBUG_NUM_EVERY_N_FRAMES == 0):
            debug_num_heatmaps(heatmaps)

        for class_id, heatmap in enumerate(heatmaps):
            if class_id == 0:
                continue
            label = label_at(class_id)
            try:
                map_w = heatmap.width()
                map_h = heatmap.height()
            except Exception:
                map_w = 12
                map_h = 12

            if map_w <= 0 or map_h <= 0:
                continue

            x_scale = img_w / map_w
            y_scale = img_h / map_h

            try:
                blobs = heatmap.find_blobs(
                    THRESHOLD_LIST,
                    x_stride=1,
                    y_stride=1,
                    area_threshold=1,
                    pixels_threshold=1,
                )
            except Exception as exc:
                print("HEATMAP_FIND_BLOBS_FAIL class=%s err=%s" % (label, exc))
                blobs = []

            for blob in blobs:
                bx, by, bw, bh = blob.rect()
                try:
                    score = heatmap.get_statistics(thresholds=THRESHOLD_LIST, roi=blob.rect()).l_mean() / 255.0
                except Exception:
                    score = MIN_CONFIDENCE

                x = int(bx * x_scale)
                y = int(by * y_scale)
                w = int(max(1, bw * x_scale))
                h = int(max(1, bh * y_scale))
                if should_keep_detection(label, x, y, w, h, score, img_w, img_h):
                    detections.append((label, x, y, w, h, score))

        return detections

    if runtime == "tf_module_detect_path":
        # OpenMV V4.3 exposes detect on the tf module, not on tf_model.
        # The API expects the model path string as the first argument.
        per_class = tf.detect(net, img, thresholds=THRESHOLD_LIST)
        for class_id, detection_list in enumerate(per_class):
            if class_id == 0 or not detection_list:
                continue
            label = label_at(class_id)
            for det in detection_list:
                x, y, w, h = rect_from_detection(det)
                x = int(x)
                y = int(y)
                w = int(w)
                h = int(h)
                score = score_from_detection(det)
                if should_keep_detection(label, x, y, w, h, score, img_w, img_h):
                    detections.append((label, x, y, w, h, score))
        return detections

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


def stable_vote(history, value, required_frames):
    history.append(value)
    if len(history) > required_frames:
        history.pop(0)
    if len(history) < required_frames:
        return "unknown"
    first = history[0]
    for item in history:
        if item != first:
            return "unknown"
    return first


def draw_detections(img, detections):
    for label, x, y, w, h, score in detections:
        cx = int(x + (w / 2))
        cy = int(y + (h / 2))
        color = COLORS[(len(label) + x + y) % len(COLORS)]
        img.draw_circle((cx, cy, 12), color=color, thickness=2)
        img.draw_string(max(0, x), max(0, y - 12), label, color=(255, 255, 255))
        print("%s x=%d y=%d score=%.2f" % (label, cx, cy, score))


def init_uart():
    if not UART_ENABLE or UART is None:
        return None
    try:
        uart = UART(UART_ID, UART_BAUD, timeout_char=1000)
        print("UART_READY")
        return uart
    except Exception as exc:
        print("UART_INIT_FAIL:", exc)
        return None


def send_line(uart, line):
    print(line)
    if uart is not None:
        try:
            uart.write(line + "\n")
        except Exception as exc:
            print("UART_WRITE_FAIL:", exc)


def unsupported_loop(reason):
    print("UNSUPPORTED_FOMO_RUNTIME")
    print(reason)
    print("This is not a fixed-ROI problem. The model is FOMO output 12x12x21.")
    print("This firmware needs ml.Model(...).predict(...), tf.segment(...), or old net.detect(...).")
    print("Camera preview will stay alive; no exception popup should appear.")

    clock = time.clock()
    counter = 0
    while True:
        clock.tick()
        img = sensor.snapshot()
        try:
            img.draw_string(2, 2, "FOMO runtime unsupported", color=(255, 0, 0))
        except Exception:
            pass
        counter += 1
        if counter % 20 == 0:
            print("camera_alive fps %.2f" % clock.fps())
        gc.collect()


def run():
    print("SMARTCAR_FOMO_SAFE_RUNNER_START")
    print("ml_available:", ml is not None)
    print("tf_available:", tf is not None)

    init_camera()
    runtime, net = load_model()

    if runtime == "no_model":
        unsupported_loop("No usable ml or tf model loader was found.")
        return

    if runtime == "unsupported":
        unsupported_loop("tf.load works, but this tf_model has no detect/predict method.")
        return

    uart = init_uart()
    num_history = []
    char_history = []
    last_line = ""
    fail_count = 0
    clock = time.clock()
    printed_size = False

    print("INFERENCE_READY:", runtime)
    print("labels:", LABELS)
    print("thresholds: global=%.2f num=%.2f char=%.2f" % (MIN_CONFIDENCE, NUM_MIN_CONFIDENCE, CHAR_MIN_CONFIDENCE))
    print("weak_char_labels:", WEAK_CHAR_LABELS)
    print("class_thresholds:", CLASS_THRESHOLDS)
    print("valid_center_filter:", USE_VALID_CENTER_FILTER)
    print("use_full_qvga:", USE_FULL_QVGA)
    print("ipm_enabled:", USE_IPM)
    if USE_IPM:
        print("ipm_corners:", IPM_CORNERS)

    while True:
        clock.tick()
        img = sensor.snapshot()
        img = apply_inverse_perspective(img)
        if not printed_size:
            print("image_size:", img.width(), img.height())
            printed_size = True

        try:
            detections = infer(runtime, net, img)
            fail_count = 0
        except Exception as exc:
            fail_count += 1
            print("INFERENCE_FAIL_%d:" % fail_count, exc)
            if fail_count >= 3:
                unsupported_loop("Inference API exists but failed repeatedly: " + str(exc))
                return
            continue

        draw_detections(img, detections)
        (num_label, num_score), (char_label, char_score) = best_by_group(detections)
        char_vote_frames = VOTE_FRAMES
        if char_label in WEAK_CHAR_LABELS:
            char_vote_frames = VOTE_FRAMES + 1
        stable_num = stable_vote(num_history, num_label, VOTE_FRAMES)
        stable_char = stable_vote(char_history, char_label, char_vote_frames)

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
        gc.collect()


try:
    run()
except Exception as exc:
    # OpenMV IDE uses an exception to interrupt a running script. Do not catch
    # that one, or the Stop button will appear to be broken.
    if "IDE interrupt" in str(exc) or "KeyboardInterrupt" in str(exc):
        raise
    print("TOP_LEVEL_CAUGHT:", exc)
    try:
        unsupported_loop("Top-level exception was caught safely.")
    except Exception as fallback_exc:
        if "IDE interrupt" in str(fallback_exc) or "KeyboardInterrupt" in str(fallback_exc):
            raise
        print("FALLBACK_LOOP_FAIL:", fallback_exc)
        while True:
            time.sleep_ms(1000)
