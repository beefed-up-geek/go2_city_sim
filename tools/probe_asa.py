#!/usr/bin/env python3
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from pxr import Usd, UsdGeom, UsdShade

A = "/workspace/urban-sim/assets_custom/usd/ped_led_countdown/ped_led_countdown.usd"
st = Usd.Stage.Open(A)
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
for prim in st.Traverse():
    if not prim.IsA(UsdGeom.Mesh): continue
    r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    mn, mx = r.GetMin(), r.GetMax()
    mat = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
    col = None
    if mat:
        for sh in mat.GetPrim().GetChildren():
            shd = UsdShade.Shader(sh)
            for nm in ("base_color_factor", "diffuse_color_constant"):
                inp = shd.GetInput(nm) if shd else None
                if inp and inp.Get() is not None: col = tuple(round(float(c),2) for c in list(inp.Get())[:3]); break
            if col: break
    print(f"AMESH {prim.GetPath()} z=({mn[1]:.1f}..{mx[1]:.1f}) xz=({mn[0]:.1f}..{mx[0]:.1f},{mn[2]:.1f}..{mx[2]:.1f}) mat={mat.GetPath().name if mat else None} col={col}", flush=True)
app.close()
