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
EXT, RW, SWI, SWO = 65.0, 3.5, 3.5, 6.5
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
GEXT = 77.0
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
_lay("block", GR["block"], m_gran, 0.3)
_lay("fill", GR["fill"], m_gran, 0.3)
_lay("walk", GR["walk"], m_pave, 0.8)
_lay("narrow", GR["narrow"], m_pave, 0.8)
for i, r in enumerate(GR["brick"]): rect_slab(f"{G}/brick{i}", *r, -0.05, CURB, m_cobb, uv=0.8)

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
    if rp.get("why") == "crosswalk":
        continue
    x, y = rp["pos"]; dx_, dy_ = rp["down"]
    ls = abs(dx_)*rp["w"] + abs(dy_)*rp["d"]
    wa = abs(dy_)*rp["w"] + abs(dx_)*rp["d"]
    yaw_ = math.degrees(math.atan2(dy_, dx_))
    pitch_ = math.degrees(math.atan((CURB + 0.002)/ls))
    box_mesh(f"{Z}/ramp{ri}", x, y, ls, wa, -0.20, 0.006 + (CURB - 0.004)/2, m_pave, yaw=yaw_, pitch=pitch_, uv=0.8)
ARMV = {"N": (0,1), "S": (0,-1), "E": (1,0), "W": (-1,0)}
for ci, cw in enumerate(L["crosswalks"]):  # 정지선(접근차로 반폭)
    ix, iy = cw["inter"]; dx, dy = ARMV[cw["arm"]]
    if dy:  # v-road arm: 접근차로는 arm N -> x<ix
        x1, x2 = (ix-RW+0.2, ix-0.15) if dy > 0 else (ix+0.15, ix+RW-0.2)
        rect_slab(f"{Z}/stop{ci}", x1, iy+dy*7.0, x2, iy+dy*7.45, 0.0, 0.012, m_white, uv=0)
    else:
        y1, y2 = (iy+0.15, iy+RW-0.2) if dx > 0 else (iy-RW+0.2, iy-0.15)
        rect_slab(f"{Z}/stop{ci}", ix+dx*7.0, y1, ix+dx*7.45, y2, 0.0, 0.012, m_white, uv=0)
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
print(f"[city] ground+marks done ({di} dashes)", flush=True)

# ---------------- 프로토타입 로더 ----------------
PROTOS = UsdGeom.Scope.Define(stage, "/World/_protos")
def make_proto(name, asset, target_h=None, target_wd=None):
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
    k = mpu * s
    # 피벗 보정: 회전(Y-up→Z-up) 후 기준으로 xy는 bbox 중심, z는 바닥이 원점에 오도록
    if up == "Y":
        cx_, cy_, z0 = (mn[0]+mx[0])/2, -(mn[2]+mx[2])/2, mn[1]
    else:
        cx_, cy_, z0 = (mn[0]+mx[0])/2, (mn[1]+mx[1])/2, mn[2]
    xf.AddTranslateOp().Set(Gf.Vec3d(-cx_*k, -cy_*k, -z0*k))
    xf.AddRotateXOp().Set(90.0 if up == "Y" else 0.0)
    xf.AddScaleOp().Set(Gf.Vec3f(k))
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
for i, b in enumerate(L["buildings"]):  # 실측 native 크기 그대로
    asset = b["asset"]
    if asset not in protos_b:
        protos_b[asset] = make_proto(f"bld_{asset[9:17]}", f"{CUSTOM}/objects/{asset}/{asset}.usd")
    place(f"/World/Buildings/B{i}", protos_b[asset], b["pos"][0], b["pos"][1], CURB, yaw=b["rot"], instanceable=False)
FUR = dict(bench=("Bench_", 0.9), trash_bin=("Trash_bin_", 1.0), bus_stop=("busstation_", 2.7),
           phone_booth=("Telephone_booth_", 2.4), vending=("Vending_machine_", 1.8), mailbox=("Mailbox_", 1.15))
FUR_PICK = {  # 저장소에는 실제 사용 폴더만 포함 — 과거 해시 선택 결과를 고정해 재현성 보장
    "Bench_": "Bench_39ee5c499030472ca7460f3b03077135",
    "busstation_": "busstation_5acd6128d0b64ea2802bb7ae9aaa6c3d",
    "Mailbox_": "Mailbox_a3b4bc95daf243f1a95b37d4d5880856",
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
print("[city] buildings+furniture done", flush=True)

# ---------------- 조명 ----------------
dome = UsdLux.DomeLight.Define(stage, "/World/QualitySky")
dome.CreateIntensityAttr(1000.0); dome.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
_sky = f"{NV}/Assets/Skies/Clear/kloppenheim_02_4k.hdr"
if os.path.exists(_sky): dome.CreateTextureFileAttr(_sky)
sun = UsdLux.DistantLight.Define(stage, "/World/QualitySun")
sun.CreateIntensityAttr(3500.0); sun.CreateColorAttr(Gf.Vec3f(1.0, 0.98, 0.92)); sun.CreateAngleAttr(0.53)
sx_ = UsdGeom.Xformable(sun.GetPrim()); sx_.ClearXformOpOrder(); sx_.AddRotateXYZOp().Set(Gf.Vec3d(-58.0, 25.0, 0.0))

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
