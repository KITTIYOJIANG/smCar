# OpenMV character classifier.
#
# Files to copy to the OpenMV disk:
#   - main.py                  <- this file, or rename this file to main.py
#   - classifier.tflite        <- converted/quantized model
#   - labels.txt               <- one label per line, same order as training
#
# The PyTorch .pt model saved by the PC training script cannot run directly on
# OpenMV. Convert it to a quantized TensorFlow Lite model first, then name the
# converted file classifier.tflite.

import sensor
import time
import tf


# -------- Model files --------

MODEL_PATH = "classifier.tflite"
LABELS_PATH = "classifier_labels.txt"

# Ignore low-confidence predictions. Raise this to reduce false positives.
MIN_CONFIDENCE = 0.35


# -------- Camera profile --------

# QVGA is much faster and lighter for OpenMV inference. If your board has enough
# memory and the result is unstable, try sensor.VGA and scale the ROIs by 2.
FRAME_SIZE = sensor.QVGA  # 320 x 240
PIX_FORMAT = sensor.RGB565

# Same dark-screen idea as main_dark_screen.py, scaled from VGA to QVGA.
EXPOSURE_US_START = 220
EXPOSURE_US_MIN = 80
EXPOSURE_US_MAX = 900
GAIN_DB = 0

BRIGHTNESS = -4
CONTRAST = 1
SATURATION = 3

# Bright game screen ROI in QVGA coordinates: (x, y, w, h).
# Tune this red box first so it covers only the projected game area.
SCREEN_ROI = (102, 2, 142, 112)

# Classification ROI. Leave as full frame first because the current PC model was
# trained from full camera frames. If you later train from cropped character
# cards, change this to that card/person area for a tighter drawn box.
CLASSIFY_ROI = (0, 0, 320, 240)

# Optional target-area inverse perspective mapping. Train and infer with the
# same setting so the board sees the same cropped/warped target area.
USE_IPM = False
IPM_CORNERS = ((108, 63), (204, 64), (204, 155), (104, 155))
IPM_FAIL_CLOSED = False

try:
    from roi_runtime_config import CLASSIFY_ROI as CONFIG_CLASSIFY_ROI
    from roi_runtime_config import SCREEN_ROI as CONFIG_SCREEN_ROI

    CLASSIFY_ROI = CONFIG_CLASSIFY_ROI
    SCREEN_ROI = CONFIG_SCREEN_ROI
except ImportError:
    pass

try:
    import ipm_runtime_config as ipm_config

    USE_IPM = bool(getattr(ipm_config, "USE_IPM", USE_IPM))
    IPM_CORNERS = getattr(ipm_config, "IPM_CORNERS", IPM_CORNERS)
    IPM_FAIL_CLOSED = bool(getattr(ipm_config, "IPM_FAIL_CLOSED", IPM_FAIL_CLOSED))
except Exception:
    pass

TARGET_L_MEAN = 48
TARGET_L_UQ = 68
AUTO_EXPOSURE_TRIM = True
TRIM_EVERY_N_FRAMES = 20

DARKEN_STRONG = 0.88
DARKEN_SOFT = 0.95
BRIGHTEN_SOFT = 1.02
BRIGHTEN_STRONG = 1.04


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def scale_exposure(exposure_us, factor):
    next_exposure = int(exposure_us * factor)
    if factor > 1 and next_exposure <= exposure_us:
        next_exposure = exposure_us + 1
    elif factor < 1 and next_exposure >= exposure_us:
        next_exposure = exposure_us - 1
    return clamp(next_exposure, EXPOSURE_US_MIN, EXPOSURE_US_MAX)


def set_manual_camera(exposure_us):
    sensor.set_auto_gain(False, gain_db=GAIN_DB)
    sensor.set_auto_exposure(False, exposure_us=exposure_us)
    sensor.set_auto_whitebal(False)
    sensor.set_brightness(BRIGHTNESS)
    sensor.set_contrast(CONTRAST)
    sensor.set_saturation(SATURATION)


def load_labels(path):
    labels = []
    try:
        with open(path) as handle:
            for line in handle:
                label = line.strip()
                if label:
                    labels.append(label)
    except OSError:
        # Fallback keeps the script debuggable if labels.txt was not copied.
        labels = [
            "DonaldDuck",
            "GreyWolf",
            "Mickey",
            "Nazha",
            "SpongeBob",
            "calabash_brothers",
            "ggbond",
            "num",
            "pika",
            "pleasantSheep",
            "son",
        ]
    return labels


def best_prediction(scores):
    best_index = 0
    best_score = scores[0]
    for index in range(1, len(scores)):
        if scores[index] > best_score:
            best_index = index
            best_score = scores[index]
    return best_index, best_score


def translate_rect(rect, roi):
    return (rect[0] + roi[0], rect[1] + roi[1], rect[2], rect[3])


def draw_prediction(img, rect, label, score):
    color = (0, 255, 0)
    img.draw_rectangle(rect, color=color, thickness=2)
    text = "%s %.2f" % (label, score)
    text_y = rect[1] - 14
    if text_y < 0:
        text_y = rect[1] + 4
    img.draw_string(rect[0] + 2, text_y, text, color=color, scale=1, mono_space=False)


IPM_RUNTIME_ENABLED = USE_IPM
IPM_WARNED = False


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


sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)
set_manual_camera(EXPOSURE_US_START)
sensor.skip_frames(time=2000)

net = tf.load(MODEL_PATH, load_to_fb=True)
labels = load_labels(LABELS_PATH)

clock = time.clock()
exposure_us = EXPOSURE_US_START
frame_count = 0
print("IPM_ENABLED:", USE_IPM)
if USE_IPM:
    print("IPM_CORNERS:", IPM_CORNERS)

while True:
    clock.tick()
    img = sensor.snapshot()
    frame_count += 1

    stats = img.get_statistics(roi=SCREEN_ROI)
    l_mean = stats.l_mean()
    l_uq = stats.l_uq()

    if AUTO_EXPOSURE_TRIM and (frame_count % TRIM_EVERY_N_FRAMES == 0):
        if l_uq > TARGET_L_UQ + 12 or l_mean > TARGET_L_MEAN + 14:
            exposure_us = scale_exposure(exposure_us, DARKEN_STRONG)
        elif l_uq > TARGET_L_UQ + 5 or l_mean > TARGET_L_MEAN + 7:
            exposure_us = scale_exposure(exposure_us, DARKEN_SOFT)
        elif l_mean < TARGET_L_MEAN - 12 and l_uq < TARGET_L_UQ - 15:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_STRONG)
        elif l_mean < TARGET_L_MEAN - 6 and l_uq < TARGET_L_UQ - 8:
            exposure_us = scale_exposure(exposure_us, BRIGHTEN_SOFT)
        sensor.set_auto_exposure(False, exposure_us=exposure_us)

    infer_img = apply_inverse_perspective(img)

    # Classify the configured ROI. With min_scale=1.0, OpenMV returns the full
    # classifier window, which we draw as the detection box.
    crop = infer_img.copy(roi=CLASSIFY_ROI)
    best_label = None
    best_score = 0.0
    best_rect = None

    for obj in tf.classify(net, crop, min_scale=1.0, scale_mul=0.8, x_overlap=0.0, y_overlap=0.0):
        scores = obj.output()
        label_index, score = best_prediction(scores)
        if score > best_score:
            best_score = score
            best_label = labels[label_index] if label_index < len(labels) else str(label_index)
            best_rect = translate_rect(obj.rect(), CLASSIFY_ROI)

    # Debug ROIs. Comment these two lines out after tuning.
    if not IPM_RUNTIME_ENABLED:
        img.draw_rectangle(SCREEN_ROI, color=(255, 0, 0), thickness=1)
    infer_img.draw_rectangle(CLASSIFY_ROI, color=(0, 0, 255), thickness=1)

    if best_label is not None and best_score >= MIN_CONFIDENCE:
        draw_prediction(infer_img, best_rect, best_label, best_score)
        print("%s %.3f fps=%.1f exp_us=%d" % (best_label, best_score, clock.fps(), exposure_us))
    else:
        print("unknown %.3f fps=%.1f exp_us=%d" % (best_score, clock.fps(), exposure_us))
