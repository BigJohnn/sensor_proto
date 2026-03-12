# RealSense Recording Sink Design

日期: 2026-03-12

## 背景

`sensor_proto.stream_main` 之前在同步 consumer 路径里直接执行 `recorder.record(aligned_set)`。
这会把 LeRobot 写盘、RGB 转换、视频编码排队等成本叠加到主消费链上，导致：

- producer 队列打满
- camera frame 被 `QueueFull` 丢弃
- aligned set 产出频率下降
- recording sidecar 的真实时间轴显著拉长

## 决策

采用 **RecordingSink + bounded queue + dedicated worker thread**，默认策略为：

- `recording.queue_maxsize = 32`
- `recording.overflow_policy = fail_recording_keep_stream`

## 方案说明

### 主链路

`handle_aligned_set()` 只负责：

1. `repository.publish(...)`
2. `recording_sink.submit(aligned_set)`

不再 inline 执行 `LeRobotRecorder.record(...)`。

### worker 线程

后台线程独立执行：

- RGB 转换
- `LeRobotRecorder.record(...)`
- 最终 `save_episode()` / `finalize()`

## Backend 热点定位

对容器内 `lerobot==0.5.0` 的实际实现检查后，确认热点不在 `RecordingSink` 本身，而在 `LeRobotDataset.add_frame()` 的默认路径：

- 当 `_streaming_encoder is None` 时，`add_frame()` 会对每个 video feature 执行 `_save_image(...)`
- 这条路径会产生逐帧图像临时文件写盘，再在 `save_episode()` 阶段编码成 MP4
- 7 路 `640x480@30fps` 下，这个 per-frame image write 会显著拖低 recorder worker 吞吐

当前优化方向因此收敛为：

- 保持 `RecordingSink + worker thread` 架构不变
- 在 `LeRobotDataset.create(...)` 返回对象上原地启用 `StreamingVideoEncoder`
- 让 `add_frame()` 直接走 `feed_frame(...)` 流式视频编码路径，避免逐帧 PNG 落盘

### 队列策略

- 队列是 bounded，不能无限增长
- 队列满时，recording 进入 failed/degraded 状态
- stream 服务继续运行
- 后续 aligned set 不再写入 recording
- health API 暴露 recording 状态，便于外部判断

## 取舍

### 为什么不用 `asyncio.create_task`

`recorder.record()` 不是纯 async IO，仍会阻塞同一条消费链，不能解决根因。

### 为什么不直接上独立进程/独立服务

当前主要负担是同进程慢路径阻塞；先用 worker thread 解耦能以最小改动解决主问题。
独立进程后续仍可在 `RecordingSink` 抽象后面演进。

### 为什么默认不静默丢录制帧

录制数据集比 preview 更强调完整性。静默丢帧会生成表面成功、实际退化的数据集。

## 运行语义

- stream 实时性优先于 recording 成功
- recording 若失败，不再阻塞主 stream
- 失败信息通过 health/日志暴露
- 旧 episode 若没有真实时间轴 sidecar，replay 仍回退到 MP4 名义时间轴
