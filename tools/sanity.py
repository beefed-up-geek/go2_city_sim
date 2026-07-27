import traceback

for mod in ["isaaclab", "metaurban", "jax", "urbansim"]:
    try:
        __import__(mod)
        print(f"OK {mod}", flush=True)
    except Exception as e:
        print(f"FAIL {mod}: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        break
