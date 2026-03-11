# RealSense 8路同步窗口边界实验报告

日期: 2026-03-11

## 1. 执行摘要

本轮实验聚焦 `Intel RealSense D435/D435i/D435if` 的 **8 路自由运行采集**，目标是在 **不启用硬件同步** 的前提下，确定一个可用于当前阶段运营的 `sync.tolerance_ms`。

本轮结论:

- 新增第 `8` 台相机在首次接入后，USB 层可见但 `pyrealsense2` 未枚举；重新插拔后，RealSense SDK 成功枚举 `8` 台设备。
- `8` 路短跑扫描结果表明，真正值得进入正式长测的窗口范围是 `40ms` 与 `45ms`。
- `30s` 正式对比中，`45ms` 相比 `40ms` 表现更优:
  - `40ms`: `aligned_sets=857`，`dropped_frames=123`
  - `45ms`: `aligned_sets=860`，`dropped_frames=81`
- `50ms` 不建议采用。它没有换来更好的成组质量，反而显著放大了 `avg_skew_ms` 和 `clock_drift` 告警数量。
- 因此，本轮建议将 **[configs/realsense-8cam-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session.json)** 的 `sync.tolerance_ms` 固定为 `45.0`，但将其定义为**当前自由运行阶段的软件运营边界**，而不是“物理同步精度”。

面向老板的管理结论:

1. 当前系统已经完成 `8` 路 RealSense 的可运行验证。
2. 当前 `45ms` 是一个工程折中值，用来在无硬同步条件下维持可接受的成组率。
3. 若后续业务需要高速动态场景下更强的跨视角时序一致性，应优先投入硬件同步或漂移治理，而不是继续放宽软件窗口。

## 2. 实验目标

本轮实验回答三个问题:

1. 新增第 `8` 台相机是否能被 USB 层与 RealSense SDK 同时识别。
2. `8` 路自由运行场景下，可用软件同步窗口边界落在什么范围。
3. 在兼顾成组率、丢帧率和风险告警的情况下，`8` 路正式配置应选用哪个窗口。

## 3. 实验环境与前提

- 运行方式: `docker compose -f docker/compose.yaml --profile hw run --rm sensor-hw`
- 运行模式: `hardware_sync_mode = disabled`
- 分辨率: `640x480`
- 帧率: `30 FPS`
- 队列深度: `320`
- 处理延迟: `0 ms`
- 时间戳来源: RealSense `timestamp_domain.global_time`
- 校准策略: `device-clock-soft-sync`

## 4. 实验过程

新增第 `8` 台相机后，首先进行设备识别验证。

现象:

- USB 层可以识别到 `8` 台 RealSense
- `pyrealsense2` 最初只能枚举 `7` 台

处理:

- 对新增相机重新插拔

结果:

- SDK 枚举恢复到 `8` 台
- 新增设备信息为:
  - 型号: `Intel RealSense D435I`
  - SDK 序列号: `406122070707`

随后进入两阶段验证:

1. `5s` 短跑扫描: 比较 `40ms / 45ms / 50ms`
2. `30s` 正式长测: 比较 `40ms / 45ms`

## 5. 实验设计与判断指标

### 5.1 方法

采用“先扫描、后长测”的策略:

1. 用短跑快速收敛窗口范围
2. 用长测验证候选窗口的稳定性与风险

### 5.2 指标

核心判断指标:

- `aligned_sets`: 成组次数，越高越好
- `dropped_frames`: 同步窗口丢弃次数，越低越好
- `avg_skew_ms`: 平均跨机时间散布，越低越好
- `max_skew_ms`: 最大跨机时间散布，用于判断是否贴近窗口上沿
- `warnings`: 重点关注 `clock_drift`

### 5.3 解释口径

`tolerance_ms` 的物理含义不是“系统真实同步精度”，而是:

> 系统允许一组 `8` 路帧中，最早帧与最晚帧之间的最大时间差。

在 `30 FPS` 下，一帧周期约为 `33.3ms`。因此 `45ms` 已经超过单帧周期，属于工程折中窗口，而不是严格同时采样窗口。

## 6. 关键结果

### 6.1 8路短跑扫描结果

| 报告 | 窗口 | aligned_sets | dropped_frames | avg_skew_ms | max_skew_ms | warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `artifacts/realsense-8cam-validation-40ms-report.json` | 40ms | 110 | 81 | 35.104 | 36.284 | 0 |
| `artifacts/realsense-8cam-validation-45ms-report.json` | 45ms | 111 | 84 | 31.352 | 32.752 | 1 |
| `artifacts/realsense-8cam-validation-50ms-report.json` | 50ms | 110 | 80 | 45.694 | 49.984 | 6 |

判断:

- `50ms` 明显过宽，不宜进入正式长测
- 真正值得比较的候选窗口收敛到 `40ms` 与 `45ms`

### 6.2 8路正式长跑结果

| 报告 | 窗口 | aligned_sets | dropped_frames | avg_skew_ms | max_skew_ms | warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `artifacts/realsense-8cam-report-40ms.json` | 40ms | 857 | 123 | 34.994 | 39.987 | 2 |
| `artifacts/realsense-8cam-report-45ms.json` | 45ms | 860 | 81 | 31.086 | 44.985 | 1 |
| `artifacts/realsense-8cam-report.json` | 45ms | 854 | 118 | 41.818 | 45.000 | 4 |

解释:

- 第一轮 `45ms` 正式长测明显优于 `40ms`
- 使用正式配置再次执行标准命令后，`45ms` 仍然保持可运行，但告警数量上升，说明当前 `8` 路自由运行状态存在批次波动

## 7. 核心结论

### 7.1 最终窗口选择

本轮建议采用 **`45ms`** 作为当前 `8` 路正式窗口边界。

原因:

- 相比 `40ms`，`45ms` 在正式长测中显著降低了 `dropped_frames`
- 相比 `50ms`，`45ms` 没有把系统推到明显更宽、更不稳定的散布区间
- `45ms` 仍然属于“工程可用但不严格”的窗口，适合作为当前阶段的运营配置

### 7.2 不建议继续放宽到50ms

`50ms` 的问题不在于完全不可用，而在于:

- `avg_skew_ms` 明显恶化
- `max_skew_ms` 基本贴近窗口上沿
- `clock_drift` 告警显著增加

这意味着系统只是“接受了更松的配对”，并没有得到真正更稳的边界。

### 7.3 面向老板的一句话版本

> 当前系统已经完成 `8` 路 RealSense 的可运行验证，建议将软件同步窗口暂定为 `45ms` 作为运营边界；但该方案仍属于自由运行条件下的软件折中，不应被视为严格同步方案。

## 8. 风险与限制

1. 当前未启用 RealSense 硬件触发同步，所有结论都属于“自由运行 + 软件对齐”范畴。
2. `45ms` 已经大于单帧周期，不适合作为高速动态场景下的严格几何一致性保证。
3. 正式配置复跑时，`clock_drift` 告警数量上升，说明 `45ms` 虽可用，但稳定性仍受设备漂移和瞬时负载影响。
4. 因此，`45ms` 更适合作为当前阶段的运营窗口，而不是最终长期 SLA。

## 9. 建议的下一步

1. 以 [configs/realsense-8cam-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session.json) 作为当前 `8` 路正式配置。
2. 对 `rs-02`、`rs-05`、`rs-06`、`rs-07` 的漂移来源做定点排查。
3. 增加重复长测样本，统计 `45ms` 下告警波动范围。
4. 若后续业务对高速动态场景或严格时序分析有更高要求，应优先投入硬件同步，而不是继续放宽软件窗口。

## 10. 相关产物

配置文件:

- [configs/realsense-8cam-session.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session.json)
- [configs/realsense-8cam-session-40ms.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session-40ms.json)
- [configs/realsense-8cam-session-45ms.json](/home/corenetic/Code/sensor_proto/configs/realsense-8cam-session-45ms.json)

报告文件:

- [artifacts/realsense-8cam-report-40ms.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-report-40ms.json)
- [artifacts/realsense-8cam-report-45ms.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-report-45ms.json)
- [artifacts/realsense-8cam-report.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-report.json)

## 11. 附录: 本轮正式标准命令

```bash
docker compose -f docker/compose.yaml --profile hw run --rm sensor-hw --config configs/realsense-8cam-session.json
```
