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

抓取当前最新一组同步帧：

```bash
make stream-shot
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

## 开发与测试

运行测试：

```bash
make test
```

运行 mock：

```bash
make mock-run
```

## 进一步文档

- 快速上手文档：[realsense-stream-quickstart.md](/home/corenetic/Code/sensor_proto/docs/realsense-stream-quickstart.md)
- 设计说明文档：[realsense-8cam-stream-service-design.md](/home/corenetic/Code/sensor_proto/docs/realsense-8cam-stream-service-design.md)
