# Jetson AGX Orin 신호 처리 및 FPS 측정 결과

## 1. 측정 목적

Waymo LiDAR ROS 2 bag을 CenterPoint PointPillars로 처리할 때 Jetson AGX
Orin에서 실제로 몇 프레임을 처리할 수 있는지 확인했다. 모델 추론 시간과 ROS 2
전체 처리 시간, 실제 상태 토픽 발행률을 구분해 측정했다.

이 결과는 OpenPCDet가 아니라 현재 저장소의 CenterPoint `det3d` 구현에 대한
측정값이다. RTX 5060 노트북에서 측정한 OpenPCDet 결과와 직접 비교할 때는
프레임워크와 측정 구간이 다르다는 점을 고려해야 한다.

## 2. 측정 환경

| 항목 | 값 |
| --- | --- |
| 장비 | NVIDIA Jetson AGX Orin Developer Kit |
| 전력 모드 | MAXN (`nvpmodel -q`: mode 0) |
| JetPack | 6.2.2 |
| CUDA | 12.6 |
| PyTorch | 2.5.0a0+872d972e41.nv24.08 |
| ROS | ROS 2 Humble |
| 정밀도 | CUDA FP16 autocast |
| RViz2 | 실제 FPS 계측에서는 비활성화 |
| 입력 재생 속도 | Waymo 원래 속도 1.0배, 약 10 Hz |
| 점수 임계값 | 0.50 |
| NMS 설정 | pre 4096, post 500 |

입력 bag은 `/home/kopti/Desktop/bag`이며 다음 200개 LiDAR 프레임을 포함한다.

```text
duration: 19.9 s
/waymo/points: 200 messages
/waymo/ground_truth: 200 messages
/waymo/frame_info: 200 messages
```

사용한 체크포인트는 다음과 같다.

```text
/home/kopti/Desktop/bag/
centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
```

체크포인트 메타데이터와 가중치 키를 확인한 결과 CenterPoint `det3d` 형식이다.

## 3. 신호 처리 흐름

```text
Waymo rosbag2
  -> /waymo/points (sensor_msgs/PointCloud2)
  -> XYZ, intensity, elongation 추출
  -> NumPy [N, 5] 변환
  -> CPU Numba voxelization
  -> GPU tensor 전송
  -> PointPillars PFN 및 pillar scatter
  -> RPN 및 CenterHead
  -> CUDA NMS
  -> /centerpoint/detections (MarkerArray)
  -> /centerpoint/status
  -> RViz2 표시
```

현재 bag의 포인트에는 `elongation` 필드가 없어서 해당 feature는 0으로 채운다.
정상 프레임은 약 48,000~51,000개 포인트와 약 10,000~14,000개 voxel을
처리했다.

## 4. 2026-07-23 실제 출력 FPS

측정 명령은 10 Hz 입력을 유지하고 RViz2 렌더링 영향을 제외했다.

```bash
RVIZ=false LOOP=false BAG_RATE=1.0 STARTUP_DELAY=6 \
  ./scripts/run_waymo_bag.sh

ros2 topic hz /centerpoint/status --window 100
```

첫 프레임은 Numba 및 CUDA kernel 준비로 인해 평균에서 제외했다. 첫 프레임은
voxelization 2661.8 ms, 모델 추론 3940.1 ms, 전체 6614.7 ms가 걸렸다.

워밍업 이후 `/centerpoint/status`에서 확인한 실제 발행률은 다음과 같다.

```text
average rate: 7.640 Hz
minimum interval: 0.111 s
maximum interval: 0.156 s
```

따라서 현재 구성의 실제 지속 처리량은 **약 7.6 FPS**이다. 입력은 10 FPS이므로
약 2.4 FPS가 부족하며, 실시간 입력에서는 일부 최신 프레임만 처리되고 중간
프레임은 sensor-data QoS에 따라 드롭될 수 있다.

## 5. 구간별 처리 시간

워밍업 이후 로그에 기록된 대표 프레임은 다음과 같다.

| 프레임 | 포인트 | voxel | 검출 | voxelization | 모델 추론 | 전체 처리 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 51,273 | 11,448 | 5 | 3.0 ms | 109.8 ms | 120.3 ms |
| 40 | 51,448 | 11,295 | 3 | 5.3 ms | 94.1 ms | 109.1 ms |
| 60 | 48,820 | 14,141 | 3 | 7.4 ms | 102.1 ms | 122.3 ms |
| 80 | 50,365 | 12,848 | 5 | 6.9 ms | 105.3 ms | 125.7 ms |
| **평균** | **50,477** | **12,433** | **4** | **5.7 ms** | **102.8 ms** | **119.4 ms** |

대표 프레임 평균으로 환산하면 모델 forward와 NMS의 계산 속도는 약 9.7 FPS이고,
callback 내부 전체 처리 시간은 약 8.4 FPS이다. DDS 수신과 프레임 사이의 대기까지
포함한 실제 토픽 출력은 7.6 FPS이므로, 시스템 처리량을 나타내는 기준값은
`ros2 topic hz`의 7.6 FPS를 사용한다.

## 6. GPU 상태

10 Hz 입력으로 연속 부하를 주었을 때 `tegrastats`에서 다음 상태를 확인했다.

| 항목 | 관찰값 |
| --- | --- |
| GPU 사용률 | 최대 99% |
| GPU 전력 | 약 17~22 W |
| GPU 온도 | 약 45~46°C |
| 열 스로틀링 징후 | 없음 |

입력을 1 Hz로 낮추면 프레임 사이에 GPU 동적 클럭이 내려가 모델 추론이 약
145 ms까지 느려졌다. 10 Hz 연속 입력에서는 약 94~110 ms 구간으로 개선됐다.
따라서 낮은 재생 속도에서 측정한 단일 프레임 지연만으로 최대 처리량을 판단하면
안 된다.

## 7. 결과 해석

- 현재 Jetson AGX Orin이나 CUDA가 비정상적으로 제한된 상태는 아니다.
- CPU voxelization은 평균 5.7 ms로 전체 병목의 작은 부분이다.
- 가장 큰 병목은 CenterPoint `det3d` 모델 forward와 NMS이다.
- 현재 PyTorch FP16 구성은 Waymo 10 Hz 입력을 완전히 따라가지 못한다.
- RTX 5060의 OpenPCDet 20 FPS와 공정하게 비교하려면 동일 OpenPCDet commit,
  config, checkpoint, FP16/FP32 설정 및 측정 구간을 Orin에서 사용해야 한다.
- `jetson_clocks`는 동적 클럭 편차를 줄일 수 있지만 7.6 FPS를 단독으로 20 FPS까지
  높일 가능성은 낮다.

## 8. 기준 결론

현재 CenterPoint PointPillars ROS 2 파이프라인의 기준 성능은 다음과 같이 기록한다.

```text
실제 지속 출력: 약 7.6 FPS
대표 callback 처리량: 약 8.4 FPS
모델 forward + NMS: 약 9.7 FPS
Waymo 입력 요구 속도: 10 FPS
현재 부족분: 약 2.4 FPS
```

10 FPS 이상을 안정적으로 달성하려면 동일한 OpenPCDet 구현을 Orin에 포팅해
비교한 뒤, TensorRT FP16, CUDA 전처리, NMS 후보 축소 순서로 최적화하는 것이
적절하다.
