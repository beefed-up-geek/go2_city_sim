#!/usr/bin/env python3
"""캐릭터 USD + 걷기 모션(SkelAnimation) 결합 → assets/usd/peds_anim/<name>.usd

SynBody 캐릭터(55 조인트)와 모션(70 조인트)은 SMPL-X 조인트 이름 체계를 공유하므로
UsdSkel이 이름으로 매핑한다. 개체마다 레이어 오프셋을 줘 걸음 위상이 겹치지 않게 한다.
"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from pxr import Usd, UsdGeom, UsdSkel, Sdf
import glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEDS = sorted(glob.glob(f"{ROOT}/assets/usd/peds/*/*.usd"))
MOTION = f"{ROOT}/assets/usd/motions/synbody_walking426/synbody_walking426.usd"
ANIM_PATH = "/World/SMPLX_neutral/root/pelvis/SMPLX_neutral_Scene"
OUT = f"{ROOT}/assets/usd/peds_anim"
os.makedirs(OUT, exist_ok=True)
assert os.path.isfile(MOTION), f"모션 없음: {MOTION}"

made = 0
for i, cf in enumerate(PEDS):
    name = os.path.splitext(os.path.basename(cf))[0] + "_walk"
    out = f"{OUT}/{name}.usd"
    if os.path.exists(out):
        made += 1; continue
    st = Usd.Stage.CreateNew(out)
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.y)      # 캐릭터 원본이 Y-up
    UsdGeom.SetStageMetersPerUnit(st, 1.0)
    st.SetTimeCodesPerSecond(30.0)
    st.SetStartTimeCode(0); st.SetEndTimeCode(28)
    root = UsdGeom.Xform.Define(st, "/Ped")
    st.SetDefaultPrim(root.GetPrim())
    ch = st.DefinePrim("/Ped/Char")
    ch.GetReferences().AddReference(cf)
    an = st.DefinePrim("/Ped/Anim")
    # 개체별 위상차: 레이어 오프셋으로 타임샘플을 밀어 걸음이 동기화되지 않게
    an.GetReferences().AddReference(MOTION, ANIM_PATH,
                                    Sdf.LayerOffset(offset=-(i * 7 % 29)))
    nb = 0
    for p in Usd.PrimRange(ch):
        if p.GetTypeName() in ("SkelRoot", "Skeleton"):
            UsdSkel.BindingAPI.Apply(p).CreateAnimationSourceRel().SetTargets([an.GetPath()])
            nb += 1
    st.GetRootLayer().Save()
    print(f"[anim] {name} 바인딩 {nb}개", flush=True)
    made += 1
print(f"[anim] COMPLETE {made}개", flush=True)
app.close()
