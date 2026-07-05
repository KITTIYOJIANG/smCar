def probe(name):
    try:
        module = __import__(name)
        print(name + "_OK")
        print(module)
        return True
    except Exception as exc:
        print(name + "_FAIL", exc)
        return False


print("OPENART_RUNTIME_PROBE_START")
probe("ml")
probe("tf")
probe("tensorflow")
probe("sensor")
probe("image")
print("OPENART_RUNTIME_PROBE_END")
