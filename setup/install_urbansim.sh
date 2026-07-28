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
$PY -m pip install -q stable_baselines3 tensorboard scikit-image pyyaml gdown "pybind11[global]" \
  jax chex distrax optax flax
# metaurban ORCA 플래너의 C++ 모듈(bind.so) 경로 등록 — 빌드 산출물은 워크스페이스에 존재
SITE=$($PY -c "import site; print(site.getsitepackages()[0])" 2>/dev/null | tail -1)
echo "/workspace/urban-sim/meta_source/metaurban/metaurban/orca_algo/build" > "$SITE/orca_bind.pth" \
  || echo "orca_bind.pth 생성 실패 — PYTHONPATH로 대체 필요"

echo "== sanity import =="
$PY -c "import isaaclab, urbansim, metaurban; print('imports ok')" 2>&1 | tail -3
echo "INSTALL_OK"
