#!/usr/bin/env python3
"""변환된 URBAN-SIM 건물/가구 USD의 실측 bbox 카탈로그 -> JSON"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import glob, json, os
from pxr import Usd, UsdGeom

out = {}
for f in sorted(glob.glob("/workspace/urban-sim/assets_custom/usd/objects/*/*.usd")):
    name = os.path.basename(os.path.dirname(f))
    try:
        st = Usd.Stage.Open(f)
        up = UsdGeom.GetStageUpAxis(st)
        mpu = UsdGeom.GetStageMetersPerUnit(st) or 1.0
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render", "proxy"])
        r = cache.ComputeWorldBound(st.GetPseudoRoot()).ComputeAlignedRange()
        s = [r.GetSize()[i] * mpu for i in range(3)]
        if up == "Y": fp_w, fp_d, hgt = s[0], s[2], s[1]
        else: fp_w, fp_d, hgt = s[0], s[1], s[2]
        out[name] = dict(up=str(up), w=round(fp_w, 2), d=round(fp_d, 2), h=round(hgt, 2))
    except Exception as e:
        out[name] = dict(error=str(e))
json.dump(out, open("/workspace/urban-sim/assets_custom/bboxes.json", "w"), indent=1)
print("dumped", len(out))
app.close()
