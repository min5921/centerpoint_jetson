# 전체 파일 구조와 코드 동작 설명

## 1. 전체 디렉터리 구조

```text
/home/kopti/Desktop/
├── bag/                                      # 실행 데이터와 weight
│   ├── metadata.yaml                         # rosbag2 메타데이터
│   ├── waymo_val_sample_0.db3                # SQLite3 형식 bag 데이터
│   └── centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
│                                               # Waymo PointPillars checkpoint
└── new-project/
    ├── centerpoint/                           # 원본 CenterPoint native runtime
    │   ├── .venv-jetson/                      # Jetson용 Python/PyTorch 환경
    │   │   └── vendor/                        # cuSPARSELt 등 native library
    │   └── src/CenterPoint/
    │       ├── configs/waymo/pp/              # Waymo PointPillars config
    │       └── det3d/
    │           └── ops/iou3d_nms/             # 빌드된 CUDA NMS 확장
    └── centerpoint_ros2_ws/                   # 이 ROS 2 workspace
        ├── .gitignore
        ├── README.md
        ├── docs/
        │   ├── KOREAN_MANUAL.md
        │   └── CODE_AND_FILE_STRUCTURE.md
        ├── scripts/
        │   ├── build.sh
        │   ├── run_rviz.sh
        │   └── run_waymo_bag.sh
        ├── src/
        │   └── centerpoint_pointpillars_ros/
        │       ├── package.xml
        │       ├── setup.py
        │       ├── setup.cfg
        │       ├── resource/
        │       │   └── centerpoint_pointpillars_ros
        │       ├── launch/
        │       │   └── inference.launch.py
        │       ├── rviz/
        │       │   └── pointpillars.rviz
        │       └── centerpoint_pointpillars_ros/
        │           ├── __init__.py
        │           └── inference_node.py
        ├── build/                             # colcon 자동 생성
        ├── install/                           # colcon 자동 생성
        ├── log/                               # colcon 자동 생성
        └── .cache/                            # Numba와 ROS 실행 로그
```

`build`, `install`, `log`, `.cache`는 자동 생성되는 폴더입니다. 직접 수정해야 하는
코드는 `src`, `scripts`, `docs`에 있습니다.

## 2. ROS 2 workspace 파일별 역할

### `README.md`

프로젝트 목적, 현재 검증된 경로, 가장 빠른 빌드와 실행 방법을 안내하는 첫 문서입니다.

### `scripts/build.sh`

ROS 2 Humble 환경을 불러오고 `.venv-jetson`에 설치된 `colcon`으로 패키지를
빌드합니다.

실제로 수행하는 핵심 명령은 다음과 같습니다.

```bash
source /opt/ros/humble/setup.bash
.../.venv-jetson/bin/colcon build \
  --symlink-install \
  --packages-select centerpoint_pointpillars_ros
```

### `scripts/run_rviz.sh`

CenterPoint 추론 실행에 필요한 환경을 준비합니다.

- 빌드 결과, 가상환경, config, checkpoint 존재 여부 검사
- CUDA NMS `.so` 존재 여부 검사
- ROS 2와 workspace setup 파일 source
- `PYTHONPATH`에 원본 CenterPoint 추가
- `LD_LIBRARY_PATH`에 cuSPARSELt 추가
- Numba cache와 ROS log 경로 설정
- `inference.launch.py` 실행

시스템 ROS Python에는 Jetson PyTorch가 설치되어 있지 않기 때문에, 추론 process는
반드시 `.venv-jetson/bin/python`으로 실행해야 합니다.

### `scripts/run_waymo_bag.sh`

Waymo 데모 전체를 제어합니다.

1. bag과 checkpoint를 검사합니다.
2. `run_rviz.sh`를 background process로 시작합니다.
3. 모델 로딩을 기다립니다.
4. `/waymo/points`, `/waymo/ground_truth`, `/waymo/frame_info`를 재생합니다.
5. 종료 신호를 받으면 bag과 launch process를 함께 정리합니다.

### `src/centerpoint_pointpillars_ros/package.xml`

ROS 2 패키지 이름, 버전, build type과 runtime dependency를 정의합니다.

주요 dependency는 다음과 같습니다.

- `ament_python`
- `rclpy`
- `sensor_msgs`, `sensor_msgs_py`
- `visualization_msgs`
- `launch`, `launch_ros`
- `rviz2`

PyTorch, NumPy, CenterPoint는 ROS package dependency가 아니라 native 가상환경에서
제공됩니다.

### `src/centerpoint_pointpillars_ros/setup.py`

Python 패키지를 colcon으로 설치하는 설정입니다. Python module뿐 아니라 launch와
RViz 설정 파일도 `install/.../share/centerpoint_pointpillars_ros`에 복사합니다.

### `src/centerpoint_pointpillars_ros/setup.cfg`

ament Python 패키지의 script 설치 위치를 지정하는 setuptools 설정입니다.

### `src/centerpoint_pointpillars_ros/resource/centerpoint_pointpillars_ros`

ament index가 이 패키지를 찾을 수 있도록 등록하는 marker 파일입니다. 내용이
비어 있어도 필요한 파일입니다.

### `src/centerpoint_pointpillars_ros/launch/inference.launch.py`

두 process를 묶어 실행합니다.

- 추론: `CENTERPOINT_PYTHON -m centerpoint_pointpillars_ros.inference_node`
- 시각화: `rviz2 -d pointpillars.rviz`

일반적인 `launch_ros.actions.Node` 대신 추론에 `ExecuteProcess`를 사용하는 이유는
ROS 2의 시스템 Python과 CUDA PyTorch가 설치된 가상환경 Python이 서로 다르기
때문입니다. RViz2는 일반 ROS 2 `Node` action으로 실행합니다.

추론 process가 비정상 종료되면 launch 전체를 종료하여 입력 없이 RViz2만 남는
상태를 방지합니다.

### `src/centerpoint_pointpillars_ros/rviz/pointpillars.rviz`

RViz2 화면 구성을 저장합니다.

- Grid
- `/centerpoint/points` PointCloud2
- `/centerpoint/detections` MarkerArray
- `/waymo/ground_truth` MarkerArray
- 어두운 배경과 차량 주변을 보는 Orbit camera

launch 인자의 `frame_id`가 RViz2의 Fixed Frame을 덮어씁니다. Waymo bag 실행 시
`vehicle`이 사용됩니다.

### `src/centerpoint_pointpillars_ros/centerpoint_pointpillars_ros/__init__.py`

이 디렉터리를 Python package로 인식시키는 파일입니다.

### `src/centerpoint_pointpillars_ros/centerpoint_pointpillars_ros/inference_node.py`

PointCloud2 수신부터 CUDA 추론과 MarkerArray 발행까지 담당하는 핵심 코드입니다.

## 3. 전체 데이터 흐름

```text
Waymo rosbag2
  │
  ├── /waymo/ground_truth ───────────────────────────────┐
  │                                                       │
  └── /waymo/points                                      │
          │                                               │
          ▼                                               │
  PointPillarsInference.on_pointcloud()                    │
          │                                               │
          ├── cloud header/frame 복사                     │
          │       └── /centerpoint/points ───────────┐    │
          │                                           │    │
          ├── PointCloud2 -> NumPy [N, 5]             │    │
          │       x, y, z, intensity, elongation      │    │
          │                                           │    │
          ├── VoxelGenerator -> pillars/coordinates   │    │
          │                                           │    │
          ├── Tensor를 cuda:0으로 이동                │    │
          │                                           │    │
          ├── CenterPoint PointPillars forward        │    │
          │                                           │    │
          ├── score filter + CUDA NMS 결과            │    │
          │       └── /centerpoint/detections ────────┤    │
          │                                           │    │
          └── latency/count                            │    │
                  └── /centerpoint/status              │    │
                                                      ▼    ▼
                                                            RViz2
```

Ground Truth는 추론 노드를 통과하지 않습니다. bag player가 발행한 MarkerArray를
RViz2가 직접 구독합니다.

## 4. `inference_node.py` 처리 단계

### 4.1 상수와 좌표 회전

`CLASS_NAMES`와 `CLASS_COLORS`가 Waymo의 세 클래스와 표시 색상을 정의합니다.
CenterPoint box yaw와 ROS Marker yaw 표현 차이를 맞추기 위해 yaw에 `pi / 2`를
더하고 quaternion으로 변환합니다.

### 4.2 `PointPillarsInference.__init__`

초기화 순서는 다음과 같습니다.

1. ROS 파라미터를 선언하고 읽습니다.
2. config와 checkpoint 파일을 검사합니다.
3. CUDA 사용 가능 여부를 검사합니다.
4. CenterPoint config에서 voxel 설정을 읽습니다.
5. PointPillars detector를 만들고 checkpoint를 로드합니다.
6. 모델을 GPU로 이동하고 evaluation mode로 변경합니다.
7. publisher와 PointCloud2 subscriber를 생성합니다.

입력 subscriber는 센서 데이터용 QoS를 사용합니다. RViz2로 보내는 point cloud는
`RELIABLE`, depth 1 QoS를 사용하여 RViz2 기본 설정과 호환되도록 했습니다.

### 4.3 `pointcloud_to_model_input`

ROS `PointCloud2`를 연속된 `float32` NumPy 배열로 변환합니다.

```text
PointCloud2 -> [x, y, z, intensity, elongation] -> shape [N, 5]
```

- `x`, `y`, `z`가 없으면 해당 frame 처리를 실패시킵니다.
- intensity 또는 elongation이 없으면 0으로 채웁니다.
- intensity는 기본적으로 `tanh` 정규화합니다.
- NaN 또는 Inf가 포함된 point는 제거합니다.

### 4.4 `make_example`

CPU의 Numba 기반 `VoxelGenerator`로 point를 pillar 단위로 묶습니다. 생성된
`voxels`, `coordinates`, `num_points`, `num_voxels`를 PyTorch tensor로 변환한 뒤
GPU로 이동합니다.

### 4.5 `result_markers`

모델의 box, score, class id를 RViz2 `MarkerArray`로 변환합니다.

- 매 frame 첫 marker는 `DELETEALL`로 이전 box를 삭제합니다.
- box는 `Marker.CUBE`입니다.
- label은 `Marker.TEXT_VIEW_FACING`입니다.
- score threshold 미만의 결과는 먼저 제거됩니다.
- 결과가 너무 많으면 score 순으로 `max_detections`개만 남깁니다.

### 4.6 `on_pointcloud`

새 PointCloud2가 도착할 때마다 호출되는 callback입니다.

1. 입력 cloud를 `/centerpoint/points`로 재발행합니다.
2. point 배열을 만들고 voxelization합니다.
3. `torch.inference_mode()`에서 GPU forward를 실행합니다.
4. 결과를 CPU NumPy 배열로 가져옵니다.
5. threshold와 최대 검출 수를 적용합니다.
6. 3D box와 label을 발행합니다.
7. 처리 시간을 `/centerpoint/status`로 발행합니다.

CUDA 작업은 비동기이므로 정확한 `inference_ms` 측정을 위해 forward 전후에
`torch.cuda.synchronize()`를 호출합니다.

frame 처리 중 예외가 발생하면 빈 MarkerArray로 이전 box를 지우고, 오류 내용을
`/centerpoint/status`에 발행합니다. 노드 전체를 즉시 종료하지 않으므로 다음
정상 frame을 계속 처리할 수 있습니다.

## 5. 모델과 데이터 계약

### 모델 config

```text
/home/kopti/Desktop/new-project/centerpoint/src/CenterPoint/configs/waymo/pp/
waymo_centerpoint_pp_two_pfn_stride1_3x.py
```

이 config가 voxel 크기, point cloud 범위, PFN 구조, detection head, NMS 설정을
정의합니다. weight는 이 config와 같은 모델 구조로 학습된 파일이어야 합니다.

### checkpoint

```text
/home/kopti/Desktop/bag/
centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth
```

현재 checkpoint는 실제 모델에 로드하여 동작을 확인했습니다. 다른 architecture의
weight를 넣으면 tensor shape mismatch 또는 부정확한 결과가 발생할 수 있습니다.

### 입력 좌표와 feature

```text
x: forward
y: left
z: up
feature: [x, y, z, intensity, elongation]
```

현재 bag은 `vehicle` frame이고 elongation이 없어서 0으로 보완합니다.

## 6. rosbag2 파일 역할

### `metadata.yaml`

storage 형식, 재생 시간, 메시지 수, 토픽 이름과 타입을 기록합니다. `ros2 bag play`
명령에는 `.db3` 파일이 아니라 이 파일이 있는 `bag` 디렉터리를 전달합니다.

### `waymo_val_sample_0.db3`

실제 serialized ROS 2 메시지가 저장된 SQLite3 파일입니다. 이 파일만 직접 Python으로
읽는 대신 `ros2 bag play`를 사용합니다.

### `.pth`

rosbag2 데이터가 아니라 PyTorch checkpoint입니다. 편의를 위해 같은 `bag` 폴더에
있지만 bag player가 읽는 파일은 아닙니다.

## 7. 수정하려는 목적별 파일

| 변경 목적 | 수정 파일 |
| --- | --- |
| 추론 입력/전처리 변경 | `inference_node.py` |
| box 색상, label, yaw 변경 | `inference_node.py` |
| 기본 토픽, threshold 인자 변경 | `inference.launch.py`, 실행 스크립트 |
| RViz2 display 또는 camera 변경 | `pointpillars.rviz` |
| Python/ROS dependency 변경 | `package.xml`, `setup.py` |
| bag 경로, 속도, 반복 정책 변경 | `run_waymo_bag.sh` |
| CUDA/Python 환경 경로 변경 | `run_rviz.sh` |

## 8. 소스 변경 후 확인 순서

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
./scripts/build.sh
LOOP=false ./scripts/run_waymo_bag.sh
```

다른 터미널에서 다음을 확인합니다.

```bash
source /opt/ros/humble/setup.bash
source /home/kopti/Desktop/new-project/centerpoint_ros2_ws/install/local_setup.bash
ros2 topic echo /centerpoint/status
```

코드가 import 가능한지만 빠르게 검사하려면 다음 명령을 사용합니다. CenterPoint와
CUDA 관련 환경 변수가 필요한 실제 node 실행 검사는 전체 실행 절차로 확인합니다.

```bash
python3 -m py_compile \
  /home/kopti/Desktop/new-project/centerpoint_ros2_ws/src/centerpoint_pointpillars_ros/centerpoint_pointpillars_ros/inference_node.py \
  /home/kopti/Desktop/new-project/centerpoint_ros2_ws/src/centerpoint_pointpillars_ros/launch/inference.launch.py
```
