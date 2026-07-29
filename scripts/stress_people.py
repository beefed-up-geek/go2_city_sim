#!/usr/bin/env python3
"""보행자 렌더 크래시 재현용 최소 부하 씬 — Isaac Sim 버전 간 A/B 비교용.

텔레옵에서 관측된 크래시 조건은 "카메라가 움직이는 동안 애니메이션 보행자가
시야에 들어올 때"였다(보행자를 끄면 주행해도 멀쩡). 이 스크립트는 URBAN-SIM
스택 없이 그 조건만 재현한다:
  · NVIDIA People 캐릭터 N명 + AnimationGraph(MotionMatching) 보행
  · 카메라가 그 사이를 계속 이동하며 매 프레임 렌더 + GPU→CPU 읽기

실행:  /isaac-sim/python.sh go2_city_sim/scripts/stress_people.py [인원] [프레임]
결과:  살아남은 프레임 수와 CUDA 오류 발생 여부
"""
from isaacsim import SimulationApp

ANIM_EXTS = ["omni.anim.graph.bundle", "omni.anim.retarget.bundle"]
_extra = []
for _e in ANIM_EXTS:
    _extra += ["--enable", _e]
app = SimulationApp({"headless": True, "width": 1280, "height": 720, "extra_args": _extra})

import math, os, sys
import numpy as _np
import carb, carb.settings
import omni.usd, omni.timeline
from isaacsim.core.utils.extensions import enable_extension
enable_extension("isaacsim.sensors.camera")

from pxr import Usd, UsdGeom, UsdLux, UsdSkel, Gf
import AnimGraphSchema
import omni.anim.graph.core as ag
from isaacsim.sensors.camera import Camera

N_PED = int(sys.argv[1]) if len(sys.argv) > 1 else 17
N_FRAME = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
DO_READ = os.environ.get("STRESS_READ", "1") != "0"   # 버전 간 조건을 맞추기 위한 스위치
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PPL = f"{ROOT}/assets/usd/people"
AG_PATH = "/World/Characters/Biped_Setup/CharacterAnimation/AnimationGraph"

_cs = carb.settings.get_settings()
_cs.set("/rtx/post/aa/op", int(os.environ.get("STRESS_AA", "3")))
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
UsdGeom.Xformable(gp).AddScaleOp().Set(Gf.Vec3f(60, 60, 0.5))

UsdGeom.Xform.Define(stage, "/World/Characters")
bs = stage.DefinePrim("/World/Characters/Biped_Setup", "Xform")
bs.GetReferences().AddReference(f"{PPL}/Characters/Biped_Setup.usd")
UsdGeom.Imageable(bs).MakeInvisible()

import glob as _glob
chars = sorted(f"{d}/{os.path.basename(d)}.usd" for d in _glob.glob(f"{PPL}/Characters/*")
               if os.path.isdir(d) and os.path.basename(d) != "biped_demo"
               and not os.path.basename(d).startswith("original_"))
chars = [c for c in chars if os.path.isfile(c)]
print(f"[stress] 캐릭터 {len(chars)}종, 배치 {N_PED}명", flush=True)

R = 14.0
peds = []
for i in range(N_PED):
    a = 2 * math.pi * i / N_PED
    x0, y0 = R * math.cos(a), R * math.sin(a)
    pr = stage.DefinePrim(f"/World/Characters/ped{i}", "Xform")
    pr.GetReferences().AddReference(chars[i % len(chars)])
    yaw = math.degrees(a + math.pi)                       # 원 중심을 향해 걷는다
    for op in UsdGeom.Xformable(pr).GetOrderedXformOps():
        nm = op.GetOpName()
        try:
            if "translate" in nm: op.Set(Gf.Vec3d(x0, y0, 0.0))
            elif "rotate" in nm:  op.Set(Gf.Vec3d(0.0, 0.0, yaw))
        except Exception:
            if "translate" in nm: op.Set(Gf.Vec3f(x0, y0, 0.0))
            elif "rotate" in nm:  op.Set(Gf.Vec3f(0.0, 0.0, yaw))
    sr = next((q for q in Usd.PrimRange(pr) if q.IsA(UsdSkel.Root)), None)
    if sr is None: continue
    AnimGraphSchema.AnimationGraphAPI.Apply(sr).GetAnimationGraphRel().SetTargets([AG_PATH])
    peds.append((str(sr.GetPath()), x0, y0, a))

cam = Camera(prim_path="/World/cam", resolution=(1280, 720))
cam.initialize()
tl = omni.timeline.get_timeline_interface(); tl.play()
for _ in range(40): app.update()
UsdGeom.Camera(stage.GetPrimAtPath("/World/cam")).GetFocalLengthAttr().Set(18.0)
for _ in range(10): app.update()
_camx = UsdGeom.Xformable(stage.GetPrimAtPath("/World/cam"))


def place_cam(x, y, z, yaw_deg):
    """Camera.set_world_pose 가 버전에 따라 동작이 달라 xformOp 로 직접 쓴다."""
    ops = {o.GetOpName(): o for o in _camx.GetOrderedXformOps()}
    for nm, o in ops.items():
        if "translate" in nm:
            try: o.Set(Gf.Vec3d(x, y, z))
            except Exception: o.Set(Gf.Vec3f(x, y, z))
        elif "orient" in nm:
            h = math.radians(yaw_deg) / 2.0
            try: o.Set(Gf.Quatd(math.cos(h), 0.0, 0.0, math.sin(h)))
            except Exception: o.Set(Gf.Quatf(math.cos(h), 0.0, 0.0, math.sin(h)))
        elif "rotate" in nm:
            try: o.Set(Gf.Vec3d(90.0, 0.0, yaw_deg + 90.0))
            except Exception: o.Set(Gf.Vec3f(90.0, 0.0, yaw_deg + 90.0))


def quat(yaw_deg):
    h = math.radians(yaw_deg) / 2.0
    return _np.array([math.cos(h), 0.0, 0.0, math.sin(h)])


# 원 둘레를 오가는 경로를 주면 서로 스쳐 지나가며 계속 걷는다
handles = []
for path, x0, y0, a in peds:
    c = ag.get_character(path)
    if c is None: continue
    far = ((x0 * -1.0), (y0 * -1.0))
    c.set_variable("PathPoints", [carb.Float3(x0, y0, 0.0), carb.Float3(far[0], far[1], 0.0)])
    c.set_variable("Walk", 1.0)
    c.set_variable("Action", "Walk")
    handles.append((c, x0, y0, a))
print(f"[stress] 캐릭터 핸들 {len(handles)}개 확보 — {N_FRAME}프레임 시험 시작", flush=True)

ok = 0
n_readfail = 0
try:
    for f in range(1, N_FRAME + 1):
        # 카메라가 군중 사이를 계속 이동(텔레옵 주행과 같은 조건)
        t = f * 0.02
        cx, cy = 9.0 * math.cos(t * 0.35), 9.0 * math.sin(t * 0.35)
        place_cam(cx, cy, 1.4, math.degrees(t * 0.35) + 180.0)
        app.update()
        try:                                     # 매 프레임 GPU→CPU 읽기 (STRESS_READ=0 이면 생략)
            if not DO_READ: raise RuntimeError("skip")
            arr = cam.get_rgba()                 # (5.1 은 오버스캔 파라미터 문제로 실패할 수 있음)
            if arr is None or arr.size < 100: n_readfail += 1
        except Exception:
            n_readfail += 1
        # 보행자 위치 읽기 + 경로 갱신(텔레옵과 동일한 상호작용)
        if f % 2 == 0:
            for c, x0, y0, a in handles:
                pos = carb.Float3(0, 0, 0); rot = carb.Float4(0, 0, 0, 0)
                c.get_world_transform(pos, rot)
                if math.hypot(pos[0], pos[1]) > R - 1.0:      # 바깥에 닿으면 반대편으로
                    c.set_variable("PathPoints",
                                   [carb.Float3(pos[0], pos[1], 0.0),
                                    carb.Float3(-pos[0], -pos[1], 0.0)])
                    c.set_variable("Action", "Walk")
        ok = f
        if f % 250 == 0:
            print(f"[stress] {f}프레임 통과", flush=True)
except Exception as e:
    import traceback
    print(f"[stress] 예외 발생 f{ok}: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()

print(f"[stress] RESULT frames={ok}/{N_FRAME} 읽기실패={n_readfail}", flush=True)
app.close()
