import sensor
import tf

print("TF_CAPABILITY_PROBE_START")

def show_dir(name, obj):
    print("DIR", name)
    try:
        items = dir(obj)
        print(items)
    except Exception as exc:
        print("dir_FAIL", name, exc)

show_dir("tf", tf)

try:
    net = tf.load("trained.tflite", load_to_fb=False)
    print("MODEL_LOAD_OK", net)
    show_dir("net", net)
except Exception as exc:
    print("MODEL_LOAD_FAIL", exc)
    net = None

if net:
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.set_windowing((240, 240))
    sensor.skip_frames(time=1000)
    img = sensor.snapshot()

    calls = [
        ("tf.classify", lambda: tf.classify(net, img, min_scale=1.0, scale_mul=0.5, x_overlap=0.0, y_overlap=0.0)),
        ("tf.detect", lambda: tf.detect(net, img)),
        ("net.classify", lambda: net.classify(img)),
        ("net.detect", lambda: net.detect(img)),
        ("net.predict", lambda: net.predict(img)),
    ]

    for name, fn in calls:
        print("CALL", name)
        try:
            result = fn()
            print("OK", name, result)
            try:
                print("LEN", len(result))
            except Exception as exc:
                print("LEN_FAIL", exc)
        except Exception as exc:
            print("FAIL", name, exc)

print("TF_CAPABILITY_PROBE_END")
