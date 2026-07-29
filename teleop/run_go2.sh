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
    --peds-static) TRAFFIC_PED_MODE=static ;;
    --no-peds) TRAFFIC_PEDS=0 ;;
    --no-traffic) TRAFFIC_CARS=0; TRAFFIC_PEDS=0 ;;
    --cars) TRAFFIC_N_CARS="$2"; shift ;;
    --peds) TRAFFIC_N_PEDS="$2"; shift ;;
    --traffic-speed) TRAFFIC_SPEED="$2"; shift ;;
    -h|--help) echo "사용: run_go2.sh [--no-cars] [--no-peds] [--no-traffic] [--peds-static] [--cars N] [--peds N] [--traffic-speed X]"; exit 0 ;;
    *) echo "알 수 없는 인자: $1"; exit 1 ;;
  esac
  shift
done
TRAFFIC_PED_ASSET="${TRAFFIC_PED_ASSET:-anim}"     # anim | plain | mix
TRAFFIC_PED_MODE="${TRAFFIC_PED_MODE:-anim}"       # anim(애니메이션) | static(정지 자세)
# 보행자 애니메이션(NVIDIA People)에 필요한 확장 — 반드시 Kit 기동 시점에 켜야 한다.
# 기동 후 enable_extension 으로 켜면 OGN 노드 등록이 실패하고 그래프 실행에서 죽는다.
KIT_ARGS="--enable omni.anim.graph.bundle --enable omni.anim.retarget.bundle"
# 텍스처 스트리밍: 보행자 캐릭터가 시야에 들어올 때 4K 텍스처가 몰려 올라오며
# 리소스 회수 경합(Xid 31 FAULT_PDE)이 의심되어 끌 수 있게 둔다.
# VRAM 24GB 중 9GB만 쓰므로 꺼도 여유가 있다. TELEOP_TEXSTREAM=1 이면 켠 채로 둔다.
if [ "${TELEOP_TEXSTREAM:-0}" = "0" ]; then
  KIT_ARGS="$KIT_ARGS --/rtx-transient/resourcemanager/texturestreaming/enabled=false"
fi
TELEOP_AA="${TELEOP_AA:-3}"                        # 3=DLSS 2=TAA 1=FXAA 0=off
CT="${URBANSIM_CONTAINER:-urbansim}"               # Isaac Sim 컨테이너 이름(버전 비교용)
TELEOP_CAMS="${TELEOP_CAMS:-2}"                    # 2=에고+3인칭, 1=에고만
# Fabric(USDRT)은 기본으로 끈다. 켜면 보행자(UsdSkel 스킨드 메시)가 씬에 있는 채로
# 로봇이 이동할 때 수십 초 안에 GPU 불법 메모리 접근으로 렌더가 죽는다.
#   Fabric ON  : 3m 주행 46초 만에 크래시 (재현 10회 이상)
#   Fabric OFF : 440m 주행 9분 완주, fps 5.2 → 5.7 로 오히려 상승
# num_envs=1 텔레옵에서는 Fabric 이득이 없어 끄는 편이 낫다.
TELEOP_FABRIC="${TELEOP_FABRIC:-0}"                # 1=Fabric 활성(크래시 재현용)
export TRAFFIC_CARS TRAFFIC_PEDS TRAFFIC_N_CARS TRAFFIC_N_PEDS TRAFFIC_SPEED TRAFFIC_PED_ASSET TRAFFIC_PED_MODE TELEOP_AA TELEOP_CAMS TELEOP_FABRIC KIT_ARGS
echo "[runner] container=$CT traffic cars=$TRAFFIC_CARS peds=$TRAFFIC_PEDS n_cars=${TRAFFIC_N_CARS:-기본} n_peds=${TRAFFIC_N_PEDS:-기본} speed=$TRAFFIC_SPEED"
WS="${URBANSIM_WS_HOST:-/home/gty/urban_sim}"
REL="$(realpath --relative-to="$WS" "$REPO")"
case "$REL" in ..*) echo "저장소($REPO)가 워크스페이스($WS) 밖에 있습니다"; exit 1;; esac
REPO_CT="/workspace/urban-sim/$REL"          # 컨테이너에서 본 저장소 경로

# 자동 리스폰 횟수(GPU 크래시 자동 복구용) — RUN_GO2_LIVES 로 조정
# go2_web.py = play.py 프렐류드(1~431행) + teleop_append.py
head -n 431 "$WS/urbansim/learning/RL/play.py" > "$WS/urbansim/learning/RL/go2_web.py"
cat "$REPO/teleop/teleop_append.py" >> "$WS/urbansim/learning/RL/go2_web.py"
cp "$REPO/teleop/go2_web.yaml" "$WS/configs/env_configs/navigation/go2_web.yaml"

echo "go2_web runner start $(date)" > "$WS/pipeline_state.log"
docker exec "$CT" bash -c 'for p in $(pgrep -f "python.*(go2_we[b]|random_en[v])"); do kill -9 "$p" 2>/dev/null; done'
sleep 3
LIVES="${RUN_GO2_LIVES:-200}"
for r in $(seq 1 "$LIVES"); do
  echo "go2_web launch #$r $(date)" >> "$WS/pipeline_state.log"
  [ -f "$WS/go2_web.log" ] && mv -f "$WS/go2_web.log" "$WS/go2_web.prev$((r % 3)).log"
  docker exec -e GO2CITY_ROOT="$REPO_CT" -e PYTHONPATH="/workspace/urban-sim/meta_source/metaurban/metaurban/orca_algo/build" \
    -e TRAFFIC_CARS="$TRAFFIC_CARS" -e TRAFFIC_PEDS="$TRAFFIC_PEDS" -e TRAFFIC_N_CARS="$TRAFFIC_N_CARS" \
    -e TRAFFIC_N_PEDS="$TRAFFIC_N_PEDS" -e TRAFFIC_SPEED="$TRAFFIC_SPEED" \
    -e TRAFFIC_PED_ASSET="$TRAFFIC_PED_ASSET" -e TRAFFIC_PED_MODE="$TRAFFIC_PED_MODE" -e TELEOP_AA="$TELEOP_AA" -e TELEOP_CAMS="$TELEOP_CAMS" -e TELEOP_FABRIC="$TELEOP_FABRIC" "$CT" bash -c "cd /workspace/urban-sim && /isaac-sim/python.sh urbansim/learning/RL/go2_web.py --env configs/env_configs/navigation/go2_web.yaml --headless --enable_cameras --num_envs 1 --kit_args \"$KIT_ARGS\"" > "$WS/go2_web.log" 2>&1
  echo "EXIT:$? at $(date)" >> "$WS/go2_web.log"
  echo "GO2_EXITED #$r $(date)" >> "$WS/pipeline_state.log"
  sleep 8
done
echo "RUNNER_GAVE_UP $(date)" >> "$WS/pipeline_state.log"
