# TODO

已完成事项已从此文件清理，归档结论见 `docs/` 下相关文档。

---

## Hikrobot 自动探测 + 时间同步 + 推流

> 目标：插上 Hikrobot 相机后 `make hikrobot-stream-up` 即可完整跑通——自动探测在线设备、生成运行时配置、做时间同步、向 host 推流。
> 约束：**不改动 RealSense 主逻辑**，只对数据采集层做加法。

### T1 — hikrobot 自动探测 & 运行时配置生成

**核心约束：无论宿主机上是否连接了其他种类相机（RealSense、Orbbec 等），该路径只调用 `discover_hikrobot_devices()`，仅枚举 Hikrobot USB3 Vision 设备，其余设备一律忽略。**

**文件**：`src/sensor_proto/stream_main.py`

- [x] 新增 `build_hikrobot_stream_config_payload(template_payload, devices)` 函数
- [x] 扩展 `prepare_stream_runtime_config()` 增加 "all-hikrobot" 分支（内部委托给 `_prepare_hikrobot_runtime_config()`）
  - 检测到 all-hikrobot 模板 → 只调 `discover_hikrobot_devices()`，其余设备忽略
  - 写入 `artifacts/hikrobot-stream-runtime.json`

**验收**：启动时终端打印 `Detected N Hikrobot camera(s): DA540xxxx, ...`，并在 `artifacts/hikrobot-stream-runtime.json` 写出含真实序列号的运行时配置。

### T2 — HikrobotCameraAdapter 时钟校准（开机对齐）

**文件**：`src/sensor_proto/cameras/hikrobot.py`

- [x] 在 `_open()` 末尾增加时钟校准步骤（`_calibrate_device_clock()`）
  - 调用 `MV_CC_SetCommandValue("TimestampLatch")` + `MV_CC_GetIntValueEx("Timestamp", ...)`
  - 记录 host `time.monotonic()` 作为原点；固件不支持时 fallback 到 `(0, 0.0)`
- [x] `_next_frame()` 中用 epoch 修正 `device_timestamp_ms`，映射到 host 单调时间轴

**验收**：双相机启动后前 5 帧内 `skew_ms < 45ms`（而非等待 EMA 收敛 30+ 帧）。

### T3 — 新增 hikrobot 推流配置模板

**文件**：`configs/hikrobot-stream.json`（新建）

- [x] 创建 `configs/hikrobot-stream.json`，不含硬编码序列号（`serial: ""`，runtime 阶段自动填充）

> `configs/hikrobot-2cam.json` 保留不变，作为有确定序列号时的静态配置备用。

### T4 — Docker：新增 sensor-hikrobot-stream 服务

**文件**：`docker/compose.yaml`

- [x] 新增 `sensor-hikrobot-stream` service（`profiles: ["hikrobot"]`）
  - `INSTALL_REALSENSE: "0"`，挂载 `/opt/MVS:/opt/MVS:ro`，USB 透传，`privileged + network_mode: host`

**前提**：宿主机需提前通过 Hikrobot 官方安装包完成 MVS SDK 安装（`/opt/MVS`）。

### T5 — Makefile + 启动脚本

**文件**：`Makefile`, `scripts/run_hikrobot_stream_service.sh`（新建）

- [x] 新增 `scripts/run_hikrobot_stream_service.sh`
- [x] Makefile 新增 target：`hikrobot-stream-up`, `hikrobot-stream-down`, `hikrobot-stream-logs`, `hikrobot-stream-shot`, `hikrobot-stream-viewer`

### T6 — 端到端验证清单

- [ ] `make hikrobot-stream-up` 无报错启动
- [ ] `artifacts/hikrobot-stream-runtime.json` 中 `cameras` 含真实序列号
- [ ] `make hikrobot-stream-shot` 能保存同步帧到 `artifacts/latest-aligned-frames/`
- [ ] `curl http://127.0.0.1:8787/api/health` 返回 `200`，`camera_count` 与实际插入数一致
- [ ] `make hikrobot-stream-viewer` 实时预览，`skew_ms < 45ms`
- [ ] `make hikrobot-stream-down` 正常停止
- [ ] 回归验证：`make stream-up` 仍正常，hikrobot 改动无副作用

### 范围说明（不在本批次内）

- `streaming.py`, `synchronization.py`, `pipeline.py` 不改
- HTTP / ZMQ transport 层不改
- Recording / LeRobot 录制流程不改
- Hikrobot + RealSense 混用（mixed kind）暂缓，后续按需评估

---

## ZMQ Cutover Remaining Work

- [ ] Measure CPU cost of server-side JPEG encode under target load.
- [ ] Validate that server-side LeRobot v3 recording output remains unchanged in structure and camera feature mapping after the ZMQ cutover.
- [ ] After cutover, simplify the codebase into explicit control-plane HTTP, data-plane ZMQ, and downstream integration boundaries.

## Post-LAN Follow-Up

- [ ] Run the `rs-07` hardware swap experiment using the current dual-machine LAN setup and compare before/after `id -> serial` mapping plus sync drift metrics.
- [ ] Determine whether the persistent positive offset follows serial `152222070161` or the original USB path / cable / controller lane.
- [ ] Run recording parity validation on the Docker-based `sensor-stream` server after the `rs-07` hardware path is characterized.
