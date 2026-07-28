#!/usr/bin/env python3
"""보행자 gltf → USD 변환 (SynBody/characters) → <repo>/assets/usd/peds/<name>/<name>.usd"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from isaacsim.core.utils.extensions import enable_extension
enable_extension("omni.kit.asset_converter")
import omni.kit.asset_converter as conv
import asyncio, glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("URBANSIM_WS", "/workspace/urban-sim")
SRC = [f"{BASE}/assets/pedestrians/SynBody_actor/converted",
       f"{BASE}/assets/pedestrians/characters_yup"]
OUT = f"{ROOT}/assets/usd/peds"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 12

jobs = []
for d in SRC:
    for g in sorted(glob.glob(f"{d}/*.gltf")):
        tag = os.path.basename(os.path.dirname(d)) if False else os.path.basename(d)[:4]
        name = f"ped_{tag}_{os.path.splitext(os.path.basename(g))[0]}"
        jobs.append((g, f"{OUT}/{name}/{name}.usd"))
jobs = jobs[:LIMIT]
print(f"[peds] {len(jobs)} jobs", flush=True)

async def run():
    ok = fail = 0
    for i, (inp, outp) in enumerate(jobs):
        if os.path.exists(outp):
            ok += 1; continue
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        ctx = conv.AssetConverterContext()
        ctx.use_meter_as_world_unit = True
        task = conv.get_instance().create_converter_task(inp, outp, None, ctx)
        if await task.wait_until_finished(): ok += 1
        else:
            fail += 1
            print(f"[peds] FAIL {os.path.basename(inp)}: {task.get_error_message()}", flush=True)
        if (i + 1) % 4 == 0: print(f"[peds] {i+1}/{len(jobs)} ok={ok} fail={fail}", flush=True)
    print(f"[peds] COMPLETE ok={ok} fail={fail}", flush=True)

asyncio.get_event_loop().run_until_complete(run())
app.close()
