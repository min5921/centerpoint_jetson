import copy
import math
import time
from pathlib import Path

import numpy as np
import rclpy
import torch
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray

from det3d.core.input.voxel_generator import VoxelGenerator
from det3d.models import build_detector
from det3d.torchie import Config
from det3d.torchie.trainer import load_checkpoint


CLASS_NAMES = ("VEHICLE", "PEDESTRIAN", "CYCLIST")
CLASS_COLORS = ((0.10, 0.45, 1.00), (1.00, 0.20, 0.15), (1.00, 0.80, 0.05))


def quaternion_from_yaw(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def centerpoint_yaw_to_ros_yaw(yaw):
    return yaw + math.pi / 2.0


class VoxelNetInference(Node):
    def __init__(self):
        super().__init__("centerpoint_voxelnet")
        self.declare_parameter("config_path", "")
        self.declare_parameter("checkpoint_path", "")
        self.declare_parameter("allow_random_weights", False)
        self.declare_parameter("input_topic", "/lidar/points")
        self.declare_parameter("points_topic", "/voxelnet/points")
        self.declare_parameter("detections_topic", "/voxelnet/detections")
        self.declare_parameter("status_topic", "/voxelnet/status")
        self.declare_parameter("frame_id", "lidar")
        self.declare_parameter("device", "cuda:0")
        self.declare_parameter("precision", "fp16")
        self.declare_parameter("profile_stages", False)
        self.declare_parameter("score_threshold", 0.5)
        self.declare_parameter("max_detections", 200)
        self.declare_parameter("nms_pre_max_size", 4096)
        self.declare_parameter("nms_post_max_size", 500)
        self.declare_parameter("intensity_field", "intensity")
        self.declare_parameter("elongation_field", "elongation")
        self.declare_parameter("normalize_intensity", True)

        self.frame_id = str(self.get_parameter("frame_id").value)
        self.threshold = float(self.get_parameter("score_threshold").value)
        self.max_detections = max(int(self.get_parameter("max_detections").value), 1)
        self.nms_pre_max_size = max(
            int(self.get_parameter("nms_pre_max_size").value), 1
        )
        self.nms_post_max_size = max(
            int(self.get_parameter("nms_post_max_size").value), 1
        )
        if self.nms_post_max_size > self.nms_pre_max_size:
            raise ValueError("nms_post_max_size cannot exceed nms_pre_max_size")
        self.intensity_field = str(self.get_parameter("intensity_field").value)
        self.elongation_field = str(self.get_parameter("elongation_field").value)
        self.normalize_intensity = bool(
            self.get_parameter("normalize_intensity").value
        )
        self.device = torch.device(str(self.get_parameter("device").value))
        self.precision = str(self.get_parameter("precision").value).lower()
        if self.precision not in {"fp16", "fp32"}:
            raise ValueError("precision must be either 'fp16' or 'fp32'")
        if self.precision == "fp16" and self.device.type != "cuda":
            raise ValueError("fp16 precision requires a CUDA device")
        self.use_amp = self.precision == "fp16"
        self.profile_stages = bool(self.get_parameter("profile_stages").value)
        if self.profile_stages and self.device.type != "cuda":
            raise ValueError("stage profiling requires a CUDA device")
        self.warned_fields = set()
        self.frames = 0

        config_path = Path(str(self.get_parameter("config_path").value)).expanduser()
        checkpoint_value = str(self.get_parameter("checkpoint_path").value).strip()
        if checkpoint_value == "__none__":
            checkpoint_value = ""
        checkpoint_path = Path(checkpoint_value).expanduser() if checkpoint_value else None
        allow_random_weights = bool(
            self.get_parameter("allow_random_weights").value
        )
        if not config_path.is_file():
            raise FileNotFoundError(f"CenterPoint config not found: {config_path}")
        if checkpoint_path is not None and not checkpoint_path.is_file():
            raise FileNotFoundError(f"VoxelNet checkpoint not found: {checkpoint_path}")
        if checkpoint_path is None and not allow_random_weights:
            raise RuntimeError(
                "VoxelNet checkpoint is required. Set allow_random_weights=true only "
                "for compute-performance benchmarking."
            )
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable to the native PyTorch runtime")

        self.get_logger().info(f"Loading config: {config_path}")
        self.cfg = Config.fromfile(str(config_path))
        self.cfg.test_cfg.score_threshold = self.threshold
        self.cfg.test_cfg.nms.nms_pre_max_size = self.nms_pre_max_size
        self.cfg.test_cfg.nms.nms_post_max_size = self.nms_post_max_size
        voxel_cfg = self.cfg.voxel_generator
        max_voxel_num = voxel_cfg.max_voxel_num
        if isinstance(max_voxel_num, (list, tuple)):
            max_voxel_num = max_voxel_num[-1]
        self.max_voxels = int(max_voxel_num)
        self.voxel_generator = VoxelGenerator(
            voxel_size=voxel_cfg.voxel_size,
            point_cloud_range=voxel_cfg.range,
            max_num_points=int(voxel_cfg.max_points_in_voxel),
            max_voxels=self.max_voxels,
        )

        self.model = build_detector(
            self.cfg.model, train_cfg=None, test_cfg=self.cfg.test_cfg
        )
        if checkpoint_path is not None:
            self.weights_mode = "checkpoint"
            self.get_logger().info(f"Loading checkpoint: {checkpoint_path}")
            load_checkpoint(
                self.model,
                str(checkpoint_path),
                map_location="cpu",
                strict=False,
                logger=self.get_logger(),
            )
        else:
            self.weights_mode = "random-benchmark-only"
            self.get_logger().warning(
                "Using random VoxelNet weights for compute benchmarking only; "
                "detections and accuracy are not valid"
            )
        self.model.to(self.device).eval()
        if self.device.type == "cuda":
            torch.cuda.set_device(self.device)
            torch.backends.cudnn.benchmark = True

        rviz_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.points_pub = self.create_publisher(
            PointCloud2,
            str(self.get_parameter("points_topic").value),
            rviz_qos,
        )
        self.detections_pub = self.create_publisher(
            MarkerArray, str(self.get_parameter("detections_topic").value), 1
        )
        self.status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        input_topic = str(self.get_parameter("input_topic").value)
        self.subscription = self.create_subscription(
            PointCloud2, input_topic, self.on_pointcloud, qos_profile_sensor_data
        )
        self.get_logger().info(
            f"Ready: input={input_topic}, device={self.device}, "
            f"precision={self.precision}, threshold={self.threshold:.2f}, "
            f"max_voxels={self.max_voxels}, profile_stages={self.profile_stages}, "
            f"nms_pre={self.nms_pre_max_size}, nms_post={self.nms_post_max_size}, "
            f"weights={self.weights_mode}"
        )

    def warn_missing_field(self, field_name):
        if field_name and field_name not in self.warned_fields:
            self.warned_fields.add(field_name)
            self.get_logger().warning(
                f"PointCloud2 field '{field_name}' is missing; filling it with zeros"
            )

    def pointcloud_to_model_input(self, message):
        available = {field.name for field in message.fields}
        required = {"x", "y", "z"}
        missing = required - available
        if missing:
            raise ValueError(f"PointCloud2 is missing required fields: {sorted(missing)}")

        selected = ["x", "y", "z"]
        if self.intensity_field in available:
            selected.append(self.intensity_field)
        else:
            self.warn_missing_field(self.intensity_field)
        if self.elongation_field in available:
            selected.append(self.elongation_field)
        else:
            self.warn_missing_field(self.elongation_field)

        structured = point_cloud2.read_points(
            message, field_names=selected, skip_nans=False
        )
        point_count = len(structured)
        points = np.zeros((point_count, 5), dtype=np.float32)
        for column, name in enumerate(("x", "y", "z")):
            points[:, column] = np.asarray(structured[name], dtype=np.float32)
        if self.intensity_field in selected:
            points[:, 3] = np.asarray(
                structured[self.intensity_field], dtype=np.float32
            )
            if self.normalize_intensity:
                np.tanh(points[:, 3], out=points[:, 3])
        if self.elongation_field in selected:
            points[:, 4] = np.asarray(
                structured[self.elongation_field], dtype=np.float32
            )
        return np.ascontiguousarray(points[np.isfinite(points).all(axis=1)])

    def make_example(self, points):
        voxel_started = time.perf_counter()
        voxels, coordinates, num_points = self.voxel_generator.generate(
            points, max_voxels=self.max_voxels
        )
        if len(voxels) == 0:
            voxel_ms = (time.perf_counter() - voxel_started) * 1000.0
            return None, 0, voxel_ms, 0.0
        coordinates = np.pad(
            coordinates, ((0, 0), (1, 0)), mode="constant", constant_values=0
        )
        voxel_ms = (time.perf_counter() - voxel_started) * 1000.0

        h2d_started = time.perf_counter()
        example = {
            "voxels": torch.from_numpy(voxels).to(self.device),
            "coordinates": torch.from_numpy(coordinates).to(self.device),
            "num_points": torch.from_numpy(num_points).to(self.device),
            "num_voxels": torch.tensor(
                [len(voxels)], dtype=torch.int64, device=self.device
            ),
            "points": [None],
            "shape": np.expand_dims(self.voxel_generator.grid_size, axis=0),
            "metadata": [None],
        }
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        h2d_ms = (time.perf_counter() - h2d_started) * 1000.0
        return example, len(voxels), voxel_ms, h2d_ms

    def run_profiled_model(self, example):
        events = {}

        def run_stage(name, callback):
            started = torch.cuda.Event(enable_timing=True)
            finished = torch.cuda.Event(enable_timing=True)
            started.record()
            output = callback()
            finished.record()
            events[name] = (started, finished)
            return output

        voxels = example["voxels"]
        coordinates = example["coordinates"]
        num_points = example["num_points"]
        batch_size = len(example["points"])
        input_shape = example["shape"][0]

        voxel_features = run_stage(
            "voxel_reader",
            lambda: self.model.reader(voxels, num_points),
        )
        spatial_features, _ = run_stage(
            "sparse_backbone",
            lambda: self.model.backbone(
                voxel_features, coordinates, batch_size, input_shape
            ),
        )
        if self.model.with_neck:
            spatial_features = run_stage(
                "rpn", lambda: self.model.neck(spatial_features)
            )
        predictions, _ = run_stage(
            "head", lambda: self.model.bbox_head(spatial_features)
        )
        results = run_stage(
            "decode_nms",
            lambda: self.model.bbox_head.predict(
                example, predictions, self.model.test_cfg
            ),
        )

        torch.cuda.synchronize(self.device)
        timings = {
            name: started.elapsed_time(finished)
            for name, (started, finished) in events.items()
        }
        if "rpn" not in timings:
            timings["rpn"] = 0.0
        return results[0], timings

    def copy_cloud_for_output(self, message):
        output = copy.copy(message)
        output.header = copy.copy(message.header)
        if self.frame_id:
            output.header.frame_id = self.frame_id
        return output

    def empty_markers(self, header):
        marker = Marker()
        marker.header = header
        marker.action = Marker.DELETEALL
        return MarkerArray(markers=[marker])

    def result_markers(self, boxes, scores, labels, header):
        markers = self.empty_markers(header)
        for marker_id, (box, score, class_id) in enumerate(
            zip(boxes, scores, labels)
        ):
            class_id = int(class_id)
            if not 0 <= class_id < len(CLASS_NAMES):
                continue
            cube = Marker()
            cube.header = header
            cube.ns = "centerpoint_boxes"
            cube.id = marker_id
            cube.type = Marker.CUBE
            cube.action = Marker.ADD
            cube.pose.position.x = float(box[0])
            cube.pose.position.y = float(box[1])
            cube.pose.position.z = float(box[2])
            cube.scale.x = max(float(box[4]), 0.01)
            cube.scale.y = max(float(box[3]), 0.01)
            cube.scale.z = max(float(box[5]), 0.01)
            yaw = centerpoint_yaw_to_ros_yaw(float(box[-1]))
            qx, qy, qz, qw = quaternion_from_yaw(yaw)
            cube.pose.orientation.x = qx
            cube.pose.orientation.y = qy
            cube.pose.orientation.z = qz
            cube.pose.orientation.w = qw
            cube.color.r, cube.color.g, cube.color.b = CLASS_COLORS[class_id]
            cube.color.a = 0.45
            markers.markers.append(cube)

            label = Marker()
            label.header = header
            label.ns = "centerpoint_labels"
            label.id = marker_id
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = float(box[0])
            label.pose.position.y = float(box[1])
            label.pose.position.z = float(box[2] + box[5] / 2.0 + 0.5)
            label.pose.orientation.w = 1.0
            label.scale.z = 0.65
            label.color.r = 1.0
            label.color.g = 1.0
            label.color.b = 1.0
            label.color.a = 1.0
            label.text = f"{CLASS_NAMES[class_id]} {float(score):.2f}"
            markers.markers.append(label)
        return markers

    def publish_status(self, text):
        message = String()
        message.data = text
        self.status_pub.publish(message)

    def on_pointcloud(self, message):
        started = time.perf_counter()
        cloud_publish_started = time.perf_counter()
        output_cloud = self.copy_cloud_for_output(message)
        self.points_pub.publish(output_cloud)
        cloud_publish_ms = (time.perf_counter() - cloud_publish_started) * 1000.0
        header = copy.copy(output_cloud.header)
        try:
            decode_started = time.perf_counter()
            points = self.pointcloud_to_model_input(message)
            decode_ms = (time.perf_counter() - decode_started) * 1000.0
            example, voxel_count, voxel_ms, h2d_ms = self.make_example(points)
            if example is None:
                self.detections_pub.publish(self.empty_markers(header))
                self.publish_status(f"points={len(points)} voxels=0 detections=0")
                return

            inference_started = time.perf_counter()
            with torch.inference_mode():
                with torch.autocast(
                    device_type=self.device.type,
                    dtype=torch.float16,
                    enabled=self.use_amp,
                ):
                    if self.profile_stages:
                        result, stage_ms = self.run_profiled_model(example)
                    else:
                        result = self.model(example, return_loss=False)[0]
                        stage_ms = {}
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            inference_ms = (time.perf_counter() - inference_started) * 1000.0
            if not rclpy.ok():
                return

            post_started = time.perf_counter()
            scores = result["scores"].detach().cpu().numpy()
            boxes = result["box3d_lidar"].detach().cpu().numpy()
            labels = result["label_preds"].detach().cpu().numpy()
            keep = scores >= self.threshold
            scores, boxes, labels = scores[keep], boxes[keep], labels[keep]
            if len(scores) > self.max_detections:
                order = np.argsort(scores)[-self.max_detections :][::-1]
                scores, boxes, labels = scores[order], boxes[order], labels[order]
            post_ms = (time.perf_counter() - post_started) * 1000.0

            markers_started = time.perf_counter()
            markers = self.result_markers(boxes, scores, labels, header)
            self.detections_pub.publish(markers)
            markers_ms = (time.perf_counter() - markers_started) * 1000.0
            self.frames += 1
            total_ms = (time.perf_counter() - started) * 1000.0
            status = (
                f"frame={self.frames} model=voxelnet precision={self.precision} "
                f"weights={self.weights_mode} "
                f"nms_pre={self.nms_pre_max_size} "
                f"nms_post={self.nms_post_max_size} "
                f"points={len(points)} voxels={voxel_count} "
                f"detections={len(scores)} voxel_ms={voxel_ms:.1f} "
                f"inference_ms={inference_ms:.1f} total_ms={total_ms:.1f}"
            )
            if self.profile_stages:
                status += (
                    f" cloud_ms={cloud_publish_ms:.1f} decode_ms={decode_ms:.1f} "
                    f"h2d_ms={h2d_ms:.1f} "
                    f"voxel_reader_ms={stage_ms['voxel_reader']:.1f} "
                    f"sparse_backbone_ms={stage_ms['sparse_backbone']:.1f} "
                    f"rpn_ms={stage_ms['rpn']:.1f} "
                    f"head_ms={stage_ms['head']:.1f} "
                    f"decode_nms_ms={stage_ms['decode_nms']:.1f} "
                    f"post_ms={post_ms:.1f} markers_ms={markers_ms:.1f}"
                )
            self.publish_status(status)
            if self.frames == 1 or self.frames % 20 == 0:
                self.get_logger().info(status)
        except Exception as error:
            if not rclpy.ok():
                return
            self.get_logger().error(f"VoxelNet inference failed: {error}")
            self.detections_pub.publish(self.empty_markers(header))
            self.publish_status(f"error={type(error).__name__}: {error}")


def main(args=None):
    rclpy.init(args=args)
    node = VoxelNetInference()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.destroy_node()
        except KeyboardInterrupt:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
