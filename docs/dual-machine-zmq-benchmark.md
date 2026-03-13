# Dual-Machine ZMQ Benchmark

本文把当前这台机器视为 `server`，另一台机器视为 `client`。

目标：

- `server` 负责 RealSense 采集、HTTP control-plane、preview、ZMQ aligned-set data-plane
- `client` 只负责订阅 `/api/health` 和 ZMQ aligned-set data-plane
- 用真实 LAN 而不是同机 loopback 或 Docker bridge 评估吞吐和时延

## 1. Server 端

前提：

- `server` 能访问 RealSense 设备
- `server` 和 `client` 在同一局域网
- `client` 能访问 `server` 的 `8787/tcp` 和 `5555/tcp`

推荐直接使用已经验证过的 ZMQ 模板：

- [configs/realsense-8cam-zmq-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-zmq-session.json)

如果直接用容器启动正式镜像：

```bash
docker run --rm \
  --name sensor-stream-lan \
  --privileged \
  -p 8787:8787 \
  -p 5555:5555 \
  -v /dev/bus/usb:/dev/bus/usb \
  -v /run/udev:/run/udev:ro \
  --entrypoint python \
  sensor-proto-sensor-stream \
  -m sensor_proto.stream_main \
  --config configs/realsense-8cam-zmq-session.json \
  --generated-config /tmp/realsense-8cam-zmq-runtime.json
```

如果从工作区直接启动：

```bash
PYTHONPATH=src python -m sensor_proto.stream_main \
  --config configs/realsense-8cam-zmq-session.json \
  --generated-config artifacts/realsense-8cam-zmq-runtime.json
```

启动后先在 `server` 上自检：

```bash
curl -s http://127.0.0.1:8787/api/health | python -m json.tool
```

预期至少看到：

- `transport.enabled = true`
- `transport.kind = "zmq"`
- `transport.port = 5555`
- `transport.active = true`

## 2. Client 端部署

`client` 不需要 RealSense SDK，也不需要容器特权；只需要：

- Python 3.10+
- `uv`
- `numpy`
- `opencv-python-headless`
- 本项目代码

### 方式 A：本地 Python 环境

```bash
git clone <your-repo-url> sensor_proto
cd sensor_proto

uv venv .venv
uv pip install --python .venv/bin/python numpy opencv-python-headless
uv pip install --python .venv/bin/python .
```

验证依赖：

```bash
.venv/bin/python -c "import cv2, zmq, sensor_proto; print('ok')"
```

### 方式 B：容器 client

如果 `client` 机器也能访问同一份镜像，可以直接运行：

```bash
docker run --rm --entrypoint python sensor-proto-sensor-stream -c "import cv2, zmq; print('ok')"
```

然后所有 client 命令都用 `docker run --rm --entrypoint python sensor-proto-sensor-stream ...` 执行。

## 3. 连通性检查

先在 `client` 上确认能看到 `server` 的 HTTP health。

假设 `server` 局域网 IP 是 `192.168.1.20`：

```bash
curl -s http://192.168.1.20:8787/api/health | python -m json.tool
```

如果这里失败，不要继续测 ZMQ，先检查：

- `server` 防火墙
- 交换机 / AP 隔离
- 端口映射是否真的监听在 `0.0.0.0`

## 4. Client 端跑基准

HTTP 基准：

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.transport_benchmark \
  --base-url http://192.168.1.20:8787 \
  --transport http \
  --count 40 \
  --timeout-s 5 \
  --max-wait-s 20
```

ZMQ 基准：

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.transport_benchmark \
  --base-url http://192.168.1.20:8787 \
  --transport zmq \
  --count 40 \
  --timeout-s 5 \
  --max-wait-s 20
```

建议至少记录：

- `throughput_hz`
- `latency_ms.avg`
- `latency_ms.median`
- `latency_ms.max`
- `health.preview.avg_encode_ms`
- `health.transport.dropped_sets`
- `health.transport.would_block_events`
- `health.sync.avg_skew_ms`

## 5. Client 端抓拍验证

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.stream_client_cli \
  --base-url http://192.168.1.20:8787 \
  --transport auto \
  --output-dir artifacts/latest-aligned-frames-lan
```

预期：

- 能保存每个相机一张 PNG
- `camera_order` 与 `health.camera_ids` 一致
- `offsets_ms` 和 `device_timestamps_ms` 都非空且数值合理

## 6. 判定建议

这轮真实双机 LAN benchmark 至少要回答 3 个问题：

1. ZMQ 相比 HTTP 是否维持相同或更高的 `throughput_hz`
2. ZMQ 是否维持更低或不更差的平均/中位延迟
3. ZMQ 开启后 `dropped_sets` 是否仍保持在 `0` 或可接受范围

如果 LAN benchmark 通过，再进入：

- recording parity 验证
- `/api/latest-set` debug-only 保留策略复审
- cutover 后的 transport 清理
