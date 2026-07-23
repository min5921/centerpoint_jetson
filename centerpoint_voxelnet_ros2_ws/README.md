# CenterPoint VoxelNet ROS 2

Jetson AGX Orin에서 CenterPoint `det3d`의 Waymo VoxelNet 모델을 ROS 2 Humble과
연결하고, 기존 PointPillars 파이프라인과 같은 Waymo bag으로 처리량을 비교하는
별도 워크스페이스입니다.

기존 PointPillars 패키지와 분리된 하위 ROS 2 워크스페이스입니다.

## 중요: 가중치 상태

공식 CenterPoint Waymo VoxelNet 체크포인트는 Waymo 라이선스 확인 후 제공됩니다.
현재 로컬에는 VoxelNet 체크포인트가 없으므로 `ALLOW_RANDOM_WEIGHTS=true`는
**연산 성능 측정 전용**입니다. 이 모드의 검출 box와 정확도는 유효하지 않습니다.

정상 체크포인트를 받으면 `CHECKPOINT=/absolute/path/model.pth`를 지정하고
random mode 없이 실행합니다.

## 구성

- ROS 2 Humble
- CenterPoint one-stage VoxelNet
- Waymo 1-sweep config
- voxel size: `0.1 x 0.1 x 0.15 m`
- point-cloud range: `[-75.2, -75.2, -2, 75.2, 75.2, 4]`
- spconv 2.3.8, cumm 0.7.11, Orin `sm_87`
- PyTorch CUDA FP16

## 준비 및 빌드

```bash
cd centerpoint_voxelnet_ros2_ws
./scripts/setup_spconv.sh
./scripts/build.sh
```

## 성능 측정용 실행

```bash
ALLOW_RANDOM_WEIGHTS=true ./scripts/run_waymo_bag.sh
```

RViz2 없이 한 번만 재생하려면 다음과 같이 실행합니다.

```bash
ALLOW_RANDOM_WEIGHTS=true RVIZ=false LOOP=false BAG_RATE=1.0 \
  ./scripts/run_waymo_bag.sh
```

실제 체크포인트가 있을 때는 다음과 같이 실행합니다.

```bash
CHECKPOINT=/absolute/path/waymo_voxelnet.pth ./scripts/run_waymo_bag.sh
```

## 주요 토픽

| 토픽 | 내용 |
| --- | --- |
| `/waymo/points` | Waymo bag LiDAR 입력 |
| `/voxelnet/points` | RViz2용 point cloud |
| `/voxelnet/detections` | VoxelNet 예측 box |
| `/voxelnet/status` | 처리 시간 및 FPS 계측 상태 |
| `/waymo/ground_truth` | bag의 ground-truth box |

## 2026-07-23 기준 성능

동일 Waymo bag을 1.0배속으로 반복 재생하고 RViz2를 끈 상태에서 100개 출력
표본을 측정했다.

```text
실제 /voxelnet/status 출력: 4.164 FPS
대표 voxelization 평균: 111.2 ms
대표 모델 forward + NMS 평균: 119.0 ms
대표 callback 전체 평균: 238.6 ms
```

세부 조건과 PointPillars 비교는
[VoxelNet 성능 측정 보고서](docs/benchmark_2026-07-23.md)에 정리되어 있습니다.
