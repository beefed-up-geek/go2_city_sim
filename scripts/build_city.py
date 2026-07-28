#!/usr/bin/env python3
"""정적 도시 조립: city_layout.json -> /workspace/urban-sim/city_static.usd + 검증 스크린샷"""
from isaacsim import SimulationApp
app = SimulationApp({"headless": True, "width": 1280, "height": 720})

import json, math, os, glob, hashlib
import numpy as _np
import carb.settings
import omni.usd, omni.timeline
from pxr import Usd, UsdGeom, UsdShade, UsdLux, UsdPhysics, Sdf, Gf
from PIL import Image as _Image

_cs = carb.settings.get_settings()
_cs.set("/rtx/post/aa/op", 3)
_cs.set("/rtx/ambientOcclusion/enabled", True)
_cs.set("/rtx/reflections/enabled", True)
_cs.set("/rtx/indirectDiffuse/enabled", True)
_cs.set("/rtx/post/tonemap/filmIso", 100)
_cs.set("/rtx/post/histogram/enabled", False)

ctx = omni.usd.get_context()
ctx.new_stage()
stage = ctx.get_stage()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
world = UsdGeom.Xform.Define(stage, "/World")
stage.SetDefaultPrim(world.GetPrim())

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # go2_city_sim 저장소 루트
BASE = os.environ.get("URBANSIM_WS", "/workspace/urban-sim")          # 외부 워크스페이스(NVIDIA 에셋·출력)
L = json.load(open(f"{ROOT}/assets/city_layout.json"))
EXT, RW, SWI, SWO = 65.0, 5.5, 5.5, 8.5      # v6: 차도 반폭 3.5→5.5
LANE, SHLD = 3.5, 2.0                        # 차로 / 갓길
RCL, BLK, PER, SH = 28.0, 21.5, 34.5, 3.0
CURB = 0.105   # v5.3: 보도 두께 1.5배 (0.07 → 0.105)
MAT = f"{BASE}/assets/materials"
NV = f"{BASE}/assets_nvidia/NVIDIA"
CUSTOM = f"{ROOT}/assets/usd"

# ---------------- materials ----------------
def mdl_mat(name, mdl_path, sub):
    mp = f"/World/Looks/{name}"
    mat = UsdShade.Material.Define(stage, mp)
    sh = UsdShade.Shader.Define(stage, mp + "/Shader")
    sh.CreateImplementationSourceAttr(UsdShade.Tokens.sourceAsset)
    sh.SetSourceAsset(mdl_path, "mdl")
    sh.SetSourceAssetSubIdentifier(sub, "mdl")
    mat.CreateSurfaceOutput("mdl").ConnectToSource(sh.ConnectableAPI(), "out")
    return mat

def pbr_mat(name, rgb, rough=0.9):
    mp = f"/World/Looks/{name}"
    mat = UsdShade.Material.Define(stage, mp)
    sh = UsdShade.Shader.Define(stage, mp + "/Shader")
    sh.CreateImplementationSourceAttr(UsdShade.Tokens.sourceAsset)
    sh.SetSourceAsset("OmniPBR.mdl", "mdl")
    sh.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
    sh.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    sh.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(rough)
    mat.CreateSurfaceOutput("mdl").ConnectToSource(sh.ConnectableAPI(), "out")
    return mat

m_asph = mdl_mat("asphalt", f"{MAT}/Ground/Asphalt_Fine.mdl", "Asphalt_Fine")
m_pave = mdl_mat("paving", f"{MAT}/Ground/Paving_Stones.mdl", "Paving_Stones")
m_cobb = mdl_mat("cobble", f"{MAT}/Ground/Small_Cobblestone.mdl", "Small_Cobblestone")
m_gran = mdl_mat("granite", f"{MAT}/Ground/Large_Granite_Paving.mdl", "Large_Granite_Paving")
m_mulch = mdl_mat("mulch", f"{MAT}/Ground/Mulch.mdl", "Mulch")
m_grass = pbr_mat("grass", (0.16, 0.27, 0.11), 1.0)
m_white = pbr_mat("white", (0.85, 0.85, 0.82), 0.75)
m_yellow = pbr_mat("yellow", (0.85, 0.65, 0.10), 0.8)
m_metal = pbr_mat("metal", (0.35, 0.36, 0.38), 0.45)
m_kgrn = pbr_mat("kr_green", (0.10, 0.42, 0.20), 0.88)   # 한국 이면도로 보행자 통행로 도색

# ---------------- box mesh (UV 포함) ----------------
def box_mesh(path, cx, cy, w, d, z0, z1, mat, yaw=0.0, pitch=0.0, uv=0.5):
    m = UsdGeom.Mesh.Define(stage, path)
    hx, hy = w / 2, d / 2
    pts = [(-hx,-hy,z0),(hx,-hy,z0),(hx,hy,z0),(-hx,hy,z0),(-hx,-hy,z1),(hx,-hy,z1),(hx,hy,z1),(-hx,hy,z1)]
    m.CreatePointsAttr([Gf.Vec3f(*p) for p in pts])
    m.CreateFaceVertexCountsAttr([4]*6)
    m.CreateFaceVertexIndicesAttr([4,5,6,7, 0,3,2,1, 0,1,5,4, 2,3,7,6, 1,2,6,5, 3,0,4,7])
    st = []
    top = [(cx-hx,cy-hy),(cx+hx,cy-hy),(cx+hx,cy+hy),(cx-hx,cy+hy)]
    st += [(u*uv, v*uv) for (u,v) in top]                       # top
    st += [(u*uv, v*uv) for (u,v) in [top[0],top[3],top[2],top[1]]]  # bottom
    for _ in range(4): st += [(0,0),(uv,0),(uv,0.1),(0,0.1)]    # sides
    pv = UsdGeom.PrimvarsAPI(m).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    pv.Set([Gf.Vec2f(*s) for s in st])
    m.CreateExtentAttr([Gf.Vec3f(-hx,-hy,z0), Gf.Vec3f(hx,hy,z1)])
    xf = UsdGeom.Xformable(m)
    xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, 0))
    if yaw: xf.AddRotateZOp().Set(yaw)
    if pitch: xf.AddRotateYOp().Set(pitch)
    UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(mat)
    UsdPhysics.CollisionAPI.Apply(m.GetPrim())
    return m

def rect_slab(path, x1, y1, x2, y2, z0, z1, mat, uv=0.5):
    return box_mesh(path, (x1+x2)/2, (y1+y2)/2, abs(x2-x1), abs(y2-y1), z0, z1, mat, uv=uv)

G = "/World/Ground"
GR = L["ground"]
GEXT = 88.0
rect_slab(G+"/grass", -GEXT, -GEXT, GEXT, GEXT, -0.30, -0.002, m_grass, uv=0.25)
for i, r in enumerate(GR["road"]): rect_slab(f"{G}/road{i}", *r, -0.30, 0.0, m_asph, uv=0.35)
# v5.3 커브램프(보도 절개형): 횡단보도 양끝에서 보도를 절개(본선 4.0m + 플레어 1.2m×2, 런 1.5m)
RAMP_L, RAMP_F = 1.5, 1.2
_CUTS = []
for _cw in L["crosswalks"]:
    _ccx, _ccy = _cw["center"]; _hw = _cw["depth"]/2 + RAMP_F
    for _sgn in (1, -1):
        if _cw["axis"] == "v":
            _e = _ccx + _sgn*RW
            _CUTS.append((min(_e, _e+_sgn*RAMP_L), _ccy-_hw, max(_e, _e+_sgn*RAMP_L), _ccy+_hw))
        else:
            _e = _ccy + _sgn*RW
            _CUTS.append((_ccx-_hw, min(_e, _e+_sgn*RAMP_L), _ccx+_hw, max(_e, _e+_sgn*RAMP_L)))
SH_BAND = 3.0                     # 혼용길 끝단 연석 절개 폭(코스 진출입부)
for _sh in L.get("shared", []):
    if _sh["axis"] != "v": continue
    for _ey in (_sh["lo"] + 2.0, _sh["hi"] - 2.0):
        _cy2 = _sh["hi"] - SH_BAND/2 if _ey > 0 else _sh["lo"] + SH_BAND/2
        for _sx in (-1, 1):
            _e2 = _sx * _sh["w"]
            _CUTS.append((min(_e2, _e2 + _sx*RAMP_L), _cy2 - SH_BAND/2,
                          max(_e2, _e2 + _sx*RAMP_L), _cy2 + SH_BAND/2))
def _sub_rect(rects, cut):
    out = []
    cx1, cy1, cx2, cy2 = cut
    for (x1, y1, x2, y2) in rects:
        if cx1 >= x2-1e-6 or cx2 <= x1+1e-6 or cy1 >= y2-1e-6 or cy2 <= y1+1e-6:
            out.append((x1, y1, x2, y2)); continue
        iy1, iy2 = max(y1, cy1), min(y2, cy2)
        if iy1 > y1: out.append((x1, y1, x2, iy1))
        if iy2 < y2: out.append((x1, iy2, x2, y2))
        if max(x1, cx1) > x1: out.append((x1, iy1, max(x1, cx1), iy2))
        if min(x2, cx2) < x2: out.append((min(x2, cx2), iy1, x2, iy2))
    return out
def _lay(nm, rects, mat, uv):
    rs = [tuple(r) for r in rects]
    for _c in _CUTS: rs = _sub_rect(rs, _c)
    for i, r in enumerate(rs):
        if r[2]-r[0] > 0.02 and r[3]-r[1] > 0.02:
            rect_slab(f"{G}/{nm}{i}", *r, -0.05, CURB, mat, uv=uv)
_lay("block", GR["block"], m_asph, 0.35)   # v7.1: 블록 내부 = 차도와 같은 아스팔트(노상 주차장)
_lay("fill", GR["fill"], m_gran, 0.3)
_lay("walk", GR["walk"], m_pave, 0.8)
_lay("narrow", GR["narrow"], m_pave, 0.8)
_SHR = L.get("shared", [])
def _is_shared(r):
    for sh in _SHR:
        if sh["axis"] == "v" and abs((r[0]+r[2])/2 - sh["c"]) < 0.6 and abs(abs(r[2]-r[0]) - 2*sh["w"]) < 0.6:
            return sh
    return None
for i, r in enumerate(GR["brick"]):
    sh = _is_shared(r)
    if not sh:
        rect_slab(f"{G}/brick{i}", *r, -0.05, CURB, m_cobb, uv=0.8); continue
    # 한국식 이면도로: 연석 없는 아스팔트 노면 + 양측 가장자리 백색 실선 + 실선 바깥 녹색 보행 통행로
    # 골목(v7.2): 노면·표시 모두 일반 차도와 동일 — 아스팔트 + 황색 중앙선 + 백색 가장자리선
    rect_slab(f"{G}/shared{i}", *r, -0.30, 0.0, m_asph, uv=0.35)
    _sx1, _sy1, _sx2, _sy2 = r
    _scx = (_sx1 + _sx2) / 2
    for _ei2, _se in enumerate((_sx1 + 0.6, _sx2 - 0.6)):       # 가장자리 백색 실선
        rect_slab(f"{G}/shedge{i}_{_ei2}", _se-0.075, _sy1, _se+0.075, _sy2, 0.0, 0.010, m_white, uv=0)
    _t2 = _sy1 + 1.0                                           # 황색 중앙선(점선)
    _k2 = 0
    while _t2 < _sy2 - 2.0:
        rect_slab(f"{G}/shcl{i}_{_k2}", _scx-0.07, _t2, _scx+0.07, _t2+2.0, 0.0, 0.008, m_yellow, uv=0)
        _t2 += 4.0; _k2 += 1

# 횡단보도 + 정지선 + 램프
Z = "/World/Marks"
for ci, cw in enumerate(L["crosswalks"]):
    cx, cy = cw["center"]; dp = cw["depth"]
    if cw["axis"] == "v":
        x = cx - RW + 0.35; j = 0
        while x < cx + RW - 0.3:
            rect_slab(f"{Z}/cw{ci}_{j}", x, cy-dp/2, x+0.7, cy+dp/2, 0.0, 0.012, m_white, uv=0); x += 1.4; j += 1
    else:
        y = cy - RW + 0.35; j = 0
        while y < cy + RW - 0.3:
            rect_slab(f"{Z}/cw{ci}_{j}", cx-dp/2, y, cx+dp/2, y+0.7, 0.0, 0.012, m_white, uv=0); y += 1.4; j += 1
# v5.3 커브램프 본선(피치 box) + 플레어(닫힌 삼각 프리즘 2매×양측, 법선 외향 와인딩)
def tri_prism(path, pts3, mat, z0=-0.05, uv=0.8):
    (ax_, ay_, az_), (bx_, by_, bz_), (cx_, cy_, cz_) = pts3
    if (bx_-ax_)*(cy_-ay_) - (by_-ay_)*(cx_-ax_) < 0:   # 상면 CCW(위에서) 보장
        (bx_, by_, bz_), (cx_, cy_, cz_) = (cx_, cy_, cz_), (bx_, by_, bz_)
    top = [(ax_, ay_, az_), (bx_, by_, bz_), (cx_, cy_, cz_)]
    m = UsdGeom.Mesh.Define(stage, path)
    pts = [Gf.Vec3f(x_, y_, z0) for (x_, y_, _z) in top] + [Gf.Vec3f(*p) for p in top]
    m.CreatePointsAttr(pts)                     # 0..2 바닥, 3..5 상면
    m.CreateFaceVertexCountsAttr([3, 3, 4, 4, 4])
    m.CreateFaceVertexIndicesAttr([3,4,5, 0,2,1, 0,1,4,3, 1,2,5,4, 2,0,3,5])
    st = [(p[0]*uv, p[1]*uv) for p in top]
    st += [(top[0][0]*uv, top[0][1]*uv), (top[2][0]*uv, top[2][1]*uv), (top[1][0]*uv, top[1][1]*uv)]
    st += [(0,0),(uv,0),(uv,0.1),(0,0.1)]*3
    pv = UsdGeom.PrimvarsAPI(m).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    pv.Set([Gf.Vec2f(*x) for x in st])
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [float(p[2]) for p in pts]
    m.CreateExtentAttr([Gf.Vec3f(min(xs), min(ys), min(zs)), Gf.Vec3f(max(xs), max(ys), max(zs))])
    UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(mat)
    UsdPhysics.CollisionAPI.Apply(m.GetPrim())

_ZL = 0.012                       # 연석선 접속 높이(횡단보도 도색면과 flush)
_SLP = (CURB - _ZL) / RAMP_L      # 본선 경사 (Δh 93mm / 1.5m = 6.2%)
for ci, cw in enumerate(L["crosswalks"]):
    ccx, ccy = cw["center"]; hw = cw["depth"]/2
    for si, sgn in enumerate((1, -1)):
        L1 = RAMP_L + 0.03        # 보도 밑으로 3cm 랩 (미세 틈 방지)
        if cw["axis"] == "v":
            e = ccx + sgn*RW
            rcx, rcy = e + sgn*L1/2, ccy
            dwn = (-sgn, 0.0)
        else:
            e = ccy + sgn*RW
            rcx, rcy = ccx, e + sgn*L1/2
            dwn = (0.0, -sgn)
        box_mesh(f"{Z}/cut{ci}_{si}", rcx, rcy, L1, cw["depth"], -0.20, _ZL + _SLP*L1/2, m_pave,
                 yaw=math.degrees(math.atan2(dwn[1], dwn[0])), pitch=math.degrees(math.atan(_SLP)), uv=0.8)
        for fi, s2 in enumerate((1, -1)):
            if cw["axis"] == "v":
                A = (e, ccy + s2*hw, _ZL)
                B = (e, ccy + s2*(hw+RAMP_F), CURB)
                C = (e + sgn*RAMP_L, ccy + s2*hw, CURB)
                D = (e + sgn*RAMP_L, ccy + s2*(hw+RAMP_F), CURB)
            else:
                A = (ccx + s2*hw, e, _ZL)
                B = (ccx + s2*(hw+RAMP_F), e, CURB)
                C = (ccx + s2*hw, e + sgn*RAMP_L, CURB)
                D = (ccx + s2*(hw+RAMP_F), e + sgn*RAMP_L, CURB)
            tri_prism(f"{Z}/cutf{ci}_{si}_{fi}a", (A, B, C), m_pave)
            tri_prism(f"{Z}/cutf{ci}_{si}_{fi}b", (B, D, C), m_pave)

for ri, rp in enumerate(L["ramps"]):  # 잔여 웨지 램프(차량 진입·공사 우회) — crosswalk형은 v5.3 절개형으로 대체
    if rp.get("why") in ("crosswalk", "lane_car"):
        continue
    x, y = rp["pos"]; dx_, dy_ = rp["down"]
    ls = abs(dx_)*rp["w"] + abs(dy_)*rp["d"]
    wa = abs(dy_)*rp["w"] + abs(dx_)*rp["d"]
    yaw_ = math.degrees(math.atan2(dy_, dx_))
    pitch_ = math.degrees(math.atan((CURB + 0.002)/ls))
    box_mesh(f"{Z}/ramp{ri}", x, y, ls, wa, -0.20, 0.006 + (CURB - 0.004)/2, m_pave, yaw=yaw_, pitch=pitch_, uv=0.8)
_ZS = 0.004
_SLPS = (CURB - _ZS) / RAMP_L
for _si, _sh in enumerate(L.get("shared", [])):
    if _sh["axis"] != "v": continue
    for _pi, _cy2 in enumerate((_sh["hi"] - SH_BAND/2, _sh["lo"] + SH_BAND/2)):
        for _sx in (-1, 1):
            _e2 = _sx * _sh["w"]; _L1 = RAMP_L + 0.03
            box_mesh(f"{Z}/shcut{_si}_{_pi}_{'p' if _sx>0 else 'm'}",
                     _e2 + _sx*_L1/2, _cy2, _L1, SH_BAND, -0.20, _ZS + _SLPS*_L1/2, m_pave,
                     yaw=0.0 if _sx < 0 else 180.0, pitch=math.degrees(math.atan(_SLPS)), uv=0.8)
ARMV = {"N": (0,1), "S": (0,-1), "E": (1,0), "W": (-1,0)}
for ci, cw in enumerate(L["crosswalks"]):  # 정지선(접근차로 반폭)
    ix, iy = cw["inter"]; dx, dy = ARMV[cw["arm"]]
    cx0, cy0 = cw["center"]; off = cw["depth"]/2 + 0.1     # 횡단보도 바깥(접근 차로 쪽)
    if dy:
        x1, x2 = (ix-RW+0.2, ix-0.15) if dy > 0 else (ix+0.15, ix+RW-0.2)
        rect_slab(f"{Z}/stop{ci}", x1, cy0+dy*off, x2, cy0+dy*(off+0.45), 0.0, 0.012, m_white, uv=0)
    else:
        y1, y2 = (iy+0.15, iy+RW-0.2) if dx > 0 else (iy-RW+0.2, iy-0.15)
        rect_slab(f"{Z}/stop{ci}", cx0+dx*off, y1, cx0+dx*(off+0.45), y2, 0.0, 0.012, m_white, uv=0)
di = 0
for r in L["roads"]:  # 중앙선 점선(황색), 교차로/횡단보도 회피
    lo, hi = r["lo"], r["hi"]; t = lo + 2.0
    while t < hi - 2.0:
        mid = t + 1.0
        if not any(abs(mid - (iy if r["axis"]=="v" else ix)) < 13.5 for (ix, iy) in L["meta"]["intersections"]):
            if r["axis"] == "v": rect_slab(f"{Z}/cl{di}", r["c"]-0.07, t, r["c"]+0.07, t+2.0, 0.0, 0.008, m_yellow, uv=0)
            else: rect_slab(f"{Z}/cl{di}", t, r["c"]-0.07, t+2.0, r["c"]+0.07, 0.0, 0.008, m_yellow, uv=0)
            di += 1
        t += 4.0
# 가장자리 차선(백색 실선): 차로와 갓길의 경계
_VC = [r["c"] for r in L["roads"] if r["axis"] == "v"]
_HC = [r["c"] for r in L["roads"] if r["axis"] == "h"]
_SHW = [(sh["c"], sh["w"]) for sh in L.get("shared", [])]
def _gaps_for(road):
    g = []
    cross = _HC if road["axis"] == "v" else _VC
    for c2 in cross: g.append((c2 - RW - 0.4, c2 + RW + 0.4))
    for cw in L["crosswalks"]:
        if cw["axis"] != road["axis"]: continue
        cx0, cy0 = cw["center"]
        along, perp = (cy0, cx0) if road["axis"] == "v" else (cx0, cy0)
        if abs(perp - road["c"]) > RW: continue
        g.append((along - cw["depth"]/2 - 0.3, along + cw["depth"]/2 + 0.3))
    if road["axis"] == "h":                      # 혼용길 진입 개구부
        for sc, sw in _SHW: g.append((sc - sw - 0.6, sc + sw + 0.6))
    return sorted(g)
_ei = 0
for r in L["roads"]:
    for gp in _gaps_for(r):
        pass
    segs, t = [], r["lo"]
    for a, b in _gaps_for(r):
        if b <= r["lo"] or a >= r["hi"]: continue
        if a > t: segs.append((t, min(a, r["hi"])))
        t = max(t, b)
    if t < r["hi"]: segs.append((t, r["hi"]))
    for a, b in segs:
        if b - a < 0.8: continue
        for sd in (-1, 1):
            e = r["c"] + sd * LANE
            if r["axis"] == "v": rect_slab(f"{Z}/edge{_ei}", e-0.075, a, e+0.075, b, 0.0, 0.010, m_white, uv=0)
            else:                rect_slab(f"{Z}/edge{_ei}", a, e-0.075, b, e+0.075, 0.0, 0.010, m_white, uv=0)
            _ei += 1
print(f"[city] ground+marks done ({di} dashes, {_ei} edge lines)", flush=True)

# ---------------- 프로토타입 로더 ----------------
PROTOS = UsdGeom.Xform.Define(stage, "/World/_protos")   # Scope는 트랜스폼 불가 → 원본을 치우려면 Xform
PROTO_FP = {}   # name -> (평면 x, 평면 y, 높이) 스케일 적용 후
def make_proto(name, asset, target_h=None, target_wd=None, target_w_min=None):
    root = UsdGeom.Xform.Define(stage, f"/World/_protos/{name}")
    fix = UsdGeom.Xform.Define(stage, f"/World/_protos/{name}/fix")
    g = UsdGeom.Xform.Define(stage, f"/World/_protos/{name}/fix/g")
    g.GetPrim().GetReferences().AddReference(asset)
    try:
        lay = Usd.Stage.Open(asset)
        up = UsdGeom.GetStageUpAxis(lay)
        mpu = UsdGeom.GetStageMetersPerUnit(lay) or 1.0
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render", "proxy"])
        bb = cache.ComputeWorldBound(lay.GetPseudoRoot()).ComputeAlignedRange()
        mn = [bb.GetMin()[i] for i in range(3)]; mx = [bb.GetMax()[i] for i in range(3)]
        size = [(mx[i]-mn[i]) * mpu for i in range(3)]
    except Exception as e:
        print(f"[proto] {name} bbox fail {e}", flush=True)
        up, mpu, size, mn, mx = "Z", 1.0, [1,1,1], [0,0,0], [1,1,1]
    xf = UsdGeom.Xformable(fix)
    h = size[1] if up == "Y" else size[2]
    w = max(size[0], size[2] if up == "Y" else size[1])
    s = 1.0
    if target_h and h > 1e-4: s = target_h / h
    if target_wd and w > 1e-4: s = target_wd / w
    wmin = min(size[0], size[2] if up == "Y" else size[1])
    if target_w_min and wmin > 1e-4: s = target_w_min / wmin
    k = mpu * s
    # 피벗 보정: 회전(Y-up→Z-up) 후 기준으로 xy는 bbox 중심, z는 바닥이 원점에 오도록
    if up == "Y":
        cx_, cy_, z0 = (mn[0]+mx[0])/2, -(mn[2]+mx[2])/2, mn[1]
    else:
        cx_, cy_, z0 = (mn[0]+mx[0])/2, (mn[1]+mx[1])/2, mn[2]
    xf.AddTranslateOp().Set(Gf.Vec3d(-cx_*k, -cy_*k, -z0*k))
    xf.AddRotateXOp().Set(90.0 if up == "Y" else 0.0)
    xf.AddScaleOp().Set(Gf.Vec3f(k))
    PROTO_FP[name] = (size[0]*s, (size[2] if up == "Y" else size[1])*s, h*s)
    print(f"[proto] {name} up={up} mpu={mpu:.3f} size=({size[0]:.2f},{size[1]:.2f},{size[2]:.2f}) s={s:.3f} off=({cx_*k:.2f},{cy_*k:.2f})", flush=True)
    return name

def place(path, proto, x, y, z, yaw=0.0, scale=1.0, instanceable=True):
    xf = UsdGeom.Xform.Define(stage, path)
    p = xf.GetPrim()
    p.GetReferences().AddInternalReference(Sdf.Path(f"/World/_protos/{proto}"))
    xf.AddTranslateOp().Set(Gf.Vec3d(x, y, z))
    xf.AddRotateZOp().Set(yaw)
    if scale != 1.0: xf.AddScaleOp().Set(Gf.Vec3f(scale))
    if instanceable: p.SetInstanceable(True)
    return p

def h(s):  # 결정적 해시 0..1
    return int(hashlib.md5(s.encode()).hexdigest()[:6], 16) / 0xFFFFFF

# 나무·가로등·볼라드
SP_MAP = {"Black_Oak": "Honey_Locust"}  # 참나무: 근접 LOD 저품질 -> 교체
for sp in ["Japanese_Cherry", "Honey_Locust", "American_Beech", "Japanese_Maple", "Gray_Birch"]:
    make_proto(f"tree_{sp}", f"{NV}/Assets/Vegetation/Trees/{sp}.usd")
lampf = sorted(glob.glob(f"{NV}/dsready_content/nv_content/common_assets/props_poles/gen_street_lamp_01/*.usd"))
bolf = sorted(glob.glob(f"{NV}/dsready_content/nv_content/common_assets/props_traffic/bollard_01/*.usd"))
barrf = sorted(glob.glob(f"{NV}/dsready_content/nv_content/common_assets/props_traffic/barricade_01/*.usd"))
drumf = sorted(glob.glob(f"{NV}/dsready_content/nv_content/common_assets/props_traffic/barrel_01/*.usd"))
make_proto("lamp", lampf[0]); make_proto("bollard", bolf[0])
make_proto("barricade", barrf[0]); make_proto("drum", drumf[0])
make_proto("veh_head", f"{NV}/dsready_content/nv_content/korea/country_assets/traffic_lights_tmp/assemblies/1001001/1001001.usda")
# 보행등 v4: asa21 실사 모델 + 상태별 검은 커버 오버레이 (red/grn/cnt/off visibility 토글)
# 모델은 모든 표시(적사람/녹사람/카운트다운)가 항상 점등 텍스처 → 비활성 표시만 검은 커버로 가림
_ASA = f"{CUSTOM}/ped_light_asa21/ped_light_asa21.usd"
_ast = Usd.Stage.Open(_ASA)
_ac = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
_ar = _ac.ComputeWorldBound(_ast.GetPseudoRoot()).ComputeAlignedRange()
_amn, _amx = _ar.GetMin(), _ar.GetMax()
_asc = 3.0 / float(_amx[1] - _amn[1])          # 전고 3.0m (native Y-up)
_acx = (float(_amn[0]) + float(_amx[0])) / 2 * _asc
_acy = -(float(_amn[2]) + float(_amx[2])) / 2 * _asc
_ped2 = UsdGeom.Xform.Define(stage, "/World/_protos/ped_sig")
_am = UsdGeom.Xform.Define(stage, "/World/_protos/ped_sig/m")
_ag = UsdGeom.Xform.Define(stage, "/World/_protos/ped_sig/m/g")
_ag.GetPrim().GetReferences().AddReference(_ASA)
_axf = UsdGeom.Xformable(_am)
_axf.AddTranslateOp().Set(Gf.Vec3d(-_acx, -_acy, -float(_amn[1]) * _asc))
_axf.AddRotateXOp().Set(90.0)
_axf.AddScaleOp().Set(Gf.Vec3f(_asc))
m_cov = pbr_mat("ped_cover", (0.02, 0.02, 0.025), 0.4)
def _pcov(path, cx, cz, w, hgt):
    c2 = UsdGeom.Cube.Define(stage, path)
    xf2 = UsdGeom.Xformable(c2)
    xf2.AddTranslateOp().Set(Gf.Vec3d(cx, -0.115, cz))
    xf2.AddScaleOp().Set(Gf.Vec3f(w/2, 0.006, hgt/2))
    UsdShade.MaterialBindingAPI.Apply(c2.GetPrim()).Bind(m_cov)
# 표시 창 좌표 (격리 씬 눈금 캘리브레이션): red/grn=사람 창, cnt=카운트다운 열
_CW = {"red": (0.05, 2.11, 0.20, 0.28), "grn": (0.05, 1.84, 0.18, 0.26), "cnt": (0.255, 1.98, 0.12, 0.60)}
# 상태 그룹 = 그 상태에서 가려야 할 표시들의 커버 묶음 (이름은 텔레옵 토글과 동일)
_GROUPS = {"red": ("grn", "cnt"), "grn": ("red", "cnt"), "cnt": ("red",), "off": ("red", "grn", "cnt")}
for _snm, _hides in _GROUPS.items():
    UsdGeom.Xform.Define(stage, f"/World/_protos/ped_sig/{_snm}")
    for _wn in _hides:
        _pcov(f"/World/_protos/ped_sig/{_snm}/c_{_wn}", *_CW[_wn])
    if _snm != "red":
        UsdGeom.Imageable(stage.GetPrimAtPath(f"/World/_protos/ped_sig/{_snm}")).MakeInvisible()
PED2_YAW = 90.0
print("[proto] ped_sig = asa21 + cover overlay", flush=True)

for i, t in enumerate(L["trees"]):
    x, y = t["pos"]
    sp = SP_MAP.get(t["species"], t["species"])
    place(f"/World/Trees/t{i}", f"tree_{sp}", x, y, CURB, yaw=h(f"t{i}")*360, scale=0.85+0.4*h(f"ts{i}"))
    box_mesh(f"/World/Trees/soil{i}", x, y, 1.4, 1.4, -0.02, CURB+0.002, m_mulch, uv=1.0)
for i, l in enumerate(L["lamps"]):
    x, y = l["pos"]; toward = -90 if x < -25 or (abs(x) < 25 and False) else 90
    place(f"/World/Lamps/l{i}", "lamp", x, y, CURB, yaw=(90 if x > 0 or abs(y) > 25 else -90))
for i, b in enumerate(L["bollards"]):
    place(f"/World/Bollards/b{i}", "bollard", b["pos"][0], b["pos"][1], CURB)
cons = L["construction"][0]["rect"]
ccx, ccy = (cons[0]+cons[2])/2, (cons[1]+cons[3])/2
for i, yy in enumerate([cons[1]+0.6, ccy, cons[3]-0.6]):
    place(f"/World/Cons/bar{i}", "barricade", ccx, yy, CURB, yaw=90, instanceable=False)
place("/World/Cons/drum0", "drum", ccx, cons[1]-0.2, CURB, instanceable=False)   # 보도 공사구역 양끝 (차로 밖)
place("/World/Cons/drum1", "drum", ccx, cons[3]+0.2, CURB, instanceable=False)
print("[city] props done", flush=True)

# ---------------- 신호등 ----------------
def cyl(path, r, h_, x, y, z, rotY=0.0, mat=m_metal):
    c = UsdGeom.Cylinder.Define(stage, path)
    c.CreateRadiusAttr(r); c.CreateHeightAttr(h_); c.CreateAxisAttr("Z")
    c.CreateExtentAttr([Gf.Vec3f(-r,-r,-h_/2), Gf.Vec3f(r,r,h_/2)])
    xf = UsdGeom.Xformable(c)
    xf.AddTranslateOp().Set(Gf.Vec3d(x, y, z))
    if rotY: xf.AddRotateYOp().Set(rotY)
    UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(mat)
    return c

CORNER = {(1,1):((-1,0),(0,-1)), (-1,-1):((1,0),(0,1)), (1,-1):((0,1),(-1,0)), (-1,1):((0,-1),(1,0))}
for i, v in enumerate(L["veh_lights"]):
    x, y = v["pos"]; ix, iy = v["inter"]
    sx, sy = (1 if x > ix else -1), (1 if y > iy else -1)
    arm, face = CORNER[(sx, sy)]
    root = f"/World/Signals/v{i}"
    UsdGeom.Xform.Define(stage, root)
    cyl(root+"/pole", 0.055, 3.5, x, y, 1.75)
    ax, ay = arm
    alen = 5.6
    acx, acy = x + ax*alen/2, y + ay*alen/2
    a = cyl(root+"/arm", 0.04, alen, acx, acy, 3.42)
    xfa = UsdGeom.Xformable(a); xfa.ClearXformOpOrder()
    xfa.AddTranslateOp().Set(Gf.Vec3d(acx, acy, 3.42))
    xfa.AddRotateZOp().Set(math.degrees(math.atan2(ay, ax)))
    xfa.AddRotateYOp().Set(90)
    hx, hy = x + ax*(alen-0.6), y + ay*(alen-0.6)
    yaw = math.degrees(math.atan2(face[1], face[0]))
    head = place(root+"/head", "veh_head", hx, hy, 3.05, yaw=yaw, instanceable=False)
    ns = (face == (0,-1) or face == (0,1))
    ns_serves = (arm[0] != 0)  # 팔이 x방향 -> v도로 위 -> 남북 통행 담당
    active = "red" if ns_serves else "green"
    for bulb, nm in [("combined_solid_red_0","red"),("combined_solid_yellow_1","yellow"),("combined_solid_green_2","green")]:
        bp = None
        for cand in (f"{root}/head/fix/g/RootNode/{bulb}", f"{root}/head/fix/g/{bulb}"):
            q = stage.GetPrimAtPath(cand)
            if q and q.IsValid(): bp = q; break
        if bp:
            UsdGeom.Imageable(bp).GetVisibilityAttr().Set("inherited" if nm == active else "invisible")
        else:
            print(f"[sig] bulb missing {root} {bulb}", flush=True)
PED_YAW_OFF = PED2_YAW if 'PED2_YAW' in dir() else 90.0
for i, p in enumerate(L["ped_lights"]):
    x, y = p["pos"]
    place(f"/World/Signals/p{i}", "ped_sig", x, y, CURB, yaw=p["face"] + PED_YAW_OFF, instanceable=False)
print("[city] signals done", flush=True)

# ---------------- 건물·가구 ----------------
protos_b = {}
_BLD_FP = []          # 배치된 건물 footprint(여유 0.35 m 포함) — 주차구획 회피용
for i, b in enumerate(L["buildings"]):  # 실측 native 크기 그대로
    asset = b["asset"]
    _key = (asset, b.get("h"))            # 높이 지정이 다르면 별도 프로토
    if _key not in protos_b:
        _tag = f"bld_{asset[9:17]}" + (f"_h{int(b['h'])}" if b.get("h") else "")
        protos_b[_key] = make_proto(_tag, f"{CUSTOM}/objects/{asset}/{asset}.usd", target_h=b.get("h"))
        # GLB 폭주 메시 가드(프로토 단계 → 전 인스턴스 전파): 60 m 넘는 메시는 깨진 지오메트리
        _bc9 = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render", "proxy"])
        for _pr9 in Usd.PrimRange(stage.GetPrimAtPath(f"/World/_protos/{protos_b[_key]}")):
            if not _pr9.IsA(UsdGeom.Mesh): continue
            _r9 = _bc9.ComputeWorldBound(_pr9).ComputeAlignedRange()
            if _r9.IsEmpty(): continue
            _mn9, _mx9 = _r9.GetMin(), _r9.GetMax()
            _ext9 = max(_mx9[0]-_mn9[0], _mx9[1]-_mn9[1], _mx9[2]-_mn9[2])
            if _ext9 > 60.0:
                UsdGeom.Imageable(_pr9).MakeInvisible()
                UsdPhysics.CollisionAPI.Apply(_pr9).CreateCollisionEnabledAttr(False)
                print(f"[guard] runaway mesh hidden in {protos_b[asset]}: {_pr9.GetName()} {_ext9:.0f}m", flush=True)
    place(f"/World/Buildings/B{i}", protos_b[_key], b["pos"][0], b["pos"][1], CURB, yaw=b["rot"], instanceable=False)
    _bf = PROTO_FP.get(protos_b[_key])
    if _bf:
        _fw, _fd = (_bf[1], _bf[0]) if b["rot"] % 180 else (_bf[0], _bf[1])
        _BLD_FP.append((b["pos"][0]-_fw/2-0.35, b["pos"][1]-_fd/2-0.35,
                        b["pos"][0]+_fw/2+0.35, b["pos"][1]+_fd/2+0.35))
FUR = dict(bench=("Bench_", 0.9), trash_bin=("Trash_bin_", 1.0), bus_stop=("busstation_", 2.7),
           phone_booth=("Telephone_booth_", 2.4), vending=("Vending_machine_", 1.8))   # mailbox 제거(v5.4)
FUR_PICK = {  # 저장소에는 실제 사용 폴더만 포함 — 과거 해시 선택 결과를 고정해 재현성 보장
    "Bench_": "Bench_39ee5c499030472ca7460f3b03077135",
    "busstation_": "busstation_5acd6128d0b64ea2802bb7ae9aaa6c3d",
    "Trash_bin_": "Trash_bin_8dca3d38daf44ef9b3866efdce2eb8bb",
    "Vending_machine_": "Vending_machine_72ce292e1bd945aea580d223c75a870e",
}
fur_protos = {}
for i, f in enumerate(L["furniture"]):
    cat, th = FUR[f["type"]]
    if cat not in fur_protos:
        pick = FUR_PICK.get(cat)
        if pick and os.path.isfile(f"{CUSTOM}/objects/{pick}/{pick}.usd"):
            fs = [f"{CUSTOM}/objects/{pick}/{pick}.usd"]
        else:  # 저장소 외 전체 에셋 폴더에서 실행할 때의 과거 해시 선택 방식
            fs = sorted(glob.glob(f"{CUSTOM}/objects/{cat}*/*.usd"))
            fs = [fs[int(h(cat)*len(fs)) % len(fs)]] if fs else []
        fur_protos[cat] = make_proto(f"fur_{cat.strip('_')}", fs[0], target_h=th) if fs else None
    if fur_protos[cat]:
        place(f"/World/Furniture/f{i}", fur_protos[cat], f["pos"][0], f["pos"][1], CURB, yaw=f["rot"], instanceable=False)
make_proto("shrub_box", f"{NV}/Assets/Vegetation/Shrub/Boxwood.usd")
make_proto("shrub_bar", f"{NV}/Assets/Vegetation/Shrub/Barberry.usd")
_bc2 = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
_ns = 0
for _bi, _bb in enumerate(L["buildings"]):   # 건물 부속 저품질 초록 블롭 -> 숨기고 NVIDIA 관목
    _rt = stage.GetPrimAtPath(f"/World/Buildings/B{_bi}")
    for prim in Usd.PrimRange(_rt):
        if not prim.IsA(UsdGeom.Mesh): continue
        _m = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
        _col = None
        if _m:
            for _sh in _m.GetPrim().GetChildren():
                _shd = UsdShade.Shader(_sh)
                for _nmI in ("base_color_factor", "diffuse_color_constant"):
                    _inp = _shd.GetInput(_nmI) if _shd else None
                    if _inp and _inp.Get() is not None: _col = _inp.Get(); break
                if _col is not None: break
        if not _col: continue
        _r, _g, _b2 = float(_col[0]), float(_col[1]), float(_col[2])
        if not (_g > 0.35 and _g > 1.6*max(_r, _b2)): continue
        try:
            _rng = _bc2.ComputeWorldBound(prim).ComputeAlignedRange()
        except Exception:
            continue
        _s3 = _rng.GetSize(); _mid = _rng.GetMidpoint()
        if max(_s3[0], _s3[1]) > 3.0 or _s3[2] > 3.0 or _s3[2] < 0.15: continue
        UsdGeom.Imageable(prim).MakeInvisible()
        _sc = max(0.4, min(1.6, float(_s3[2]) / 0.9))
        _sc = max(0.15, min(0.5, float(_s3[2]) / 2.3))
        place(f"/World/Shrubs/s{_ns}", "cand2_hibiscus",
              float(_mid[0]), float(_mid[1]), max(0.0, float(_rng.GetMin()[2])),
              yaw=(_ns*73) % 360, scale=_sc, instanceable=False)
        _ns += 1
print(f"[fix] green blobs replaced: {_ns}", flush=True)

# 수풀 후보 라인업 (렌더 테스트로 승자 선정)
_veg = f"{NV}/dsready_content/nv_content/common_assets/props_vegetation"
CAND = [("cand0_boxwood", f"{NV}/Assets/Vegetation/Shrub/Boxwood.usd"),
        ("cand1_forsythia", f"{NV}/Assets/Vegetation/Shrub/Forsythia.usd"),
        ("cand2_hibiscus", f"{NV}/Assets/Vegetation/Shrub/Hibiscus.usd"),
        ("cand3_spirea", f"{NV}/Assets/Vegetation/Shrub/Goldflame_Spirea.usd"),
        ("cand4_photina", f"{NV}/Assets/Vegetation/Shrub/Fraser_Photina.usd")]
for _ci, (_cn, _cf) in enumerate(CAND):
    try:
        make_proto(_cn, _cf)
    except Exception as _e:
        print(f"[cand] {_cn} failed: {_e}", flush=True)
print(f"[cand] lineup: {[c[0] for c in CAND]}", flush=True)

m_red = pbr_mat("hydrant_red", (0.62, 0.04, 0.04), 0.5)
_bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
for f_i, f in enumerate(L["furniture"]):        # 정류장 부속 소화전(노랑) -> 빨강 강제 오버라이드
    if f["type"] != "bus_stop": continue
    rootp = stage.GetPrimAtPath(f"/World/Furniture/f{f_i}")
    for prim in Usd.PrimRange(rootp):
        if prim.IsA(UsdGeom.Mesh) and "hydrant" in prim.GetName().lower():
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(m_red, bindingStrength=UsdShade.Tokens.strongerThanDescendants)
            print(f"[fix] hydrant red: {prim.GetName()}", flush=True)
UsdGeom.Imageable(PROTOS.GetPrim()).MakeInvisible()
# 건물이 소속 블록을 벗어나는지 검증(에셋 원본 크기 오배치 조기 발견)
_over = 0
for _bi8, _b8 in enumerate(L["buildings"]):
    _fp8 = PROTO_FP.get(protos_b.get((_b8["asset"], _b8.get("h"))))
    if not _fp8: continue
    _w8, _d8 = (_fp8[1], _fp8[0]) if _b8["rot"] % 180 else (_fp8[0], _fp8[1])
    _x8, _y8 = _b8["pos"]
    _blk = next((r for r in GR["block"] if r[0] <= _x8 <= r[2] and r[1] <= _y8 <= r[3]), None)
    if _blk and (_x8-_w8/2 < _blk[0]-1.5 or _x8+_w8/2 > _blk[2]+1.5 or
                 _y8-_d8/2 < _blk[1]-1.5 or _y8+_d8/2 > _blk[3]+1.5):
        _over += 1
        print(f"[warn] B{_bi8} {_b8['asset'][9:17]} {_w8:.0f}x{_d8:.0f}m 이 블록을 벗어남 "
              f"(블록 {_blk[2]-_blk[0]:.0f}x{_blk[3]-_blk[1]:.0f}m) — h 지정으로 축소 검토", flush=True)
print(f"[city] 건물 블록 초과: {_over}건", flush=True)
print("[city] buildings+furniture done", flush=True)

# ---------------- 불법 주차 차량 (갓길) ----------------
VEH_W = {"car": 1.85, "scooter": 0.75, "bike": 0.62}     # 차폭 목표(갓길 2.0 m 안에 수용)
_vproto = {}
for _i, _p in enumerate(L.get("parked", [])):
    _a, _k = _p["asset"], _p["kind"]
    if _a not in _vproto:
        _vproto[_a] = make_proto(f"veh_{_a[:12]}", f"{CUSTOM}/objects/{_a}/{_a}.usd", target_w_min=VEH_W[_k])
    _pn = _vproto[_a]
    _fw, _fd, _fh = PROTO_FP[_pn]
    _yaw = _p["yaw"] + (90.0 if _fd > _fw else 0.0)      # 모델 장축을 도로 방향으로
    _x, _y = _p["pos"]
    place(f"/World/Parked/v{_i}", _pn, _x, _y, 0.0, yaw=_yaw, instanceable=False)
    _ln, _wd = max(_fw, _fd), min(_fw, _fd)              # 상세 메시 대신 박스 충돌체(비가시)
    _cw, _cd = (_ln, _wd) if _p["yaw"] % 180 == 0 else (_wd, _ln)
    _cb = box_mesh(f"/World/Parked/c{_i}", _x, _y, _cw, _cd, 0.02, max(0.5, _fh*0.92), m_metal, uv=0)
    UsdGeom.Imageable(_cb.GetPrim()).MakeInvisible()
print(f"[city] parked {len(L.get('parked', []))} vehicles ({len(_vproto)} models)", flush=True)

# ---------------- 블록 내부 노상 주차장 구획선 ----------------
STALL_W, STALL_D, SLW = 2.5, 5.0, 0.11        # 구획 폭 / 깊이 / 선 두께
_sn = 0
def _stall_row(x1, x2, y_edge, sgn, tag):
    """y_edge에서 sgn 방향으로 깊이 STALL_D인 주차열 (구획선은 x 간격)"""
    global _sn
    n = int((x2 - x1) // STALL_W)
    if n < 2: return
    ox = x1 + ((x2 - x1) - n * STALL_W) / 2
    for k in range(n + 1):
        px = ox + k * STALL_W
        rect_slab(f"{Z}/pl{tag}_{_sn}", px-SLW/2, min(y_edge, y_edge+sgn*STALL_D),
                  px+SLW/2, max(y_edge, y_edge+sgn*STALL_D), CURB, CURB+0.010, m_white, uv=0); _sn += 1
    ye = y_edge + sgn*STALL_D
    rect_slab(f"{Z}/pl{tag}_{_sn}", ox, ye-SLW/2, ox+n*STALL_W, ye+SLW/2, CURB, CURB+0.010, m_white, uv=0); _sn += 1
def _stall_col(y1, y2, x_edge, sgn, tag):
    global _sn
    n = int((y2 - y1) // STALL_W)
    if n < 2: return
    oy = y1 + ((y2 - y1) - n * STALL_W) / 2
    for k in range(n + 1):
        py = oy + k * STALL_W
        rect_slab(f"{Z}/pl{tag}_{_sn}", min(x_edge, x_edge+sgn*STALL_D), py-SLW/2,
                  max(x_edge, x_edge+sgn*STALL_D), py+SLW/2, CURB, CURB+0.010, m_white, uv=0); _sn += 1
    xe = x_edge + sgn*STALL_D
    rect_slab(f"{Z}/pl{tag}_{_sn}", xe-SLW/2, oy, xe+SLW/2, oy+n*STALL_W, CURB, CURB+0.010, m_white, uv=0); _sn += 1
_free = [tuple(r) for r in GR["block"]]
for _b in _BLD_FP: _free = _sub_rect(_free, _b)
for _c in _CUTS: _free = _sub_rect(_free, _c)
for _fi, (fx1, fy1, fx2, fy2) in enumerate(_free):
    fw, fd = fx2-fx1, fy2-fy1
    if fw < STALL_W*2 or fd < STALL_W*2: continue
    if fw >= fd:                                   # 가로로 긴 영역 → 위·아래 가장자리에 주차열
        if fd >= STALL_D + 0.3: _stall_row(fx1+0.3, fx2-0.3, fy1+0.15, +1, _fi)
        if fd >= STALL_D*2 + 1.0: _stall_row(fx1+0.3, fx2-0.3, fy2-0.15, -1, _fi)
    else:
        if fw >= STALL_D + 0.3: _stall_col(fy1+0.3, fy2-0.3, fx1+0.15, +1, _fi)
        if fw >= STALL_D*2 + 1.0: _stall_col(fy1+0.3, fy2-0.3, fx2-0.15, -1, _fi)
print(f"[city] block parking lots: {len(_free)} areas, {_sn} lines", flush=True)

# ---------------- 조명 ----------------
dome = UsdLux.DomeLight.Define(stage, "/World/QualitySky")
dome.CreateIntensityAttr(1000.0); dome.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
_sky = f"{NV}/Assets/Skies/Clear/kloppenheim_02_4k.hdr"
if os.path.exists(_sky): dome.CreateTextureFileAttr(_sky)
sun = UsdLux.DistantLight.Define(stage, "/World/QualitySun")
sun.CreateIntensityAttr(3500.0); sun.CreateColorAttr(Gf.Vec3f(1.0, 0.98, 0.92)); sun.CreateAngleAttr(0.53)
sx_ = UsdGeom.Xformable(sun.GetPrim()); sx_.ClearXformOpOrder(); sx_.AddRotateXYZOp().Set(Gf.Vec3d(-58.0, 25.0, 0.0))

# 프로토타입 원본 더미가 원점(0,0)에 쌓여 충돌·렌더되는 것을 차단.
# 컨테이너(/World/_protos)의 트랜스폼·가시성은 참조 대상(자식 프림)에 합성되지 않으므로
# 인스턴스에는 영향이 없다 — 원본만 지하로 치우고 숨긴다.
_pc = stage.GetPrimAtPath("/World/_protos")
UsdGeom.Xformable(_pc).AddTranslateOp().Set(Gf.Vec3d(0, 0, -500.0))
UsdGeom.Imageable(_pc).MakeInvisible()
print("[city] proto container parked at z=-500 (hidden)", flush=True)

ctx.save_as_stage(f"{BASE}/city_static.usd")
print("[city] saved city_static.usd", flush=True)

# ---------------- 검증 스크린샷 ----------------
from isaacsim.core.utils.extensions import enable_extension
enable_extension("isaacsim.sensors.camera")
from isaacsim.sensors.camera import Camera

def _quat_yaw_pitch(yaw, pitch):
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    cp, sp = math.cos(pitch/2), math.sin(pitch/2)
    return _np.array([cy*cp, -sy*sp, cy*sp, sy*cp])

cam = Camera(prim_path="/World/shot_cam", resolution=(1280, 720))
cam.initialize()
omni.timeline.get_timeline_interface().play()
for _ in range(60): app.update()
SHOTS = [
    ("aerial_top", (0, -160, 270), 90, 56),
    ("aerial_ne",  (125, -125, 95), 135, 33),
    ("start",      (10.0, -23, 1.6), 0, 3),
    ("a1_cross",   (19, -11.5, 1.8), -33, 4),
    ("b1_narrow",  (32.4, -8, 1.6), 90, 3),
    ("d1_lane",    (0, 19, 1.6), -90, 3),
    ("prom_p1",    (-28, 45, 1.6), -90, 3),
    ("ring_road",  (70, -45, 1.8), 90, 2),
    ("ramp_close", (14.3, -24.0, 1.1), 0, 9),
    ("corner_pole", (16.5, -16.5, 1.7), -45, 4),
    ("inter_sw",   (-33.8, -33.8, 2.3), 45, 5),
    ("sig_sw_e", (-13, -28, 5.0), 180, 10), ("sig_sw_s", (-28, -13, 5.0), -90, 10),
    ("sig_se_e", (13, -28, 5.0), 0, 10),    ("sig_se_s", (28, -13, 5.0), -90, 10),
    ("sig_nw_e", (-13, 28, 5.0), 180, 10),  ("sig_nw_s", (-28, 13, 5.0), 90, 10),
    ("sig_ne_e", (13, 28, 5.0), 0, 10),     ("sig_ne_s", (28, 13, 5.0), 90, 10),
    ("ped_face", (22.5, -19.5, 1.4), 0, 2),
    ("user_view", (19.0, -24.5, 1.6), 30, 3),
    ("ped_head", (28.7, -15.4, 2.3), 0, -6),
    ("ped_head2", (34.6, -15.4, 2.35), 180, -8),
    ("ped_face2", (30.0, 19.6, 1.4), 172, 2),
    ("planter", (20.5, -16.0, 1.4), 165, 4),
]
os.makedirs(f"{BASE}/shots", exist_ok=True)
for name, pos, yaw, pitch in SHOTS:
    cam.set_world_pose(_np.array(pos), _quat_yaw_pitch(math.radians(yaw), math.radians(pitch)), camera_axes="world")
    for _ in range(25): app.update()
    arr = cam.get_rgba()
    if arr is not None and arr.size > 100:
        _Image.fromarray(arr[:, :, :3]).save(f"{BASE}/shots/{name}.jpg", quality=90)
        print(f"[shot] {name} saved", flush=True)
    else:
        print(f"[shot] {name} EMPTY", flush=True)
print("[city] ALL DONE", flush=True)
app.close()
