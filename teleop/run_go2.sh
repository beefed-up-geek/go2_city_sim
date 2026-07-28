#!/bin/bash
# go2_city_sim 텔레옵 러너 — go2_web.py 재조립 + 설정 설치 + 자동 리스폰(최대 6회)
#
# 사용(호스트에서):  bash teleop/run_go2.sh
# 전제: Isaac Sim 5.0 컨테이너 'urbansim'이 $WS를 /workspace/urban-sim으로 마운트,
#       $WS에 URBAN-SIM 체크아웃(urbansim/…/play.py)과 configs/ 존재.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  docker exec -e GO2CITY_ROOT="$REPO_CT" -e PYTHONPATH="/workspace/urban-sim/meta_source/metaurban/metaurban/orca_algo/build" urbansim bash -c "cd /workspace/urban-sim && /isaac-sim/python.sh urbansim/learning/RL/go2_web.py --env configs/env_configs/navigation/go2_web.yaml --headless --enable_cameras --num_envs 1" > "$WS/go2_web.log" 2>&1
  echo "EXIT:$? at $(date)" >> "$WS/go2_web.log"
  echo "GO2_EXITED #$r $(date)" >> "$WS/pipeline_state.log"
  sleep 8
done
echo "RUNNER_GAVE_UP $(date)" >> "$WS/pipeline_state.log"
