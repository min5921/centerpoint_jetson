# CenterPoint VoxelNet Jetson AGX Orin 성능 측정

## 결론

Waymo 10 Hz 입력과 동일한 조건에서 `/voxelnet/status`의 실제 지속 출력률은
**4.164 FPS**였다. 기존 CenterPoint PointPillars의 7.640 FPS보다 약 45.5%
낮으며, PointPillars가 약 1.83배 빠르다.

## 측정 조건

| 항목 | VoxelNet 측정값 |
| --- | --- |
| 장비 | NVIDIA Jetson AGX Orin Developer Kit |
| 전력 모드 | MAXN |
| ROS | ROS 2 Humble |
| CUDA | 12.6 |
| PyTorch | 2.5.0a0+872d972e41.nv24.08 |
| sparse convolution | cumm 0.7.11, spconv 2.3.8, sm_87 source build |
| 모델 | CenterPoint one-stage VoxelNet |
| config | `waymo_centerpoint_voxelnet_1x.py` |
| 정밀도 | PyTorch CUDA FP16 autocast |
| 입력 | Waymo ROS 2 bag, 1.0배속, 약 10 Hz |
| 출력 표본 | 100개 sliding window |
| RViz2 | 비활성화 |
| score threshold | 0.5 |
| NMS pre/post | 4096/500 |

## 가중치 제한

로컬에 Waymo VoxelNet 체크포인트가 없어서 이번 실행은
`random-benchmark-only` 모드를 사용했다. sparse convolution의 active voxel과
주요 convolution 연산량은 입력 좌표와 모델 구조로 결정되므로 backbone 및 head
처리량 비교에는 사용할 수 있다.

그러나 random head에서는 threshold를 넘는 검출이 0개이므로 학습 체크포인트보다
NMS 및 Marker 생성 비용이 작을 수 있다. 따라서 4.164 FPS는 **연산 성능의 잠정
기준값**이며, 검출 정확도나 시각화 품질을 의미하지 않는다. 공식 또는 학습된
체크포인트를 확보하면 같은 명령으로 최종 재측정해야 한다.

## 실제 토픽 출력률

실행 명령은 다음과 같다.

```bash
cd centerpoint_voxelnet_ros2_ws
LOOP=true MEASURE_SECONDS=30 ./scripts/benchmark_waymo.sh
```

100개 표본에서 마지막으로 확인한 결과는 다음과 같다.

```text
average rate: 4.164 Hz
minimum interval: 0.211 s
maximum interval: 0.278 s
window: 100
```

## 대표 프레임 처리 시간

첫 프레임은 Numba와 CUDA/spconv 초기화가 포함되어 총 3765.1 ms가 걸렸으므로
평균에서 제외했다.

| 프레임 | 포인트 | voxel | voxelization | 모델 추론 | 전체 callback |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 51,255 | 40,947 | 116.1 ms | 137.3 ms | 263.7 ms |
| 40 | 49,632 | 41,519 | 110.2 ms | 110.5 ms | 226.4 ms |
| 60 | 49,660 | 40,871 | 116.1 ms | 116.6 ms | 241.4 ms |
| 80 | 50,591 | 40,681 | 107.8 ms | 121.6 ms | 238.7 ms |
| 100 | 50,229 | 40,920 | 112.5 ms | 120.4 ms | 241.9 ms |
| 120 | 48,604 | 42,567 | 103.4 ms | 123.5 ms | 235.6 ms |
| 140 | 49,214 | 39,559 | 112.3 ms | 102.9 ms | 222.8 ms |
| **평균** | **49,884** | **41,009** | **111.2 ms** | **119.0 ms** | **238.6 ms** |

대표 callback 시간의 역수는 약 4.19 FPS이며, DDS 수신 간격까지 포함한 실제
토픽 출력률 4.164 FPS와 일치한다.

## PointPillars 비교

| 항목 | PointPillars | VoxelNet | 차이 |
| --- | ---: | ---: | ---: |
| 실제 ROS 출력 | 7.640 FPS | 4.164 FPS | VoxelNet -45.5% |
| voxelization | 5.7 ms | 111.2 ms | VoxelNet +105.5 ms |
| 모델 forward + NMS | 102.8 ms | 119.0 ms | VoxelNet +16.2 ms |
| callback 전체 | 119.4 ms | 238.6 ms | VoxelNet +119.2 ms |
| 대표 voxel 수 | 약 12,433 | 약 41,009 | 약 3.30배 |

현재 차이의 대부분은 VoxelNet 모델 자체보다 CPU voxelization에서 발생한다.
PointPillars는 `0.32 x 0.32 x 6.0 m`, VoxelNet은
`0.1 x 0.1 x 0.15 m` voxel을 사용하므로 VoxelNet이 약 3.3배 많은 active
voxel을 만든다.

## 다음 측정

1. 학습된 Waymo VoxelNet 체크포인트를 확보해 검출과 NMS를 포함한 최종 FPS 측정
2. CPU Numba voxelization을 spconv/CUDA point-to-voxel로 교체
3. sparse backbone, RPN, head, NMS 구간별 CUDA event profiling
4. RViz2 활성화 상태의 표시 성능 별도 측정
