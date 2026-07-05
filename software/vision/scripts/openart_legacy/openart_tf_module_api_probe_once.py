import sensor
import tf

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
            idx = 0
            for item in result:
                print("ITEM_%d:" % idx, item)
                idx += 1
                if idx >= 4:
                    break
        except Exception as exc:
            print("ITER_FAIL:", exc)
        return True
    except Exception as exc:
        print("FAIL:", name, exc)
        return False


print("=== RUN_THIS_FILE_TF_API_PROBE_ONCE ===")
print("TF_MODULE_API_PROBE_ONCE_START")
print("tf_dir:", safe_dir(tf))

try:
    net = tf.load(MODEL_PATH, load_to_fb=False)
    print("tf_load_OK:", net)
    print("net_dir:", safe_dir(net))
except Exception as exc:
    print("tf_load_FAIL:", exc)
    net = None

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
    img = None

ok_count = 0
if img is not None:
    calls = [
        ("tf.detect_path_kw", lambda: tf.detect(MODEL_PATH, img, thresholds=THRESHOLDS)),
        ("tf.detect_path_pos_none", lambda: tf.detect(MODEL_PATH, img, None, THRESHOLDS)),
        ("tf.detect_path_pos_roi", lambda: tf.detect(MODEL_PATH, img, (0, 0, img.width(), img.height()), THRESHOLDS)),
        ("tf.segment_path", lambda: tf.segment(MODEL_PATH, img)),
        ("tf.fastdetect_path", lambda: tf.fastdetect(MODEL_PATH, img, THRESHOLDS)),
        ("tf.invoke_path_img", lambda: tf.invoke(MODEL_PATH, img)),
    ]

    if net is not None:
        calls.extend([
            ("tf.detect_net_kw", lambda: tf.detect(net, img, thresholds=THRESHOLDS)),
            ("tf.detect_net_pos_none", lambda: tf.detect(net, img, None, THRESHOLDS)),
            ("tf.segment_net", lambda: tf.segment(net, img)),
            ("tf.fastdetect_net", lambda: tf.fastdetect(net, img, THRESHOLDS)),
            ("tf.invoke_net_img", lambda: tf.invoke(net, img)),
        ])

    for name, fn in calls:
        if show_result(name, fn):
            ok_count += 1

print("TF_MODULE_API_PROBE_ONCE_SUMMARY_OK_COUNT:", ok_count)
print("TF_MODULE_API_PROBE_ONCE_END")
print("=== PROBE_FINISHED_YOU_CAN_STOP_OR_RUN_ANOTHER_FILE ===")
