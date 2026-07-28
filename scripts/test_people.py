#!/usr/bin/env python3
"""NVIDIA 공식 보행자(People) 파이프라인 검증 씬.

우리가 쓰던 방식(SynBody 캐릭터 + SMPL-X skelanim 수동 바인딩)은 골격이 달라
(101관절 Reallusion vs 81관절 NVIDIA biped) 원천적으로 성립하지 않는다.
공식 방식은 Biped_Setup.usd 의 AnimationGraph 를 캐릭터 SkelRoot 에 붙이고
omni.anim.graph.core 로 상태(Action)를 구동하는 것이다.

이 스크립트는 그 배선이 실제로 (a) 렌더되고 (b) 포즈가 변하는지 확인한다.
실행(컨테이너): /isaac-sim/python.sh go2_city_sim/scripts/test_people.py
출력: $URBANSIM_WS/shots/people_f{30,60,90,120}.jpg
"""
from isaacsim import SimulationApp

# anim 확장은 반드시 앱 기동 시점에 켜야 한다. 기동 후 enable_extension 으로 켜면
# omni.graph OGN 노드 등록이 실패("Aborting Python node registration")하고
# 이후 그래프 실행에서 세그폴트가 난다.
ANIM_EXTS = ["omni.anim.graph.bundle", "omni.anim.retarget.bundle"]
_extra = []
for _e in ANIM_EXTS:
    _extra += ["--enable", _e]
app = SimulationApp({"headless": True, "width": 1280, "height": 720, "extra_args": _extra})

import math, os
import numpy as _np
import carb, carb.settings
import omni.usd, omni.timeline
from isaacsim.core.utils.extensions import enable_extension
from PIL import Image as _Image

enable_extension("isaacsim.sensors.camera")

from pxr import Usd, UsdGeom, UsdLux, UsdSkel, Gf
import AnimGraphSchema
import omni.anim.graph.core as ag
from isaacsim.sensors.camera import Camera

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("URBANSIM_WS", "/workspace/urban-sim")
PPL = f"{ROOT}/assets/usd/people"
AG_PATH = "/World/Characters/Biped_Setup/CharacterAnimation/AnimationGraph"

_cs = carb.settings.get_settings()
_cs.set("/rtx/post/aa/op", 3)
_cs.set("/rtx/post/histogram/enabled", False)

ctx = omni.usd.get_context(); ctx.new_stage(); stage = ctx.get_stage()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
world = UsdGeom.Xform.Define(stage, "/World"); stage.SetDefaultPrim(world.GetPrim())

UsdLux.DomeLight.Define(stage, "/World/Sky").CreateIntensityAttr(1200.0)
sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
sun.CreateIntensityAttr(3000.0); sun.CreateAngleAttr(0.53)
UsdGeom.Xformable(sun.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3d(-50.0, 15.0, 0.0))
gp = UsdGeom.Cube.Define(stage, "/World/ground")
UsdGeom.Xformable(gp).AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.5))
UsdGeom.Xformable(gp).AddScaleOp().Set(Gf.Vec3f(40, 40, 0.5))

# --- Biped_Setup: 애니메이션 그래프 공급원(자체 지오메트리는 숨김) ---
UsdGeom.Xform.Define(stage, "/World/Characters")
bs = stage.DefinePrim("/World/Characters/Biped_Setup", "Xform")
bs.GetReferences().AddReference(f"{PPL}/Characters/Biped_Setup.usd")

# 측면 시점이라 1명만 세운다(여러 명이면 서로 가림)
CHARS = ["F_Business_02"]
chars = []
for i, name in enumerate(CHARS):
    p = stage.DefinePrim(f"/World/Characters/ped{i}", "Xform")
    p.GetReferences().AddReference(f"{PPL}/Characters/{name}/{name}.usd")
    # 캐릭터 USD 루트에 이미 translate/rotate/scale 옵이 있으므로 CommonAPI로 덮어쓴다
    UsdGeom.XformCommonAPI(p).SetTranslate(Gf.Vec3d(0.0, -3.0, 0.0))
    sr = None
    for q in Usd.PrimRange(p):
        if q.IsA(UsdSkel.Root):
            sr = q; break
    if sr is None:
        print(f"[people] {name}: SkelRoot 없음", flush=True); continue
    api = AnimGraphSchema.AnimationGraphAPI.Apply(sr)
    api.GetAnimationGraphRel().SetTargets([AG_PATH])
    chars.append((name, str(sr.GetPath()), 0.0))
    print(f"[people] {name} SkelRoot={sr.GetPath()}", flush=True)

# Biped_Setup 은 그래프 공급원일 뿐이므로 통째로 화면에서 제외
UsdGeom.Imageable(bs).MakeInvisible()

cam = Camera(prim_path="/World/cam", resolution=(1280, 720))
cam.initialize()


def quat(yaw_deg):
    h = math.radians(yaw_deg) / 2.0
    return _np.array([math.cos(h), 0.0, 0.0, math.sin(h)])  # w,x,y,z


tl = omni.timeline.get_timeline_interface()
tl.play()
for _ in range(40):
    app.update()

# 측면 시점: 캐릭터는 y축을 따라 걷고 카메라는 +x 에서 -x 방향을 본다.
# 걷기 사이클(다리 교차)이 보여야 애니메이션 재생이 확인된다.
# 카메라 포즈는 반드시 timeline.play() 이후에 설정한다(재생 시 초기 포즈로 되돌아감).
cam.set_world_pose(_np.array([7.0, 0.0, 1.2]), quat(180.0), camera_axes="world")
for _ in range(10):
    app.update()
# 기본 초점거리 50mm(수평화각 23°)는 너무 좁다 — 18mm(약 60°)로 넓힌다
UsdGeom.Camera(stage.GetPrimAtPath("/World/cam")).GetFocalLengthAttr().Set(18.0)
for _ in range(5):
    app.update()
_p, _q = cam.get_world_pose()
print(f"[people] 카메라 실제 위치 = {tuple(round(float(v),2) for v in _p)}", flush=True)

SPEED_SET = 1.0   # Walk 상태의 blendWeight(0=대기, 1=MotionMatching 보행)
handles = []
for name, path, x0 in chars:
    c = ag.get_character(path)
    if c is None:
        print(f"[people] {name}: get_character 실패", flush=True); continue
    # MotionMatching 이 경로를 따라 캐릭터를 직접 이동시킨다 — 위치를 매 프레임
    # 덮어쓰면 보행 사이클이 생기지 않는다.
    c.set_variable("PathPoints", [carb.Float3(x0, -3.0, 0.0), carb.Float3(x0, 3.0, 0.0)])
    c.set_variable("Walk", SPEED_SET)
    c.set_variable("Action", "Walk")
    handles.append((name, c, x0))
    print(f"[people] {name}: 핸들 확보, Action=Walk, 경로 2점", flush=True)

os.makedirs(f"{BASE}/shots", exist_ok=True)
SHOTS = (40, 60, 80, 100, 120, 140)
for f in range(1, 161):
    app.update()
    if f % 20 == 0:
        for name, c, x0 in handles:
            pos = carb.Float3(0, 0, 0); rot = carb.Float4(0, 0, 0, 0)
            c.get_world_transform(pos, rot)
            print(f"[people] f{f:3d} {name} 위치=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})", flush=True)
    if f in SHOTS:
        arr = cam.get_rgba()
        if arr is not None and arr.size > 100:
            _Image.fromarray(arr[:, :, :3]).save(f"{BASE}/shots/people_f{f}.jpg", quality=92)
            print(f"[shot] people_f{f}", flush=True)

# 실제로 스키닝이 갱신되는지 수치로도 확인
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
for name, path, _x in chars:
    pos = carb.Float3(0, 0, 0); rot = carb.Float4(0, 0, 0, 0)
    c = ag.get_character(path)
    if c:
        c.get_world_transform(pos, rot)
        print(f"[people] {name} 최종 위치 = ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})", flush=True)

print("[people] DONE", flush=True)
app.close()
