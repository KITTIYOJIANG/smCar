# OpenART target-area character classifier.
#
# Required files on the board root:
# - classifier.tflite
# - classifier_labels.txt
# - ipm_runtime_config.py

import sensor
import tf
import time
import math


SCRIPT_VERSION = "CHAR_CLASSIFIER_SOFTMAX_V5_20260630"
MODEL_PATH = "classifier.tflite"
LABELS_PATH = "classifier_labels.txt"
MIN_CONFIDENCE = 0.45
VOTE_FRAMES = 3

FRAME_SIZE = sensor.QVGA
PIX_FORMAT = sensor.RGB565

CLASSIFY_ROI = (0, 0, 320, 240)
USE_IPM = True
IPM_CORNERS = ((108, 63), (204, 64), (204, 155), (104, 155))
IPM_FAIL_CLOSED = False

NON_CHARACTER_LABELS = ("num", "background", "unknown")
DEFAULT_LABELS = (
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
)

CHARACTER_LABELS = (
    "DonaldDuck",
    "GreyWolf",
    "Mickey",
    "Nazha",
    "SpongeBob",
    "calabash_brothers",
    "ggbond",
    "pika",
    "pleasantSheep",
    "son",
)

try:
    import ipm_runtime_config as ipm_config

    USE_IPM = bool(getattr(ipm_config, "USE_IPM", USE_IPM))
    IPM_CORNERS = getattr(ipm_config, "IPM_CORNERS", IPM_CORNERS)
    IPM_FAIL_CLOSED = bool(getattr(ipm_config, "IPM_FAIL_CLOSED", IPM_FAIL_CLOSED))
except Exception:
    pass


def load_labels(path):
    # The labels are embedded to prevent OpenMV IDE cached files or FAT read
    # hiccups from causing numeric labels such as "2" to be printed.
    labels = list(DEFAULT_LABELS)
    try:
        handle = open(path)
        try:
            file_labels = []
            for line in handle:
                label = line.strip()
                if label:
                    file_labels.append(label)
        finally:
            handle.close()
        if len(file_labels) == len(DEFAULT_LABELS):
            labels = file_labels
        else:
            print("LABEL_FILE_LENGTH_MISMATCH:", len(file_labels))
    except OSError as exc:
        print("LABEL_LOAD_FAIL:", exc)
    return labels


def best_prediction(scores):
    best_index = 0
    best_score = scores[0]
    for index in range(1, len(scores)):
        score = scores[index]
        if score > best_score:
            best_index = index
            best_score = score
    if best_score > 1.0:
        best_score = best_score / 255.0
    return best_index, best_score


def normalized_score(value):
    if value > 1.0:
        return value / 255.0
    return value


def top_predictions(scores, labels, count):
    raw = []
    max_score = -9999.0
    for index in range(len(scores)):
        label = label_for_index(labels, index)
        score = normalized_score(scores[index])
        raw.append((score, label))
        if score > max_score:
            max_score = score

    total = 0.0
    for index in range(len(raw)):
        total += math.exp(raw[index][0] - max_score)

    first_score = -9999.0
    second_score = -9999.0
    third_score = -9999.0
    first_label = "unknown"
    second_label = "unknown"
    third_label = "unknown"

    for index in range(len(raw)):
        label = raw[index][1]
        if total > 0.0:
            score = math.exp(raw[index][0] - max_score) / total
        else:
            score = 0.0
        if score > first_score:
            third_score = second_score
            third_label = second_label
            second_score = first_score
            second_label = first_label
            first_score = score
            first_label = label
        elif score > second_score:
            third_score = second_score
            third_label = second_label
            second_score = score
            second_label = label
        elif score > third_score:
            third_score = score
            third_label = label

    top = []
    if count >= 1:
        top.append((first_score, first_label))
    if count >= 2:
        top.append((second_score, second_label))
    if count >= 3:
        top.append((third_score, third_label))
    return top


def best_from_scores(scores, labels):
    top = top_predictions(scores, labels, 3)
    if len(top) == 0:
        return "unknown", 0.0, top
    return top[0][1], top[0][0], top


def format_top(top):
    text = "TOP3="
    for index in range(len(top)):
        if index:
            text += ","
        text += "%s:%.2f" % (top[index][1], top[index][0])
    return text


def is_character_label(label):
    return label in CHARACTER_LABELS


def label_for_index(labels, index):
    if index < len(labels):
        label = labels[index]
        if label and not label.isdigit():
            return label
    if index < len(DEFAULT_LABELS):
        return DEFAULT_LABELS[index]
    return "unknown"


def stable_vote(history, label, required_frames):
    history.append(label)
    if len(history) > required_frames:
        history.pop(0)
    if len(history) < required_frames:
        return "unknown"
    first = history[0]
    for item in history:
        if item != first:
            return "unknown"
    return first


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
    except Exception as exc:
        if not IPM_WARNED:
            print("IPM_DISABLED:", exc)
            IPM_WARNED = True
        IPM_RUNTIME_ENABLED = False
        if IPM_FAIL_CLOSED:
            raise
    return img


def full_image_roi(img):
    return (0, 0, img.width(), img.height())


def draw_result(img, label, score):
    color = (0, 255, 0) if score >= MIN_CONFIDENCE else (255, 255, 0)
    img.draw_rectangle(full_image_roi(img), color=color, thickness=2)
    img.draw_string(4, 4, "%s %.2f" % (label, score), color=color, scale=2)


sensor.reset()
sensor.set_pixformat(PIX_FORMAT)
sensor.set_framesize(FRAME_SIZE)
sensor.skip_frames(time=2000)

print(SCRIPT_VERSION)
print("CHARACTER_CLASSIFIER_IPM_START")
print("ipm_enabled:", USE_IPM)
print("ipm_corners:", IPM_CORNERS)

net = tf.load(MODEL_PATH, load_to_fb=True)
print("MODEL_LOAD_OK:", net)
labels = load_labels(LABELS_PATH)
if len(labels) == 0:
    labels = list(DEFAULT_LABELS)
    print("LABEL_FALLBACK_USED")
print("labels:", labels)
print("min_confidence:", MIN_CONFIDENCE)
print("non_character_labels:", NON_CHARACTER_LABELS)
print("vote_frames:", VOTE_FRAMES)

clock = time.clock()
char_history = []
while True:
    clock.tick()
    img = sensor.snapshot()
    infer_img = apply_inverse_perspective(img)
    crop = infer_img.copy(roi=full_image_roi(infer_img))

    best_label = "unknown"
    best_score = -9999.0
    best_top = []
    for obj in tf.classify(net, crop, min_scale=1.0, scale_mul=0.8, x_overlap=0.0, y_overlap=0.0):
        label, score, top = best_from_scores(obj.output(), labels)
        if score > best_score:
            best_label = label
            best_score = score
            best_top = top

    if best_score < 0.0:
        best_score = 0.0

    output_label = best_label
    if not is_character_label(best_label) or best_score < MIN_CONFIDENCE:
        output_label = "unknown"
        char_history = []
    else:
        output_label = stable_vote(char_history, best_label, VOTE_FRAMES)

    draw_result(infer_img, output_label, best_score)
    if output_label != "unknown":
        print("CHAR=%s,CONF=%.2f,%s,fps=%.1f" % (output_label, best_score, format_top(best_top), clock.fps()))
    else:
        print("CHAR=unknown,BEST=%s,CONF=%.2f,%s,fps=%.1f" % (best_label, best_score, format_top(best_top), clock.fps()))
