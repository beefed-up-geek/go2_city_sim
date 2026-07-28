#!/bin/bash
# go2_city_sim 텔레옵 러너 — go2_web.py 재조립 + 설정 설치 + 자동 리스폰(최대 6회)
#
# 사용(호스트에서):  bash teleop/run_go2.sh
# 전제: Isaac Sim 5.0 컨테이너 'urbansim'이 $WS를 /workspace/urban-sim으로 마운트,
#       $WS에 URBAN-SIM 체크아웃(urbansim/…/play.py)과 configs/ 존재.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- 트래픽 실행 인자 ----
TRAFFIC_CARS=1; TRAFFIC_PEDS=1; TRAFFIC_N_CARS=""; TRAFFIC_N_PEDS=""; TRAFFIC_SPEED=1.0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-cars) TRAFFIC_CARS=0 ;;
    --no-peds) TRAFFIC_PEDS=0 ;;
    --no-traffic) TRAFFIC_CARS=0; TRAFFIC_PEDS=0 ;;
    --cars) TRAFFIC_N_CARS="$2"; shift ;;
    --peds) TRAFFIC_N_PEDS="$2"; shift ;;
    --traffic-speed) TRAFFIC_SPEED="$2"; shift ;;
    -h|--help) echo "사용: run_go2.sh [--no-cars] [--no-peds] [--no-traffic] [--cars N] [--peds N] [--traffic-speed X]"; exit 0 ;;
    *) echo "알 수 없는 인자: $1"; exit 1 ;;
  esac
  shift
done
TRAFFIC_PED_ASSET="${TRAFFIC_PED_ASSET:-anim}"     # anim | plain | mix
# 보행자 애니메이션(NVIDIA People)에 필요한 확장 — 반드시 Kit 기동 시점에 켜야 한다.
# 기동 후 enable_extension 으로 켜면 OGN 노드 등록이 실패하고 그래프 실행에서 죽는다.
KIT_ARGS="--enable omni.anim.graph.bundle --enable omni.anim.retarget.bundle"
export TRAFFIC_CARS TRAFFIC_PEDS TRAFFIC_N_CARS TRAFFIC_N_PEDS TRAFFIC_SPEED TRAFFIC_PED_ASSET KIT_ARGS
echo "[runner] traffic cars=$TRAFFIC_CARS peds=$TRAFFIC_PEDS n_cars=${TRAFFIC_N_CARS:-기본} n_peds=${TRAFFIC_N_PEDS:-기본} speed=$TRAFFIC_SPEED"
WS="${URBANSIM_WS_HOST:-/home/gty/urban_sim}"
REL="$(realpath --relative-to="$WS" "$REPO")"
case "$REL" in ..*) echo "저장소($REPO)가 워크스페이스($WS) 밖에 있습니다"; exit 1;; esac
REPO_CT="/workspace/urban-sim/$REL"          # 컨테이너에서 본 저장소 경로

# go2_web.py = play.py 프렐류드(1~431행) + teleop_append.py
head -n 431 "$WS/urbansim/learning/RL/play.py" > "$WS/urbansim/learning/RL/go2_web.py"
cat "$REPO/teleop/teleop_append.py" >> "$WS/urbansim/learning/RL/go2_web.py"
cp "$REPO/teleop/go2_web.yaml" "$WS/configs/env_configs/navigation/go2_web.yaml"

echo "go2_web runner start $(date)" > "$WS/pipeline_state.log"
docker exec urbansim bash -c 'for p in $(pgrep -f "python.*(go2_we[b]|random_en[v])"); do kill -9 "$p" 2>/dev/null; done'
sleep 3
for r in 1 2 3 4 5 6; do
  echo "go2_web launch #$r $(date)" >> "$WS/pipeline_state.log"
  docker exec -e GO2CITY_ROOT="$REPO_CT" -e PYTHONPATH="/workspace/urban-sim/meta_source/metaurban/metaurban/orca_algo/build" \
    -e TRAFFIC_CARS="$TRAFFIC_CARS" -e TRAFFIC_PEDS="$TRAFFIC_PEDS" -e TRAFFIC_N_CARS="$TRAFFIC_N_CARS" \
    -e TRAFFIC_N_PEDS="$TRAFFIC_N_PEDS" -e TRAFFIC_SPEED="$TRAFFIC_SPEED" \
    -e TRAFFIC_PED_ASSET="$TRAFFIC_PED_ASSET" urbansim bash -c "cd /workspace/urban-sim && /isaac-sim/python.sh urbansim/learning/RL/go2_web.py --env configs/env_configs/navigation/go2_web.yaml --headless --enable_cameras --num_envs 1 --kit_args \"$KIT_ARGS\"" > "$WS/go2_web.log" 2>&1
  echo "EXIT:$? at $(date)" >> "$WS/go2_web.log"
  echo "GO2_EXITED #$r $(date)" >> "$WS/pipeline_state.log"
  sleep 8
done
echo "RUNNER_GAVE_UP $(date)" >> "$WS/pipeline_state.log"
