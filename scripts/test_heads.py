#!/usr/bin/env python3
"""보행등(asa21) 격리 캘리브레이션 씬.

도시 전체를 재빌드하지 않고 asa21 모델 + 상태 커버의 좌표를 빠르게 검증한다.
- 기본: 커버를 적용한 상태(적색 사람만 보임)를 정면/전신 2컷 렌더
- TH_RULER=1: 파란 z눈금(1.6~2.6m)·노란 x눈금을 함께 렌더 — 표시창 좌표를
  픽셀로 판독할 때 사용(카메라별 px/m이 달라 눈금 없는 역산은 부정확)

실행(컨테이너): /isaac-sim/python.sh scripts/test_heads.py
출력: $URBANSIM_WS/shots/asa_front.jpg, asa_front_full.jpg
"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True, "width": 1280, "height": 720})
import math, os
import numpy as _np
import carb.settings
import omni.usd, omni.timeline
from pxr import Usd, UsdGeom, UsdShade, UsdLux, Sdf, Gf
from PIL import Image as _Image

_cs = carb.settings.get_settings()
_cs.set("/rtx/post/aa/op", 3)
_cs.set("/rtx/post/histogram/enabled", False)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("URBANSIM_WS", "/workspace/urban-sim")
CUSTOM = f"{ROOT}/assets/usd"
RULER = os.environ.get("TH_RULER", "0") == "1"

ctx = omni.usd.get_context()
ctx.new_stage()
stage = ctx.get_stage()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
world = UsdGeom.Xform.Define(stage, "/World")
stage.SetDefaultPrim(world.GetPrim())

# 조명 + 바닥
dome = UsdLux.DomeLight.Define(stage, "/World/Sky"); dome.CreateIntensityAttr(1000.0)
sun = UsdLux.DistantLight.Define(stage, "/World/Sun"); sun.CreateIntensityAttr(3000.0); sun.CreateAngleAttr(0.53)
UsdGeom.Xformable(sun.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3d(-50.0, 15.0, 0.0))
gp = UsdGeom.Cube.Define(stage, "/World/ground")
UsdGeom.Xformable(gp).AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.5))
UsdGeom.Xformable(gp).AddScaleOp().Set(Gf.Vec3f(30, 30, 0.5))

def pbr(name, rgb, rough):
    mat = UsdShade.Material.Define(stage, f"/World/Looks/{name}")
    sh = UsdShade.Shader.Define(stage, f"/World/Looks/{name}/Shader")
    sh.CreateImplementationSourceAttr(UsdShade.Tokens.sourceAsset)
    sh.SetSourceAsset("OmniPBR.mdl", "mdl"); sh.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
    sh.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    sh.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(rough)
    mat.CreateSurfaceOutput("mdl").ConnectToSource(sh.ConnectableAPI(), "out")
    return mat

# asa21: 전고 3m 스케일, 표시면 -y — build_city.py의 프로토와 동일한 배치식
ASA = f"{CUSTOM}/ped_light_asa21/ped_light_asa21.usd"
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
ast = Usd.Stage.Open(ASA)
r = cache.ComputeWorldBound(ast.GetPseudoRoot()).ComputeAlignedRange()
mn, mx = r.GetMin(), r.GetMax()
sc = 3.0 / float(mx[1] - mn[1])
print(f"[asa] bbox y-up h={float(mx[1]-mn[1]):.1f} sc={sc:.5f}", flush=True)
h = UsdGeom.Xform.Define(stage, "/World/asa")
g = UsdGeom.Xform.Define(stage, "/World/asa/g")
g.GetPrim().GetReferences().AddReference(ASA)
xf = UsdGeom.Xformable(h)
cx_ = (float(mn[0]) + float(mx[0])) / 2 * sc
cy_ = -(float(mn[2]) + float(mx[2])) / 2 * sc
xf.AddTranslateOp().Set(Gf.Vec3d(-cx_, -cy_, -float(mn[1]) * sc))
xf.AddRotateXOp().Set(90.0)
xf.AddScaleOp().Set(Gf.Vec3f(sc))

# 상태 커버 (build_city.py _CW와 동일 좌표 — 눈금 캘리브레이션 확정값)
covm = pbr("cover", (0.02, 0.02, 0.025), 0.4)
def cover(path, cx, cz, w, hgt, y=-0.115):
    c = UsdGeom.Cube.Define(stage, path)
    xf2 = UsdGeom.Xformable(c)
    xf2.AddTranslateOp().Set(Gf.Vec3d(cx, y, cz))
    xf2.AddScaleOp().Set(Gf.Vec3f(w/2, 0.006, hgt/2))
    UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(covm)
if not RULER:
    # 적색 사람 상태: 녹색 사람 + 카운트다운 커버 (cov_red 좌표는 (0.05,2.11,0.20,0.28))
    cover("/World/cov_grn", 0.05, 1.84, 0.18, 0.26)
    cover("/World/cov_cnt", 0.255, 1.98, 0.12, 0.60)
else:
    rulm = pbr("rul_z", (0.1, 0.3, 1.0), 0.9)
    rulm2 = pbr("rul_x", (1.0, 0.9, 0.1), 0.9)
    for zi in range(11):
        zz = 1.6 + zi * 0.1
        bar = UsdGeom.Cube.Define(stage, f"/World/rz{zi}")
        xf3 = UsdGeom.Xformable(bar)
        xf3.AddTranslateOp().Set(Gf.Vec3d(0.1, -0.125, zz))
        thick = 0.006 if zi % 5 else 0.014     # 0.5m마다 굵은 눈금
        xf3.AddScaleOp().Set(Gf.Vec3f(0.35, 0.004, thick/2))
        UsdShade.MaterialBindingAPI.Apply(bar.GetPrim()).Bind(rulm)
    for xi in range(5):
        bar = UsdGeom.Cube.Define(stage, f"/World/rx{xi}")
        xf3 = UsdGeom.Xformable(bar)
        xf3.AddTranslateOp().Set(Gf.Vec3d(-0.1 + xi * 0.1, -0.125, 2.1))
        xf3.AddScaleOp().Set(Gf.Vec3f(0.003, 0.004, 0.5))
        UsdShade.MaterialBindingAPI.Apply(bar.GetPrim()).Bind(rulm2)

from isaacsim.core.utils.extensions import enable_extension
enable_extension("isaacsim.sensors.camera")
from isaacsim.sensors.camera import Camera

def q(yaw, pitch):
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    cp, sp = math.cos(pitch/2), math.sin(pitch/2)
    return _np.array([cy*cp, -sy*sp, cy*sp, sy*cp])

cam = Camera(prim_path="/World/cam", resolution=(1280, 720))
cam.initialize()
omni.timeline.get_timeline_interface().play()
for _ in range(50): app.update()
SHOTS = [
    ("asa_front", (0.0, -3.0, 2.3), 90, 0),
    ("asa_front_full", (0.0, -4.5, 1.5), 90, 0),
]
os.makedirs(f"{BASE}/shots", exist_ok=True)
for name, pos, yaw, pitch in SHOTS:
    cam.set_world_pose(_np.array(pos), q(math.radians(yaw), math.radians(pitch)), camera_axes="world")
    for _ in range(20): app.update()
    arr = cam.get_rgba()
    if arr is not None and arr.size > 100:
        _Image.fromarray(arr[:, :, :3]).save(f"{BASE}/shots/{name}.jpg", quality=90)
        print(f"[shot] {name}", flush=True)
print("[test] DONE", flush=True)
app.close()
