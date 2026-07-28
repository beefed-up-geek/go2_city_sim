# go2_city_sim

Isaac Sim 5.0 + URBAN-SIM 기반 **VLA 학습 데이터 수집용 도시 시뮬레이션**.
130×130m 루프 코스 도시(신호교차로 4개, 보차혼용길, 프롬나드, 공사구역)에서
COCO 배달로봇(Unitree Go2 기반)을 웹 브라우저로 텔레옵하며, 신호등이 실제
운영 계획(43.8초 사이클, 동시보행 스크램블)대로 점등한다.

| 적색 (차량 통행) | 보행 (동시보행) | 점멸 (1Hz) |
|---|---|---|
| ![red](docs/shots/ped_red.jpg) | ![green](docs/shots/ped_green.jpg) | ![blink](docs/shots/ped_blink.jpg) |

## 저장소 구조

```
assets/
  city_layout.json      # 도시 좌표 단일 소스(도로·횡단보도·신호등·건물·course·routes)
  usd/ped_light_asa21/  # 보행등 실사 모델 (Sketchfab CC-BY, Objaverse 경유)
  usd/objects/          # 사용 중인 건물 13종 + 가구 5종 (URBAN-SIM GLB → USD 변환본)
  src/                  # 원본 GLB
scripts/
  build_city.py         # city_layout.json → city_static.usd + 검증 스크린샷
  convert_assets.py     # GLB → USD 일괄 변환 (omni.kit.asset_converter)
  gen_signal_plan.py    # 신호 운영 계획 웹문서(docs/city_plan.html) 생성
  test_heads.py         # 보행등 격리 캘리브레이션 씬 (TH_RULER=1로 눈금 렌더)
  dump_bboxes.py, s3_pull.py   # 유틸: bbox 실측 / NVIDIA SimReady 에셋 다운로드
teleop/
  teleop_append.py      # 웹 텔레옵 + 신호 상태머신 (play.py 프렐류드 뒤에 이어붙임)
  go2_web.yaml          # 환경 설정 (unitree_go2, num_envs 1)
  run_go2.sh            # 재조립 + 설정 설치 + 기동 (자동 리스폰 6회)
setup/                  # 컨테이너/URBAN-SIM 설치 스크립트
docs/
  city_plan.html        # 신호 운영 계획 v1.4 (애니메이션 도면)
  shots/                # 검증 스크린샷
```

## 외부 의존성 (저장소 미포함)

외부 에셋은 **`python3 setup/fetch_assets.py`** 한 번으로 수급·정리·검증된다
(없는 것만 내려받음, `--check`는 검증만). 세부:

| 의존성 | 크기 | 출처 (fetch_assets.py가 자동 처리) |
|---|---|---|
| NVIDIA 에셋(`assets_nvidia/`) — 나무·관목·신호등·소품·HDR | 1.8GB | NVIDIA Omniverse 공개 S3 |
| URBAN-SIM 에셋 팩 — objects GLB·vMaterials·COCO 로봇·보행자 | 8.6GB | HuggingFace `Hollis71025/URBAN-SIM-Assets` |
| asa21 보행등 GLB | 0.7MB | Objaverse (저장소에도 동봉) |
| Isaac Sim 5.0 컨테이너 + URBAN-SIM 코드 체크아웃 | — | 별도: NGC 이미지, URBAN-SIM 저장소 → `setup/install_urbansim.sh` |

워크스페이스(호스트 `~/urban_sim` = 컨테이너 `/workspace/urban-sim`)에 위
의존성이 있고, 이 저장소를 워크스페이스 아래에 클론했다고 가정한다.
다른 경로는 환경변수로 조정: `URBANSIM_WS`(컨테이너 쪽), `URBANSIM_WS_HOST`,
`GO2CITY_ROOT`, `CITY_USD`.

## 실행

```bash
# 1) 도시 빌드 (컨테이너 안, 워밍 상태 1~2분)
docker exec urbansim bash -c \
  'cd /workspace/urban-sim && /isaac-sim/python.sh go2_city_sim/scripts/build_city.py'

# 2) 텔레옵 기동 (호스트, 서버 상주)
setsid nohup bash go2_city_sim/teleop/run_go2.sh > /dev/null 2>&1 &

# 3) 브라우저에서 http://<서버>:8003
```

### 웹 엔드포인트

| 엔드포인트 | 설명 |
|---|---|
| `/` | 에고/3인칭 MJPEG + 미니맵 + 체크포인트 UI (방향키 조작) |
| `/status` | 위치·명령·sim fps·**현재 신호 페이즈** JSON |
| `POST /cmd` | `(vx, vy, wz)` 속도 명령 |
| `POST /goto` | `{x,y,z,yaw}` 텔레포트 |
| `POST /sigcfg` | `{"blink": 초}` 보행 점멸 시간 변경 (기본 5.83 = 7m ÷ 1.2m/s) |
| `POST /cam` | 3인칭 카메라 라이브 튜닝 |
| `/layout` | city_layout.json 서빙 (미니맵용) |
| `/frame/ego`, `/frame/tpv` | 단일 프레임 캡처 |

## 신호 시스템

전 교차로 동기, 사이클 = 38 + blink 초:

```
남북 녹10 → 황3 → 전적1 → 동서 녹10 → 황3 → 전적1
→ 동시보행(스크램블) 녹8 → 점멸 blink(기본 5.83) → 전적2
```

- 차량등 16기: 한국형 신호등(NVIDIA dsready)의 전구 프림 visibility 토글
- 보행등 28기(횡단보도 양끝 2기씩): **asa21 실사 모델 + 검은 커버 오버레이** —
  모델의 LED 표시(적사람/녹사람/카운트다운)가 항상 켜진 텍스처라서,
  상태별로 *비활성 표시만* 검은 커버로 가린다. 상태 그룹(red/grn/cnt/off)의
  visibility만 토글하면 되므로 런타임 로직이 단순하다.
- 점멸은 1Hz (0.5s 토글은 DLSS 시간적 잔상에 묻혀 항상 켜져 보임)
- 좌회전은 비보호(전용 화살표 없음) — 운영 계획은 `docs/city_plan.html` 참고

## 에셋 출처

모든 에셋의 출처·원본 링크·라이선스는 **[assets/ATTRIBUTION.md](assets/ATTRIBUTION.md)** 참조.
요약: 보행등 = "Pedestrian Traffic Light" by ASA21 (Sketchfab, CC BY 4.0) · 건물/가구/로봇 = URBAN-SIM (Apache-2.0) ·
신호등/나무/소품 = NVIDIA Omniverse 콘텐츠(미포함, `s3_pull.py`) · 재질 = NVIDIA vMaterials
