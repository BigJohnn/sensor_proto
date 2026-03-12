# sensor_proto

RealSense 多相机同步采集、推流与 host 侧可视化工具集。

当前这套流程已经收敛为：

- 容器内自动探测当前在线 RealSense
- 自动生成运行时配置
- 对齐多路时间戳后推流到 host
- host 侧可用 OpenCV 实时查看
- host 侧代码可直接拿到同步后的 `frames, timestamp`

## 最常用命令

进入仓库：

```bash
cd /home/corenetic/Code/sensor_proto
```

启动推流服务：

```bash
make stream-up
```

打开实时多路预览：

```bash
make stream-viewer
```

用 Rerun 可视化一个已录好的 episode：

```bash
make episode-rerun EPISODE=artifacts/lerobot/hw-10s-episode-20260312T134201
```

抓取当前最新一组同步帧：

```bash
make stream-shot
```

录制一条目标为 `300` 个对齐帧的 LeRobot v3 episode（约等于 `10` 秒 @ `30fps`）：

```bash
make stream-record-10s
```

查看推流日志：

```bash
make stream-logs
```

停止推流服务：

```bash
make stream-down
```

## 这套命令做了什么

`make stream-up` 会自动：

1. 启动 `sensor-stream` 容器
2. 探测当前有效连接的 RealSense
3. 提取序列号、型号、USB 端口等关键信息
4. 自动生成运行时配置
5. 在 host 暴露 `http://127.0.0.1:8787`

默认会按当前在线相机数自适应启动，不要求必须满 `8` 台。

## Host 侧代码如何拿到同步后的 frames

主入口在 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py)。

最常用接口：

```python
from sensor_proto.stream_client import AlignedStreamClient

client = AlignedStreamClient("http://127.0.0.1:8787")
frames, timestamp = client.get_latest_aligned_frames()

frame_rs00 = frames["rs-00"]   # numpy.ndarray, BGR
print(timestamp, frame_rs00.shape)
```

这里的语义是：

- `frames`: `dict[camera_id, numpy.ndarray]`
- `timestamp`: 该同步帧集的统一参考时间

注意：

- 这是同步后的统一 `timestamp`
- 不是每路各自一份 `timestamps`
- 当前是软同步，所以各路仍可能存在小的 `offsets_ms`

如果你还需要诊断信息，用详细接口：

```python
from sensor_proto.stream_client import AlignedStreamClient

client = AlignedStreamClient("http://127.0.0.1:8787")
aligned = client.get_latest_aligned_set()

print(aligned.set_id)
print(aligned.timestamp)
print(aligned.skew_ms)
print(aligned.offsets_ms)
print(aligned.device_timestamps_ms)
```

详细接口返回：

- `set_id`
- `timestamp`
- `frames`
- `offsets_ms`
- `device_timestamps_ms`
- `skew_ms`
- `camera_order`
- `raw_payload`

## Host 侧实时查看

实时 viewer 入口在 [stream_viewer.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_viewer.py)。

直接使用：

```bash
make stream-viewer
```

行为：

- 自动按网格布局显示多路相机
- 自动 resize，尽量完整铺进屏幕
- 顶部显示 `set_id / timestamp / skew_ms / camera_count`
- 每个子画面显示 `camera_id / offset`
- 按 `q` 或 `ESC` 退出

## Host 侧用 Rerun 看已录好的 episode

命令：

```bash
make episode-rerun EPISODE=artifacts/lerobot/hw-10s-episode-20260312T134201
```

底层脚本是：

```bash
bash scripts/run_episode_rerun.sh artifacts/lerobot/hw-10s-episode-20260312T134201
```

行为：

- 脚本运行在 host
- 输入是一个已经落盘完成的 LeRobot v3 episode 目录
- 自动从 `meta/info.json` 和 `videos/` 发现相机和视频文件
- 用 `rerun-sdk` 记录每路相机图像以及一张 mosaic 总览
- 默认会自动拉起本地 Rerun viewer

## Host 侧抓拍

命令：

```bash
make stream-shot
```

底层使用 [stream_client_cli.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client_cli.py)，会把当前最新同步帧集保存到：

- [artifacts/latest-aligned-frames](/home/corenetic/Code/sensor_proto/artifacts/latest-aligned-frames)

## 运行时产物

推流服务启动后，运行时配置会写到：

- [realsense-8cam-stream-runtime.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-stream-runtime.json)

这里能看到：

- 当前参与推流的相机列表
- 每台相机的 `serial`
- 自动识别到的 `model`
- `device_inventory`

如果同事想确认“这次到底连了哪几台”，优先看这个文件。

## 依赖说明

### 服务端

- Docker
- `docker compose`
- RealSense 设备访问权限

### Host 侧 Python/OpenCV

host 侧 viewer 和 Python client 依赖：

- `numpy`
- `cv2`
- `uv`

仓库已经通过脚本和 `make` 目标固化了必要环境变量，不需要手写长串命令。

## 排障顺序

如果同事用不起来，按这个顺序查：

1. `make stream-logs`
2. 看 [realsense-8cam-stream-runtime.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-stream-runtime.json)
3. 运行 `make stream-shot`
4. 最后再看 GUI 显示问题

常见判断：

- `make stream-shot` 成功，`make stream-viewer` 失败
  说明同步流和 host client 是通的，问题在 GUI 显示链路
- `127.0.0.1:8787` 连不上
  先看 `make stream-logs`
- 相机数量不是 `8`
  默认允许按当前在线相机数自适应启动

## 录制 300 个对齐帧的 episode

最短入口：

```bash
make stream-record-10s
```

底层实际调用的是：

```bash
bash scripts/record_stream_episode.sh 10
```

这个脚本会：

- 以 [realsense-8cam-stream.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-stream.json) 作为模板
- 在启动前临时注入 `recording` 配置，但不写死真实相机列表
- 启动时自动探测当前在线 RealSense，并生成运行时配置
- 以 `300` 个对齐帧作为默认停止条件（约等于 `10` 秒 @ `30fps`）
- 给 LeRobot v3 的视频编码和 `finalize()` 预留足够的收尾时间
- 另外保留一个独立 watchdog，防止硬件异常时无限挂住

默认产物：

- 数据集输出到 `artifacts/lerobot/hw-10s-episode-<timestamp>`
- 运行时配置输出到 [realsense-8cam-stream-recording-runtime.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-stream-recording-runtime.json)

可选环境变量：

- `SENSOR_PROTO_RECORD_OUTPUT_DIR`
- `SENSOR_PROTO_RECORD_FINALIZE_GRACE_S`
- `SENSOR_PROTO_RECORD_MAX_RUNTIME_S`
- `SENSOR_PROTO_RECORD_TARGET_ALIGNED_SETS`
- `SENSOR_PROTO_RECORD_FPS`
- `SENSOR_PROTO_RECORD_TASK`
- `SENSOR_PROTO_RECORD_REPO_ID`
- `SENSOR_PROTO_RECORD_ROBOT_TYPE`

## 开发与测试

运行测试：

```bash
make test
```

运行 mock：

```bash
make mock-run
```

## 录制为 LeRobot v3

当前支持把同步后的多相机观测直接录制为本地 LeRobot v3 数据集。

前提：

- 运行环境已安装官方 `lerobot` 包
- 参与录制的相机都启用了 `capture_image_data`
- 如果多路相机 `fps` 不一致，需要在配置里显式设置 `recording.fps`

最小 mock 示例配置见 [mock-lerobot-recording.json](/home/corenetic/Code/sensor_proto/configs/mock-lerobot-recording.json)。

启动录制：

```bash
source $HOME/.local/bin/env
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run --no-project --python "$(command -v python3)" python -m sensor_proto.stream_main --config configs/mock-lerobot-recording.json
```

说明：

- 录制入口复用同步流服务，不走 host 侧 HTTP 轮询
- 一次进程生命周期默认保存为一个 episode
- 使用 `Ctrl-C` 退出时会执行 `save_episode()` 和 `finalize()`
- 默认输出目录由配置里的 `recording.root_dir` 控制，例如 `artifacts/lerobot/mock-session`

## 进一步文档

- 快速上手文档：[realsense-stream-quickstart.md](/home/corenetic/Code/sensor_proto/docs/realsense-stream-quickstart.md)
- 设计说明文档：[realsense-8cam-stream-service-design.md](/home/corenetic/Code/sensor_proto/docs/realsense-8cam-stream-service-design.md)
