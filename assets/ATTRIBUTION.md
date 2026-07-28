# 에셋 출처 및 라이선스 (Asset Attribution)

이 문서는 go2_city_sim이 사용하는 **모든** 3D 에셋·재질의 출처, 원본 링크, 라이선스를 기록한다.
저장소에 포함된 것과 런타임에 외부에서 가져오는 것을 구분한다.

---

## 1. 저장소 포함 에셋 (`assets/usd/`, `assets/src/`)

### 1.1 보행자 신호등 — `usd/ped_light_asa21/`

| 항목 | 내용 |
|---|---|
| 모델명 | **"Pedestrian Traffic Light"** |
| 제작자 | **ASA21** — https://sketchfab.com/ASA21 |
| 원본 페이지 | https://sketchfab.com/3d-models/2f720ea69cb2407ba8598c02305ce524 |
| 라이선스 | **CC BY 4.0** (Creative Commons Attribution) — http://creativecommons.org/licenses/by/4.0/ |
| 확보 경로 | Objaverse 1.0 미러: https://huggingface.co/datasets/allenai/objaverse/resolve/main/glbs/000-078/2f720ea69cb2407ba8598c02305ce524.glb |
| 저장소 내 원본 | `assets/src/ped_light_asa21.glb` (712 KB), USD 변환은 `scripts/convert_assets.py` |
| 변경 사항 | GLB→USD 변환, 전고 3 m 스케일, 상태 표시용 검은 커버 오버레이 추가(빌드 시) |

> 표기 예: *"Pedestrian Traffic Light" by ASA21 (Sketchfab), licensed under CC BY 4.0. 3D 모델을 변환·수정하여 사용.*

Objaverse 데이터셋 자체는 **ODC-By 1.0**으로 배포된다
(Deitke et al., *Objaverse: A Universe of Annotated 3D Objects*, CVPR 2023 — https://objaverse.allenai.org).

### 1.2 건물 13종 · 가구 4종 — `usd/objects/`

| 항목 | 내용 |
|---|---|
| 출처 | **URBAN-SIM** 프로젝트 배포 에셋(objects GLB 모음)을 USD로 변환 |
| 프로젝트 | https://github.com/metadriverse/urban-sim (MetaDriverse, UCLA) |
| 라이선스 | **Apache License 2.0** — 원문 사본: [`licenses/URBAN-SIM.Apache-2.0.txt`](licenses/URBAN-SIM.Apache-2.0.txt) (NOTICE 파일 없음) |
| 변환 | `scripts/convert_assets.py` (omni.kit.asset_converter), 폴더명 = 원본 GLB 파일명(UUID) |

포함 폴더 (17):

```
Building_1fddcc3a…  Building_234942f5…  Building_2ed85303…  Building_315756ab…
Building_35df908b…  Building_694adf50…  Building_738972de…  Building_7458a492…
Building_845ebddd…  Building_992ee80b…  Building_cef9a721…  Building_d67227ca…
Building_f7d7b826…
Bench_39ee5c49…     Trash_bin_8dca3d38…  Vending_machine_72ce292e…  busstation_5acd6128…
```



---

## 2. 런타임 외부 의존 에셋 (저장소 미포함)

### 2.1 NVIDIA Omniverse / Isaac Sim 공식 콘텐츠 — `$URBANSIM_WS/assets_nvidia/NVIDIA/`

| 용도 | 에셋 경로(요약) |
|---|---|
| 가로수 5종 | `Assets/Vegetation/Trees/` (Japanese_Cherry, Honey_Locust, American_Beech, Japanese_Maple, Gray_Birch) |
| 화분 관목 | `Assets/Vegetation/Shrub/Hibiscus.usd` |
| 차량 신호등(한국형 3구) | `dsready_content/nv_content/korea/country_assets/traffic_lights_tmp/assemblies/1001001/` |
| 가로등·볼라드·바리케이드·드럼 | `dsready_content/nv_content/common_assets/props_poles/`, `props_traffic/` |
| 하늘 HDR | `Assets/Skies/Clear/kloppenheim_02_4k.hdr` |

- 출처: NVIDIA Omniverse 공개 콘텐츠 버킷 `omniverse-content-production.s3-us-west-2.amazonaws.com`
  (prefix `Assets/Isaac/5.0/…`), 다운로드 스크립트: `scripts/s3_pull.py`
- 라이선스: **NVIDIA Omniverse License Agreement** — NVIDIA가 Omniverse/Isaac Sim 생태계용으로
  제공하는 콘텐츠. 재배포 제약이 있어 **저장소에 포함하지 않는다** (각자 s3_pull.py로 수령).
  https://docs.omniverse.nvidia.com/platform/latest/common/NVIDIA_Omniverse_License_Agreement.html

### 2.2 NVIDIA vMaterials (MDL 재질) — `$URBANSIM_WS/assets/materials/`

- 용도: 차도(Asphalt_Fine)·보도(Paving_Stones)·벽돌길(Small_Cobblestone)·광장(Large_Granite_Paving)·흙(Mulch)
- 출처: **NVIDIA vMaterials 2** (URBAN-SIM 에셋 패키지에 동봉된 사본 사용)
- 라이선스: NVIDIA vMaterials 라이선스(무료 사용 허용, 재배포 제약) — https://developer.nvidia.com/vmaterials

### 2.3 로봇 — `$URBANSIM_WS/assets/robots/coco_one.usd`

- COCO 배달로봇(외형) + Unitree Go2(보행 제어 기반): **URBAN-SIM** 배포 에셋 (Apache-2.0 배포 기준)
- Unitree Go2의 원 모델·URDF는 Unitree Robotics 공개 자료에서 유래

### 2.4 실행 환경

- **Isaac Sim 5.0** (docker 컨테이너): NVIDIA Omniverse/Isaac Sim 라이선스
- **URBAN-SIM** 프레임워크(코드, play.py 등): Apache License 2.0

---

## 3. 요약 표

| 에셋 | 출처 | 라이선스 | 저장소 포함 |
|---|---|---|---|
| 보행등 (asa21) | Sketchfab @ASA21 → Objaverse | CC BY 4.0 | ✅ |
| 건물 13·가구 4 | URBAN-SIM | Apache-2.0 | ✅ |
| 나무·관목·차량신호등·가로등·볼라드·HDR | NVIDIA Omniverse 콘텐츠 | NVIDIA Omniverse License | ❌ (s3_pull.py) |
| 도로·보도 MDL 재질 | NVIDIA vMaterials (URBAN-SIM 동봉) | vMaterials License | ❌ |
| COCO/Go2 로봇 | URBAN-SIM (원류: Unitree) | Apache-2.0 | ❌ |
| 도로·연석·램프·횡단보도 지오메트리 | 본 저장소 자작 (`build_city.py`) | 저장소 라이선스 | ✅ |
