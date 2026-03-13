# ZMQ Transport Validation Snapshot

日期：

- 2026-03-13

范围：

- `sensor_proto` ZMQ aligned-set data-plane
- HTTP control-plane / preview 共存
- mock localhost、RealSense 硬件、正式 `sensor-stream` 镜像验证

## 1. 本次已经实际执行过的验证路径

### 1.1 Mock localhost benchmark

server 配置：

- [configs/mock-stream-zmq-benchmark.json](/home/corenetic/Code/sensor_proto/configs/mock-stream-zmq-benchmark.json)

server 启动：

```bash
PYTHONPATH=src python -m sensor_proto.stream_main --config configs/mock-stream-zmq-benchmark.json
```

benchmark：

```bash
PYTHONPATH=src python -m sensor_proto.transport_benchmark \
  --base-url http://127.0.0.1:8787 \
  --transport http \
  --count 40 \
  --timeout-s 5 \
  --max-wait-s 20
```

```bash
PYTHONPATH=src python -m sensor_proto.transport_benchmark \
  --base-url http://127.0.0.1:8787 \
  --transport zmq \
  --count 40 \
  --timeout-s 5 \
  --max-wait-s 20
```

结果摘要：

- HTTP: `29.235 Hz`, `28.641 ms avg`
- ZMQ: `28.823 Hz`, `23.139 ms avg`
- `transport.dropped_sets = 0`
- `transport.would_block_events = 0`

### 1.2 Mock snapshot CLI 验证

```bash
PYTHONPATH=src python -m sensor_proto.stream_client_cli \
  --base-url http://127.0.0.1:8787 \
  --transport auto \
  --output-dir artifacts/latest-aligned-frames
```

结果摘要：

- 自动选择 ZMQ data-plane 成功
- 保存每路 PNG 成功
- `set_id / camera_order / offsets_ms` 正常

### 1.3 RealSense 硬件, bridge-network 跨容器代理 benchmark

说明：

- 这一步不是“真实双机 LAN”
- 它只证明 ZMQ 在非同进程、非 loopback 的网络路径上工作正常

server 模板：

- [configs/realsense-8cam-zmq-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-zmq-session.json)

结果摘要：

- HTTP: `30.030 Hz`, `94.559 ms avg`
- ZMQ: `30.366 Hz`, `81.695 ms avg`
- preview 维持约 `30 Hz`
- `transport.dropped_sets = 0`
- `transport.would_block_events = 0`

### 1.4 RealSense 硬件, 正式 `sensor-stream` 镜像验证

目的：

- 验证正式镜像内已包含 `pyzmq`
- 验证 ZMQ startup 不再依赖运行时补装

镜像内依赖检查：

```bash
docker run --rm --entrypoint python sensor-proto-sensor-stream -c "import zmq; print(zmq.__version__)"
```

已验证结果：

- 输出 `27.1.0`

正式镜像 server 启动：

```bash
docker run -d \
  --name sensor-stream-official \
  --network sensor-validate \
  --privileged \
  -v /dev/bus/usb:/dev/bus/usb \
  -v /run/udev:/run/udev:ro \
  --entrypoint python \
  sensor-proto-sensor-stream \
  -m sensor_proto.stream_main \
  --config configs/realsense-8cam-zmq-session.json \
  --generated-config /tmp/realsense-8cam-zmq-runtime.json
```

正式镜像 client benchmark：

```bash
docker run --rm \
  --network sensor-validate \
  --entrypoint python \
  sensor-proto-sensor-stream \
  -m sensor_proto.transport_benchmark \
  --base-url http://sensor-stream-official:8787 \
  --transport zmq \
  --count 20 \
  --timeout-s 5 \
  --max-wait-s 20
```

正式镜像 client snapshot：

```bash
docker run --rm \
  --network sensor-validate \
  --entrypoint python \
  sensor-proto-sensor-stream \
  -m sensor_proto.stream_client_cli \
  --base-url http://sensor-stream-official:8787 \
  --transport auto \
  --output-dir /tmp/latest-aligned-frames-official
```

结果摘要：

- 正式镜像 server 直接启动成功
- 正式镜像 client 直接跑 ZMQ benchmark 成功
- ZMQ benchmark: `30.051 Hz`, `83.775 ms avg`
- 正式镜像 client `stream_client_cli --transport auto` 成功保存 8 路 PNG
- preview 维持约 `29.876 Hz`
- `transport.dropped_sets = 0`
- `transport.would_block_events = 0`

## 2. 本次修复/确认过的问题

- benchmark 时钟域 bug 已修复：
  - `reference_timestamp_s` 为 epoch 时用 `time.time()`
  - mock monotonic 路径仍用 `time.monotonic()`
- 正式镜像缺 `pyzmq` 的问题已修复：
  - [pyproject.toml](/home/corenetic/Code/sensor_proto/pyproject.toml) 现在显式声明 `pyzmq>=26,<28`

## 3. 当前结论

已完成：

- ZMQ vertical slice 已经 end-to-end 可用
- mock localhost 已过
- 代表性 8 路 RealSense 硬件已过
- 正式 `sensor-stream` 镜像已过
- HTTP preview 与 ZMQ data-plane 可以共存

仍未完成：

- 真实双机 LAN benchmark
- server-side JPEG encode CPU 成本量化
- recording parity 最终验证

## 4. 下一步

真实双机部署和 benchmark 操作步骤见：

- [docs/dual-machine-zmq-benchmark.md](/home/corenetic/Code/sensor_proto/docs/dual-machine-zmq-benchmark.md)
