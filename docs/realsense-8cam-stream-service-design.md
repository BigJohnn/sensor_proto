# RealSense 8 路同步推流服务设计记录

## 背景

当前仓库已将 [configs/realsense-8cam-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session.json) 作为 `8` 路正式采集配置，`sync.tolerance_ms` 定为 `45.0`，用于自由运行 RealSense `8` 机位的软同步对齐。

在此基础上，新增一条“同步后再转发”的运行路径，用于：

- 在容器内完成 `8` 路采集与时间戳对齐
- 将同步后的帧集通过 HTTP 服务转发到 host
- 在 host 侧提供可视化客户端
- 为后续 Python/OpenCV 客户端提供稳定接口

## 当前方案结论

### 1. 服务边界

新增同步推流服务入口 [src/sensor_proto/stream_main.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_main.py)，运行形态为：

- 后台采集线程持续读取 `8` 路 RealSense
- 使用现有 [src/sensor_proto/synchronization.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/synchronization.py) 生成 `AlignedFrameSet`
- HTTP 服务同时暴露：
  - 完整同步数据路径：最新同步帧集元数据与逐路图像
  - 低延迟 preview 路径：latest-only mosaic 单图预览

当前推流服务以 [configs/realsense-8cam-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session.json) 作为模板配置；启动时先探测当前有效连接的 RealSense，相机序列号和关键设备信息会被提取出来，并自动生成运行时配置后再启动推流。

### 2. Host 转发方式

当前采用最小依赖方案：

- 元数据接口：`/api/health`
- 最新同步帧集接口：`/api/latest-set`
- 单路图像接口：`/api/sets/{set_id}/frames/{camera_id}.bmp`
- preview 接口：`/api/preview.jpg`
- 可视化页面：`/`

图像以 BMP 返回，原因是：

- 不引入 Pillow/OpenCV 作为服务端硬依赖
- 浏览器可直接显示
- Python 客户端可直接解码为 OpenCV `ndarray`

新增 preview 通道后：

- 完整数据路径仍保持 BMP + 逐路拉取，供调试和算法消费
- preview 路径改为服务端直接生成单张 mosaic `JPEG`
- 该路径只追最新、允许覆盖旧帧，不承担同步数据分发职责
- 因为 mosaic 在服务端编码，`sensor-stream` 容器需要提供 `numpy` 与 headless OpenCV

### 3. 自动探测与配置生成

推流服务当前的标准启动流程为：

1. 读取 session 模板配置
2. 枚举当前有效连接的 RealSense 设备
3. 提取每台设备的：
   - `serial`
   - `name`
   - `model`
   - `physical_port`
   - `product_line`
   - `usb_type`
   - `firmware_version`
4. 按 `physical_port + serial` 做稳定排序
5. 自动生成运行时 stream config
6. 再启动真机推流服务

生成后的运行时 config 会：

- 保留模板中的同步参数
- 自动重写 `cameras`
- 将每路 `capture_image_data` 置为 `true`
- 自动把 `sync.reference_camera_id` 对齐到新的 `rs-00`
- 记录设备清单，便于事后核对

默认行为按“当前在线相机数”自适应生成并启动；如需严格卡数量，可在启动参数里显式传入 `--expected-cameras`。

### 4. 数据模型结论

同步后的核心对象为 `AlignedFrameSet`，包含：

- `set_id`
- `reference_camera_id`
- `reference_timestamp_s`
- `skew_ms`
- `frames`
- `offsets_ms`

其中 `reference_timestamp_s` 是该同步帧集对外的统一时间语义。

### 5. Client 接口结论

对于 host 侧 Python client，主接口应定义为：

```python
frames, timestamp = client.get_latest_aligned_frames()
```

而不是：

```python
frames, timestamps = client.get_latest_aligned_frames()
```

原因：

- 同步后的主语义是“一个对齐帧集”，不是“八个彼此独立时间戳”
- `AlignedFrameSet` 已存在统一参考时间 `reference_timestamp_s`
- 每路 `device_timestamp_ms` 仍应保留，但属于诊断元数据，不应作为主业务接口暴露

需要明确的边界：

- 这里的 `timestamp` 指同步帧集的统一参考时间
- 这不意味着 `8` 路原始设备时间戳数值完全相同
- 在软同步下，各路仍可能存在 `offsets_ms`

因此，推荐双层接口：

1. 开箱即用主接口

```python
frames, timestamp = client.get_latest_aligned_frames()
```

2. 诊断接口

```python
aligned = client.get_latest_aligned_set()
```

其中详细结构应包含：

- `frames`
- `timestamp`
- `offsets_ms`
- `device_timestamps`
- `skew_ms`

## 当前实现状态

已完成：

- `AlignedFrameSet` 数据模型
- 同步器输出对齐帧集
- RealSense 图像数据采集与缓存
- HTTP 推流服务
- 浏览器可视化页面
- host 侧 Python/OpenCV client SDK
- host 侧单次拉取 preview mosaic 能力
- host 侧最小 CLI 工具
- `docker compose` 下的 `sensor-stream` 服务定义
- 基础单元测试

待补齐：
- preview 通道的进一步 profile 与质量参数调优

## 工程判断

当前实现已经满足“同步后转发到 host 并可视化”的最小闭环；目前已明确拆成两条路径：

- `data path`：`AlignedFrameSet` 元数据 + 单路 BMP，保留完整同步语义
- `preview path`：服务端直接输出单张 preview mosaic，供人眼低延迟预览

若目标是让 host 侧算法代码直接消费同步帧集，则继续使用 Python client 的完整数据接口：

- 现已提供 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py)
- 主接口为 `frames, timestamp = client.get_latest_aligned_frames()`
- 详细接口为 `client.get_latest_aligned_set()`
- 低延迟预览接口为 `client.get_latest_preview()`
- Host 环境需自行提供 `numpy` 与 `cv2`

下一步推荐工作：

1. 对 `/api/preview.jpg` 做端到端 profile，量化 mosaic 编码耗时
2. 明确 host 环境的 OpenCV 依赖安装方式
3. 评估 CLI 是否需要增加连续轮询模式

## 推荐命令

给开发者和同事的推荐入口已经收敛为 `make`：

```bash
make stream-up
```

```bash
make stream-viewer
```

```bash
make stream-shot
```

```bash
make stream-down
```

底层仍使用 `uv` 作为统一入口，包装脚本会自动固化环境变量：

```bash
source $HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src uv run --no-project --python "$(command -v python3)" python -m pytest tests/test_pipeline.py tests/test_stream_service.py tests/test_stream_autoconfig.py tests/test_stream_client.py tests/test_stream_client_cli.py tests/test_stream_viewer.py
```

```bash
source $HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run --no-project --python "$(command -v python3)" python -m sensor_proto.stream_main --config configs/realsense-8cam-session.json --generated-config artifacts/realsense-8cam-stream-runtime.json
```

```bash
source $HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run --no-project --python "$(command -v python3)" python -m sensor_proto.stream_client_cli --base-url http://127.0.0.1:8787 --output-dir artifacts/latest-aligned-frames
```

## Host Client 最小示例

```python
from sensor_proto.stream_client import AlignedStreamClient

client = AlignedStreamClient("http://127.0.0.1:8787")
frames, timestamp = client.get_latest_aligned_frames()

frame_rs00 = frames["rs-00"]  # numpy.ndarray, BGR
print(timestamp, frame_rs00.shape)
```
