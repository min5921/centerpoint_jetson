from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory("centerpoint_pointpillars_ros"))
    config = LaunchConfiguration("config")
    checkpoint = LaunchConfiguration("checkpoint")
    input_topic = LaunchConfiguration("input_topic")
    frame_id = LaunchConfiguration("frame_id")
    precision = LaunchConfiguration("precision")
    profile_stages = LaunchConfiguration("profile_stages")
    score_threshold = LaunchConfiguration("score_threshold")
    max_detections = LaunchConfiguration("max_detections")
    nms_pre_max_size = LaunchConfiguration("nms_pre_max_size")
    nms_post_max_size = LaunchConfiguration("nms_post_max_size")

    inference = ExecuteProcess(
        cmd=[
            EnvironmentVariable("CENTERPOINT_PYTHON"),
            "-m",
            "centerpoint_pointpillars_ros.inference_node",
            "--ros-args",
            "-p",
            ["config_path:=", config],
            "-p",
            ["checkpoint_path:=", checkpoint],
            "-p",
            ["input_topic:=", input_topic],
            "-p",
            ["frame_id:=", frame_id],
            "-p",
            ["precision:=", precision],
            "-p",
            ["profile_stages:=", profile_stages],
            "-p",
            ["score_threshold:=", score_threshold],
            "-p",
            ["max_detections:=", max_detections],
            "-p",
            ["nms_pre_max_size:=", nms_pre_max_size],
            "-p",
            ["nms_post_max_size:=", nms_post_max_size],
        ],
        output="screen",
        on_exit=Shutdown(reason="PointPillars inference process exited"),
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="screen",
        arguments=[
            "-d",
            str(share / "rviz" / "pointpillars.rviz"),
            "-f",
            frame_id,
        ],
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config", default_value=EnvironmentVariable("CENTERPOINT_CONFIG")
            ),
            DeclareLaunchArgument(
                "checkpoint",
                default_value=EnvironmentVariable("CENTERPOINT_CHECKPOINT"),
            ),
            DeclareLaunchArgument("input_topic", default_value="/lidar/points"),
            DeclareLaunchArgument("frame_id", default_value="lidar"),
            DeclareLaunchArgument("precision", default_value="fp16"),
            DeclareLaunchArgument("profile_stages", default_value="false"),
            DeclareLaunchArgument("score_threshold", default_value="0.5"),
            DeclareLaunchArgument("max_detections", default_value="200"),
            DeclareLaunchArgument("nms_pre_max_size", default_value="4096"),
            DeclareLaunchArgument("nms_post_max_size", default_value="500"),
            DeclareLaunchArgument("rviz", default_value="true"),
            inference,
            rviz,
        ]
    )
