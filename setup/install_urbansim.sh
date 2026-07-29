#!/bin/bash
# Run inside isaac-sim:5.0.0 container with repo mounted at /workspace/urban-sim
set -e
cd /workspace/urban-sim
ln -sfn /isaac-sim ./_isaac_sim
PY=/isaac-sim/python.sh

echo "== apt deps =="
apt-get update -qq >/dev/null 2>&1 || true
apt-get install -y -qq cmake make g++ unzip >/dev/null 2>&1 || echo "apt install skipped/failed (may be fine)"

export PIP_DISABLE_PIP_VERSION_CHECK=1
# NOTE: do NOT install/downgrade pip/setuptools here — the stock container env
# (setuptools 78.1.1 with pkg_resources, pip 24.3.1) works; touching it broke pip once.

echo "== vendored isaac lab =="
for d in isaaclab isaaclab_assets isaaclab_mimic isaaclab_tasks; do
  echo "-- $d"
  $PY -m pip install -q --no-build-isolation -e "isaac_source/$d"
done
echo "-- isaaclab_rl[all]"
$PY -m pip install -q --no-build-isolation -e "isaac_source/isaaclab_rl[all]" \
  || $PY -m pip install -q --no-build-isolation -e "isaac_source/isaaclab_rl"

echo "== metadrive / metaurban =="
$PY -m pip install -q --no-build-isolation -e meta_source/metadrive
$PY -m pip install -q --no-build-isolation -e meta_source/metaurban

echo "== urbansim =="
$PY -m pip install -q --no-build-isolation -e .

echo "== extras =="
$PY -m pip install -q -r "$(dirname "$0")/../requirements.txt"
# torch를 컨테이너 동봉 torchvision과 정합한 버전으로 복원(editable 설치가 올려놨을 수 있음)
# torchvision/torchaudio 도 함께 고정한다 — Isaac Sim 5.1 환경에서는 의존성 해석이
# torchvision 0.28 을 끌어와 "operator torchvision::nms does not exist" 로 기동이 죽었다.
$PY -m pip install -q "torch==2.7.0" "torchvision==0.22.0" "torchaudio==2.7.0" \
  --index-url https://download.pytorch.org/whl/cu128
$PY -m pip install -q "numpy==1.26.4" "typing_extensions==4.15.0"   # 재고정(위 설치가 되돌릴 수 있음)
# Kit pip_prebundle의 typing_extensions 사본이 site-packages보다 우선 로드됨 — 동일 버전으로 교체
SITE_TE=/isaac-sim/kit/python/lib/python3.11/site-packages/typing_extensions.py
for f in /isaac-sim/exts/omni.pip.cloud/pip_prebundle/typing_extensions.py \
         /isaac-sim/extscache/omni.services.pip_archive-*/pip_prebundle/typing_extensions.py; do
  [ -f "$f" ] && cp -n "$f" "$f.bak" && cp "$SITE_TE" "$f"
done
apt-get install -y -qq git >/dev/null 2>&1 || true                  # isaaclab이 git 실행 파일 요구
# metaurban ORCA 플래너의 C++ 모듈(bind.so) 경로 등록 — 빌드 산출물은 워크스페이스에 존재
SITE=$($PY -c "import site; print(site.getsitepackages()[0])" 2>/dev/null | tail -1)
echo "/workspace/urban-sim/meta_source/metaurban/metaurban/orca_algo/build" > "$SITE/orca_bind.pth" \
  || echo "orca_bind.pth 생성 실패 — PYTHONPATH로 대체 필요"

echo "== sanity import =="
$PY -c "import isaaclab, urbansim, metaurban; print('imports ok')" 2>&1 | tail -3
echo "INSTALL_OK"
