#!/usr/bin/env python3
"""GLB -> USD 일괄 변환 (urbansim 컨테이너 내 /isaac-sim/python.sh 로 실행)"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from isaacsim.core.utils.extensions import enable_extension
enable_extension("omni.kit.asset_converter")
import omni.kit.asset_converter as conv
import asyncio, glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 저장소 루트
BASE = os.environ.get("URBANSIM_WS", "/workspace/urban-sim")
SRC_CUSTOM = f"{ROOT}/assets/src"                 # 저장소 동봉 GLB (asa21 등)
SRC_OBJ = f"{BASE}/assets/objects"                # URBAN-SIM 원본 GLB 모음
OUT = f"{ROOT}/assets/usd"
CATS = ["Building_", "Bench_", "Trash_bin_", "TrashCan_", "busstation_", "Telephone_booth_", "Vending_machine_", "Mailbox_"]
ONLY = set(sys.argv[1:])                          # 인자 지정 시 해당 이름만 변환

jobs = []
for g in sorted(glob.glob(SRC_CUSTOM + "/*.glb")):
    name = os.path.splitext(os.path.basename(g))[0]
    if ONLY and name not in ONLY: continue
    jobs.append((g, f"{OUT}/{name}/{name}.usd"))
for g in sorted(glob.glob(SRC_OBJ + "/*.glb")):
    b = os.path.basename(g)
    if any(b.startswith(c) for c in CATS):
        name = os.path.splitext(b)[0]
        if ONLY and name not in ONLY: continue
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
