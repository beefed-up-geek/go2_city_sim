#!/usr/bin/env python3
"""동적 트래픽 엔진 — 차량·보행자가 루프를 돌며 신호를 지키고 서로 피한다.

설계(도면 GCS-T-01):
  · 기구학 이동 — 물리 충돌체 없이 매 스텝 위치만 갱신(로봇이 밀리는 사고 없음)
  · 겹침은 규칙으로 예방: 차로 오프셋 / 선행차 추종 / 신호 시간분리 / 로봇 회피
  · 모든 경로는 닫힌 루프, 에이전트는 누적거리 s로 관리

teleop_append.py에서:
    traffic = Traffic(stage, layout, repo_root, cars=True, peds=True)
    traffic.step(dt, sig_state, robot_xy)
"""
import json, math, os, random

# ---------- 기하 유틸 ----------
def _seglen(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])

def polyline(pts, closed=True):
    """점열 -> (누적거리, 총길이) 테이블"""
    p = list(pts) + ([pts[0]] if closed else [])
    cum = [0.0]
    for i in range(len(p) - 1):
        cum.append(cum[-1] + _seglen(p[i], p[i + 1]))
    return p, cum, cum[-1]

def sample(p, cum, total, s):
    """누적거리 s 위치의 (x, y, heading)"""
    s = s % total
    lo, hi = 0, len(cum) - 1
    while lo + 1 < hi:                       # 이분 탐색
        mid = (lo + hi) // 2
        if cum[mid] <= s: lo = mid
        else: hi = mid
    a, b = p[lo], p[lo + 1]
    seg = cum[lo + 1] - cum[lo]
    t = (s - cum[lo]) / seg if seg > 1e-6 else 0.0
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
            math.atan2(b[1] - a[1], b[0] - a[0]))

def _set_v3(op, x, y, z, Gf):
    """xformOp 의 정밀도(double3/float3)에 맞춰 값을 쓴다."""
    try:
        op.Set(Gf.Vec3d(x, y, z))
    except Exception:
        op.Set(Gf.Vec3f(x, y, z))

def offset_loop(loop, off):
    """폐루프를 진행방향 우측으로 off 만큼 평행이동(우측통행 차로 중심).
    진행방향 (dx,dy)의 우측 법선은 (dy,-dx) — 루프 회전방향과 무관하다."""
    n = len(loop)
    out = []
    for i in range(n):
        pv, cu, nx = loop[i - 1], loop[i], loop[(i + 1) % n]
        d1 = (cu[0] - pv[0], cu[1] - pv[1]); d2 = (nx[0] - cu[0], nx[1] - cu[1])
        l1 = math.hypot(*d1) or 1.0; l2 = math.hypot(*d2) or 1.0
        u1 = (d1[0] / l1, d1[1] / l1); u2 = (d2[0] / l2, d2[1] / l2)
        n1 = (off * u1[1], -off * u1[0])            # 우측 법선
        n2 = (off * u2[1], -off * u2[0])
        a = (pv[0] + n1[0], pv[1] + n1[1])          # 두 오프셋 직선의 교점(마이터)
        b = (cu[0] + n2[0], cu[1] + n2[1])
        den = u1[0] * u2[1] - u1[1] * u2[0]
        if abs(den) < 1e-6:                          # 평행 → 그대로 평행이동
            out.append((cu[0] + n1[0], cu[1] + n1[1]))
        else:
            t = ((b[0] - a[0]) * u2[1] - (b[1] - a[1]) * u2[0]) / den
            out.append((a[0] + u1[0] * t, a[1] + u1[1] * t))
    return out

# ---------- 편성표(도면 GCS-T-01 §02·§03) ----------
CAR_PLAN = [   # (route, 대수, 순항 m/s, 에셋 목록)
    ("V1", 3, 9.0, ["car_389f9ebcaeb84cbfb020a88a25751edc", "car_5416965277554e7682fcc2dc4961a99d",
                    "car_af108d4773df4722a62420f65dd5b8fe"]),
    ("V2", 3, 8.0, ["car_d893ecd4f4d94f509aa7312306d74c61", "car_03a6d639648540e3ad45ed38c9b19d1f",
                    "car_f3c9f419c0924e968deed17196248c98"]),
    ("V3", 2, 8.5, ["car_af108d4773df4722a62420f65dd5b8fe", "car_389f9ebcaeb84cbfb020a88a25751edc"]),
    ("V4", 2, 7.5, ["car_5416965277554e7682fcc2dc4961a99d", "car_d893ecd4f4d94f509aa7312306d74c61"]),
    ("V5", 1, 3.0, ["car_03a6d639648540e3ad45ed38c9b19d1f"]),
]
PED_PLAN = [("P1", 4, 1.25), ("P2", 4, 1.15), ("P3", 3, 1.35), ("P4", 3, 1.10), ("P5", 3, 1.45)]

LANE_OFF = 1.75        # 차로 중심 오프셋
CAR_W, CAR_L = 1.85, 4.4
HEADWAY, GAP_MIN = 8.0, 4.0
STOP_MARGIN = 0.6      # 정지선 앞 여유
ROBOT_STOP_CAR, ROBOT_STOP_PED = 8.0, 2.0
PED_W = 0.62
PED_LIFT = 0.105      # 보도·블록 상면 높이(연석 105 mm)

# ---------- 보행자(NVIDIA People + AnimationGraph) ----------
# Walk 상태는 Blend(idle, MotionMatching, weight=변수 Walk) 이고, MotionMatching
# 노드가 변수 PathPoints 를 받아 걷기 클립 12종을 골라 섞으며 캐릭터를 직접
# 이동시킨다. 따라서 위치를 매 프레임 써넣으면 안 되고, 경로를 주고 위치는
# get_world_transform 으로 읽어온다.
AG_PATH = "/World/Characters/Biped_Setup/CharacterAnimation/AnimationGraph"
PED_LOOKAHEAD = 40.0   # 한 번에 넘겨주는 경로 길이
PED_REISSUE_AT = 12.0  # 남은 경로가 이보다 짧아지면 갱신
PED_WP_REACH = 1.5     # 경유점 통과 판정
PED_STOP_DIST = 2.0    # 신호 정지선 앞 이 거리에서 정지
PED_SEP = 1.2          # 같은 통행선 앞사람과 최소 간격
PED_STALL_S = 20.0     # 신호와 무관하게 이만큼 멈춰 있으면 경로 재발급


class Agent:
    __slots__ = ("s", "v", "vmax", "prim", "path", "cum", "total", "kind", "wait", "yaw0", "lift")
    def __init__(self, s, vmax, prim, path, cum, total, kind, yaw0=0.0, lift=0.0):
        self.s, self.v, self.vmax = s, vmax, vmax
        self.prim, self.path, self.cum, self.total = prim, path, cum, total
        self.kind, self.wait, self.yaw0, self.lift = kind, False, yaw0, lift


class PedAgent:
    """애니메이션 그래프가 구동하는 보행자. 위치는 우리가 쓰지 않고 읽는다."""
    __slots__ = ("skel", "prim", "c", "wp", "i", "x", "y", "hd", "v", "line",
                 "kind", "wait", "stopped", "last", "asset", "stall", "ref")
    def __init__(self, skel, prim, wp, i, x, y, asset, line):
        self.skel, self.prim, self.c = skel, prim, None
        self.wp, self.i, self.line = wp, i, line
        self.x, self.y, self.hd, self.v = x, y, 0.0, 1.0
        self.kind, self.wait, self.stopped = "ped", False, False
        self.last, self.asset = (x, y), asset
        self.stall, self.ref = 0.0, (x, y)     # 정체 감시(초, 기준 위치)


class Traffic:
    def __init__(self, stage, layout, repo_root, cars=True, peds=True,
                 n_cars=None, n_peds=None, speed_scale=1.0, seed=7, log=print):
        from pxr import UsdGeom, Usd, Gf
        self._UsdGeom, self._Usd, self._Gf = UsdGeom, Usd, Gf
        self.stage, self.L, self.root = stage, layout, repo_root
        self.speed_scale = speed_scale
        self.log = log
        self.rng = random.Random(seed)
        self.agents = []
        self.peds = []                      # 애니메이션 보행자(PedAgent)
        self.enabled = {"cars": cars, "peds": peds}
        self.stop_pts = self._stop_points()
        UsdGeom.Xform.Define(stage, "/World/Traffic")
        if cars: self._spawn_cars(n_cars)
        if peds: self._spawn_peds(n_peds)
        log(f"[traffic] 차량 {sum(1 for a in self.agents if a.kind=='car')}대 · "
            f"보행자 {len(self.peds) + sum(1 for a in self.agents if a.kind=='ped')}명 배치",
            flush=True)

    # ----- 정지선: (x, y, 축, 교차로중심) -----
    def _stop_points(self):
        pts = []
        for cw in self.L["crosswalks"]:
            cx, cy = cw["center"]; dp = cw["depth"]
            axis = cw["axis"]                      # 'v' = 남북도로 위 횡단보도
            pts.append({"c": (cx, cy), "axis": axis,
                        "half_car": dp / 2 + STOP_MARGIN + CAR_L / 2,   # 차체 앞이 정지선 앞에 서도록
                        "half_ped": dp / 2 + 0.3})
        return pts

    # ----- 에셋 프로토 생성(빌드의 make_proto와 동일 규칙) -----
    def _proto(self, name, asset_path, target_w_min=None, target_h=None):
        UsdGeom, Usd, Gf = self._UsdGeom, self._Usd, self._Gf
        p = f"/World/Traffic/_p/{name}"
        if self.stage.GetPrimAtPath(p).IsValid():
            return p, self._fp.get(name, (1, 1, 1))
        UsdGeom.Xform.Define(self.stage, "/World/Traffic/_p")
        root = UsdGeom.Xform.Define(self.stage, p)
        fix = UsdGeom.Xform.Define(self.stage, p + "/fix")
        g = UsdGeom.Xform.Define(self.stage, p + "/fix/g")
        g.GetPrim().GetReferences().AddReference(asset_path)
        lay = Usd.Stage.Open(asset_path)
        up = UsdGeom.GetStageUpAxis(lay); mpu = UsdGeom.GetStageMetersPerUnit(lay) or 1.0
        bb = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render", "proxy"]) \
            .ComputeWorldBound(lay.GetPseudoRoot()).ComputeAlignedRange()
        mn = [bb.GetMin()[i] for i in range(3)]; mx = [bb.GetMax()[i] for i in range(3)]
        size = [(mx[i] - mn[i]) * mpu for i in range(3)]
        h = size[1] if up == "Y" else size[2]
        wmin = min(size[0], size[2] if up == "Y" else size[1])
        s = 1.0
        if target_w_min and wmin > 1e-4: s = target_w_min / wmin
        if target_h and h > 1e-4: s = target_h / h
        k = mpu * s
        if up == "Y": cx_, cy_, z0 = (mn[0]+mx[0])/2, -(mn[2]+mx[2])/2, mn[1]
        else:         cx_, cy_, z0 = (mn[0]+mx[0])/2, (mn[1]+mx[1])/2, mn[2]
        xf = UsdGeom.Xformable(fix)
        xf.AddTranslateOp().Set(Gf.Vec3d(-cx_*k, -cy_*k, -z0*k))
        xf.AddRotateXOp().Set(90.0 if up == "Y" else 0.0)
        xf.AddScaleOp().Set(Gf.Vec3f(k))
        fw, fd, fh = size[0]*s, (size[2] if up == "Y" else size[1])*s, h*s
        self._fp = getattr(self, "_fp", {}); self._fp[name] = (fw, fd, fh)
        return p, (fw, fd, fh)

    # ----- 차량 -----
    def _spawn_cars(self, n_limit):
        from pxr import Sdf, UsdGeom, Gf
        routes = {r["id"]: r for r in self.L["routes"]["cars"]}
        made = 0
        for rid, cnt, vmax, assets in CAR_PLAN:
            if rid not in routes: continue
            lp = offset_loop([tuple(p) for p in routes[rid]["loop"]], LANE_OFF)
            path, cum, total = polyline(lp, closed=True)
            for i in range(cnt):
                if n_limit is not None and made >= n_limit: return
                a = assets[i % len(assets)]
                usd = f"{self.root}/assets/usd/objects/{a}/{a}.usd"
                if not os.path.isfile(usd):
                    self.log(f"[traffic] 에셋 없음: {a}", flush=True); continue
                proto, fp = self._proto(f"car_{a[:12]}", usd, target_w_min=CAR_W)
                pp = f"/World/Traffic/car{made}"
                xf = UsdGeom.Xform.Define(self.stage, pp)
                xf.GetPrim().GetReferences().AddInternalReference(Sdf.Path(proto))
                xf.AddTranslateOp(); xf.AddRotateZOp()
                yaw0 = 90.0 if fp[1] > fp[0] else 0.0     # 모델 장축을 진행방향으로
                v = vmax * self.speed_scale * self.rng.uniform(0.85, 1.15)
                self.agents.append(Agent(total * i / max(cnt, 1), v, xf, path, cum, total, "car", yaw0))
                made += 1

    # ----- 보행자: NVIDIA People 캐릭터 + AnimationGraph -----
    def _spawn_peds(self, n_limit):
        """공식 파이프라인. 실패하면 정지 자세 보행자로 자동 대체한다."""
        import glob as _glob
        try:
            import AnimGraphSchema                      # noqa: F401  (확장 활성화 확인)
            import omni.anim.graph.core                 # noqa: F401
        except Exception as e:
            self.log(f"[traffic] anim 확장 미활성({e}) — 정지 보행자로 대체", flush=True)
            return self._spawn_peds_static(n_limit)
        ppl = f"{self.root}/assets/usd/people"
        biped = f"{ppl}/Characters/Biped_Setup.usd"
        # biped_demo 는 그래프 데모용, original_* 은 리타게팅 전 원본(같은 인물)이라 제외
        chars = sorted(f"{d}/{os.path.basename(d)}.usd"
                       for d in _glob.glob(f"{ppl}/Characters/*")
                       if os.path.isdir(d) and os.path.basename(d) != "biped_demo"
                       and not os.path.basename(d).startswith("original_"))
        chars = [c for c in chars if os.path.isfile(c)]
        if not os.path.isfile(biped) or not chars:
            self.log(f"[traffic] People 에셋 없음({ppl}) — 정지 보행자로 대체", flush=True)
            return self._spawn_peds_static(n_limit)

        import AnimGraphSchema
        from pxr import Usd, UsdGeom, UsdSkel, Gf
        UsdGeom.Xform.Define(self.stage, "/World/Characters")
        bs = self.stage.DefinePrim("/World/Characters/Biped_Setup", "Xform")
        bs.GetReferences().AddReference(biped)
        UsdGeom.Imageable(bs).MakeInvisible()           # 그래프 공급원일 뿐 — 화면 제외

        routes = {r["id"]: r for r in self.L["routes"]["peds"]}
        made = 0
        for rid, cnt, _vmax in PED_PLAN:
            if rid not in routes: continue
            lp = [tuple(q) for q in routes[rid]["loop"]]
            for i in range(cnt):
                if n_limit is not None and made >= n_limit: return
                wp = offset_loop(lp, 0.7 if i % 2 == 0 else -0.7)   # 보도 2개 통행선
                n = len(wp)
                i0 = (i * max(1, n // max(cnt, 1))) % n             # 루프상 시작점 분산
                x0, y0 = wp[i0]
                nx, ny = wp[(i0 + 1) % n]
                cusd = chars[made % len(chars)]
                pp = f"/World/Characters/ped{made}"
                pr = self.stage.DefinePrim(pp, "Xform")
                pr.GetReferences().AddReference(cusd)
                # 캐릭터 USD 루트에 이미 translate/rotate/scale 옵이 있으므로 그 옵을
                # 직접 쓴다(정밀도가 파일마다 달라 CommonAPI 로는 타입 불일치가 난다).
                yaw0 = math.degrees(math.atan2(ny - y0, nx - x0))
                for op in UsdGeom.Xformable(pr).GetOrderedXformOps():
                    nm = op.GetOpName()
                    if "translate" in nm: _set_v3(op, x0, y0, PED_LIFT, Gf)
                    elif "rotate" in nm:  _set_v3(op, 0.0, 0.0, yaw0, Gf)
                sr = next((q for q in Usd.PrimRange(pr) if q.IsA(UsdSkel.Root)), None)
                if sr is None:
                    self.log(f"[traffic] SkelRoot 없음: {cusd}", flush=True); continue
                AnimGraphSchema.AnimationGraphAPI.Apply(sr) \
                    .GetAnimationGraphRel().SetTargets([AG_PATH])
                self.peds.append(PedAgent(str(sr.GetPath()), pr, wp, i0 + 1, x0, y0,
                                          os.path.basename(cusd), f"{rid}{i % 2}"))
                made += 1
        self.log(f"[traffic] 보행자 {made}명 · 캐릭터 {len(chars)}종 "
                 f"(예: {', '.join(os.path.basename(c)[:-4] for c in chars[:3])})", flush=True)

    # ----- 보행자(대체): 애니메이션 없는 정지 자세 -----
    def _spawn_peds_static(self, n_limit):
        from pxr import Sdf, UsdGeom
        routes = {r["id"]: r for r in self.L["routes"]["peds"]}
        import glob as _glob
        _anim = sorted(_glob.glob(f"{self.root}/assets/usd/peds_anim/*.usd"))     # 걷기 애니메이션판
        _plain = sorted(_glob.glob(f"{self.root}/assets/usd/peds/*/*.usd"))       # 정지 자세 원본
        _mode = os.environ.get("TRAFFIC_PED_ASSET", "anim")                       # anim | plain | mix
        if _mode == "plain": cand = _plain or _anim
        elif _mode == "mix": cand = [x for pair in zip(_anim, _plain) for x in pair] or _anim or _plain
        else: cand = _anim or _plain
        self.log(f"[traffic] 보행자 에셋 모드={_mode} 후보 {len(cand)}종", flush=True)
        if not cand:
            self.log("[traffic] 보행자 USD 없음 — 보행자 생략(변환 필요)", flush=True); return
        made = 0
        for rid, cnt, vmax in PED_PLAN:
            if rid not in routes: continue
            lp = [tuple(p) for p in routes[rid]["loop"]]
            for i in range(cnt):
                if n_limit is not None and made >= n_limit: return
                side = 0.7 if i % 2 == 0 else -0.7           # 보도 2개 통행선
                path, cum, total = polyline(offset_loop(lp, side), closed=True)
                usd = cand[made % len(cand)]
                proto, fp = self._proto(f"ped_{made%len(cand)}", usd, target_h=1.7)
                if made < 4:
                    self.log(f"[traffic]  ped{made} ← {os.path.basename(usd)} "
                             f"{fp[0]:.2f}x{fp[1]:.2f}x{fp[2]:.2f}", flush=True)
                pp = f"/World/Traffic/ped{made}"
                xf = UsdGeom.Xform.Define(self.stage, pp)
                xf.GetPrim().GetReferences().AddInternalReference(Sdf.Path(proto))
                xf.AddTranslateOp(); xf.AddRotateZOp()
                v = vmax * self.speed_scale * self.rng.uniform(0.85, 1.15)
                self.agents.append(Agent(total * i / max(cnt, 1) + self.rng.uniform(0, 3),
                                         v, xf, path, cum, total, "ped", 0.0, lift=PED_LIFT))
                made += 1

    # ----- 신호 판정 -----
    def _blocked_by_signal(self, a, x, y, hd):
        """다음 정지선까지의 거리로 정지 여부 판단"""
        ns, ew, pd = self.sig
        best = None
        for sp in self.stop_pts:
            cx, cy = sp["c"]
            dx, dy = cx - x, cy - y
            ahead = dx * math.cos(hd) + dy * math.sin(hd)      # 진행방향 성분
            lat = abs(-dx * math.sin(hd) + dy * math.cos(hd))
            if ahead < 0 or ahead > 26 or lat > 6.0: continue
            d = ahead - (sp["half_car"] if a.kind == "car" else sp["half_ped"])
            if best is None or d < best[0]: best = (d, sp)
        if best is None: return None
        d, sp = best
        if a.kind == "car":
            moving_ns = abs(math.sin(hd)) > 0.7                # 남북 진행
            col = ns if moving_ns else ew
            if col == "green": return None
            if col == "yellow" and d < a.v * 2.0: return None  # 딜레마 존: 통과
        else:
            if pd in ("grn",): return None                     # 보행 녹색만 진입
            if pd == "cnt" and d < 0.5: return None            # 이미 진입한 사람은 통과
        return max(0.0, d)

    # ----- 보행자 경로 발급 -----
    def _issue(self, p):
        """현재 위치에서 루프를 따라 PED_LOOKAHEAD 만큼의 경로를 넘겨준다."""
        import carb
        pts = [carb.Float3(p.x, p.y, PED_LIFT)]
        n = len(p.wp)
        prev, d, k = (p.x, p.y), 0.0, 0
        while d < PED_LOOKAHEAD and k < n:
            w = p.wp[(p.i + k) % n]
            d += math.hypot(w[0] - prev[0], w[1] - prev[1])
            pts.append(carb.Float3(w[0], w[1], PED_LIFT))
            prev = w; k += 1
        p.last = prev
        p.c.set_variable("PathPoints", pts)
        p.c.set_variable("Walk", 1.0)
        p.c.set_variable("Action", "Walk")

    # ----- 보행자 한 스텝 -----
    def _step_peds(self, dt, robot_xy):
        import carb, omni.anim.graph.core as ag
        for p in self.peds:
            if p.c is None:                       # 캐릭터 매니저 준비 후에야 잡힌다
                p.c = ag.get_character(p.skel)
                if p.c is None: continue
                self._issue(p)
            pos = carb.Float3(0, 0, 0); rot = carb.Float4(0, 0, 0, 0)
            p.c.get_world_transform(pos, rot)
            p.x, p.y = float(pos[0]), float(pos[1])
            n = len(p.wp)
            if math.hypot(p.wp[p.i % n][0] - p.x, p.wp[p.i % n][1] - p.y) < PED_WP_REACH:
                p.i += 1
            tx, ty = p.wp[p.i % n]
            p.hd = math.atan2(ty - p.y, tx - p.x)

            stop = False
            d_sig = self._blocked_by_signal(p, p.x, p.y, p.hd)
            if d_sig is not None and d_sig < PED_STOP_DIST:
                stop = True
            if not stop and robot_xy is not None:
                rdx, rdy = robot_xy[0] - p.x, robot_xy[1] - p.y
                ah = rdx * math.cos(p.hd) + rdy * math.sin(p.hd)
                la = abs(-rdx * math.sin(p.hd) + rdy * math.cos(p.hd))
                if 0 < ah < ROBOT_STOP_PED and la < 0.9: stop = True
            if not stop:                          # 같은 통행선의 앞사람만 추돌 방지
                for q in self.peds:               # (다른 노선까지 보면 서로 묶여 교착)
                    if q is p or q.line != p.line: continue
                    qx, qy = q.x - p.x, q.y - p.y
                    ah = qx * math.cos(p.hd) + qy * math.sin(p.hd)
                    la = abs(-qx * math.sin(p.hd) + qy * math.cos(p.hd))
                    if 0 < ah < PED_SEP and la < 0.5: stop = True; break

            # 정체 감시: 신호 대기가 아닌데 오래 안 움직이면 경로를 다시 발급
            if math.hypot(p.ref[0] - p.x, p.ref[1] - p.y) > 0.3:
                p.ref, p.stall = (p.x, p.y), 0.0
            else:
                p.stall += dt
                if p.stall > PED_STALL_S and d_sig is None:
                    p.stall, p.stopped, stop = 0.0, False, False
                    self._issue(p)
                    self._stalls = getattr(self, "_stalls", 0) + 1
                    if self._stalls <= 5:
                        self.log(f"[traffic] 보행자 정체 해소 {p.skel.split('/')[3]}", flush=True)

            if stop != p.stopped:
                p.stopped = stop
                if stop: p.c.set_variable("Action", "None")   # 제자리 대기로 전이
                else:    self._issue(p)
            elif not stop and math.hypot(p.last[0] - p.x, p.last[1] - p.y) < PED_REISSUE_AT:
                self._issue(p)                    # 경로가 짧아지기 전에 이어붙임
            p.wait = stop
            p.v = 0.0 if stop else 1.0

    # ----- 한 스텝 -----
    def step(self, dt, sig_state, robot_xy=None):
        self.sig = sig_state
        dt = max(1e-3, min(dt, 0.5))
        if self.peds and self.enabled.get("peds", True):
            try: self._step_peds(dt, robot_xy)
            except Exception as e:
                if not getattr(self, "_ped_err", False):
                    self._ped_err = True
                    self.log(f"[traffic] 보행자 스텝 오류: {e}", flush=True)
        by_path = {}
        for a in self.agents:
            by_path.setdefault(id(a.path), []).append(a)
        for a in self.agents:
            if not self.enabled.get(a.kind + "s", True): continue
            x, y, hd = sample(a.path, a.cum, a.total, a.s)
            target = a.vmax
            # 1) 신호
            d_sig = self._blocked_by_signal(a, x, y, hd)
            if d_sig is not None:
                # 정지 목표속도 = sqrt(2·a·d) 형태로 매끄럽게 감속
                target = min(target, math.sqrt(max(0.0, d_sig) * 2.0 * 2.2))
            # 2) 선행 개체 추종(같은 경로)
            lead = None
            for b in by_path[id(a.path)]:
                if b is a: continue
                gap = (b.s - a.s) % a.total
                if gap < (HEADWAY + 6.0) and (lead is None or gap < lead): lead = gap
            if lead is not None:
                if lead < GAP_MIN: target = 0.0
                elif lead < HEADWAY: target = min(target, a.vmax * (lead - GAP_MIN) / (HEADWAY - GAP_MIN))
            # 3) COCO 로봇 회피
            if robot_xy is not None:
                rdx, rdy = robot_xy[0] - x, robot_xy[1] - y
                rd = math.hypot(rdx, rdy)
                ahead = rdx * math.cos(hd) + rdy * math.sin(hd)
                lat = abs(-rdx * math.sin(hd) + rdy * math.cos(hd))
                lim = ROBOT_STOP_CAR if a.kind == "car" else ROBOT_STOP_PED
                if 0 < ahead < lim and lat < (2.0 if a.kind == "car" else 1.0):
                    target = min(target, max(0.0, (ahead - 1.5)) * 0.5)
            # 4) 가감속
            acc = 3.0 if a.kind == "car" else 1.2
            a.v += max(-acc * 2.5 * dt, min(acc * dt, target - a.v))
            a.v = max(0.0, a.v)
            a.wait = a.v < 0.05
            a.s = (a.s + a.v * dt) % a.total
            nx, ny, nhd = sample(a.path, a.cum, a.total, a.s)
            ops = a.prim.GetOrderedXformOps()
            ops[0].Set(self._Gf.Vec3d(nx, ny, a.lift))
            ops[1].Set(math.degrees(nhd) + a.yaw0)

    def set_enabled(self, cars=None, peds=None):
        from pxr import UsdGeom
        if cars is not None: self.enabled["cars"] = bool(cars)
        if peds is not None: self.enabled["peds"] = bool(peds)
        for a in self.agents:
            vis = self.enabled.get(a.kind + "s", True)
            im = UsdGeom.Imageable(a.prim.GetPrim())
            im.MakeVisible() if vis else im.MakeInvisible()
        vis = self.enabled.get("peds", True)
        for p in self.peds:
            im = UsdGeom.Imageable(p.prim)
            im.MakeVisible() if vis else im.MakeInvisible()
            if p.c is not None and not vis:
                p.c.set_variable("Action", "None")
                p.stopped = True

    def stats(self):
        c = [a for a in self.agents if a.kind == "car"]
        sp = [a for a in self.agents if a.kind == "ped"]      # 대체 경로(정지 보행자)
        def _pos(a):
            x, y, _ = sample(a.path, a.cum, a.total, a.s)
            return [round(x, 1), round(y, 1), round(a.v, 1)]
        ped_pos = [[round(p.x, 1), round(p.y, 1), round(p.v, 1)] for p in self.peds[:4]] \
            or [_pos(a) for a in sp[:4]]
        return {"cars": len(c) if self.enabled["cars"] else 0,
                "peds": (len(self.peds) + len(sp)) if self.enabled["peds"] else 0,
                "anim_peds": sum(1 for p in self.peds if p.c is not None),
                "waiting": sum(1 for a in self.agents if a.wait) + sum(1 for p in self.peds if p.wait),
                "ped_pos": ped_pos,
                "car_pos": [_pos(a) for a in c[:3]]}
