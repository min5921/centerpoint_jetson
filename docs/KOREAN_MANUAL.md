# CenterPoint PointPillars ROS 2 전체 실행 매뉴얼

이 문서는 ROS 2를 처음 사용하는 사람도 현재 Jetson에서 Waymo bag을 재생하고,
CenterPoint PointPillars GPU 추론 결과를 RViz2로 확인할 수 있도록 작성되었습니다.

## 1. 실행 결과

정상 실행되면 다음 데이터가 동시에 RViz2에 표시됩니다.

- 회색 점: Waymo LiDAR 포인트 클라우드
- 반투명 색상 box: CenterPoint가 예측한 객체
- box 위 흰색 글자: 객체 종류와 confidence score
- Waymo Ground Truth: bag에 저장된 정답 box

예측 객체 색상은 다음과 같습니다.

| 객체 | 색상 |
| --- | --- |
| `VEHICLE` | 파란색 |
| `PEDESTRIAN` | 빨간색 |
| `CYCLIST` | 노란색 |

## 2. ROS 1 catkin과 ROS 2 colcon의 차이

이 프로젝트는 **ROS 2 Humble** 프로젝트입니다.

- ROS 1: `catkin_ws`, `catkin_make`
- ROS 2: `colcon`, `ament_python`

따라서 이 프로젝트를 `catkin_ws/src`에 복사하거나 `catkin_make`를 실행하지
않습니다. 현재의 `centerpoint_ros2_ws`가 완전한 ROS 2 workspace입니다.

## 3. 현재 장비의 디렉터리

```text
/home/kopti/Desktop/
├── bag/
│   ├── metadata.yaml
│   ├── waymo_val_sample_0.db3
│   └── centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
└── new-project/
    ├── centerpoint/
    │   ├── .venv-jetson/
    │   └── src/CenterPoint/
    └── centerpoint_ros2_ws/
        ├── README.md
        ├── docs/
        ├── scripts/
        └── src/centerpoint_pointpillars_ros/
```

각 파일의 자세한 역할은
[전체 파일 구조와 코드 설명](CODE_AND_FILE_STRUCTURE.md)을 참고합니다.

## 4. 준비된 실행 환경 확인

새 터미널을 열고 아래 명령을 실행합니다.

```bash
python3 --version
/usr/local/cuda/bin/nvcc --version
ls /opt/ros/humble/setup.bash
ls /home/kopti/Desktop/new-project/centerpoint/.venv-jetson/bin/python
ls /home/kopti/Desktop/bag/metadata.yaml
ls /home/kopti/Desktop/bag/centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
```

현재 장비에서 확인된 버전은 다음과 같습니다.

```text
Python 3.10.12
CUDA compilation tools, release 12.6, V12.6.68
ROS 2 Humble
```

`nvcc --version`에서 아무것도 나오지 않거나 명령을 찾지 못하면 PATH와 관계없이
다음 절대 경로 명령으로 확인합니다.

```bash
/usr/local/cuda/bin/nvcc --version
```

PyTorch에서 GPU를 사용할 수 있는지도 확인할 수 있습니다.

```bash
/home/kopti/Desktop/new-project/centerpoint/.venv-jetson/bin/python -c \
  "import torch; print('torch=', torch.__version__); print('cuda=', torch.cuda.is_available()); print('device=', torch.cuda.get_device_name(0))"
```

`cuda= True`가 출력되어야 합니다.

CUDA NMS 확장 모듈도 필요합니다.

```bash
ls /home/kopti/Desktop/new-project/centerpoint/src/CenterPoint/det3d/ops/iou3d_nms/iou3d_nms_cuda*.so
```

현재 구성은 PointPillars 모델이므로 `spconv`은 사용하지 않습니다.

## 5. 처음 한 번 빌드하기

### 5.1 스크립트로 빌드

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
./scripts/build.sh
```

### 5.2 스크립트 없이 직접 빌드

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
source /opt/ros/humble/setup.bash
/home/kopti/Desktop/new-project/centerpoint/.venv-jetson/bin/colcon build \
  --symlink-install \
  --packages-select centerpoint_pointpillars_ros
```

정상 빌드되면 다음 폴더가 생성됩니다.

- `build/`: 패키지 빌드 중간 결과
- `install/`: ROS 2가 실행할 수 있도록 설치된 패키지
- `log/`: colcon 빌드 로그

Python 코드만 변경한 경우 `--symlink-install` 덕분에 대부분 즉시 반영됩니다.
`setup.py`, launch 파일, RViz 설정, 패키지 메타데이터를 변경한 뒤에는 다시
빌드하는 것이 안전합니다.

## 6. Waymo bag을 가장 쉽게 실행하기

빌드 후 다음 한 줄을 실행합니다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
./scripts/run_waymo_bag.sh
```

이 스크립트는 다음 작업을 순서대로 수행합니다.

1. native Python/CUDA 환경을 설정합니다.
2. CenterPoint PointPillars 추론 노드를 실행합니다.
3. RViz2를 실행합니다.
4. 모델 로딩을 위해 5초 기다립니다.
5. Waymo bag을 `0.25x` 속도로 반복 재생합니다.

사용 예시는 다음과 같습니다.

```bash
# bag을 한 번만 재생
LOOP=false ./scripts/run_waymo_bag.sh

# 재생 속도를 0.5배로 변경
BAG_RATE=0.5 ./scripts/run_waymo_bag.sh

# score 0.35 이상인 box 표시
SCORE_THRESHOLD=0.35 ./scripts/run_waymo_bag.sh

# RViz2 없이 추론만 실행
RVIZ=false ./scripts/run_waymo_bag.sh

# 다른 weight 사용
CHECKPOINT=/absolute/path/to/another_model.pth ./scripts/run_waymo_bag.sh
```

## 7. 스크립트 없이 전체 실행하기

이 절에서는 shell script가 내부에서 하는 작업을 직접 실행합니다. 터미널 두 개를
사용합니다.

### 7.1 터미널 1: 환경 설정, 추론 노드, RViz2

아래 블록 전체를 같은 터미널에서 순서대로 실행합니다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws

source /opt/ros/humble/setup.bash
source install/local_setup.bash

export CENTERPOINT_ROOT=/home/kopti/Desktop/new-project/centerpoint
export VENV="$CENTERPOINT_ROOT/.venv-jetson"
export CENTERPOINT_PYTHON="$VENV/bin/python"
export CENTERPOINT_CONFIG="$CENTERPOINT_ROOT/src/CenterPoint/configs/waymo/pp/waymo_centerpoint_pp_two_pfn_stride1_3x.py"
export CENTERPOINT_CHECKPOINT=/home/kopti/Desktop/bag/centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth

export PYTHONPATH="$CENTERPOINT_ROOT/src/CenterPoint${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$VENV/vendor/libcusparse_lt-linux-sbsa-0.5.2.1-archive/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CUDA_HOME=/usr/local/cuda

mkdir -p .cache/numba .cache/ros-log
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
export ROS_LOG_DIR="$PWD/.cache/ros-log"

ros2 launch centerpoint_pointpillars_ros inference.launch.py \
  input_topic:=/waymo/points \
  frame_id:=vehicle \
  score_threshold:=0.5 \
  max_detections:=200 \
  rviz:=true
```

`Ready: input=/waymo/points` 로그가 나오면 입력을 기다리는 상태입니다.

### 7.2 터미널 2: Waymo bag 재생

새 터미널을 열고 실행합니다.

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /home/kopti/Desktop/bag \
  --rate 0.25 \
  --loop \
  --topics /waymo/points /waymo/ground_truth /waymo/frame_info
```

한 번만 재생하려면 `--loop`를 제거합니다.

## 8. launch 파일도 사용하지 않고 각각 실행하기

노드와 RViz2를 완전히 분리해서 실행하려면 터미널 세 개를 사용합니다. 먼저
터미널 1에서 7.1절의 환경 변수 설정을 `ros2 launch` 직전까지 실행합니다.

### 8.1 터미널 1: 추론 Python 모듈 직접 실행

```bash
"$CENTERPOINT_PYTHON" -m centerpoint_pointpillars_ros.inference_node \
  --ros-args \
  -p config_path:="$CENTERPOINT_CONFIG" \
  -p checkpoint_path:="$CENTERPOINT_CHECKPOINT" \
  -p input_topic:=/waymo/points \
  -p points_topic:=/centerpoint/points \
  -p detections_topic:=/centerpoint/detections \
  -p status_topic:=/centerpoint/status \
  -p frame_id:=vehicle \
  -p device:=cuda:0 \
  -p score_threshold:=0.5 \
  -p max_detections:=200 \
  -p intensity_field:=intensity \
  -p elongation_field:=elongation \
  -p normalize_intensity:=true
```

### 8.2 터미널 2: RViz2 직접 실행

```bash
source /opt/ros/humble/setup.bash
rviz2 \
  -d /home/kopti/Desktop/new-project/centerpoint_ros2_ws/install/centerpoint_pointpillars_ros/share/centerpoint_pointpillars_ros/rviz/pointpillars.rviz \
  -f vehicle
```

### 8.3 터미널 3: bag 직접 재생

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /home/kopti/Desktop/bag \
  --rate 0.25 \
  --loop \
  --topics /waymo/points /waymo/ground_truth /waymo/frame_info
```

## 9. RViz2에서 확인할 항목

RViz2 왼쪽 `Displays` 패널에서 다음 항목이 활성화되어 있어야 합니다.

| Display 이름 | 토픽 |
| --- | --- |
| `LiDAR Points` | `/centerpoint/points` |
| `PointPillars Detections` | `/centerpoint/detections` |
| `Waymo Ground Truth` | `/waymo/ground_truth` |

상단 또는 Global Options의 `Fixed Frame`은 `vehicle`이어야 합니다. 화면이 비어
있으면 먼저 Fixed Frame과 토픽 이름을 확인합니다.

마우스 조작은 다음과 같습니다.

- 왼쪽 버튼 드래그: 시점 회전
- 가운데 버튼 드래그: 화면 이동
- 휠: 확대/축소

## 10. 실행 상태 확인

새 터미널에서 ROS 2 환경을 먼저 불러옵니다.

```bash
source /opt/ros/humble/setup.bash
source /home/kopti/Desktop/new-project/centerpoint_ros2_ws/install/local_setup.bash
```

현재 토픽 목록을 확인합니다.

```bash
ros2 topic list
```

추론 시간과 검출 수를 확인합니다.

```bash
ros2 topic echo /centerpoint/status
```

출력 예시는 다음과 같습니다.

```text
data: frame=20 points=50927 voxels=... detections=5 voxel_ms=... inference_ms=... total_ms=...
```

입력과 출력 주기를 확인합니다.

```bash
ros2 topic hz /waymo/points
ros2 topic hz /centerpoint/detections
```

bag 자체 정보를 확인합니다.

```bash
ros2 bag info /home/kopti/Desktop/bag
```

현재 bag에는 약 20초 분량의 10 Hz 데이터가 있으며, 아래 세 토픽이 각각 200개
메시지를 가집니다.

- `/waymo/points`
- `/waymo/ground_truth`
- `/waymo/frame_info`

## 11. 주요 launch 인자와 node 파라미터

### launch 인자

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `config` | `$CENTERPOINT_CONFIG` | Waymo PointPillars config |
| `checkpoint` | `$CENTERPOINT_CHECKPOINT` | 학습 weight 파일 |
| `input_topic` | `/lidar/points` | 입력 PointCloud2 토픽 |
| `frame_id` | `lidar` | 출력과 RViz2의 좌표 frame |
| `score_threshold` | `0.5` | 표시할 최소 confidence |
| `max_detections` | `200` | 프레임당 최대 box 수 |
| `rviz` | `true` | RViz2 실행 여부 |

### 추론 node의 추가 파라미터

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `device` | `cuda:0` | 추론 GPU |
| `points_topic` | `/centerpoint/points` | RViz2용 cloud 출력 |
| `detections_topic` | `/centerpoint/detections` | 예측 MarkerArray 출력 |
| `status_topic` | `/centerpoint/status` | 성능 상태 문자열 출력 |
| `intensity_field` | `intensity` | 입력 intensity 필드명 |
| `elongation_field` | `elongation` | 입력 elongation 필드명 |
| `normalize_intensity` | `true` | intensity에 `tanh` 적용 |

## 12. 입력 PointCloud2 조건

입력 cloud는 다음 좌표계를 사용해야 합니다.

- x: 차량 전방
- y: 차량 왼쪽
- z: 위쪽

필수 필드는 `x`, `y`, `z`입니다. 모델 입력은 최종적으로
`x, y, z, intensity, elongation`의 5개 값으로 구성됩니다.

현재 Waymo bag에는 `elongation` 필드가 없으므로 노드가 0으로 채웁니다. 실행 중
아래 경고가 한 번 나오는 것은 정상입니다.

```text
PointCloud2 field 'elongation' is missing; filling it with zeros
```

현재 bag의 intensity에는 학습 전처리와 맞추기 위해 `tanh`를 적용합니다.

## 13. 성능 해석

현재 장비에서 실제 bag과 weight로 확인한 steady-state 값은 대략 다음과 같습니다.

- 순수 GPU 모델 추론: 약 186-214 ms
- voxel 생성과 후처리를 포함한 전체 callback: 약 208-242 ms
- 첫 프레임: Numba 및 CUDA warm-up 때문에 수 초 걸릴 수 있음

따라서 219 ms는 오류는 아니지만 약 4.6 FPS에 해당하므로, 원본 bag의 10 Hz를
실시간으로 모두 처리하기에는 느립니다. 입력과 예측 box의 시간 정렬을 유지하기
위해 기본 bag 속도를 `0.25x`로 설정했습니다.

성능을 비교할 때는 첫 프레임을 제외하고 `/centerpoint/status`의
`inference_ms`와 `total_ms`를 각각 확인합니다.

## 14. 종료 방법

실행한 터미널에서 `Ctrl+C`를 한 번 누릅니다. `run_waymo_bag.sh`는 bag player와
launch process를 함께 종료합니다.

각각 직접 실행했다면 bag, RViz2, 추론 노드가 실행 중인 각 터미널에서
`Ctrl+C`를 누릅니다.

## 15. 문제 해결

### `Package 'centerpoint_pointpillars_ros' not found`

workspace를 빌드하고 현재 터미널에서 setup 파일을 불러옵니다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
./scripts/build.sh
source /opt/ros/humble/setup.bash
source install/local_setup.bash
```

### `nvcc: command not found`

절대 경로로 확인합니다.

```bash
/usr/local/cuda/bin/nvcc --version
```

현재 실행 스크립트는 `CUDA_HOME=/usr/local/cuda`를 직접 설정하므로 단순히 PATH에
`nvcc`가 없는 것만으로 추론이 실패하지는 않습니다.

### `CUDA is unavailable to the native PyTorch runtime`

시스템 `python3`가 아니라 `.venv-jetson/bin/python`을 사용했는지 확인합니다.

```bash
/home/kopti/Desktop/new-project/centerpoint/.venv-jetson/bin/python -c \
  "import torch; print(torch.cuda.is_available())"
```

### `libcusparseLt.so`를 찾을 수 없음

같은 터미널에서 다음 환경 변수가 설정되어야 합니다.

```bash
export LD_LIBRARY_PATH=/home/kopti/Desktop/new-project/centerpoint/.venv-jetson/vendor/libcusparse_lt-linux-sbsa-0.5.2.1-archive/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
```

### checkpoint 또는 config를 찾을 수 없음

파일이 실제로 존재하는지 확인합니다.

```bash
ls -lh /home/kopti/Desktop/bag/*.pth
ls /home/kopti/Desktop/new-project/centerpoint/src/CenterPoint/configs/waymo/pp/waymo_centerpoint_pp_two_pfn_stride1_3x.py
```

파일명이나 위치가 다르면 `CHECKPOINT` 또는 launch의 `checkpoint:=...`를 수정합니다.

### RViz2에 점은 보이지만 box가 없음

```bash
ros2 topic echo /centerpoint/status
ros2 topic echo /centerpoint/detections --once
```

`error=...`가 있는지 확인합니다. error가 없고 `detections=0`이면 threshold를
낮춰 테스트합니다.

```bash
SCORE_THRESHOLD=0.3 ./scripts/run_waymo_bag.sh
```

### RViz2 화면 전체가 비어 있음

다음을 확인합니다.

1. RViz2 `Fixed Frame`이 `vehicle`인지 확인합니다.
2. `/waymo/points`가 발행되는지 확인합니다.
3. `/centerpoint/points`가 발행되는지 확인합니다.
4. bag player가 일시 정지되지 않았는지 확인합니다.

```bash
ros2 topic hz /waymo/points
ros2 topic hz /centerpoint/points
```

### 첫 프레임만 매우 느림

정상적인 warm-up 현상입니다. Numba voxelization과 CUDA kernel이 처음 실행될 때
초기화 비용이 발생합니다. 2번째 프레임 이후의 시간을 사용합니다.

### box가 cloud보다 늦게 따라옴

추론 속도보다 bag 입력이 빠른 상태입니다. bag 속도를 낮춥니다.

```bash
BAG_RATE=0.2 ./scripts/run_waymo_bag.sh
```

## 16. 다른 실시간 LiDAR 토픽에 연결하기

입력 토픽과 frame을 장비에 맞게 지정합니다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
CHECKPOINT=/absolute/path/to/model.pth \
INPUT_TOPIC=/lidar/points \
FRAME_ID=lidar \
./scripts/run_rviz.sh
```

실제 센서의 PointCloud2 좌표계, 단위, 필드 이름, intensity 분포가 Waymo 학습
데이터와 다르면 단순 연결만으로 좋은 검출 결과를 보장할 수 없습니다. 이 경우
센서 전처리와 모델 학습 조건을 함께 맞춰야 합니다.
