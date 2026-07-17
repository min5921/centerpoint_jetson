# 2026-07-17 CenterPoint PointPillars 추론 속도 개선 기록

## 기록 정보

| 항목 | 내용 |
| --- | --- |
| 기록 날짜 | 2026-07-17 |
| 대상 장비 | NVIDIA Jetson AGX Orin Developer Kit |
| 대상 모델 | CenterPoint PointPillars Waymo |
| ROS 환경 | ROS 2 Humble |
| 실행 방식 | Docker가 아닌 native Python/CUDA 환경 |
| 입력 데이터 | Waymo ROS 2 bag `/home/kopti/Desktop/bag` |
| 상태 | 기준 성능 측정 및 개선 방향 검토 완료, 최적화 코드는 아직 미적용 |

이 문서는 현재까지 진행한 CenterPoint PointPillars ROS 2 연동 작업과 추론 속도
분석 결과를 기록하고, 이후 최적화 결과를 같은 조건에서 비교하기 위한 작업
일지이다.

## 1. 현재까지 완료한 작업

- [x] CenterPoint와 PointPillars native 환경 구성
- [x] Jetson용 PyTorch CUDA 동작 확인
- [x] CUDA NMS 확장 모듈 빌드 및 로딩 확인
- [x] ROS 2 Humble `ament_python` 패키지 구성
- [x] Waymo PointCloud2를 모델 입력으로 변환
- [x] 실제 Waymo checkpoint 로딩 확인
- [x] 실제 Waymo bag을 이용한 GPU 추론 확인
- [x] 예측 3D box와 Ground Truth를 RViz2에서 동시 표시
- [x] `/centerpoint/status`를 이용한 추론 시간 측정
- [x] Jetson power mode 확인
- [x] 현재 config와 코드의 주요 병목 검토
- [ ] FP16 mixed precision 적용
- [ ] 세부 구간 profiler 적용
- [ ] NMS 후보 수 최적화
- [ ] 감지 범위 축소 실험
- [ ] TensorRT 변환 검토 및 구현

## 2. 현재 실행 구성

### 모델 config

```text
/home/kopti/Desktop/new-project/centerpoint/src/CenterPoint/configs/waymo/pp/
waymo_centerpoint_pp_two_pfn_stride1_3x.py
```

### checkpoint

```text
/home/kopti/Desktop/bag/
centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
```

### 입력 bag

```text
/home/kopti/Desktop/bag/
├── metadata.yaml
├── waymo_val_sample_0.db3
└── centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
```

### 사용 토픽

| 토픽 | 역할 |
| --- | --- |
| `/waymo/points` | Waymo PointCloud2 입력 |
| `/waymo/ground_truth` | Waymo Ground Truth MarkerArray |
| `/centerpoint/points` | RViz2용 point cloud 출력 |
| `/centerpoint/detections` | PointPillars 예측 box 출력 |
| `/centerpoint/status` | point, voxel, detection 수와 처리 시간 |

## 3. 기준 성능

실제 Waymo bag과 실제 checkpoint를 사용해 확인한 steady-state 값이다.

| 측정 항목 | 확인된 값 |
| --- | --- |
| 모델 추론 `inference_ms` | 약 186-214 ms |
| 전체 callback `total_ms` | 약 208-242 ms |
| 대표 추론 시간 | 약 219 ms |
| 환산 처리 속도 | 약 4.6 FPS |
| Waymo 원본 입력 속도 | 10 Hz |
| 현재 안정적인 bag 재생 속도 | `0.25x`, 약 2.5 Hz |

FPS 환산은 다음과 같다.

```text
FPS = 1000 / inference_ms
1000 / 219 = 약 4.57 FPS
```

Waymo 10 Hz 입력을 실시간으로 처리하려면 다음 조건이 필요하다.

```text
최소 조건: total_ms < 100 ms
권장 조건: total_ms < 80 ms
```

첫 프레임은 Numba voxelization과 CUDA kernel warm-up 때문에 수 초가 걸릴 수 있다.
성능 비교에서는 첫 프레임을 제외해야 한다.

## 4. 현재 모델 연산 규모

config에서 확인한 값은 다음과 같다.

| 항목 | 현재 값 |
| --- | --- |
| x 범위 | `-74.88 ~ 74.88 m` |
| y 범위 | `-74.88 ~ 74.88 m` |
| z 범위 | `-2 ~ 4 m` |
| 처리 면적 | 약 `149.76 x 149.76 m` |
| voxel 크기 | `0.32 x 0.32 x 6.0 m` |
| BEV grid | 약 `468 x 468` |
| voxel당 최대 point | 20 |
| 추론 시 최대 voxel | 60,000 |
| 입력 feature | `x, y, z, intensity, elongation` |
| PFN channel | `64, 64` |
| RPN channel | `64, 128, 256` |
| RPN 출력 channel | `128, 128, 128` |
| NMS 전 최대 후보 | 4,096 |
| NMS 후 최대 후보 | 500 |
| ROS 최종 표시 제한 | 200 |

PointPillars는 point 수만 처리하는 것이 아니라 pillar를 BEV pseudo image로 변환한
뒤 dense 2D convolution을 실행한다. 따라서 넓은 x/y 범위와 큰 BEV grid가 GPU
연산량에 직접적인 영향을 준다.

## 5. 코드에서 확인한 현재 동작

핵심 파일은 다음과 같다.

```text
/home/kopti/Desktop/new-project/centerpoint_ros2_ws/src/
centerpoint_pointpillars_ros/centerpoint_pointpillars_ros/inference_node.py
```

현재 적용된 최적화는 다음과 같다.

- `torch.inference_mode()` 사용
- 모델을 `eval()` mode로 실행
- `torch.backends.cudnn.benchmark = True` 사용
- CUDA NMS 확장 모듈 사용
- GPU 시간 측정을 위해 forward 전후 `torch.cuda.synchronize()` 사용

현재 적용되지 않은 항목은 다음과 같다.

- FP16 autocast
- TensorRT
- INT8 quantization
- CUDA voxelization
- pinned host memory와 비동기 H2D 전송
- 다음 frame 전처리와 현재 frame 추론의 pipeline 처리
- PFN, scatter, RPN, head, NMS별 세부 profiler

현재 처리 흐름은 다음과 같다.

```text
PointCloud2 수신
  -> NumPy [N, 5] 변환
  -> CPU Numba voxelization
  -> PyTorch tensor 생성
  -> CPU에서 GPU로 전송
  -> PFN
  -> Pillar Scatter
  -> RPN
  -> CenterHead
  -> CUDA NMS
  -> GPU 결과를 CPU NumPy로 이동
  -> ROS MarkerArray 생성 및 발행
```

`inference_ms`는 모델의 forward 전체를 측정하므로 PFN, scatter, RPN, CenterHead와
NMS가 포함된다. `total_ms`와의 약 20-30 ms 차이에는 PointCloud2 변환,
voxelization, GPU 전송, 결과 변환과 ROS 발행이 포함된다.

## 6. 개선 우선순위

| 순서 | 개선 항목 | 예상 효과 | 정확도 위험 | 재학습 |
| --- | --- | --- | --- | --- |
| 1 | FP16 mixed precision | 중간에서 큼 | 낮음 | 불필요 |
| 2 | NMS 후보 수 축소 | 작음에서 중간 | 낮음 | 불필요 |
| 3 | Jetson clock 고정 | 작음, 편차 감소 | 없음 | 불필요 |
| 4 | 전처리와 H2D 최적화 | 전체 시간 감소 | 없음 | 불필요 |
| 5 | 감지 x/y 범위 축소 | 큼 | 범위 밖 검출 불가 | 실험 가능 |
| 6 | TensorRT FP16 | 큼 | 낮음 | 불필요 |
| 7 | TensorRT INT8 | 매우 큼 | 중간 | calibration 필요 |
| 8 | voxel/model 경량화 | 매우 큼 | 모델에 따라 다름 | 필요 |

예상 효과는 일반적인 방향을 나타내며, 이 장비에서의 실제 개선율은 같은 bag과
checkpoint로 측정해야 한다.

## 7. 1차 개선안: FP16 mixed precision

현재 모델 forward는 FP32로 실행된다. 우선 `precision` ROS 파라미터를 추가하여
`fp32`와 `fp16`을 선택할 수 있도록 만드는 것이 좋다.

구현 형태는 다음과 같다.

```python
with torch.inference_mode():
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        result = self.model(example, return_loss=False)[0]
```

CenterPoint NMS 코드가 NMS 직전에 box와 score를 `.float()`로 변환하므로 NMS는
FP32로 유지할 수 있다.

FP16 적용 시 확인할 항목은 다음과 같다.

- checkpoint를 다시 학습하지 않고 정상 로딩되는지
- NaN 또는 Inf가 발생하지 않는지
- 동일 frame의 detection 수와 class가 크게 변하지 않는지
- box 위치와 크기가 FP32 결과에서 크게 벗어나지 않는지
- `inference_ms`의 평균과 p95가 감소하는지

FP16은 checkpoint 파일 자체를 미리 변환하는 방식보다 autocast를 우선 사용한다.
문제가 있는 연산만 FP32로 유지할 수 있기 때문이다.

## 8. 2차 개선안: NMS 제한 수정

현재 config는 다음 값을 사용한다.

```python
nms_pre_max_size = 4096
nms_post_max_size = 500
```

ROS 노드는 최종적으로 최대 200개만 표시하지만 현재 초기화 코드는 다음과 같다.

```python
self.cfg.test_cfg.nms.nms_post_max_size = max(
    self.max_detections,
    int(self.cfg.test_cfg.nms.nms_post_max_size),
)
```

`max_detections=200`을 지정해도 `max(200, 500)` 결과가 500이므로 내부 NMS는
최대 500개를 유지한다. 이후 ROS node에서 다시 200개로 줄이기 때문에 불필요한
처리가 발생한다.

검토할 변경은 다음과 같다.

```python
self.cfg.test_cfg.nms.nms_post_max_size = self.max_detections
```

추가로 동일한 검출 결과가 유지되는 범위에서 다음 값을 비교한다.

```text
nms_pre_max_size: 4096 -> 2000 -> 1000
nms_post_max_size: 500 -> 200
```

현재 실제 detection 수는 일반적으로 약 3-18개였기 때문에 NMS 축소가 최종 결과에
미치는 영향은 작을 가능성이 있다. 다만 전체 GPU 시간에서 NMS 비중을 profiler로
먼저 확인해야 한다.

## 9. Jetson power와 clock

오늘 확인한 power mode는 다음과 같다.

```text
NV Power Mode: MAXN
```

따라서 낮은 power mode가 현재 219 ms의 직접적인 원인은 아니다. 다만 GPU clock이
부하와 온도에 따라 변동할 수 있으므로 benchmark 시 clock을 고정하면 측정 편차를
줄일 수 있다.

```bash
sudo jetson_clocks
sudo jetson_clocks --show
```

온도, GPU 사용률, memory 사용량과 clock은 별도 터미널에서 확인한다.

```bash
tegrastats
```

clock 고정은 소비전력과 발열을 증가시킨다. 장시간 실행 시 온도와 thermal
throttling 여부를 함께 기록해야 한다.

## 10. 전처리와 GPU 전송 개선

현재 전체 callback에서 모델 forward 이외의 시간이 약 20-30 ms이다. 다음 순서로
개선할 수 있다.

1. PointCloud2 buffer에서 NumPy 배열을 만들 때 중복 copy를 줄인다.
2. CPU tensor에 pinned memory를 사용한다.
3. `.to(device, non_blocking=True)`로 H2D 전송을 비동기화한다.
4. CPU Numba voxelization을 CUDA voxelization으로 교체한다.
5. 현재 frame을 GPU에서 처리하는 동안 다음 frame을 CPU에서 전처리한다.
6. 입력이 처리 속도보다 빠를 때 오래된 frame을 쌓지 않고 최신 frame만 유지한다.

이 항목들은 모델의 `inference_ms`보다 `total_ms`, 처리량과 입력 지연 누적을
개선하는 데 효과가 있다.

현재 `voxel_ms`는 NumPy voxelization과 tensor 생성 시간을 측정하지만 비동기 CUDA
작업이 완전히 끝난 시간을 정확하게 분리하지 못할 수 있다. 향후 profiler에서는
아래 구간을 각각 측정해야 한다.

```text
pointcloud_decode_ms
voxel_cpu_ms
h2d_ms
pfn_ms
scatter_ms
rpn_ms
head_ms
nms_ms
d2h_ms
marker_publish_ms
total_ms
```

GPU 구간은 일반 wall clock만 사용하지 않고 CUDA Event 또는 명시적인 synchronize를
이용해 측정한다.

## 11. 감지 범위 축소

현재 처리 면적은 약 `149.76 x 149.76 m`이다. 실제 차량 전방 중심으로 다음 범위를
시험할 수 있다.

```text
x: -10 ~ 70 m
y: -40 ~ 40 m
z: -2 ~ 4 m
```

이 x/y 면적은 현재 설정의 약 29%이다. dense BEV backbone이 처리하는 공간이 크게
줄어들기 때문에 높은 속도 개선 가능성이 있다. 하지만 실제 end-to-end 시간이
면적 비율과 정확히 같은 비율로 감소하는 것은 아니다.

범위를 변경할 때 config의 다음 값을 일관되게 변경해야 한다.

- `model.reader.pc_range`
- `voxel_generator.range`
- `test_cfg.pc_range`
- `test_cfg.post_center_limit_range`

범위 밖 객체는 검출할 수 없다. 또한 학습 범위와 추론 범위의 차이가 정확도에
미치는 영향을 Ground Truth로 확인해야 한다.

## 12. voxel 크기와 모델 경량화

현재 x/y voxel 크기는 `0.32 m`이다. 예를 들어 `0.48 m`로 키우면 BEV grid의
가로와 세로 크기가 줄어 convolution 연산량이 크게 감소한다.

하지만 voxel 크기를 변경하면 객체가 grid에 표현되는 방식과 물리적 receptive
field가 달라진다. 단순히 config만 변경하기보다 해당 설정으로 fine-tuning 또는
재학습하는 것이 안전하다.

추가 경량화 후보는 다음과 같다.

- PFN channel 수 감소
- RPN layer 수 감소
- RPN channel `64/128/256` 축소
- head channel 축소
- 최대 voxel 수 축소
- 실제 필요 없는 class 제거

모델 구조를 변경하면 현재 checkpoint를 그대로 strict load할 수 없으므로 새로운
학습 또는 fine-tuning이 필요하다.

## 13. TensorRT 적용 방향

안정적인 10 Hz가 목표라면 PyTorch FP16만으로 목표를 달성하지 못할 가능성이 있다.
최종 배포 단계에서는 TensorRT FP16을 우선 검토한다.

권장 단계는 다음과 같다.

```text
PointCloud2
  -> voxelization
  -> PFN / Pillar Scatter
  -> TensorRT FP16 RPN / CenterHead
  -> CUDA NMS
  -> ROS MarkerArray
```

전체 모델을 한 번에 ONNX/TensorRT로 변환하면 dynamic voxel shape, Pillar Scatter,
CUDA NMS custom op에서 문제가 생길 가능성이 있다. 먼저 연산 비중이 큰 dense RPN과
CenterHead를 TensorRT로 변환하고, 전처리와 NMS는 기존 구현을 유지하는 단계적
접근을 사용한다.

TensorRT 적용 단계는 다음과 같다.

1. PyTorch FP32 기준 결과 저장
2. PyTorch FP16 결과와 비교
3. export 가능한 모델 구간 분리
4. ONNX graph 검증
5. TensorRT FP16 engine 생성
6. 같은 100개 frame에서 결과와 latency 비교
7. 필요할 경우 INT8 calibration 데이터 준비
8. TensorRT INT8 결과와 정확도 비교

INT8은 대표 Waymo frame을 이용한 calibration 또는 QAT가 필요하다. 속도만 비교하지
않고 class별 누락, box 위치와 score 변화도 확인해야 한다.

## 14. 우선순위가 낮거나 속도를 직접 개선하지 않는 항목

### Docker에서 native로 변경

native 구성은 저장공간과 관리 측면에서 유리하지만, 같은 CUDA/PyTorch kernel을
사용한다면 모델 연산 자체가 자동으로 크게 빨라지는 것은 아니다.

### `nvcc` 설치 또는 PATH 변경

`nvcc`는 CUDA 확장을 컴파일할 때 필요하다. 이미 빌드된 CUDA kernel의 실행 속도를
높이지는 않는다.

### bag 재생 속도 낮추기

`0.25x` 재생은 입력과 prediction의 정렬을 유지하지만 모델의 219 ms 추론 시간을
줄이지 않는다.

### synchronize 제거

`torch.cuda.synchronize()`를 제거하면 출력된 측정 시간이 작아 보일 수 있지만
실제 CUDA 작업이 빨라지는 것은 아니다. 결과를 `.cpu()`로 가져올 때 결국 GPU
완료를 기다리게 된다.

### spconv 설치

현재 모델은 PointPillars dense BEV 방식이며 이 실행 경로에 spconv이 필요하지 않다.
spconv 설치만으로 현재 모델이 빨라지지 않는다.

## 15. 성능 비교 방법

모든 최적화는 같은 조건에서 비교한다.

```text
bag: 동일한 waymo_val_sample_0.db3
checkpoint: 동일한 epoch12 weight
score threshold: 0.5
max detections: 200
warm-up: 최초 10 frame 제외
측정 frame: 최소 100 frame
power mode: MAXN
RViz2: 순수 성능 비교 시 비활성화
```

RViz2를 끄고 한 번만 재생하는 예시는 다음과 같다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
RVIZ=false LOOP=false BAG_RATE=0.25 ./scripts/run_waymo_bag.sh
```

다른 터미널에서 status를 기록한다.

```bash
source /opt/ros/humble/setup.bash
source /home/kopti/Desktop/new-project/centerpoint_ros2_ws/install/local_setup.bash
ros2 topic echo /centerpoint/status
```

각 실험에서 다음 값을 기록한다.

| 실험 | precision | 범위 | NMS pre/post | 평균 inference | p95 inference | 평균 total | detection 차이 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 기준 | FP32 | 전체 | 4096/500 | 219 ms 부근 | 미측정 | 208-242 ms | 기준 |
| FP16 | 미실시 | 전체 | 4096/500 | 미측정 | 미측정 | 미측정 | 미측정 |
| FP16+NMS | 미실시 | 전체 | 1000/200 | 미측정 | 미측정 | 미측정 | 미측정 |
| 범위 축소 | 미실시 | 전방 중심 | 1000/200 | 미측정 | 미측정 | 미측정 | 미측정 |
| TensorRT FP16 | 미실시 | 결정 예정 | 결정 예정 | 미측정 | 미측정 | 미측정 | 미측정 |

성능 숫자 외에 다음 항목도 비교한다.

- 프레임별 detection 수
- class별 detection 수
- confidence score 변화
- FP32 대비 box 중심과 크기 차이
- Ground Truth 누락과 오검출 변화
- GPU 온도와 clock
- 장시간 실행 시 throttling 여부

## 16. 단계별 목표

### 1단계: 재학습 없는 PyTorch 최적화

```text
목표: inference_ms 150 ms 이하
작업: FP16 + NMS 제한 + clock 고정 + 전처리 측정
```

### 2단계: 입력 범위와 pipeline 최적화

```text
목표: total_ms 100 ms 부근
작업: 전방 범위 실험 + H2D 개선 + 최신 frame 처리 구조
```

### 3단계: 배포 runtime 최적화

```text
목표: 안정적인 10 Hz, total_ms 80-100 ms 이하
작업: TensorRT FP16, 필요하면 INT8 또는 경량 모델 재학습
```

## 17. 다음 작업

다음 구현은 재학습 없이 현재 bag과 weight로 비교할 수 있는 항목부터 진행한다.

1. `precision:=fp32|fp16` ROS 파라미터 추가
2. 기존 FP32 결과 100 frame 기록
3. FP16 결과 100 frame 기록
4. NMS post limit를 실제 `max_detections`와 일치시키기
5. NMS pre limit 4096, 2000, 1000 비교
6. 구간별 CUDA profiler 추가
7. 성능과 detection 결과를 이 문서의 비교 표에 기록

현재 시점에는 위 최적화가 코드에 적용되지 않았다. 기준 동작을 보존한 상태에서
각 변경을 한 단계씩 적용하고 측정한 뒤 다음 단계로 진행한다.
