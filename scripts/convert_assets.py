#!/usr/bin/env python3
"""GLB -> USD 일괄 변환 (urbansim 컨테이너 내 /isaac-sim/python.sh 로 실행)"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from isaacsim.core.utils.extensions import enable_extension
enable_extension("omni.kit.asset_converter")
import omni.kit.asset_converter as conv
import asyncio, glob, os, sys

SRC_CUSTOM = "/workspace/urban-sim/assets_custom"
SRC_OBJ = "/workspace/urban-sim/assets/objects"
OUT = "/workspace/urban-sim/assets_custom/usd"
CATS = ["Building_", "Bench_", "Trash_bin_", "TrashCan_", "busstation_", "Telephone_booth_", "Vending_machine_", "Mailbox_"]

jobs = []
for g in sorted(glob.glob(SRC_CUSTOM + "/*.glb")):
    name = os.path.splitext(os.path.basename(g))[0]
    jobs.append((g, f"{OUT}/{name}/{name}.usd"))
for g in sorted(glob.glob(SRC_OBJ + "/*.glb")):
    b = os.path.basename(g)
    if any(b.startswith(c) for c in CATS):
        name = os.path.splitext(b)[0]
        jobs.append((g, f"{OUT}/objects/{name}/{name}.usd"))
print(f"[conv] {len(jobs)} jobs", flush=True)

async def run():
    ok = fail = 0
    for i, (inp, outp) in enumerate(jobs):
        if os.path.exists(outp):
            ok += 1; continue
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        ctx = conv.AssetConverterContext()
        ctx.use_meter_as_world_unit = True
        task = conv.get_instance().create_converter_task(inp, outp, None, ctx)
        success = await task.wait_until_finished()
        if success: ok += 1
        else:
            fail += 1
            print(f"[conv] FAIL {os.path.basename(inp)}: {task.get_error_message()}", flush=True)
        if (i + 1) % 10 == 0:
            print(f"[conv] {i+1}/{len(jobs)} ok={ok} fail={fail}", flush=True)
    print(f"[conv] COMPLETE ok={ok} fail={fail}", flush=True)

asyncio.get_event_loop().run_until_complete(run())
app.close()
