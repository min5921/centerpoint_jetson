# CenterPoint PointPillars ROS 2

Jetson에서 CenterPoint PointPillars를 ROS 2 Humble에 연결하고, Waymo ROS 2 bag의
포인트 클라우드와 추론 결과를 RViz2로 확인하는 워크스페이스입니다.

이 워크스페이스는 Docker를 사용하지 않습니다. 기존의 native CenterPoint 소스와
Python 가상환경을 참조하므로 CUDA/PyTorch 파일을 중복 설치하지 않습니다.

> ROS 2 Humble 프로젝트이므로 `catkin_make`가 아니라 `colcon`과
> `ament_python`을 사용합니다. 별도의 `catkin_ws`는 필요하지 않습니다.

## 문서

- [처음부터 실행하는 한국어 매뉴얼](docs/KOREAN_MANUAL.md)
- [전체 파일 구조와 코드 동작 설명](docs/CODE_AND_FILE_STRUCTURE.md)
- [Jetson AGX Orin 신호 처리 및 FPS 측정 결과](docs/progress/2026-07-23_signal_processing_fps.md)

## 현재 검증된 구성

| 항목 | 값 |
| --- | --- |
| 운영체제/보드 | Ubuntu, NVIDIA Jetson Orin (Ubuntu 22.04) |
| ROS | ROS 2 Humble |
| Python | 3.10.12 |
| CUDA Toolkit | 12.6 |
| CenterPoint | `/home/kopti/Desktop/new-project/centerpoint` |
| ROS 2 workspace | `/home/kopti/Desktop/new-project/centerpoint_ros2_ws` |
| Waymo bag | `/home/kopti/Desktop/bag` |
| 기본 weight | `/home/kopti/Desktop/bag/centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth` |

## 가장 빠른 실행

처음 한 번 빌드합니다.

```bash
cd /home/kopti/Desktop/new-project/centerpoint_ros2_ws
./scripts/build.sh
```

Waymo bag, PointPillars 추론 노드, RViz2를 한 번에 실행합니다.

```bash
./scripts/run_waymo_bag.sh
```

종료할 때 실행한 터미널에서 `Ctrl+C`를 누릅니다.

한 번만 재생하려면 다음과 같이 실행합니다.

```bash
LOOP=false ./scripts/run_waymo_bag.sh
```

## 주요 토픽

| 토픽 | 타입 | 내용 |
| --- | --- | --- |
| `/waymo/points` | `sensor_msgs/msg/PointCloud2` | bag에 저장된 입력 LiDAR |
| `/waymo/ground_truth` | `visualization_msgs/msg/MarkerArray` | bag에 저장된 정답 3D box |
| `/centerpoint/points` | `sensor_msgs/msg/PointCloud2` | RViz2용 입력 cloud 재발행 |
| `/centerpoint/detections` | `visualization_msgs/msg/MarkerArray` | 모델이 예측한 3D box와 점수 |
| `/centerpoint/status` | `std_msgs/msg/String` | 포인트 수, voxel 수, 검출 수, 처리 시간 |

스크립트 없이 각 명령을 직접 실행하는 방법, RViz2 화면 확인법, 파라미터,
문제 해결 방법은 [한국어 매뉴얼](docs/KOREAN_MANUAL.md)에 정리되어 있습니다.
