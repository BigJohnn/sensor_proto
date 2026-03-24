# Multi-Modal Pipeline 建设路线图

Date: 2026-03-24

## 现状 vs 目标 Gap

| 层 | 现有 | 缺失 |
|----|------|------|
| 相机适配器 | RealSense（仅彩色）、Orbbec、Mock | 工业相机（GigE/USB3V）、Fisheye、D405/D435 深度流 |
| 传感器模型 | `Frame`（图像专用） | `SensorSample`（通用连续值） |
| 缓冲 / 插值 | `deque` nearest-frame（图像） | `SensorRingBuffer` 线性插值（tactile/encoder） |
| 同步器 | `FrameSynchronizer`（同频相机） | `MultiModalSynchronizer`（异频、epoch trigger） |
| 录制 | `LeRobotRecorder`（单 fps、仅图像） | 支持 90Hz + 非图像 parquet 列 |
| 时钟 | `_ClockTracker` EMA（路径 C） | `global_time_enabled` 未开启（路径 B 未激活） |

---

## 实施顺序

### 第一步：确认硬件规格（写代码前）

- D405/D435 接上后跑 `rs-enumerate-devices`，确认彩色流实际最高 fps × 分辨率
- 工业相机：确认接口（GigE Vision / USB3 Vision）和厂商 Linux SDK
- Fisheye 相机：确认驱动方式（V4L2 / 厂商 SDK）
- Tactile 传感器：确认接口（USB HID / Serial / CAN / SPI）

### 第二步：扩展数据模型（`models.py`）

新增 `SensorSample`，与 `Frame` 并列：

```python
@dataclass(slots=True)
class SensorSample:
    sensor_id: str
    sensor_kind: str          # "tactile" | "encoder" | "pose"
    sequence: int
    timestamp_s: float        # CLOCK_REALTIME 或 CLOCK_MONOTONIC，与相机保持一致
    data: bytes               # raw bytes，调用方 np.frombuffer 解析
    shape: tuple[int, ...]
    dtype: str                # "uint8" | "float64" | "float32"
```

同步扩展 `AlignedFrameSet`（或新建 `AlignedObservation`），加入非图像字段和 `per_modal_lag_ms`。

### 第三步：实现 SensorRingBuffer（新文件）

新建 `src/sensor_proto/ring_buffer.py`，核心接口：

```python
class SensorRingBuffer:
    def push(self, t: float, data: np.ndarray) -> bool: ...
    # 返回 False 表示乱序（时钟跳变守卫），不写入

    def query_at(self, t: float) -> QueryResult: ...
    # QueryResult.value       线性插值结果
    # QueryResult.lag_ms      T 距最新样本的时间差（ZOH 时非零）
    # QueryResult.is_extrapolated  True 表示走了 ZOH fallback
```

单元测试必须覆盖：线性插值精度、ZOH fallback、乱序拒绝。

### 第四步：补全相机适配器

| 适配器 | 工作量 | 说明 |
|--------|--------|------|
| `RealSenseCameraAdapter` 加深度流 | 小 | `_build_rs_config` 里增加 `enable_stream(stream.depth, ...)` |
| `RealSenseCameraAdapter` 开 global_time | 极小 | `_start()` 后加 `_enable_global_time()`，约 10 行 |
| 工业相机适配器 | 中 | 继承 `CameraAdapter`，接口按厂商 SDK 实现 |
| Fisheye 适配器 | 中 | V4L2 设备可复用通用基类 |

### 第五步：实现 MultiModalSynchronizer（新文件）

新建 `src/sensor_proto/multi_modal_synchronizer.py`：

- 持有每个图像传感器的 `deque`（nearest-frame）和每个连续传感器的 `SensorRingBuffer`
- epoch trigger：Fisheye 90Hz 帧到达时触发，向所有缓冲查询时间戳 T
- 输出 `AlignedObservation`，含 `rgb_is_duplicate` 标记
- 现有 `FrameSynchronizer` 保留不改，用于纯相机场景

### 第六步：修录制层

两处修改：

1. config 里设 `recording.fps = 90`，走 `recording.py:96-97` 的显式 fps 分支，代码不需要改
2. `LeRobotRecorder.record()` 增加非图像列写入（tactile/encoder/pose 作为 parquet array 列）

### 第七步：端到端验证，再决定是否上 PTP

系统录到盘、`episode-rerun` 能回放后，查看 `sync.avg_skew_ms`：
- skew < 5ms 且任务可接受 → 不需要 PTP，EMA 纠偏已足够
- skew > 5ms 或任务对触觉时序敏感 → 上 PTP

---

## PTP 升级路径（按需）

全链：`ptp4l` 同步 NIC PHC → `phc2sys` 同步 CLOCK_REALTIME → RealSense SDK global_time 修正帧时间戳 → `synchronization.py:71-73` 路径 B 直通。

代码侧唯一改动：`RealSenseCameraAdapter._start()` 后调用 `_enable_global_time()`（约 10 行）。
同步器代码零改动，`_uses_shared_global_time_domain()` 已正确实现（`synchronization.py:137-139`）。

混合路径风险：global_time 帧的 `normalized_timestamp_s` 是 Unix epoch（~1.74×10⁹），路径 C 帧是 monotonic（~1000），两者不可混合比较，会导致所有帧落在 tolerance 窗外。升级时需确保同批次所有相机同时切换。

---

## 存储成本速查

详见 `docs/sensor-storage-cost.md`。关键数字：

| 指标 | H.264 | H.265 |
|------|-------|-------|
| 压缩后写入带宽 | ~23 MB/s | ~13 MB/s |
| 60s 单集大小 | ~1.4 GB | ~0.8 GB |
| 4TB NVMe 容量 | ~2,800 集 | ~5,000 集 |
| 非图像传感器（tactile + encoder + pose） | 22 MB/集 | 22 MB/集 |

真正的瓶颈是接口带宽和 GPU 编码能力，不是磁盘写入速度。GPU 需 RTX 4090（唯一移除 NVENC session 限制的消费级方案）。
