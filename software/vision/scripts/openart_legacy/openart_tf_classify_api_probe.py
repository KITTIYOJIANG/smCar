import sensor
import tf
import time

print("TF_CLASSIFY_API_PROBE_START")

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.set_windowing((240, 240))
sensor.skip_frames(time=1000)

net = tf.load("trained.tflite", load_to_fb=False)
print("model:", net)

img = sensor.snapshot()

tests = [
    ("default", {}),
    ("scale_0_5", {"min_scale": 1.0, "scale_mul": 0.5, "x_overlap": 0.0, "y_overlap": 0.0}),
    ("scale_0_8", {"min_scale": 1.0, "scale_mul": 0.8, "x_overlap": 0.0, "y_overlap": 0.0}),
]

for name, kwargs in tests:
    print("TEST", name)
    try:
        objs = tf.classify(net, img, **kwargs)
        print("objects:", len(objs))
        for i, obj in enumerate(objs[:3]):
            out = obj.output()
            print("obj", i, "rect", obj.rect(), "out_len", len(out))
            print("first10", out[:10])
    except Exception as exc:
        print("FAIL", name, exc)

print("TF_CLASSIFY_API_PROBE_END")
