# ZMQ Transport Validation Snapshot

日期：

- 2026-03-13

范围：

- `sensor_proto` ZMQ aligned-set data-plane
- HTTP control-plane / preview 共存
- mock localhost、RealSense 硬件、正式 `sensor-stream` 镜像验证
- 真实双机 LAN 验证

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

### 1.5 RealSense 硬件, 真实双机 LAN benchmark

说明：

- `server` 使用 Docker 硬件环境启动正式 `sensor-stream` 镜像
- `client` 通过真实局域网访问 `8787/tcp` 与 `5555/tcp`
- 为了让 HTTP debug 路径不在 8 路串行拉图时过早淘汰 set，临时将 `stream.recent_sets` 从 `4` 调到 `32`

server 配置：

- 基于 [configs/realsense-8cam-zmq-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-zmq-session.json) 生成 `recent_sets=32` 的临时副本

server 启动：

```bash
docker run --rm \
  --name sensor-stream-lan \
  --privileged \
  -p 8787:8787 \
  -p 5555:5555 \
  -v "$PWD:/workspace" \
  -v /dev/bus/usb:/dev/bus/usb \
  -v /run/udev:/run/udev:ro \
  -w /workspace \
  --entrypoint python3 \
  sensor-proto-sensor-stream:latest \
  -m sensor_proto.stream_main \
  --config artifacts/lan-benchmark-20260313T140638/realsense-8cam-zmq-session-recent32.json \
  --generated-config artifacts/lan-benchmark-20260313T140638/realsense-8cam-zmq-runtime-recent32.json
```

基线 health 摘要：

- preview publish rate 约 `29.857 Hz`
- `transport.enabled = true`
- `transport.port = 5555`
- `sync.avg_skew_ms` 约 `39.918`
- 当前映射中 `rs-07 -> serial 152222070161`

HTTP benchmark：

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.transport_benchmark \
  --base-url http://192.168.93.198:8787 \
  --transport http \
  --count 40 \
  --timeout-s 5 \
  --max-wait-s 20
```

HTTP snapshot：

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.stream_client_cli \
  --base-url http://192.168.93.198:8787 \
  --transport http \
  --output-dir artifacts/lan-client-http-snapshot
```

结果摘要：

- 在 `recent_sets=4` 时，HTTP 兼容路径曾出现 `Unknown set id` 的 `404`
- 将 `recent_sets` 提高到 `32` 后，HTTP benchmark 与 snapshot 均能完成
- HTTP benchmark: `12.502 Hz`, `212.412 ms avg`, `316.412 ms max`
- HTTP snapshot 成功保存 8 路 PNG
- 结论：HTTP `/api/latest-set` + per-frame BMP 路径只适合作为 debug fallback，不适合作为主 aligned-set data-plane

ZMQ 长跑 benchmark：

```bash
for i in 1 2 3; do
  PYTHONPATH=src .venv/bin/python -m sensor_proto.transport_benchmark \
    --base-url http://192.168.93.198:8787 \
    --transport zmq \
    --count 900 \
    --timeout-s 5 \
    --max-wait-s 60
done
```

ZMQ auto snapshot：

```bash
PYTHONPATH=src .venv/bin/python -m sensor_proto.stream_client_cli \
  --base-url http://192.168.93.198:8787 \
  --transport auto \
  --output-dir artifacts/lan-client-zmq-auto-snapshot
```

结果摘要：

- ZMQ run 1: `29.772 Hz`, `125.695 ms avg`
- ZMQ run 2: `29.755 Hz`, `126.172 ms avg`
- ZMQ run 3: `29.758 Hz`, `125.296 ms avg`
- 3 次长跑均保持：
  - `transport.dropped_sets = 0`
  - `transport.would_block_events = 0`
  - preview 维持约 `29.86 ~ 29.89 Hz`
- `stream_client_cli --transport auto` 成功保存 8 路 PNG
- 传输层结论：ZMQ 已通过真实双机 LAN 验证，可作为主 aligned-set data-plane

同步 / 硬件侧观察：

- `sync.avg_skew_ms` 在 3 次 ZMQ 长跑里稳定在 `41.198 ~ 41.214`
- `sync.max_skew_ms` 持续贴近 `45 ms` 容差上沿
- `rs-07` 在 3 次长跑中均为 `dropped_frames = 0`
- 但 `rs-07` 持续表现为正偏移机位，末尾 `last_offset_ms` 约为 `34.395 ms`、`13.699 ms`、`34.365 ms`
- 其他相机持续掉帧，说明当前更像是 sync / hardware 边缘运行，而不是 transport 回退或网络丢包

当前判断：

- transport 主要风险已关闭
- 后续排查重心应从 transport 切到 sync / hardware
- 下一步应执行 `rs-07` 对应真实设备 `serial 152222070161` 的换口 / 换线 / USB 路径对照测试

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
- 真实双机 LAN benchmark 已过
- HTTP preview 与 ZMQ data-plane 可以共存

仍未完成：

- server-side JPEG encode CPU 成本量化
- recording parity 最终验证
- `rs-07` 硬件路径归因

## 4. 下一步

双机部署和 benchmark 操作步骤见：

- [docs/dual-machine-zmq-benchmark.md](/home/corenetic/Code/sensor_proto/docs/dual-machine-zmq-benchmark.md)

后续优先事项：

- 对 `rs-07` 对应的 `serial 152222070161` 做换口 / 换线对照，判断异常是跟着设备走还是跟着 USB 路径走
- 完成 ZMQ cutover 后的 recording parity 验证
