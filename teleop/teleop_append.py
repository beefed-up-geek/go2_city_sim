
# ==================== GO2 WEB TELEOP (appended to play.py prelude) ====================
import io as _io
import os as _os
import json as _json
import threading as _threading
_REPO = _os.environ.get("GO2CITY_ROOT", "/workspace/urban-sim/go2_city_sim")
_LAYOUT_JSON = f"{_REPO}/assets/city_layout.json"
_CITY_USD = _os.environ.get("CITY_USD", "/workspace/urban-sim/city_static.usd")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as _np
from PIL import Image as _Image
import omni.usd

WEB_PORT = 8003
CAM_W, CAM_H = 1280, 720
JPEG_Q = 88

_state_lock = _threading.Lock()
_frames = {"ego": None, "tpv": None}
_frame_seq = {"ego": 0, "tpv": 0}
_frame_cond = _threading.Condition(_state_lock)
_keys = {"up": False, "down": False, "left": False, "right": False, "sl": False, "sr": False}
_keys_time = [0.0]
_reset_req = [False]
_goto_req = [None]  # (x, y, z, yaw_deg)
_des_yaw = [None]   # heading hold target (rad)
_status = {"sim_fps": 0.0, "loc": [0, 0, 0], "yaw": 0.0, "cmd": [0, 0, 0], "signal": "-"}

# ---------- build env ----------
env_cfg = parse_env_cfg()
env_cfg.episode_length_s = 1.0e6  # no time-based resets during teleop
try:
    env_cfg.commands.pose_command.resampling_time_range = (1.0e6, 1.0e6)
    env_cfg.commands.pose_command.debug_vis = False
except Exception as e:
    print("[teleop] command cfg tweak skipped:", e, flush=True)

try:
    env_cfg.scene.height_scanner.debug_vis = False
except Exception as e:
    print("[teleop] height_scanner debug off skipped:", e, flush=True)
try:
    # keep the term (rewards reference it by name) but make it never fire
    env_cfg.terminations.collision.params["threshold"] = 1.0e9
except Exception as e:
    print("[teleop] collision term defuse skipped:", e, flush=True)

env = gym.make(args_cli.task, cfg=env_cfg)
print("[teleop] action space:", env.action_space, flush=True)
ACT_DIM = int(env.action_space.shape[-1])
env.reset()

# ---------- render quality ----------
try:
    import carb.settings
    _cs = carb.settings.get_settings()
    _cs.set("/rtx/post/aa/op", 3)                      # DLSS
    _cs.set("/rtx/ambientOcclusion/enabled", True)
    _cs.set("/rtx/reflections/enabled", True)
    _cs.set("/rtx/indirectDiffuse/enabled", True)
    _cs.set("/rtx/post/tonemap/filmIso", 100)
    _cs.set("/rtx/post/histogram/enabled", False)
    print("[quality] rtx options set", flush=True)
except Exception as e:
    print("[quality] rtx options failed:", e, flush=True)


# ---------- v4 loop-course city (city_static.usd: 지형+신호등+건물+램프+콜라이더 포함) ----------
try:
    from pxr import UsdGeom as _UG2
    _t_stage = omni.usd.get_context().get_stage()
    _city = _t_stage.DefinePrim("/World/City", "Xform")
    _city.GetReferences().AddReference(_CITY_USD)
    for _nm in ["Walkable_000", "Walkable_001", "Walkable_002", "Walkable_003",
                "NonWalkable_000", "NonWalkable_001", "NonWalkable_002", "NonWalkable_003",
                "Obstacle_terrain", "defaultGroundPlane"]:
        _pp = _t_stage.GetPrimAtPath(f"/World/{_nm}")
        if _pp and _pp.IsValid():
            _UG2.Imageable(_pp).MakeInvisible()
    _gp = _t_stage.GetPrimAtPath("/World/ground")
    if _gp and _gp.IsValid():
        _UG2.Imageable(_gp).MakeInvisible()
    # 숨긴 환경 패치(구역 경계벽 포함)의 충돌 완전 비활성화 — 투명벽 방지
    from pxr import Usd as _Usd4, UsdPhysics as _UPh
    _ndis = 0; _swept = []
    print("[city] /World children:", [c.GetName() for c in _t_stage.GetPrimAtPath("/World").GetChildren()], flush=True)
    for _ch in _t_stage.GetPrimAtPath("/World").GetChildren():
        _nm4 = _ch.GetName()
        if _nm4 == "City" or _nm4.startswith(("env", "Env", "Robot", "robot", "coco", "Light", "Sky", "Dome", "Distant")):
            continue
        if _nm4.lower().startswith(("env", "light", "sky", "dome", "distant", "camera", "cam",
                                    "tpv", "ego", "physicsscene", "looks", "render", "omni")):
            continue                      # 로봇·조명·카메라·물리씬은 보존
        if _ch.IsInstanceable():          # 인스턴스 프록시는 PrimRange가 건너뛰므로 해제 후 순회
            _ch.SetInstanceable(False)
        for _pr4 in _Usd4.PrimRange(_ch):
            if _pr4.HasAPI(_UPh.CollisionAPI):
                _UPh.CollisionAPI(_pr4).CreateCollisionEnabledAttr(False); _ndis += 1
            elif _pr4.IsA(_UG2.Mesh) or _pr4.IsA(_UG2.Gprim):
                _UPh.CollisionAPI.Apply(_pr4).CreateCollisionEnabledAttr(False); _ndis += 1
        _UG2.Imageable(_ch).MakeInvisible()
        _swept.append(_nm4)
    # env 안(로봇 제외)에 원점 부근으로 남은 잔여 지오메트리 제거 — 혼용길 한복판 장애물 방지
    _bc5 = _UG2.BBoxCache(_Usd4.TimeCode.Default(), ["default", "render", "proxy"])
    _envp = _t_stage.GetPrimAtPath("/World/envs")
    _origin_hits = []
    if _envp and _envp.IsValid():
        for _pr5 in _Usd4.PrimRange(_envp):
            _ps5 = _pr5.GetPath().pathString
            if "obot" in _ps5 or "oco" in _ps5:      # Robot / coco 계열 보존
                continue
            if not _pr5.IsA(_UG2.Boundable):
                continue
            _r5 = _bc5.ComputeWorldBound(_pr5).ComputeAlignedRange()
            if _r5.IsEmpty():
                continue
            _m0, _m1 = _r5.GetMin(), _r5.GetMax()
            if _m0[0] < 3 and _m1[0] > -3 and _m0[1] < 3 and _m1[1] > -3 and _m1[2] > 0.05 and _m0[2] < 3:
                _origin_hits.append((_ps5, round(_m0[2], 2), round(_m1[2], 2)))
                if _pr5.HasAPI(_UPh.CollisionAPI):
                    _UPh.CollisionAPI(_pr5).CreateCollisionEnabledAttr(False)
                else:
                    _UPh.CollisionAPI.Apply(_pr5).CreateCollisionEnabledAttr(False)
                _UG2.Imageable(_pr5).MakeInvisible()
    print(f"[city] city_static referenced + env patch hidden + colliders off: {_ndis} | swept={_swept}", flush=True)
    print(f"[city] origin obstacles removed: {_origin_hits}", flush=True)
    # env 하위 URBAN-SIM 지형(보도/보행로 패치)도 제거 — 도시 노면 위에 겹쳐 뜨는 원인
    _terr = []
    if _envp and _envp.IsValid():
        for _pr7 in _Usd4.PrimRange(_envp):
            _n7 = _pr7.GetName()
            _p7 = _pr7.GetPath().pathString
            if "obot" in _p7 or "oco" in _p7: continue
            if not _n7.lower().startswith(("walkable", "nonwalkable", "obstacle", "terrain",
                                           "ground", "sidewalk", "plane", "road", "block")):
                continue
            try:
                if _pr7.IsInstanceable(): _pr7.SetInstanceable(False)
            except Exception: pass
            for _q7 in _Usd4.PrimRange(_pr7):
                if _q7.HasAPI(_UPh.CollisionAPI):
                    _UPh.CollisionAPI(_q7).CreateCollisionEnabledAttr(False)
                elif _q7.IsA(_UG2.Mesh):
                    _UPh.CollisionAPI.Apply(_q7).CreateCollisionEnabledAttr(False)
            _UG2.Imageable(_pr7).MakeInvisible()
            _terr.append(_n7)
    print(f"[city] env terrain hidden: {_terr[:12]} (총 {len(_terr)})", flush=True)
    # 진단: 도시(/World/City) 밖에서 골목 위에 보이는 프림 열거
    try:
        _bc7 = _UG2.BBoxCache(_Usd4.TimeCode.Default(), ["default", "render", "proxy"])
        _found = []
        for _pr6 in _t_stage.Traverse():
            _p6 = _pr6.GetPath().pathString
            if _p6.startswith("/World/City") or not _pr6.IsA(_UG2.Mesh): continue
            _r6 = _bc7.ComputeWorldBound(_pr6).ComputeAlignedRange()
            if _r6.IsEmpty(): continue
            _a6, _b6 = _r6.GetMin(), _r6.GetMax()
            if _a6[0] < 5 and _b6[0] > -5 and _a6[1] < 20 and _b6[1] > -20 and _a6[2] < 1.5 and _b6[2] > -0.5:
                if _UG2.Imageable(_pr6).ComputeVisibility() == "invisible": continue
                _found.append(f"{_p6[-58:]} x[{_a6[0]:.1f},{_b6[0]:.1f}] y[{_a6[1]:.1f},{_b6[1]:.1f}] z[{_a6[2]:.2f},{_b6[2]:.2f}]")
        print(f"[diag] 골목 위 비도시 프림 {len(_found)}개:", flush=True)
        for _f6 in _found[:15]: print("   ", _f6, flush=True)
    except Exception as _e6:
        print("[diag] 실패:", _e6, flush=True)
except Exception as e:
    print("[city] failed:", e, flush=True)

uenv = env.unwrapped
robot = uenv.scene["robot"]
device = uenv.device

# ---------- cameras ----------
from isaacsim.core.utils.extensions import enable_extension

enable_extension("isaacsim.sensors.camera")
from isaacsim.sensors.camera import Camera


def _quat_yaw_pitch(yaw, pitch):
    """world-axes camera quat (w,x,y,z): Rz(yaw) * Ry(pitch)."""
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    return _np.array([cy * cp, -sy * sp, cy * sp, sy * cp])


cam_ego = Camera(prim_path="/World/ego_cam", resolution=(CAM_W, CAM_H))
cam_tpv = Camera(prim_path="/World/tpv_cam", resolution=(CAM_W, CAM_H))
cam_ego.initialize()
cam_tpv.initialize()
_BASE_FL = float(cam_tpv.get_focal_length())
print(f"[teleop] base focal length: {_BASE_FL}", flush=True)
_last_fl = [0.0]


# TPV 구면 오빗: ta=방위각(0=로봇 정후방, deg) te=고도각(deg) tr=반경(m) ah=조준높이(m)
CAMCFG = {"ta": 0.0, "te": 31.5, "tr": 10.55, "ah": 0.6, "ex": 0.35, "ez": 0.32, "ep": 0.0, "fl": 0.55}


def _update_cameras(yaw_cmd=None):
    pos = robot.data.root_pos_w[0].detach().cpu().numpy()
    quat = robot.data.root_quat_w[0].detach().cpu().numpy()  # (w,x,y,z)
    w, x, y, z = quat
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    if yaw_cmd is not None:
        yaw = yaw_cmd
    fx, fy = math.cos(yaw), math.sin(yaw)
    c = dict(CAMCFG)
    if c.get("fl", 0) > 0 and abs(c["fl"] - _last_fl[0]) > 1e-6:
        try:
            cam_tpv.set_focal_length(_BASE_FL * c["fl"])
            _last_fl[0] = c["fl"]
            print(f"[teleop] tpv focal set to {_BASE_FL * c['fl']:.2f}", flush=True)
        except Exception as e:
            print("[teleop] focal set failed:", e, flush=True)
    ego_pos = _np.array([pos[0] + fx * c["ex"], pos[1] + fy * c["ex"], pos[2] + c["ez"]])
    cam_ego.set_world_pose(ego_pos, _quat_yaw_pitch(yaw, math.radians(c["ep"])), camera_axes="world")
    _te = math.radians(max(3.0, min(85.0, c.get("te", 31.5))))
    _tr = max(2.0, min(40.0, c.get("tr", 10.55)))
    _az = yaw + math.pi + math.radians(c.get("ta", 0.0))   # ta=0 → 정후방
    _hd = _tr * math.cos(_te)
    tpv_pos = _np.array([pos[0] + _hd * math.cos(_az), pos[1] + _hd * math.sin(_az), pos[2] + _tr * math.sin(_te)])
    _aim_z = pos[2] + c.get("ah", 0.6)
    _cy = math.atan2(pos[1] - tpv_pos[1], pos[0] - tpv_pos[0])
    _cp = math.atan2(tpv_pos[2] - _aim_z, max(_hd, 0.01))   # 양수=아래
    cam_tpv.set_world_pose(tpv_pos, _quat_yaw_pitch(_cy, _cp), camera_axes="world")
    return pos, yaw


def _capture(name, cam):
    try:
        rgba = cam.get_rgba()
        if rgba is None or rgba.size == 0:
            return
        arr = rgba[:, :, :3].astype(_np.uint8)
        buf = _io.BytesIO()
        _Image.fromarray(arr).save(buf, format="JPEG", quality=JPEG_Q)
        with _frame_cond:
            _frames[name] = buf.getvalue()
            _frame_seq[name] += 1
            _frame_cond.notify_all()
    except Exception as e:
        print(f"[teleop] capture {name} failed: {e}", flush=True)


# ---------- minimap layout ----------
try:
    with open(_LAYOUT_JSON) as _lf:
        _CL = _json.load(_lf)
    _MMAP = _json.dumps({"roads": _CL["roads"], "brick": _CL["ground"]["brick"],
                         "walk": _CL["ground"]["walk"] + _CL["ground"]["narrow"],
                         "course": _CL["course"]["waypoints"]}).encode()
    print("[teleop] minimap layout loaded", flush=True)
except Exception as _e:
    _MMAP = b'{"roads":[],"brick":[],"walk":[],"course":[]}'
    print("[teleop] minimap layout failed:", _e, flush=True)

# ---------- signal logic (42s+blink 사이클, 전 교차로 동기) ----------
SIGCFG = {"blink": round(11.0 / 1.2, 2)}
_SIG_NOW = [("red", "red", "red")]   # 보행 점멸(s) = 횡단보도 길이 11m / COCO 1.2m/s. POST /sigcfg {"blink": x}
try:
    from pxr import UsdGeom as _UGS
    _sig_stage = omni.usd.get_context().get_stage()
    _CLS = _json.loads(_MMAP.decode()) if False else None
except Exception:
    pass
_sig_veh = []   # (group, bulb_prefix)
_sig_ped = []   # inst_path
try:
    with open(_LAYOUT_JSON) as _sf:
        _CLS = _json.load(_sf)
    for _i, _v in enumerate(_CLS["veh_lights"]):
        _grp = "NS" if _v["arm"][0] != 0 else "EW"
        _b = f"/World/City/Signals/v{_i}/head/fix/g"
        if _sig_stage.GetPrimAtPath(_b + "/RootNode").IsValid():
            _b += "/RootNode"
        _sig_veh.append((_grp, _b))
    for _i in range(len(_CLS["ped_lights"])):
        _sig_ped.append(f"/World/City/Signals/p{_i}")
    print(f"[signal] veh {len(_sig_veh)} ped {len(_sig_ped)} blink={SIGCFG['blink']}s", flush=True)
except Exception as _e:
    print("[signal] setup failed:", _e, flush=True)

_BULB = {"red": "combined_solid_red_0", "yellow": "combined_solid_yellow_1", "green": "combined_solid_green_2"}
def _setvis(path, on):
    _p = _sig_stage.GetPrimAtPath(path)
    if _p and _p.IsValid():
        from pxr import UsdGeom as _UG8
        _UG8.Imageable(_p).GetVisibilityAttr().Set("inherited" if on else "invisible")

_sig_last = [None]
def _sig_step():
    _bl = max(1.0, float(SIGCFG["blink"]))
    _cyc = 38.0 + _bl
    _t = time.monotonic() % _cyc
    if _t < 10:   ph, ns, ew, pd = "차량 남북", "green", "red", "red"
    elif _t < 13: ph, ns, ew, pd = "차량 남북(황)", "yellow", "red", "red"
    elif _t < 14: ph, ns, ew, pd = "전적색", "red", "red", "red"
    elif _t < 24: ph, ns, ew, pd = "차량 동서", "red", "green", "red"
    elif _t < 27: ph, ns, ew, pd = "차량 동서(황)", "red", "yellow", "red"
    elif _t < 28: ph, ns, ew, pd = "전적색", "red", "red", "red"
    elif _t < 36: ph, ns, ew, pd = "동시 보행", "red", "red", "grn"
    elif _t < 36 + _bl:
        _on = int(_t) % 2 == 0   # 1Hz 점멸 (0.5s 토글은 DLSS 잔상에 묻힘)
        ph, ns, ew, pd = "보행 점멸", "red", "red", ("cnt" if _on else "off")
    else:         ph, ns, ew, pd = "전적색", "red", "red", "red"
    _sigkey = (ns, ew, pd)
    _SIG_NOW[0] = _sigkey          # 트래픽 엔진이 구독
    _rem = (36 + _bl - _t) if 28 <= _t < 36 + _bl else (_cyc - _t if _t >= 36 + _bl else None)
    with _state_lock:
        _status["signal"] = ph + (f" {max(0.0, (36 + _bl - _t)):.0f}s" if 28 <= _t < 36 + _bl else "")
        if _TRAF[0] is not None:
            try: _status["traffic"] = _TRAF[0].stats()
            except Exception: pass
    if _sig_last[0] == _sigkey:
        return
    _sig_last[0] = _sigkey
    for _grp, _b in _sig_veh:
        _col = ns if _grp == "NS" else ew
        for _cn, _bn in _BULB.items():
            _setvis(f"{_b}/{_bn}", _cn == _col)
    for _pp in _sig_ped:
        for _snm in ("red", "grn", "cnt", "off"):
            _setvis(f"{_pp}/{_snm}", _snm == pd)

# ---------- web ----------
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>COCO City Teleop</title>
<style>
body{margin:0;background:#111;color:#ddd;font-family:sans-serif}
.wrap{display:flex;flex-wrap:wrap;gap:8px;padding:8px;justify-content:center}
.panel{flex:1 1 480px;max-width:960px}
.panel img{width:100%;border:1px solid #333;border-radius:4px;display:block}
.panel h3{margin:4px 0;font-size:14px;font-weight:600;color:#9cf}
#bar{padding:6px 12px;background:#1a1a1a;font-size:13px;display:flex;gap:16px;flex-wrap:wrap}
kbd{background:#333;border-radius:3px;padding:1px 6px;font-size:12px}
#stat{color:#8f8}
#mmbox{position:fixed;right:10px;top:44px;background:#15171acc;border:1px solid #333;border-radius:8px;padding:6px;z-index:9}
#mm{display:block;border-radius:4px}
#nav{display:flex;align-items:center;gap:10px;margin-top:5px;font-size:13px;color:#fbb}
#navarrow{width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;border-bottom:26px solid #f55;transform-origin:50% 62%}
</style></head><body>
<div id="bar">
  <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> 전/후진 <kbd>&larr;</kbd><kbd>&rarr;</kbd> 회전 <kbd>A</kbd><kbd>D</kbd> 좌/우 게걸음 <kbd>R</kbd> 리셋</span>
  <span id="scen">
    <button data-s="1">지점&#9312;</button>
    <button data-s="2">지점&#9313;</button>
    <button data-s="3">지점&#9314;</button>
    <button data-s="4">지점&#9315;</button>
  </span>
  <span id="stat">connecting...</span>
</div>
<style>#scen button{background:#2a3140;color:#cde;border:1px solid #445;border-radius:4px;
 padding:2px 8px;font-size:12px;cursor:pointer}#scen button:hover{background:#3a4560}</style>
<div class="wrap">
  <div class="panel"><h3>제3자 뷰 (Third-person) — 드래그: 회전 · 휠: 줌</h3><img id="tpv" src="/stream/tpv" draggable="false" style="cursor:grab"></div>
  <div class="panel"><h3>에고 뷰 (Ego)</h3><img src="/stream/ego"></div>
</div>
<div id="mmbox"><canvas id="mm" width="280" height="280"></canvas>
<div id="nav"><div id="navarrow"></div><div id="navtxt">-</div></div></div>
<script>
const keys={up:false,down:false,left:false,right:false,sl:false,sr:false};
const map={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',a:'sl',A:'sl',d:'sr',D:'sr'};
function send(){fetch('/cmd',{method:'POST',body:JSON.stringify(keys)}).catch(()=>{});}
addEventListener('keydown',e=>{
  if(e.key==='r'||e.key==='R'){fetch('/reset',{method:'POST'});return;}
  if(map[e.key]!==undefined){keys[map[e.key]]=true;e.preventDefault();send();}});
addEventListener('keyup',e=>{
  if(map[e.key]!==undefined){keys[map[e.key]]=false;e.preventDefault();send();}});
setInterval(send,120);
const SPOTS={1:[10,-23,0.55,0],2:[23,-18,0.55,90],3:[0,18,0.55,-90],4:[-28,45,0.55,-90]};
document.querySelectorAll('#scen button').forEach(b=>b.addEventListener('click',()=>{
  const p=SPOTS[b.dataset.s];
  fetch('/goto',{method:'POST',body:JSON.stringify({x:p[0],y:p[1],z:p[2],yaw:p[3]})});
  b.blur();
}));
setInterval(async()=>{try{const s=await(await fetch('/status')).json();
 document.getElementById('stat').textContent=
  `sim ${s.sim_fps.toFixed(1)} Hz | pos (${s.loc[0].toFixed(1)}, ${s.loc[1].toFixed(1)}) | ${s.signal}`;
}catch(e){}},1000);
// ---- minimap & checkpoints ----
const MMW=280, WEXT=77, SCL=MMW/(2*WEXT);
const mmc=document.getElementById('mm').getContext('2d');
const base=document.createElement('canvas');base.width=MMW;base.height=MMW;
let LAY=null,CPS=[],cpi=1;
const PX=x=>(x+WEXT)*SCL, PY=y=>(WEXT-y)*SCL;
fetch('/layout').then(r=>r.json()).then(l=>{LAY=l;CPS=l.course.slice(0,-1);drawBase();});
function drawBase(){const c=base.getContext('2d');c.fillStyle='#20262c';c.fillRect(0,0,MMW,MMW);
 c.fillStyle='#9aa1a8';for(const w of LAY.walk){c.fillRect(PX(w[0]),PY(w[3]),(w[2]-w[0])*SCL,(w[3]-w[1])*SCL);}
 c.fillStyle='#565d66';for(const r of LAY.roads){if(r.axis=='v')c.fillRect(PX(r.c-3.5),PY(r.hi),7*SCL,(r.hi-r.lo)*SCL);else c.fillRect(PX(r.lo),PY(r.c+3.5),(r.hi-r.lo)*SCL,7*SCL);}
 c.fillStyle='#8a6a50';for(const b of LAY.brick){c.fillRect(PX(b[0]),PY(b[3]),(b[2]-b[0])*SCL,(b[3]-b[1])*SCL);}
 c.strokeStyle='#e5484d';c.lineWidth=2.5;c.beginPath();LAY.course.forEach((p,i)=>{i?c.lineTo(PX(p[0]),PY(p[1])):c.moveTo(PX(p[0]),PY(p[1]));});c.stroke();}
let RS={loc:[0,0,0],yaw:0};
function drawMM(){if(!LAY)return;mmc.drawImage(base,0,0);
 const t=Date.now()/400;
 CPS.forEach((p,i)=>{const nx=(i===cpi);const r=6*SCL*(nx?(1.2+0.25*Math.sin(t)):1);
  mmc.beginPath();mmc.arc(PX(p[0]),PY(p[1]),r,0,7);
  mmc.fillStyle=nx?'rgba(255,90,70,0.55)':'rgba(229,72,77,0.25)';mmc.fill();
  if(nx){mmc.strokeStyle='#ff7a5f';mmc.lineWidth=2.5;mmc.stroke();}
  mmc.fillStyle='#fff';mmc.font='bold 10px sans-serif';mmc.textAlign='center';
  mmc.fillText(i===0?'S':String(i),PX(p[0]),PY(p[1])+3.5);});
 const x=PX(RS.loc[0]),y=PY(RS.loc[1]);
 mmc.save();mmc.translate(x,y);mmc.rotate(-RS.yaw);
 mmc.fillStyle='#4af';mmc.beginPath();mmc.moveTo(8,0);mmc.lineTo(-5,5);mmc.lineTo(-5,-5);mmc.closePath();mmc.fill();
 mmc.restore();}
function updNav(){if(!CPS.length)return;const p=CPS[cpi];
 const dx=p[0]-RS.loc[0],dy=p[1]-RS.loc[1];const d=Math.hypot(dx,dy);
 if(d<6){cpi=(cpi+1)%CPS.length;return;}
 const rel=Math.atan2(dy,dx)-RS.yaw;
 document.getElementById('navarrow').style.transform=`rotate(${-rel*180/Math.PI}deg)`;
 document.getElementById('navtxt').textContent=`체크포인트 ${cpi}/${CPS.length-1} · ${d.toFixed(0)}m`;}
setInterval(async()=>{try{const s=await(await fetch('/status')).json();RS=s;drawMM();updNav();}catch(e){}},250);
// TPV 마우스 오빗/줌 (로봇 중심)
let camS={ta:0,te:31.5,tr:10.55}, camDirty=false, camDrag=null;
const tpvEl=document.getElementById('tpv');
tpvEl.addEventListener('mousedown',e=>{camDrag=[e.clientX,e.clientY];tpvEl.style.cursor='grabbing';e.preventDefault();});
addEventListener('mouseup',()=>{camDrag=null;tpvEl.style.cursor='grab';});
addEventListener('mousemove',e=>{
  if(!camDrag)return;
  camS.ta-=(e.clientX-camDrag[0])*0.4;
  camS.te=Math.max(5,Math.min(80,camS.te+(e.clientY-camDrag[1])*0.25));
  camDrag=[e.clientX,e.clientY];camDirty=true;
});
tpvEl.addEventListener('wheel',e=>{
  camS.tr=Math.max(2.5,Math.min(35,camS.tr*(e.deltaY>0?1.1:0.9)));
  camDirty=true;e.preventDefault();
},{passive:false});
setInterval(()=>{if(camDirty){camDirty=false;fetch('/cam',{method:'POST',body:JSON.stringify(camS)});}},120);
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        elif self.path.startswith("/stream/"):
            name = self.path.split("/")[-1]
            if name not in _frames:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            last = -1
            try:
                while True:
                    with _frame_cond:
                        _frame_cond.wait_for(lambda: _frame_seq[name] != last, timeout=2.0)
                        jpg = _frames[name]
                        last = _frame_seq[name]
                    if jpg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return
        elif self.path.startswith("/frame/"):
            jpg = _frames.get(self.path.split("/")[-1])
            if jpg is None:
                self.send_error(503)
                return
            self._send(jpg, "image/jpeg")
        elif self.path == "/layout":
            self._send(_MMAP, "application/json")
        elif self.path == "/status":
            with _state_lock:
                self._send(_json.dumps(_status).encode(), "application/json")
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        if self.path == "/cmd":
            try:
                data = _json.loads(raw)
                with _state_lock:
                    for k in _keys:
                        _keys[k] = bool(data.get(k, False))
                    _keys_time[0] = time.monotonic()
            except Exception:
                pass
        elif self.path == "/reset":
            _reset_req[0] = True
        elif self.path == "/goto":
            try:
                d = _json.loads(raw)
                _goto_req[0] = (float(d["x"]), float(d["y"]), float(d.get("z", 0.6)),
                                float(d.get("yaw", 0.0)))
            except Exception:
                pass
        elif self.path == "/traffic":
            try:
                d = _json.loads(raw)
                if _TRAF[0] is not None:
                    _TRAF[0].set_enabled(cars=d.get("cars"), peds=d.get("peds"))
                    print("[traffic] enabled:", _TRAF[0].enabled, flush=True)
            except Exception as e:
                print("[traffic] /traffic 오류:", e, flush=True)
        elif self.path == "/sigcfg":
            try:
                d = _json.loads(raw)
                if "blink" in d:
                    SIGCFG["blink"] = max(1.0, min(30.0, float(d["blink"])))
            except Exception:
                pass
        elif self.path == "/cam":
            try:
                data = _json.loads(raw)
                for k in list(CAMCFG):
                    if k in data:
                        CAMCFG[k] = float(data[k])
                print("[teleop] camcfg:", CAMCFG, flush=True)
            except Exception:
                pass
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


_httpd = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), _Handler)
_threading.Thread(target=_httpd.serve_forever, daemon=True).start()
print(f"[teleop] web serving on :{WEB_PORT}", flush=True)

# ---------- main loop ----------
VX_FWD, VX_BACK, VY, WZ = 1.2, -0.6, 0.5, 1.0
_tick_hist = []
step_i = 0
def _hide_env_terrain(tag=""):
    """URBAN-SIM 지형 패치 은폐 — 환경이 리셋마다 다시 보이게 하므로 재적용 필요"""
    try:
        from pxr import UsdGeom as _UG8, Usd as _U8, UsdPhysics as _UP8
        _st8 = omni.usd.get_context().get_stage()
        _n8 = 0
        for _c8 in _st8.GetPrimAtPath("/World").GetChildren():
            _nm8 = _c8.GetName()
            if _nm8.lower().startswith(("walkable", "nonwalkable", "obstacle", "terrain", "ground")):
                for _q8 in _U8.PrimRange(_c8):
                    if _q8.IsA(_UG8.Mesh):
                        _UG8.Imageable(_q8).MakeInvisible()
                        if _q8.HasAPI(_UP8.CollisionAPI):
                            _UP8.CollisionAPI(_q8).CreateCollisionEnabledAttr(False)
                        else:
                            _UP8.CollisionAPI.Apply(_q8).CreateCollisionEnabledAttr(False)
                        _n8 += 1
                _UG8.Imageable(_c8).MakeInvisible()
        if tag: print(f"[city] env terrain re-hidden{tag}: {_n8} meshes", flush=True)
    except Exception as _e8:
        print("[city] terrain hide 실패:", _e8, flush=True)

_hide_env_terrain(" (init)")

# ---------- 동적 트래픽 (차량·보행자) ----------
_TRAF = [None]
try:
    import sys as _sys3
    _sys3.path.insert(0, f"{_REPO}/teleop")
    from traffic import Traffic as _Traffic
    _tc = os.environ.get("TRAFFIC_CARS", "1") not in ("0", "false", "off")
    _tp = os.environ.get("TRAFFIC_PEDS", "1") not in ("0", "false", "off")
    _tn_c = int(os.environ["TRAFFIC_N_CARS"]) if os.environ.get("TRAFFIC_N_CARS") else None
    _tn_p = int(os.environ["TRAFFIC_N_PEDS"]) if os.environ.get("TRAFFIC_N_PEDS") else None
    _tsp = float(os.environ.get("TRAFFIC_SPEED", "1.0"))
    with open(_LAYOUT_JSON) as _lf3:
        _tlayout = _json.load(_lf3)
    _TRAF[0] = _Traffic(omni.usd.get_context().get_stage(), _tlayout, _REPO,
                        cars=_tc, peds=_tp, n_cars=_tn_c, n_peds=_tn_p, speed_scale=_tsp)
except Exception as _te:
    import traceback as _tb3
    print("[traffic] 초기화 실패:", _te, flush=True); _tb3.print_exc()
_traf_t = [time.monotonic()]
_terrain_recheck = [0]
while simulation_app.is_running():
    t0 = time.monotonic()
    with _state_lock:
        k = dict(_keys)
        stale = (time.monotonic() - _keys_time[0]) > 0.7
    if stale:
        k = {x: False for x in k}

    vx = VX_FWD if k["up"] else (VX_BACK if k["down"] else 0.0)
    vy = VY if k["sl"] else (-VY if k["sr"] else 0.0)
    wz = WZ if k["left"] else (-WZ if k["right"] else 0.0)
    if ACT_DIM == 3:
        act_v = [vx, vy, wz]
    elif ACT_DIM == 2:
        act_v = [vx, wz]
    else:
        act_v = [vx] * ACT_DIM
    action = torch.tensor([act_v], device=device, dtype=torch.float32)

    if _reset_req[0]:
        _reset_req[0] = False
        env.reset()
    if _goto_req[0] is not None:
        gx, gy, gz, gyaw = _goto_req[0]
        _goto_req[0] = None
        h2 = math.radians(gyaw) / 2.0
        pose = torch.tensor([[gx, gy, gz, math.cos(h2), 0.0, 0.0, math.sin(h2)]],
                            device=device, dtype=torch.float32)
        robot.write_root_pose_to_sim(pose)
        robot.write_root_velocity_to_sim(torch.zeros(1, 6, device=device))
        _des_yaw[0] = math.radians(gyaw)

    try:
        _sig_step()
        _terrain_recheck[0] += 1
        if _terrain_recheck[0] in (30, 200, 900):     # 리셋 후 환경이 되살리는 것을 재차 은폐
            _hide_env_terrain(f" (step {_terrain_recheck[0]})")
    except Exception as _se:
        pass
    if _TRAF[0] is not None:
        try:
            _now3 = time.monotonic()
            _dt3 = _now3 - _traf_t[0]; _traf_t[0] = _now3
            _rp3 = robot.data.root_pos_w[0].detach().cpu().numpy()
            _TRAF[0].step(_dt3, _SIG_NOW[0], (float(_rp3[0]), float(_rp3[1])))
        except Exception as _tse:
            if step_i % 200 == 0: print("[traffic] step 오류:", _tse, flush=True)
    if "town_signals" in globals():
        try:
            town_signals.step(0.1)
        except Exception:
            pass
    pos, yaw = _update_cameras()
    env.step(action)

    if step_i % 2 == 0:
        _capture("tpv", cam_tpv)
        _capture("ego", cam_ego)

    _tick_hist.append(time.monotonic() - t0)
    if len(_tick_hist) > 20:
        _tick_hist.pop(0)
    with _state_lock:
        _status["sim_fps"] = 1.0 / max(sum(_tick_hist) / len(_tick_hist), 1e-6)
        _status["loc"] = [float(pos[0]), float(pos[1]), float(pos[2])]
        _status["yaw"] = float(yaw)
        _status["cmd"] = [vx, vy, wz]
        try:
            _status["signal"] = town_ped_signal(float(pos[0]), float(pos[1]))
        except Exception:
            _status["signal"] = "-"
    step_i += 1

env.close()
simulation_app.close()
