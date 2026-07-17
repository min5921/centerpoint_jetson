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
| 상태 | FP16 적용 및 1차 FP32/FP16 비교 완료 |

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
- [x] FP16 mixed precision 적용
- [x] FP32/FP16 연속 frame 성능 비교
- [x] 세부 구간 profiler 적용 및 FP16 병목 측정
- [x] NMS 후보 수 조합 benchmark, 유의미한 개선 없음
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
- `precision:=fp16`일 때 CUDA autocast 사용
- `precision:=fp32` 비교 및 복구 경로 제공
- CUDA NMS 확장 모듈 사용
- GPU 시간 측정을 위해 forward 전후 `torch.cuda.synchronize()` 사용

현재 적용되지 않은 항목은 다음과 같다.

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

2026-07-17 작업에서 `precision` ROS 파라미터를 추가하여 `fp32`와 `fp16`을
선택할 수 있도록 구현했다. 기본값은 `fp16`이다.

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

실행 방법은 다음과 같다.

```bash
# 기본 FP16 실행
./scripts/run_waymo_bag.sh

# 비교 또는 복구용 FP32 실행
PRECISION=fp32 ./scripts/run_waymo_bag.sh
```

launch를 직접 사용할 때는 다음 인자를 지정한다.

```bash
ros2 launch centerpoint_pointpillars_ros inference.launch.py precision:=fp16
```

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
| 기준 | FP32 | 전체 | 4096/500 | 190.0 ms | 237.2 ms | 215.1 ms | 기준 |
| FP16 | FP16 autocast | 전체 | 4096/500 | 144.9 ms | 171.8 ms | 165.8 ms | 정밀 비교 필요 |
| FP16+NMS | FP16 autocast | 전체 | 1000/200 | 143.2 ms | 171.4 ms | 166.2 ms | 동일 frame 비교 미실시 |
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

1. 동일 timestamp frame의 FP32/FP16 box 좌표와 score 비교
2. Ground Truth 기반 정확도 또는 mAP 비교
3. RPN과 CenterHead 최적화 방법 비교
4. 전처리와 H2D 전송 시간 최적화

FP16은 기본 실행 mode로 적용했다. 이후 변경도 FP32 복구 경로를 유지하면서 한
단계씩 적용하고 측정한 뒤 다음 단계로 진행한다.

## 18. FP32에서 FP16으로 변경한 결과

### 구현 내용

2026-07-17에 다음 파일을 변경했다.

| 파일 | 변경 내용 |
| --- | --- |
| `inference_node.py` | `precision` 파라미터 검증, CUDA autocast, status에 precision 추가 |
| `inference.launch.py` | `precision` launch 인자 추가, 기본값 `fp16` |
| `run_rviz.sh` | `PRECISION` 환경 변수를 launch로 전달 |
| `run_waymo_bag.sh` | Waymo 실행에 `PRECISION` 전달 |

FP16은 모델 weight를 `.half()`로 영구 변환하지 않고 forward 구간에 autocast를
사용한다.

```python
with torch.inference_mode():
    with torch.autocast(
        device_type=self.device.type,
        dtype=torch.float16,
        enabled=self.use_amp,
    ):
        result = self.model(example, return_loss=False)[0]
```

잘못된 precision 값은 시작 시 거부한다.

```text
허용: fp16, fp32
기본값: fp16
fp16 조건: CUDA device 필요
```

### 측정 조건

```text
장비: Jetson AGX Orin Developer Kit
power mode: MAXN
bag rate: 0.25x
RViz2: 비활성화
score threshold: 0.5
NMS pre/post: 4096/500, 변경하지 않음
FP32 수집: 연속 50 frame
FP16 수집: 연속 64 frame
첫 frame warm-up: 제외
```

고정된 30초 동안 `/centerpoint/status`를 연속 수집했다. FP16이 더 많은 frame을
처리했기 때문에 같은 시간에 수집된 표본 수도 더 많았다.

### 측정 결과

| 지표 | FP32 | FP16 | 개선율 |
| --- | ---: | ---: | ---: |
| inference 평균 | 190.0 ms | 144.9 ms | 23.7% |
| inference p50 | 184.2 ms | 143.3 ms | 22.2% |
| inference p95 | 237.2 ms | 171.8 ms | 27.6% |
| inference 최소 | 157.0 ms | 113.4 ms | 참고값 |
| inference 최대 | 261.8 ms | 202.8 ms | 참고값 |
| total 평균 | 215.1 ms | 165.8 ms | 22.9% |
| total p50 | 208.9 ms | 162.0 ms | 22.5% |
| total p95 | 261.5 ms | 197.4 ms | 24.5% |

평균 시간으로 환산한 처리 속도는 다음과 같다.

```text
모델 inference 기준
FP32: 1000 / 190.0 = 약 5.26 FPS
FP16: 1000 / 144.9 = 약 6.90 FPS

전체 callback 기준
FP32: 1000 / 215.1 = 약 4.65 FPS
FP16: 1000 / 165.8 = 약 6.03 FPS
```

FP16 변경으로 평균 추론 시간은 약 45.1 ms, 전체 callback은 약 49.3 ms
감소했다. 실제 CUDA 실행 중 NaN, Inf 또는 inference error는 발생하지 않았고
3D detection MarkerArray도 계속 발행됐다.

### 결과 해석과 남은 검증

FP16은 현재 장비에서 의미 있는 속도 개선을 보였지만, 전체 callback 평균이
`165.8 ms`이므로 10 Hz 실시간 목표인 `100 ms`에는 아직 도달하지 못했다.

이번 측정은 동일한 bag을 사용했지만 FP32와 FP16을 순차 실행하여 서로 다른 구간의
frame을 수집했다. 따라서 detection이 정상 발행되는 것은 확인했지만 동일 timestamp
frame의 box 좌표, score와 class가 수치적으로 동일한지는 아직 검증하지 않았다.

다음 정확도 검증에서는 동일 frame을 각각 저장해 아래 항목을 비교해야 한다.

- detection 수와 class
- confidence score 차이
- box 중심, 크기와 yaw 차이
- Ground Truth 기준 누락과 오검출
- 가능하면 Waymo metric 또는 mAP

FP16 적용 후 세부 profiler를 실행한 결과는 다음 절에 기록했다. 실제 주 병목은
NMS가 아니라 dense RPN과 CenterHead로 확인됐다.

## 19. PointPillars 단계별 병목 측정

### 측정 목적

전방 120도 FOV 필터를 적용하기 전에 point 수 감소가 실제 주 병목을 줄일 수 있는지
확인하기 위해 모델과 ROS callback을 단계별로 나누어 측정했다.

### profiler 구현

`profile_stages` ROS 파라미터를 추가했다. 기본값은 `false`이므로 일반 실행은 기존
모델 forward를 그대로 사용한다. profiler를 활성화하면 PointPillars forward를
다음 단계로 분리한다.

```text
PointCloud2 publish
  -> PointCloud2 decode
  -> CPU voxelization
  -> H2D transfer
  -> PFN
  -> Pillar Scatter
  -> RPN
  -> CenterHead
  -> box decode + CUDA NMS
  -> D2H + NumPy filter
  -> MarkerArray 생성 및 publish
```

CPU 구간은 `time.perf_counter()`를 사용하고 GPU 모델 구간은 CUDA Event를 사용한다.
모든 GPU Event는 같은 CUDA stream에서 기록하고 마지막에 synchronize하여 각 구간의
실제 실행 시간을 계산한다.

profiler 실행 명령은 다음과 같다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
PRECISION=fp16 \
PROFILE_STAGES=true \
RVIZ=false \
LOOP=true \
BAG_RATE=0.25 \
./scripts/run_waymo_bag.sh
```

다른 터미널에서 전체 측정값을 확인할 수 있다.

```bash
source /opt/ros/humble/setup.bash
source /home/kopti/Desktop/new-project/centerpoint_ros2_ws/install/local_setup.bash
ros2 topic echo /centerpoint/status
```

일반 실행에서는 profiler를 끈다.

```bash
PROFILE_STAGES=false ./scripts/run_waymo_bag.sh
```

### 측정 조건

```text
날짜: 2026-07-17
precision: FP16 autocast
profile_stages: true
RViz2: 비활성화
bag rate: 0.25x
score threshold: 0.5
warm-up frame: 제외
측정 frame: 연속 51개
평균 point 수: 49,563
평균 voxel 수: 11,632
평균 detection 수: 7.9
```

profiler 자체의 CUDA Event 생성과 수집 비용이 포함되므로 일반 FP16 실행보다 평균
추론 시간이 약간 증가할 수 있다. profiler를 끈 이전 FP16 평균은 `144.9 ms`, 이번
profiler 실행 평균은 `152.5 ms`였다.

### 전체 측정 결과

| 구간 | 평균 | p50 | p95 | 최소 | 최대 |
| --- | ---: | ---: | ---: | ---: | ---: |
| PointCloud publish | 0.7 ms | 0.7 ms | 0.9 ms | 0.4 ms | 2.1 ms |
| PointCloud decode | 6.7 ms | 6.7 ms | 7.2 ms | 5.2 ms | 7.2 ms |
| CPU voxelization | 7.4 ms | 7.5 ms | 8.2 ms | 4.3 ms | 8.6 ms |
| H2D transfer | 3.3 ms | 3.0 ms | 5.8 ms | 2.5 ms | 6.5 ms |
| PFN | 23.7 ms | 20.0 ms | 43.8 ms | 12.3 ms | 46.7 ms |
| Pillar Scatter | 4.5 ms | 3.7 ms | 9.1 ms | 2.4 ms | 13.2 ms |
| RPN | 73.1 ms | 71.3 ms | 95.5 ms | 58.1 ms | 101.3 ms |
| CenterHead | 38.6 ms | 38.1 ms | 46.8 ms | 27.5 ms | 48.4 ms |
| box decode + NMS | 11.2 ms | 10.6 ms | 15.3 ms | 7.8 ms | 16.1 ms |
| D2H + NumPy filter | 0.6 ms | 0.6 ms | 0.7 ms | 0.3 ms | 0.7 ms |
| MarkerArray publish | 5.8 ms | 5.5 ms | 8.4 ms | 1.6 ms | 11.2 ms |
| 전체 모델 inference | 152.5 ms | 150.4 ms | 183.1 ms | 121.3 ms | 195.1 ms |
| 전체 callback | 177.1 ms | 176.4 ms | 211.3 ms | 145.9 ms | 222.0 ms |

51개 frame에서 inference error는 발생하지 않았다.

### 모델 내부 비중

| 모델 단계 | 평균 | inference 대비 비중 |
| --- | ---: | ---: |
| PFN | 23.7 ms | 15.5% |
| Pillar Scatter | 4.5 ms | 3.0% |
| RPN | 73.1 ms | 47.9% |
| CenterHead | 38.6 ms | 25.3% |
| box decode + NMS | 11.2 ms | 7.3% |

RPN과 CenterHead 합계는 `111.7 ms`이다.

```text
RPN + CenterHead = inference 시간의 73.2%
RPN + CenterHead = 전체 callback 시간의 63.1%
```

따라서 가장 큰 병목은 dense BEV convolution을 실행하는 RPN이며, 두 번째는
CenterHead이다. PFN은 세 번째이고 NMS의 비중은 상대적으로 작다.

### 전방 120도 필터에 대한 판단

전방 120도 point 필터는 입력 point와 pillar 수를 줄이므로 다음 구간은 개선될 수
있다.

- PointCloud decode 이후 filtering
- CPU voxelization
- H2D transfer
- PFN
- Pillar Scatter

하지만 현재 PointPillars의 BEV canvas 크기는 약 `468 x 468`로 고정되어 있다.
point를 제거해도 RPN과 CenterHead는 같은 크기의 dense BEV feature map을 처리한다.
전체 callback의 63.1%를 차지하는 두 구간이 그대로 남으므로 단순 angular filter의
속도 개선은 제한적일 가능성이 높다.

속도를 목적으로 범위를 줄인다면 point만 필터링하는 것보다 config의 x/y range와
BEV grid 자체를 함께 줄이는 직사각형 ROI 실험이 더 직접적이다. 전방 120도 조건이
필요한 경우에는 다음 두 단계를 함께 사용할 수 있다.

1. 전방 중심의 작은 직사각형 BEV range로 RPN 입력 크기를 줄인다.
2. 직사각형 안에서 각도 기준 120도 point filter를 적용한다.

### 다음 최적화 우선순위

이번 측정 결과를 기준으로 다음 순서가 적절하다.

1. RPN과 CenterHead에 TensorRT FP16 적용 가능성 확인
2. 전방 중심의 축소된 x/y range와 BEV grid 실험
3. RPN channel 또는 layer 경량화 후 fine-tuning
4. PFN 최적화와 point/voxel 수 제한 실험
5. PointCloud decode, H2D와 MarkerArray 최적화

NMS 평균은 `11.2 ms`이므로 NMS만 최적화해서는 10 Hz 목표에 도달할 수 없다.
반대로 RPN과 CenterHead를 절반으로 줄이면 이론적으로 약 `55.9 ms`를 줄일 수 있어
우선순위가 가장 높다.

## 20. NMS 후보 수 조절 결과

### 목표

목표 처리 속도를 end-to-end `7 FPS`로 설정했다.

```text
7 FPS에 필요한 전체 callback 시간 = 1000 / 7 = 142.9 ms 이하
현재 일반 FP16 전체 callback 평균 = 165.8 ms
추가로 줄여야 하는 시간 = 약 22.9 ms
```

단계별 profiler에서 box decode와 NMS 합계는 평균 `11.2 ms`였다. 따라서 이 구간을
완전히 제거해도 단독으로는 7 FPS에 도달할 수 없지만, 실제 조절 효과를 확인하기
위해 후보 수 조합을 비교했다.

### 구현 내용

다음 ROS 파라미터와 launch 인자를 추가했다.

```text
nms_pre_max_size
nms_post_max_size
```

`nms_pre_max_size`는 CUDA NMS에 입력되는 score 상위 box 수를 제한한다.
`nms_post_max_size`는 NMS가 끝난 뒤 반환할 최대 box 수를 제한하므로 연산 시간에는
영향이 거의 없다.

환경 변수로 값을 변경할 수 있다.

```bash
NMS_PRE_MAX_SIZE=1000 \
NMS_POST_MAX_SIZE=200 \
./scripts/run_waymo_bag.sh
```

잘못된 설정을 방지하기 위해 다음 조건을 검사한다.

```text
nms_pre_max_size >= 1
nms_post_max_size >= 1
nms_post_max_size <= nms_pre_max_size
```

### 측정 조건

```text
precision: FP16 autocast
profile_stages: true
RViz2: 비활성화
bag rate: 0.25x
score threshold: 0.5
NMS IoU threshold: 0.7
첫 warm-up frame: 제외
```

### 측정 결과

| NMS pre/post | frame 수 | decode+NMS 평균 | decode+NMS p95 | inference 평균 | total 평균 | 평균 detection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4096/500 | 51 | 11.2 ms | 15.3 ms | 152.5 ms | 177.1 ms | 7.9 |
| 2000/200 | 32 | 11.1 ms | 14.0 ms | 153.5 ms | 177.2 ms | 7.6 |
| 1000/200 | 61 | 10.9 ms | 13.4 ms | 143.2 ms | 166.2 ms | 6.5 |
| 500/100 | 41 | 11.6 ms | 14.8 ms | 158.3 ms | 181.7 ms | 6.3 |

각 조합은 같은 bag을 사용했지만 순차 실행 중 서로 다른 구간의 frame을 수집했다.
따라서 inference와 total 평균 차이에는 scene별 voxel 수, RPN 시간, GPU clock과
시스템 부하 변동이 포함된다. `1000/200`의 낮은 total 시간을 NMS 조절 효과로
해석하면 안 된다.

NMS 설정이 직접 영향을 주는 `decode+NMS` 평균만 비교하면 다음과 같다.

```text
4096/500: 11.2 ms
2000/200: 11.1 ms, 0.1 ms 감소
1000/200: 10.9 ms, 0.3 ms 감소
500/100: 11.6 ms, 감소 없음
```

차이는 측정 편차 수준이며 pre limit를 500까지 줄여도 추가 이득이 없었다. score
threshold `0.5`를 통과한 후보가 이미 제한값보다 적거나, 이 구간에서 heatmap과 box
decode 같은 고정 비용의 비중이 더 큰 것으로 판단된다.

평균 detection 수는 서로 다른 scene 구간에서 측정했으므로 NMS 설정에 따른 정확도
변화로 해석할 수 없다. 동일 timestamp frame의 box, score와 class 비교는 수행하지
않았다.

### 결론

- NMS 후보 수 조절로 확인된 직접적인 개선은 최대 약 `0.3 ms`였다.
- `7 FPS` 목표인 `142.9 ms`에는 도달하지 못했다.
- NMS 추가 조절은 현재 우선순위에서 제외한다.
- 정확도 검증 없이 공격적인 제한을 기본값으로 사용하지 않는다.
- 기본값은 원래 config와 같은 `4096/500`으로 유지한다.
- 실험용 NMS 파라미터 기능은 이후 재현을 위해 코드에 남긴다.

다음 속도 개선 대상은 전체 callback의 63.1%를 차지하는 RPN과 CenterHead이다.
