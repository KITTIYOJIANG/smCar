print("CMM_PROBE_START")

try:
    import cmm
    print("cmm_OK")
    try:
        print("cmm_dir:", dir(cmm))
    except Exception as exc:
        print("cmm_dir_FAIL:", exc)
except Exception as exc:
    print("cmm_FAIL:", exc)
    cmm = None

try:
    import cmm_load
    print("cmm_load_OK")
    try:
        result = cmm_load.load()
        print("cmm_load_result:", result)
    except Exception as exc:
        print("cmm_load_CALL_FAIL:", exc)
except Exception as exc:
    print("cmm_load_IMPORT_FAIL:", exc)

print("CMM_PROBE_END")
