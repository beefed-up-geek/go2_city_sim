#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신호 운영 계획 v1: city_layout.json -> 애니메이션 신호 계획 웹페이지 (기존 2D 도면 아티팩트 갱신)"""
import json

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = f"{ROOT}/assets"      # 입력: city_layout.json
PO = f"{ROOT}/docs"       # 출력: city_plan.html
L = json.load(open(f"{P}/city_layout.json"))
GEXT = 77.0
S = 8.0
W = int(2 * GEXT * S)

def X(x): return (x + GEXT) * S
def Y(y): return (GEXT - y) * S

parts = []
def rect(x1, y1, x2, y2, fill, extra=""):
    parts.append(f'<rect x="{X(x1):.0f}" y="{Y(y2):.0f}" width="{(x2-x1)*S:.0f}" height="{(y2-y1)*S:.0f}" fill="{fill}" {extra}/>')

GR = L["ground"]
rect(-GEXT, -GEXT, GEXT, GEXT, "var(--grass)")
for r in GR["block"]: rect(*r, "var(--block)")
for r in GR["fill"]: rect(*r, "var(--block)")
for r in GR["walk"]: rect(*r, "var(--walk)")
for r in GR["narrow"]: rect(*r, "var(--walk)")
for r in GR["road"]: rect(*r, "var(--road)")
for r in GR["brick"]: rect(*r, "var(--brick)")
RW = 3.5
for cw in L["crosswalks"]:
    cx, cy = cw["center"]; dp = cw["depth"]
    if cw["axis"] == "v":
        x = cx - RW + 0.35
        while x < cx + RW - 0.3:
            rect(x, cy-dp/2, x+0.7, cy+dp/2, "var(--zebra)"); x += 1.4
    else:
        y = cy - RW + 0.35
        while y < cy + RW - 0.3:
            rect(cx-dp/2, y, cx+dp/2, y+0.7, "var(--zebra)"); y += 1.4
# 코스(참고, 옅게)
wp = L["course"]["waypoints"]
pts = " ".join(f"{X(x):.0f},{Y(y):.0f}" for (x, y) in wp)
parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--coco)" stroke-width="3" opacity="0.28"/>')

# 신호등: 차량(그룹 NS/EW) + 보행(전부 P그룹)
veh_js, ped_js = [], []
for v in L["veh_lights"]:
    grp = "NS" if v["arm"][0] != 0 else "EW"           # 암이 x방향=세로도로 위=남북 통행 담당
    hx, hy = v["head"]
    px, py = v["pos"]
    parts.append(f'<line x1="{X(px):.0f}" y1="{Y(py):.0f}" x2="{X(hx):.0f}" y2="{Y(hy):.0f}" stroke="var(--ink3)" stroke-width="2"/>')
    parts.append(f'<circle cx="{X(px):.0f}" cy="{Y(py):.0f}" r="2.6" fill="var(--ink)"/>')
    veh_js.append(dict(x=round(X(hx)), y=round(Y(hy)), g=grp))
for p in L["ped_lights"]:
    px, py = p["pos"]
    ped_js.append(dict(x=round(X(px)), y=round(Y(py))))
for (ix, iy) in L["meta"]["intersections"]:
    parts.append(f'<text x="{X(ix):.0f}" y="{Y(iy)+4:.0f}" class="il">{"NW" if ix<0 and iy>0 else "NE" if ix>0 and iy>0 else "SW" if ix<0 else "SE"}</text>')

svg = (f'<svg id="map" viewBox="0 0 {W} {W}" xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>")

html = f"""<title>신호 운영 계획 v1 — 루프 코스 도시</title>
<style>
:root {{ --paper:#F5F4EF; --panel:#FFF; --ink:#23282D; --ink2:#4C555E; --ink3:#6B7681; --line:#DDD9CE;
 --grass:#A9BE93; --block:#DFDACC; --walk:#CFC8B8; --road:#4A5058; --brick:#B37A5E; --zebra:#F2EFE6;
 --coco:#D92D20; --red:#E5484D; --yel:#F5B62E; --grn:#30A46C; --off:#3A3F45; }}
@media (prefers-color-scheme: dark) {{ :root {{ --paper:#191C20; --panel:#22262B; --ink:#E8E6E1; --ink2:#B9BDC2;
 --ink3:#8C949C; --line:#3A3F45; --grass:#4A5A42; --block:#3A3D40; --walk:#4E4C45; --road:#23272C;
 --brick:#7E5745; --zebra:#C9C5B8; --coco:#F2555A; --off:#15171A; }} }}
:root[data-theme="dark"] {{ --paper:#191C20; --panel:#22262B; --ink:#E8E6E1; --ink2:#B9BDC2; --ink3:#8C949C;
 --line:#3A3F45; --grass:#4A5A42; --block:#3A3D40; --walk:#4E4C45; --road:#23272C; --brick:#7E5745;
 --zebra:#C9C5B8; --coco:#F2555A; --off:#15171A; }}
:root[data-theme="light"] {{ --paper:#F5F4EF; --panel:#FFF; --ink:#23282D; --ink2:#4C555E; --ink3:#6B7681;
 --line:#DDD9CE; --grass:#A9BE93; --block:#DFDACC; --walk:#CFC8B8; --road:#4A5058; --brick:#B37A5E;
 --zebra:#F2EFE6; --coco:#D92D20; --off:#3A3F45; }}
* {{ box-sizing:border-box; }}
body {{ background:var(--paper); color:var(--ink); margin:0; padding:26px 18px 60px;
 font-family:"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif; line-height:1.55; }}
main {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:1.4rem; margin:0 0 4px; text-wrap:balance; }}
.sub {{ color:var(--ink2); font-size:0.92rem; margin:0 0 16px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:16px; }}
#map {{ width:100%; height:auto; display:block; border-radius:6px; }}
.il {{ font:700 15px sans-serif; fill:#fff; text-anchor:middle; paint-order:stroke; stroke:#0008; stroke-width:3px; }}
#bar {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px; }}
#tl {{ flex:1 1 420px; height:34px; border-radius:7px; overflow:hidden; display:flex; position:relative; min-width:300px; cursor:pointer; }}
.seg {{ height:100%; display:flex; align-items:center; justify-content:center; font-size:11.5px; font-weight:700; color:#fff; text-shadow:0 1px 2px #0007; }}
#cursor {{ position:absolute; top:0; bottom:0; width:2.5px; background:#fff; box-shadow:0 0 4px #000a; }}
button {{ background:var(--panel); color:var(--ink); border:1px solid var(--line); border-radius:7px; padding:5px 14px; font-size:0.9rem; cursor:pointer; }}
button:hover {{ border-color:var(--ink3); }}
#clock {{ font-variant-numeric:tabular-nums; font-weight:700; min-width:88px; }}
table {{ border-collapse:collapse; width:100%; font-size:0.88rem; }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }}
th {{ font-size:0.78rem; letter-spacing:0.05em; color:var(--ink3); text-transform:uppercase; }}
td.n {{ font-variant-numeric:tabular-nums; }}
.dot {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
.note {{ color:var(--ink2); font-size:0.88rem; }}
h2 {{ font-size:1.02rem; margin:22px 0 10px; }}
</style>
<main>
<h1>신호 운영 계획 v1.4 — 3페이즈 사이클 43.8초 (교차로 4개 동기화 · 비보호 좌회전)</h1>
<p class="sub">▶ 재생을 누르면 아래 지도에서 차량등 16기·보행등 28기(횡단보도 양끝 대각 배치)가 실제 계획대로 순환합니다. 보행 페이즈에는 <b>모든 교차로의 보행신호가 동시에 녹색</b>이 됩니다(요청 반영).</p>

<div class="card">
<div id="bar">
  <button id="play">⏸ 일시정지</button>
  <button id="speed">배속 ×4</button>
  <span id="clock">t = 0.0s</span>
  <div id="tl"></div>
  <span id="phase" style="font-weight:700"></span>
</div>
{svg}
</div>

<h2>페이즈 구성 (사이클 42초, 전 교차로 공통 시계)</h2>
<table>
<thead><tr><th>페이즈</th><th class="n">구간</th><th>차량등 (남북 그룹)</th><th>차량등 (동서 그룹)</th><th>보행등 (전 방향)</th></tr></thead>
<tbody>
<tr><td><b>V1 남북 통행</b></td><td class="n">0–10s</td><td><span class="dot" style="background:var(--grn)"></span>녹색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td>V1 황색</td><td class="n">10–13s</td><td><span class="dot" style="background:var(--yel)"></span>황색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td>전적색 ①</td><td class="n">13–14s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td><b>V2 동서 통행</b></td><td class="n">14–24s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--grn)"></span>녹색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td>V2 황색</td><td class="n">24–27s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--yel)"></span>황색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td>전적색 ②</td><td class="n">27–28s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
<tr><td><b>P 동시 보행</b></td><td class="n">28–36s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--grn)"></span><b>전 방향 녹색</b></td></tr>
<tr><td>P 녹색 점멸 (기본 5.8s = 횡단보도 7m ÷ COCO 1.2m/s, <b>파라미터로 조절</b>)</td><td class="n">36–41.8s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--grn)"></span>점멸 (카운트다운 4s)</td></tr>
<tr><td>전적색 ③</td><td class="n">41.8–43.8s</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td><td><span class="dot" style="background:var(--red)"></span>적색</td></tr>
</tbody>
</table>

<h2>운영 규칙</h2>
<p class="note">
① <b>동시 보행(스크램블) 방식</b>: 보행 페이즈에는 차량등 14기가 전부 적색, 보행등 14기가 전부 녹색 — 교차로마다 모든 횡단보도를 한 번에 건널 수 있습니다.
② <b>전 교차로 동기화</b>: 4개 교차로가 같은 전역 시계를 공유합니다(위상차 0). COCO·보행자·차량 데이터가 예측 가능해집니다.
③ <b>T자 교차로(북서·남동)</b>: 프롬나드 접속 팔은 차량이 없으므로 해당 방향 차량등이 없고(코너 2기 생략), 존재하는 접근로에는 동일 사이클이 적용됩니다.
④ <b>외곽 링·비신호 접속부</b>: 링 도로와 보차혼용길 진입은 무신호(서행·양보). 차량 루프(V1~V5)는 신호에 따라 정지선에서 대기합니다.
⑤ <b>구현 방식</b>: 차량등은 전구 프림 visibility 토글(적/황/녹 개별 USD), 보행등(횡단보도당 양끝 2기, 서로 반대편向 대각 배치)은 asa21 실사 모델 + 상태별 검은 커버 오버레이(항상 켜진 LED 텍스처에서 비활성 표시만 가림; red/grn/cnt/off 그룹 토글) + 점멸은 1s 주기(1Hz, 실제 신호기와 동일). 텔레옵 루프에 42초 전역 타이머 훅으로 넣습니다(기존 검증된 방식).
⑥ <b>좌회전 = 비보호 좌회전</b>: 차량 신호등은 3구(적·황·녹)로 좌회전 화살표 없음 — 왕복 2차로 도로 특성상 녹색 시 대향차가 없을 때 좌회전(5단계 차량 로직에 반영). 
⑦ <b>보행 점멸 시간 파라미터</b>: 기본값 = 횡단보도 길이(7m) ÷ COCO 속도(1.2m/s) ≈ 5.8초. 런타임에 <code>POST /sigcfg {{"blink": 초}}</code>로 조절되며 사이클 길이(38+blink)도 함께 변함. 
⑧ COCO 학습 시나리오: S4(신호 횡단)는 P 페이즈에만 진행해야 정답 — 위반(차량 페이즈 중 진입) 라벨링이 자연스럽게 가능합니다.
</p>
</main>
<script>
const VEH = {json.dumps(veh_js)};
const PED = {json.dumps(ped_js)};
const CYCLE = 43.8;
const SEGS = [
 ["V1 남북", 0, 10, "var(--grn)", "NS"], ["황", 10, 13, "var(--yel)", "NSy"], ["", 13, 14, "var(--red)", "AR"],
 ["V2 동서", 14, 24, "var(--grn)", "EW"], ["황", 24, 27, "var(--yel)", "EWy"], ["", 27, 28, "var(--red)", "AR"],
 ["P 동시 보행", 28, 36, "#2C8ADB", "PED"], ["점멸", 36, 41.8, "#2C8ADB", "PEDF"], ["", 41.8, 43.8, "var(--red)", "AR"]];
const svgEl = document.getElementById("map");
const NS = "http://www.w3.org/2000/svg";
function mk(x, y, r) {{ const c = document.createElementNS(NS, "circle");
 c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", r);
 c.setAttribute("stroke", "#fff"); c.setAttribute("stroke-width", "1.4"); svgEl.appendChild(c); return c; }}
const vehEls = VEH.map(v => mk(v.x, v.y, 6.5));
const pedEls = PED.map(p => mk(p.x, p.y, 5.5));
const tl = document.getElementById("tl");
for (const [nm, a, b, col] of SEGS) {{
  const d = document.createElement("div"); d.className = "seg";
  d.style.width = ((b - a) / CYCLE * 100) + "%"; d.style.background = col; d.textContent = nm;
  tl.appendChild(d); }}
const cur = document.createElement("div"); cur.id = "cursor"; tl.appendChild(cur);
let t = 0, playing = true, speed = 1, last = performance.now();
tl.addEventListener("click", e => {{ const r = tl.getBoundingClientRect(); t = (e.clientX - r.left) / r.width * CYCLE; }});
document.getElementById("play").onclick = e => {{ playing = !playing; e.target.textContent = playing ? "⏸ 일시정지" : "▶ 재생"; }};
document.getElementById("speed").onclick = e => {{ speed = speed === 1 ? 4 : 1; e.target.textContent = "배속 ×" + (speed === 1 ? 4 : 1); }};
function phaseAt(t) {{ for (const s of SEGS) if (t >= s[1] && t < s[2]) return s; return SEGS[0]; }}
function tick(now) {{
  if (playing) t = (t + (now - last) / 1000 * speed) % CYCLE;
  last = now;
  const ph = phaseAt(t), key = ph[4];
  const blinkOn = Math.floor(t) % 2 === 0;
  let vNS = "var(--red)", vEW = "var(--red)", pd = "var(--red)", pdOp = 1;
  if (key === "NS") vNS = "var(--grn)"; else if (key === "NSy") vNS = "var(--yel)";
  else if (key === "EW") vEW = "var(--grn)"; else if (key === "EWy") vEW = "var(--yel)";
  else if (key === "PED") pd = "var(--grn)";
  else if (key === "PEDF") {{ pd = "var(--grn)"; pdOp = blinkOn ? 1 : 0.25; }}
  vehEls.forEach((el, i) => el.setAttribute("fill", VEH[i].g === "NS" ? vNS : vEW));
  pedEls.forEach(el => {{ el.setAttribute("fill", pd); el.setAttribute("opacity", pdOp); }});
  cur.style.left = (t / CYCLE * 100) + "%";
  document.getElementById("clock").textContent = "t = " + t.toFixed(1) + "s";
  document.getElementById("phase").textContent = key === "AR" ? "전적색" : ph[0];
  requestAnimationFrame(tick);
}}
requestAnimationFrame(tick);
</script>
"""
open(f"{PO}/city_plan.html", "w").write(html)
print("ok veh:", len(veh_js), "ped:", len(ped_js), "kb:", len(html)//1024)
