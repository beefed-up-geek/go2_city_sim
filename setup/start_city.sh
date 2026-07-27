#!/bin/bash
# One-shot morning start: docker start + sim launch. Web: http://115.145.179.126:8003
docker start sim45 >/dev/null 2>&1
sleep 3
docker exec sim45 bash -c 'for p in $(pgrep -f "city_4[5]"); do kill -9 "$p" 2>/dev/null; done' 2>/dev/null
nohup docker exec -t -e PYTHONUNBUFFERED=1 sim45 bash -c "cd /workspace/urban-sim && /isaac-sim/python.sh /workspace/urban-sim/city_45.py" > /home/gty/urban_sim/sim45.log 2>&1 &
echo "starting... web will be up in ~2-4 min at :8003"
