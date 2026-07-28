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


class Agent:
    __slots__ = ("s", "v", "vmax", "prim", "path", "cum", "total", "kind", "wait", "yaw0", "lift")
    def __init__(self, s, vmax, prim, path, cum, total, kind, yaw0=0.0, lift=0.0):
        self.s, self.v, self.vmax = s, vmax, vmax
        self.prim, self.path, self.cum, self.total = prim, path, cum, total
        self.kind, self.wait, self.yaw0, self.lift = kind, False, yaw0, lift


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
        self.enabled = {"cars": cars, "peds": peds}
        self.stop_pts = self._stop_points()
        UsdGeom.Xform.Define(stage, "/World/Traffic")
        if cars: self._spawn_cars(n_cars)
        if peds: self._spawn_peds(n_peds)
        log(f"[traffic] 차량 {sum(1 for a in self.agents if a.kind=='car')}대 · "
            f"보행자 {sum(1 for a in self.agents if a.kind=='ped')}명 배치", flush=True)

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

    # ----- 보행자 -----
    def _spawn_peds(self, n_limit):
        from pxr import Sdf, UsdGeom
        routes = {r["id"]: r for r in self.L["routes"]["peds"]}
        import glob as _glob
        cand = sorted(_glob.glob(f"{self.root}/assets/usd/peds_anim/*.usd"))      # 걷기 애니메이션판 우선
        if not cand:
            cand = sorted(_glob.glob(f"{self.root}/assets/usd/peds/*/*.usd"))
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
                if made == 0:
                    self.log(f"[traffic] 보행자 에셋 {os.path.basename(usd)} 스케일 후 "
                             f"{fp[0]:.2f}x{fp[1]:.2f}x{fp[2]:.2f} m", flush=True)
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

    # ----- 한 스텝 -----
    def step(self, dt, sig_state, robot_xy=None):
        self.sig = sig_state
        dt = max(1e-3, min(dt, 0.5))
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

    def stats(self):
        c = [a for a in self.agents if a.kind == "car"]
        p = [a for a in self.agents if a.kind == "ped"]
        def _pos(a):
            x, y, _ = sample(a.path, a.cum, a.total, a.s)
            return [round(x, 1), round(y, 1), round(a.v, 1)]
        return {"cars": len(c) if self.enabled["cars"] else 0,
                "peds": len(p) if self.enabled["peds"] else 0,
                "waiting": sum(1 for a in self.agents if a.wait),
                "ped_pos": [_pos(a) for a in p[:4]],
                "car_pos": [_pos(a) for a in c[:3]]}
