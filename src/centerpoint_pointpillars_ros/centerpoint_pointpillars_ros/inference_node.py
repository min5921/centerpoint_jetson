import copy
import math
import time
from pathlib import Path

import numpy as np
import rclpy
import torch
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


class PointPillarsInference(Node):
    def __init__(self):
        super().__init__("centerpoint_pointpillars")
        self.declare_parameter("config_path", "")
        self.declare_parameter("checkpoint_path", "")
        self.declare_parameter("input_topic", "/lidar/points")
        self.declare_parameter("points_topic", "/centerpoint/points")
        self.declare_parameter("detections_topic", "/centerpoint/detections")
        self.declare_parameter("status_topic", "/centerpoint/status")
        self.declare_parameter("frame_id", "lidar")
        self.declare_parameter("device", "cuda:0")
        self.declare_parameter("score_threshold", 0.5)
        self.declare_parameter("max_detections", 200)
        self.declare_parameter("intensity_field", "intensity")
        self.declare_parameter("elongation_field", "elongation")
        self.declare_parameter("normalize_intensity", True)

        self.frame_id = str(self.get_parameter("frame_id").value)
        self.threshold = float(self.get_parameter("score_threshold").value)
        self.max_detections = max(int(self.get_parameter("max_detections").value), 1)
        self.intensity_field = str(self.get_parameter("intensity_field").value)
        self.elongation_field = str(self.get_parameter("elongation_field").value)
        self.normalize_intensity = bool(
            self.get_parameter("normalize_intensity").value
        )
        self.device = torch.device(str(self.get_parameter("device").value))
        self.warned_fields = set()
        self.frames = 0

        config_path = Path(str(self.get_parameter("config_path").value)).expanduser()
        checkpoint_path = Path(
            str(self.get_parameter("checkpoint_path").value)
        ).expanduser()
        if not config_path.is_file():
            raise FileNotFoundError(f"CenterPoint config not found: {config_path}")
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"PointPillars checkpoint not found: {checkpoint_path}")
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable to the native PyTorch runtime")

        self.get_logger().info(f"Loading config: {config_path}")
        self.cfg = Config.fromfile(str(config_path))
        self.cfg.test_cfg.score_threshold = self.threshold
        self.cfg.test_cfg.nms.nms_post_max_size = max(
            self.max_detections, int(self.cfg.test_cfg.nms.nms_post_max_size)
        )
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
        self.get_logger().info(f"Loading checkpoint: {checkpoint_path}")
        load_checkpoint(
            self.model,
            str(checkpoint_path),
            map_location="cpu",
            strict=False,
            logger=self.get_logger(),
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
            f"threshold={self.threshold:.2f}, max_voxels={self.max_voxels}"
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
        voxels, coordinates, num_points = self.voxel_generator.generate(
            points, max_voxels=self.max_voxels
        )
        if len(voxels) == 0:
            return None, 0
        coordinates = np.pad(
            coordinates, ((0, 0), (1, 0)), mode="constant", constant_values=0
        )
        example = {
            "voxels": torch.from_numpy(voxels).to(self.device),
            "coordinates": torch.from_numpy(coordinates).to(self.device),
            "num_points": torch.from_numpy(num_points).to(self.device),
            "num_voxels": torch.tensor(
                [len(voxels)], dtype=torch.int64, device=self.device
            ),
            "shape": np.expand_dims(self.voxel_generator.grid_size, axis=0),
            "metadata": [None],
        }
        return example, len(voxels)

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
        output_cloud = self.copy_cloud_for_output(message)
        self.points_pub.publish(output_cloud)
        header = copy.copy(output_cloud.header)
        try:
            points = self.pointcloud_to_model_input(message)
            voxel_started = time.perf_counter()
            example, voxel_count = self.make_example(points)
            voxel_ms = (time.perf_counter() - voxel_started) * 1000.0
            if example is None:
                self.detections_pub.publish(self.empty_markers(header))
                self.publish_status(f"points={len(points)} voxels=0 detections=0")
                return

            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            inference_started = time.perf_counter()
            with torch.inference_mode():
                result = self.model(example, return_loss=False)[0]
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            inference_ms = (time.perf_counter() - inference_started) * 1000.0
            if not rclpy.ok():
                return

            scores = result["scores"].detach().cpu().numpy()
            boxes = result["box3d_lidar"].detach().cpu().numpy()
            labels = result["label_preds"].detach().cpu().numpy()
            keep = scores >= self.threshold
            scores, boxes, labels = scores[keep], boxes[keep], labels[keep]
            if len(scores) > self.max_detections:
                order = np.argsort(scores)[-self.max_detections :][::-1]
                scores, boxes, labels = scores[order], boxes[order], labels[order]

            self.detections_pub.publish(
                self.result_markers(boxes, scores, labels, header)
            )
            self.frames += 1
            total_ms = (time.perf_counter() - started) * 1000.0
            status = (
                f"frame={self.frames} points={len(points)} voxels={voxel_count} "
                f"detections={len(scores)} voxel_ms={voxel_ms:.1f} "
                f"inference_ms={inference_ms:.1f} total_ms={total_ms:.1f}"
            )
            self.publish_status(status)
            if self.frames == 1 or self.frames % 20 == 0:
                self.get_logger().info(status)
        except Exception as error:
            if not rclpy.ok():
                return
            self.get_logger().error(f"PointPillars inference failed: {error}")
            self.detections_pub.publish(self.empty_markers(header))
            self.publish_status(f"error={type(error).__name__}: {error}")


def main(args=None):
    rclpy.init(args=args)
    node = PointPillarsInference()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
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
