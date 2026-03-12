# RealSense Stream 优化优先级记录

日期：2026-03-12

## 当前判断

上一轮已经完成两件高性价比优化：

- viewer 改走单次 preview mosaic，而不是 `1 + N` 串行拉图
- 服务端新增 latest-only preview 通道

这已经缩短了 host 预览链路，但当前剩余瓶颈还没有被量化清楚，尤其是：

- preview `JPEG` 编码成本
- 对齐帧集实际产出速率
- 相机 stall 对首帧和稳态帧率的影响

因此，后续优化必须按优先级推进，而不是直接跳到多进程或更重的改造。

## 优先级

### P1：量化 preview 路径并做低风险参数调优

目标：

- 在 `/api/health` 中暴露 preview 编码耗时与发布速率
- 让 preview 分辨率和 `JPEG` 质量可配置
- 将默认 preview 参数调到更适合低延迟预览，而不是偏大图质量

原因：

- 这是当前最小、最稳、最能直接指导下一步决策的改动
- 只有先量化，后续是否需要更重的架构改造才有依据

本轮状态：已执行

### P2：进一步将 preview 首帧可用性与完整对齐帧集解耦

目标：

- 让 preview 更接近“最新帧优先”
- 当个别相机短时抖动或掉帧时，不必完全阻塞人眼预览

原因：

- 当前 preview 仍然依附于 `AlignedFrameSet` 发布
- 只要上游迟迟拼不出完整对齐集，preview 首帧和稳态刷新都会被拖住

本轮状态：未执行

### P3：仅在 profile 证明必要时，再考虑更重方案

候选方向：

- client 并发或推送式传输
- 预览与数据分发进程拆分
- 共享内存或更轻量编码
- `C++` 热路径

原因：

- 这些方案工程成本高，必须建立在前两级已经量化完成的基础上

本轮状态：未执行

## 当前建议

当前推荐路线：

1. 先落地 P1
2. 观察真实硬件下的 `preview.encode_*`、发布速率和相机 stall
3. 只有当这些数据仍证明预览体验不够时，再推进 P2

## 本轮结论

基于长时间运行的 `/api/health` 观测，当前结论已经明确：

- preview 路径当前不是主要瓶颈
- `preview.publish_rate_hz` 已经稳定接近 `30Hz`
- `preview.avg_encode_ms` 处于可接受区间，不足以解释剩余体验问题
- 剩余主要成本在多机软同步和硬件稳定性，而不是 preview 编码

因此当前建议调整为：

1. 保持当前 preview 实现，不继续优先做 preview 优化
2. 不进入 P2，除非后续数据重新证明 preview 首帧或稳态刷新仍然明显受限
3. 后续优化重心转到 sync / hardware，重点关注：
   - `sync.avg_skew_ms`
   - `sync.max_skew_ms`
   - `sync.incomplete_sets`
   - `sync.per_camera.*.dropped_frames`
