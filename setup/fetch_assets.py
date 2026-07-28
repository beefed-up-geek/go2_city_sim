#!/usr/bin/env python3
"""go2_city_sim 에셋 자동 수급·정리·검증 (호스트 python3, Isaac 불필요)

사용:
  python3 setup/fetch_assets.py            # 없는 것만 내려받아 규정 위치에 정리
  python3 setup/fetch_assets.py --check    # 다운로드 없이 존재 검증만
  python3 setup/fetch_assets.py --keep-zip # URBAN-SIM zip을 풀고도 보관

정리 규격 (WS = $URBANSIM_WS_HOST, 기본 /home/gty/urban_sim):
  WS/assets_nvidia/NVIDIA/...   NVIDIA Omniverse 공개 S3 (나무·관목·신호등·소품·HDR)
  WS/assets/...                 URBAN-SIM 에셋 팩 (objects GLB·vMaterials·robots·pedestrians)
  <repo>/assets/...             저장소 동봉 (변환 USD·asa21 GLB·city_layout.json)
"""
import argparse, os, sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET, zipfile, shutil, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.environ.get("URBANSIM_WS_HOST", "/home/gty/urban_sim")
NV = f"{WS}/assets_nvidia"

S3 = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
S3ROOT = "Assets/Isaac/5.0/"
URBANSIM_ZIP = "https://huggingface.co/datasets/Hollis71025/URBAN-SIM-Assets/resolve/main/assets_urbansim.zip?download=true"
ASA21_GLB = ("https://huggingface.co/datasets/allenai/objaverse/resolve/main/"
             "glbs/000-078/2f720ea69cb2407ba8598c02305ce524.glb")

PEOPLE = f"{REPO}/assets/usd/people"   # 보행자 캐릭터·걷기 클립·애니메이션 그래프

TREES = ["Japanese_Cherry", "Honey_Locust", "American_Beech", "Japanese_Maple", "Gray_Birch"]
SHRUBS = ["Boxwood", "Barberry", "Forsythia", "Hibiscus", "Goldflame_Spirea", "Fraser_Photina"]
S3_JOBS = [  # (ROOT 하위 prefix, 부분문자열 필터 또는 None=전체)
    ("NVIDIA/dsready_content/nv_content/common_assets/traffic_lights/", None),
    ("NVIDIA/dsready_content/nv_content/korea/country_assets/", None),
    ("NVIDIA/dsready_content/nv_content/common_assets/props_traffic/",
     ["bollard_01/", "barricade_01/", "barrel_01/"]),
    ("NVIDIA/dsready_content/nv_content/common_assets/props_poles/", ["gen_street_lamp_01/"]),
    ("NVIDIA/dsready_content/nv_core/materials/", None),
    ("NVIDIA/Assets/Vegetation/Trees/", TREES + ["materials/"]),
    ("NVIDIA/Assets/Vegetation/Shrub/", SHRUBS + ["materials/", "textures/"]),
    ("NVIDIA/Assets/Skies/Clear/", ["kloppenheim_02"]),
]

# ---------- 검증 목록: 빌드·텔레옵이 실제 참조하는 모든 외부 경로 ----------
def manifest():
    m = []
    for t in TREES: m.append(("NVIDIA 나무", f"{NV}/NVIDIA/Assets/Vegetation/Trees/{t}.usd"))
    for s in SHRUBS: m.append(("NVIDIA 관목", f"{NV}/NVIDIA/Assets/Vegetation/Shrub/{s}.usd"))
    m += [
        ("NVIDIA 하늘 HDR", f"{NV}/NVIDIA/Assets/Skies/Clear/kloppenheim_02_4k.hdr"),
        ("NVIDIA 차량신호등(한국형)", f"{NV}/NVIDIA/dsready_content/nv_content/korea/country_assets/"
                                    "traffic_lights_tmp/assemblies/1001001/1001001.usda"),
        ("NVIDIA 가로등", f"{NV}/NVIDIA/dsready_content/nv_content/common_assets/props_poles/gen_street_lamp_01", "dir"),
        ("NVIDIA 볼라드", f"{NV}/NVIDIA/dsready_content/nv_content/common_assets/props_traffic/bollard_01", "dir"),
        ("NVIDIA 바리케이드", f"{NV}/NVIDIA/dsready_content/nv_content/common_assets/props_traffic/barricade_01", "dir"),
        ("NVIDIA 드럼", f"{NV}/NVIDIA/dsready_content/nv_content/common_assets/props_traffic/barrel_01", "dir"),
        ("vMaterials 차도", f"{WS}/assets/materials/Ground/Asphalt_Fine.mdl"),
        ("vMaterials 보도", f"{WS}/assets/materials/Ground/Paving_Stones.mdl"),
        ("vMaterials 벽돌", f"{WS}/assets/materials/Ground/Small_Cobblestone.mdl"),
        ("vMaterials 광장", f"{WS}/assets/materials/Ground/Large_Granite_Paving.mdl"),
        ("vMaterials 흙", f"{WS}/assets/materials/Ground/Mulch.mdl"),
        ("URBAN-SIM objects(GLB)", f"{WS}/assets/objects", "dir_min100"),
        ("URBAN-SIM COCO 로봇", f"{WS}/assets/robots/coco_one/coco_one.usd"),
        ("저장소 레이아웃", f"{REPO}/assets/city_layout.json"),
        ("저장소 asa21 GLB", f"{REPO}/assets/src/ped_light_asa21.glb"),
        ("저장소 보행등 USD", f"{REPO}/assets/usd/ped_light_asa21/ped_light_asa21.usd"),
        ("People 애니메이션 그래프", f"{PEOPLE}/Characters/Biped_Setup.usd"),
        ("People 그래프 기준 캐릭터", f"{PEOPLE}/Characters/biped_demo/biped_demo_meters.usd"),
        ("People 제자리 걷기 클립", f"{PEOPLE}/Animations/stand_walk_loop_in_place.skelanim.usd"),
        ("People 걷기 클립 24종", f"{PEOPLE}/Animations", "dir_min20"),
        ("People 캐릭터 10종", f"{PEOPLE}/Characters", "dir_min10"),
    ]
    # 저장소 변환 USD: 레이아웃이 참조하는 건물·가구·차량 전부
    import json
    L = json.load(open(f"{REPO}/assets/city_layout.json"))
    need = {b["asset"] for b in L["buildings"]}
    need |= {p["asset"] for p in L.get("parked", [])}
    need |= {"Bench_39ee5c499030472ca7460f3b03077135", "busstation_5acd6128d0b64ea2802bb7ae9aaa6c3d",
             "Trash_bin_8dca3d38daf44ef9b3866efdce2eb8bb", "Vending_machine_72ce292e1bd945aea580d223c75a870e"}
    for n in sorted(need):
        m.append((f"저장소 USD {n[:26]}…", f"{REPO}/assets/usd/objects/{n}/{n}.usd"))
    return m

def check(verbose=True):
    ok = missing = 0
    for row in manifest():
        name, path, kind = (row + ("file",))[:3]
        if kind == "dir": good = os.path.isdir(path) and bool(os.listdir(path))
        elif kind.startswith("dir_min"):
            good = os.path.isdir(path) and len(os.listdir(path)) >= int(kind[7:])
        else: good = os.path.isfile(path) and os.path.getsize(path) > 0
        if good: ok += 1
        else:
            missing += 1
            print(f"  [없음] {name}: {path}", flush=True)
    if verbose: print(f"[검증] OK {ok} / 누락 {missing}", flush=True)
    return missing

# ---------- NVIDIA S3 ----------
def s3_keys(prefix):
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    tok = None
    while True:
        u = f"{S3}/?list-type=2&prefix={urllib.parse.quote(S3ROOT + prefix)}"
        if tok: u += f"&continuation-token={urllib.parse.quote(tok)}"
        root = ET.fromstring(urllib.request.urlopen(u, timeout=60).read())
        for c in root.findall("s:Contents", ns):
            yield c.find("s:Key", ns).text, int(c.find("s:Size", ns).text)
        t = root.find("s:NextContinuationToken", ns)
        if t is None: return
        tok = t.text

def pull_nvidia():
    done = skip = fail = 0
    for prefix, filters in S3_JOBS:
        for key, size in s3_keys(prefix):
            rel = key[len(S3ROOT):]
            if "/.thumbs/" in rel: continue
            if filters and not any(f in rel for f in filters): continue
            out = f"{NV}/{rel}"
            if os.path.exists(out) and os.path.getsize(out) == size:
                skip += 1; continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                urllib.request.urlretrieve(f"{S3}/{urllib.parse.quote(key)}", out); done += 1
                if done % 25 == 0: print(f"[nvidia] {done}개 수신 중…", flush=True)
            except Exception as e:
                fail += 1; print(f"[nvidia] 실패 {rel}: {e}", flush=True)
    print(f"[nvidia] 신규 {done} · 보유 {skip} · 실패 {fail}", flush=True)

# ---------- NVIDIA People(보행자) ----------
def pull_people():
    """캐릭터·걷기 클립·Biped_Setup(AnimationGraph). Biped_Setup 은 Animations 전체와
    biped_demo 를 페이로드로 참조하므로 셋 다 받아야 한다.
    original_* 은 리타게팅 전 원본(같은 인물)이라 제외한다."""
    base = S3ROOT + "Isaac/People/"
    done = skip = fail = 0
    for key, size in s3_keys("Isaac/People/"):
        rel = key[len(base):]
        if "/.thumbs/" in rel or rel.startswith(".") or not rel: continue
        if rel.startswith(("DH_Characters", "Characters/original_")): continue
        out = f"{PEOPLE}/{rel}"
        if os.path.exists(out) and os.path.getsize(out) == size:
            skip += 1; continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            urllib.request.urlretrieve(f"{S3}/{urllib.parse.quote(key)}", out); done += 1
            if done % 20 == 0: print(f"[people] {done}개 수신 중…", flush=True)
        except Exception as e:
            fail += 1; print(f"[people] 실패 {rel}: {e}", flush=True)
    print(f"[people] 신규 {done} · 보유 {skip} · 실패 {fail}", flush=True)

# ---------- URBAN-SIM 팩 ----------
def pull_urbansim(keep_zip):
    have = (os.path.isdir(f"{WS}/assets/objects") and len(os.listdir(f"{WS}/assets/objects")) >= 100
            and os.path.isfile(f"{WS}/assets/robots/coco_one/coco_one.usd")
            and os.path.isfile(f"{WS}/assets/materials/Ground/Asphalt_Fine.mdl"))
    if have:
        print("[urbansim] 에셋 팩 보유 — 건너뜀", flush=True); return
    z = f"{WS}/assets_urbansim.zip"
    if not os.path.exists(z):
        print("[urbansim] 8.6GB 팩 다운로드 시작 (HuggingFace)…", flush=True)
        urllib.request.urlretrieve(URBANSIM_ZIP, z)
    print("[urbansim] 압축 해제…", flush=True)
    with zipfile.ZipFile(z) as f: f.extractall(WS)
    if not os.path.isdir(f"{WS}/assets") and os.path.isdir(f"{WS}/assets_urbansim/assets"):
        shutil.move(f"{WS}/assets_urbansim/assets", f"{WS}/assets")
    if not keep_zip and os.path.exists(z):
        os.remove(z); print("[urbansim] zip 삭제(--keep-zip으로 보관 가능)", flush=True)

def pull_asa21():
    out = f"{REPO}/assets/src/ped_light_asa21.glb"
    if os.path.isfile(out) and os.path.getsize(out) > 0: return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print("[asa21] Objaverse에서 다운로드…", flush=True)
    urllib.request.urlretrieve(ASA21_GLB, out)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="검증만 수행")
    ap.add_argument("--keep-zip", action="store_true")
    a = ap.parse_args()
    if a.check:
        sys.exit(1 if check() else 0)
    pull_nvidia()
    pull_people()
    pull_urbansim(a.keep_zip)
    pull_asa21()
    print("[정리] 규격 배치 완료 여부 검증:", flush=True)
    sys.exit(1 if check() else 0)
