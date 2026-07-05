import sensor
import tf
import time

MODEL_PATH = "trained.tflite"
THRESHOLDS = [(179, 255)]


def safe_dir(obj):
    try:
        return dir(obj)
    except Exception as exc:
        return ["dir_FAIL", str(exc)]


def show_result(name, fn):
    print("CALL:", name)
    try:
        result = fn()
        print("OK:", name, result)
        try:
            print("LEN:", len(result))
        except Exception as exc:
            print("LEN_FAIL:", exc)
        try:
            for i, item in enumerate(result):
                print("ITEM_%d:" % i, item)
                if i >= 3:
                    break
        except Exception as exc:
            print("ITER_FAIL:", exc)
        return True
    except Exception as exc:
        print("FAIL:", name, exc)
        return False


print("TF_MODULE_API_PROBE_START")
print("tf_dir:", safe_dir(tf))

try:
    net = tf.load(MODEL_PATH, load_to_fb=False)
    print("tf_load_OK:", net)
    print("net_dir:", safe_dir(net))
except Exception as exc:
    print("tf_load_FAIL:", exc)
    net = None

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.set_windowing((240, 240))
sensor.skip_frames(time=1000)
img = sensor.snapshot()
print("camera_OK:", img.width(), img.height())

calls = [
    ("tf.detect_path_kw", lambda: tf.detect(MODEL_PATH, img, thresholds=THRESHOLDS)),
    ("tf.detect_path_pos_none", lambda: tf.detect(MODEL_PATH, img, None, THRESHOLDS)),
    ("tf.detect_path_pos_roi", lambda: tf.detect(MODEL_PATH, img, (0, 0, img.width(), img.height()), THRESHOLDS)),
    ("tf.detect_net_kw", lambda: tf.detect(net, img, thresholds=THRESHOLDS)),
    ("tf.detect_net_pos_none", lambda: tf.detect(net, img, None, THRESHOLDS)),
    ("tf.segment_path", lambda: tf.segment(MODEL_PATH, img)),
    ("tf.segment_net", lambda: tf.segment(net, img)),
    ("tf.fastdetect_path", lambda: tf.fastdetect(MODEL_PATH, img, THRESHOLDS)),
    ("tf.fastdetect_net", lambda: tf.fastdetect(net, img, THRESHOLDS)),
    ("tf.invoke_path_img", lambda: tf.invoke(MODEL_PATH, img)),
    ("tf.invoke_net_img", lambda: tf.invoke(net, img)),
]

ok_count = 0
for name, fn in calls:
    if net is None and "_net" in name:
        print("SKIP:", name, "no net")
        continue
    if show_result(name, fn):
        ok_count += 1

print("TF_MODULE_API_PROBE_SUMMARY_OK_COUNT:", ok_count)
print("TF_MODULE_API_PROBE_END")

clock = time.clock()
counter = 0
while True:
    clock.tick()
    img = sensor.snapshot()
    counter += 1
    if counter % 30 == 0:
        print("probe_alive fps %.2f ok_count %d" % (clock.fps(), ok_count))
