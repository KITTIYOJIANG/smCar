import gc
import uos
import tf

print("TFLITE_FILE_PROBE_START")
print("cwd:", uos.getcwd())
print("listdir:")
try:
    print(uos.listdir())
except Exception as exc:
    print("listdir_FAIL", exc)

for path in ("trained.tflite", "/trained.tflite", "labels.txt", "/labels.txt"):
    print("CHECK", path)
    try:
        print("stat:", uos.stat(path))
    except Exception as exc:
        print("stat_FAIL", exc)
    try:
        f = open(path, "rb")
        data = f.read(16)
        f.close()
        print("read16:", data)
    except Exception as exc:
        print("read_FAIL", exc)

print("mem_free:", gc.mem_free())
for load_to_fb in (False, True):
    try:
        print("tf.load trained.tflite load_to_fb=", load_to_fb)
        net = tf.load("trained.tflite", load_to_fb=load_to_fb)
        print("tf_load_OK", net)
        print("input:", net.input_width(), net.input_height(), net.input_channels(), net.input_datatype())
        print("output:", net.output_width(), net.output_height(), net.output_channels(), net.output_datatype())
    except Exception as exc:
        print("tf_load_FAIL", load_to_fb, exc)

print("TFLITE_FILE_PROBE_END")
