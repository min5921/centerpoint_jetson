from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory("centerpoint_voxelnet_ros"))
    config = LaunchConfiguration("config")
    checkpoint = LaunchConfiguration("checkpoint")
    allow_random_weights = LaunchConfiguration("allow_random_weights")
    input_topic = LaunchConfiguration("input_topic")
    frame_id = LaunchConfiguration("frame_id")
    precision = LaunchConfiguration("precision")
    score_threshold = LaunchConfiguration("score_threshold")
    max_detections = LaunchConfiguration("max_detections")

    inference = ExecuteProcess(
        cmd=[
            EnvironmentVariable("VOXELNET_PYTHON"),
            "-m",
            "centerpoint_voxelnet_ros.inference_node",
            "--ros-args",
            "-p",
            ["config_path:=", config],
            "-p",
            ["checkpoint_path:=", checkpoint],
            "-p",
            ["allow_random_weights:=", allow_random_weights],
            "-p",
            ["input_topic:=", input_topic],
            "-p",
            ["frame_id:=", frame_id],
            "-p",
            ["precision:=", precision],
            "-p",
            ["score_threshold:=", score_threshold],
            "-p",
            ["max_detections:=", max_detections],
        ],
        output="screen",
        on_exit=Shutdown(reason="VoxelNet inference process exited"),
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2_voxelnet",
        output="screen",
        arguments=[
            "-d",
            str(share / "rviz" / "voxelnet.rviz"),
            "-f",
            frame_id,
        ],
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config", default_value=EnvironmentVariable("VOXELNET_CONFIG")
            ),
            DeclareLaunchArgument("checkpoint", default_value="__none__"),
            DeclareLaunchArgument("allow_random_weights", default_value="false"),
            DeclareLaunchArgument("input_topic", default_value="/lidar/points"),
            DeclareLaunchArgument("frame_id", default_value="lidar"),
            DeclareLaunchArgument("precision", default_value="fp16"),
            DeclareLaunchArgument("score_threshold", default_value="0.5"),
            DeclareLaunchArgument("max_detections", default_value="200"),
            DeclareLaunchArgument("rviz", default_value="true"),
            inference,
            rviz,
        ]
    )
