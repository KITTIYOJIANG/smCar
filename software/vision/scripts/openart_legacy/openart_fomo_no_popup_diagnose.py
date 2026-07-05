import sensor
import tf

print("NO_POPUP_FOMO_DIAGNOSE_START")

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


def safe_dir(obj):
    try:
        return dir(obj)
    except Exception as exc:
        return ["dir_FAIL", str(exc)]


try:
    print("tf_dir:", safe_dir(tf))
    net = tf.load("trained.tflite", load_to_fb=False)
    print("tf_load_OK:", net)
    print("net_dir:", safe_dir(net))
except Exception as exc:
    print("tf_load_FAIL:", exc)
    print("FINAL: model could not be loaded by tf.load.")
    print("NO_POPUP_FOMO_DIAGNOSE_END")
    net = None

img = None
if net is not None:
    try:
        sensor.reset()
        sensor.set_pixformat(sensor.RGB565)
        sensor.set_framesize(sensor.QVGA)
        sensor.set_windowing((240, 240))
        sensor.skip_frames(time=1000)
        img = sensor.snapshot()
        print("camera_OK:", img.width(), img.height())
    except Exception as exc:
        print("camera_FAIL:", exc)

methods = safe_dir(net) if net is not None else []
if "detect" in methods:
    print("HAS_NET_DETECT: this firmware may run old Edge Impulse FOMO via net.detect().")
else:
    print("NO_NET_DETECT")

if "segment" in methods:
    print("HAS_NET_SEGMENT")
else:
    print("NO_NET_SEGMENT")

if "predict" in methods:
    print("HAS_NET_PREDICT")
else:
    print("NO_NET_PREDICT")

if "classify" in methods:
    print("HAS_NET_CLASSIFY")
else:
    print("NO_NET_CLASSIFY")

print("TEST_CALLS")

if net is not None and img is not None:
    try:
        result = net.detect(img, thresholds=[(179, 255)])
        print("net.detect_OK:", result)
    except Exception as exc:
        print("net.detect_FAIL:", exc)

    try:
        result = tf.classify(net, img, min_scale=1.0, scale_mul=0.5, x_overlap=0.0, y_overlap=0.0)
        print("tf.classify_OK:", result)
    except Exception as exc:
        print("tf.classify_FAIL:", exc)

    try:
        result = net.classify(img)
        print("net.classify_OK:", result)
    except Exception as exc:
        print("net.classify_FAIL:", exc)
else:
    print("SKIP_TEST_CALLS: no loaded model or camera image")

print("FINAL_ANALYSIS:")
print("This model is FOMO. PC output shape is 1x12x12x21.")
print("To run FOMO on old OpenMV tf, firmware must expose net.detect().")
print("If net.detect_FAIL says no attribute, this firmware build cannot run FOMO.")
print("Then the real fix is firmware with Edge Impulse/FOMO detect support, or a classification model.")
print("NO_POPUP_FOMO_DIAGNOSE_END")
