# ROS2 Bridge Multi-Machine Architecture

Date: 2026-03-23

## Goal

Capture the current `sensor_proto` architecture and the recommended next-step architecture for:

- multi-machine deployment
- multi-sensor fusion
- ROS2 ecosystem integration

The core recommendation remains:

- keep `sensor_proto` responsible for capture-time truth
- keep the hot capture path outside ROS2
- add ROS2 as a bridge layer after `AlignedFrameSet` is formed

## Current Architecture

```mermaid
flowchart LR
    subgraph EdgeBox["Single Capture Box / Current Architecture"]
        C1["Camera Adapters
        RealSense / Hikrobot"]
        F["Frame
        device_timestamp_ms
        host_received_at"]
        S["FrameSynchronizer
        soft sync
        normalize + align"]
        A["AlignedFrameSet"]
        T["HTTP control-plane
        + ZMQ data-plane"]
        R["RecordingSink
        LeRobot episode"]
        V["Host Viewer / Client"]

        C1 --> F --> S --> A
        A --> T
        A --> R
        T --> V
    end
```

## Target Architecture

```mermaid
flowchart TB
    subgraph Time["Global Time Infrastructure"]
        TS["PTP / NTP
        cross-machine clock sync"]
    end

    subgraph M1["Machine A: Camera Rig"]
        C1["Camera Adapters"]
        S1["FrameSynchronizer"]
        A1["AlignedFrameSet"]
        Z1["Local ZMQ / HTTP
        debug + ops"]
        B1["ROS2 Bridge
        aligned_set -> ROS topics"]
        C1 --> S1 --> A1
        A1 --> Z1
        A1 --> B1
    end

    subgraph M2["Machine B: IMU / LiDAR Rig"]
        I1["IMU Driver"]
        L1["LiDAR Driver"]
        P1["Preprocess / calibration"]
        B2["ROS2 Native Publishers"]
        I1 --> P1
        L1 --> P1
        P1 --> B2
    end

    subgraph M3["Machine C: Robot Control"]
        R1["Robot State
        joint / pose / action"]
        B3["ROS2 Native Publishers"]
        R1 --> B3
    end

    subgraph ROS["ROS2 Domain / DDS"]
        T1["/rig_a/aligned_set"]
        T2["/imu/data"]
        T3["/lidar/points"]
        T4["/robot/state"]
        TF["/tf / extrinsics"]
    end

    subgraph Fusion["Fusion / Planning Cluster"]
        F1["Fusion Node
        time align + association"]
        F2["Perception Node"]
        F3["Policy / Planning Node"]
        BAG["rosbag2 / replay / observability"]

        F1 --> F2 --> F3
        F1 --> BAG
    end

    TS -. sync clocks .-> M1
    TS -. sync clocks .-> M2
    TS -. sync clocks .-> M3

    B1 --> T1
    B2 --> T2
    B2 --> T3
    B3 --> T4
    B1 --> TF
    B2 --> TF
    B3 --> TF

    T1 --> F1
    T2 --> F1
    T3 --> F1
    T4 --> F1
    TF --> F1
```

## Responsibility Split

```mermaid
flowchart LR
    subgraph HotPath["Non-ROS2 Hot Path"]
        CA["Camera Adapters"]
        SYNC["Sync Core"]
        SET["AlignedFrameSet"]
        REC["Recording"]
        CA --> SYNC --> SET --> REC
    end

    subgraph Bridge["ROS2 Bridge"]
        MAP["Message Mapping
        AlignedFrameSetMsg
        CameraInfo
        TF"]
        PUB["ROS2 Publishers"]
        SET --> MAP --> PUB
    end

    subgraph Native["Native ROS2 Sensors"]
        IMU["IMU topics"]
        LIDAR["LiDAR topics"]
        STATE["Robot state topics"]
    end

    subgraph Compute["Distributed Compute Nodes"]
        FUSION["Fusion"]
        PERCEPTION["Perception"]
        CONTROL["Planning / Control"]
    end

    PUB --> FUSION
    IMU --> FUSION
    LIDAR --> FUSION
    STATE --> FUSION
    FUSION --> PERCEPTION --> CONTROL
```

## Design Rules

- `sensor_proto` owns capture-time truth: device timestamps, host receive timestamps, per-camera drift, sync-window behavior, and `AlignedFrameSet` semantics.
- ROS2 bridge owns interoperability: topic publication, `tf`, standard message mapping, and downstream integration.
- Recording should continue consuming in-memory `AlignedFrameSet`, not re-decoded ROS2 or JPEG payloads.
- Cross-machine time sync must exist before downstream fusion claims temporal correctness.

## Why The Bridge Sits After Alignment

- ROS2 can transport timestamps; it does not make bad timestamps correct.
- Camera-device clocks, USB jitter, and sync-window drop behavior are repository-specific concerns already modeled by `sensor_proto`.
- Downstream fusion nodes should consume a stable observation-step abstraction, not rebuild camera alignment from raw per-camera traffic.
