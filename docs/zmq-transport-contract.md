# ZMQ Multipart Transport Contract

日期: 2026-03-13

状态: 已冻结，供 `sensor_proto` 的 ZMQ 数据面迁移使用

## 目标

为同步后的 `AlignedFrameSet` 定义一个最小、稳定、可测试的 ZMQ multipart v1 传输契约。

这个契约只覆盖 `sensor_proto` 内部和 host-side consumer 之间的 aligned-set 数据面，不覆盖 LeRobot robot/client 集成。

## 决策摘要

- HTTP 保留为 control-plane only：
  - `/`
  - `/api/health`
  - `/api/preview.jpg`
- ZMQ multipart 成为 aligned-set data-plane only。
- 迁移期间，`/api/latest-set` 只作为兼容路径存在，不再视为目标长期契约。
- 一个 ZMQ multipart message 必须精确表示一个 `AlignedFrameSet`。
- v1 元数据序列化格式固定为 UTF-8 `json`，不采用 `msgpack`。
- v1 图像 payload 编码固定为 `jpeg`。
- recording 仍消费服务器内存中的原始 `AlignedFrameSet`，不能从 ZMQ/JPEG 反解码后回灌。

## 为什么 v1 选 JSON 而不是 Msgpack

当前代码库已经大量使用标准库 `json`，而 v1 的主要诉求是：

- 最小依赖
- 容易抓包和人工检查
- 先把协议语义冻结，再考虑进一步压缩 metadata 成本

因此，v1 选 `json`。如果未来有充分证据表明 metadata 成本是瓶颈，可以在新协议版本里再评估二进制元数据格式。

## 核心不变量

### 1. 原子性

- 一个 multipart message = 一个 `AlignedFrameSet`
- 任何一台相机都不能脱离所属的 `AlignedFrameSet` 单独发布
- subscriber 不得跨 message 拼接相机图像
- 如果某个 aligned set 无法完整发送，应整组丢弃，而不是部分发送

### 2. 观察步语义

- downstream 每收到一个合法 message，就得到一个完整 observation step
- 一个 observation step 对应一个 `set_id`
- `set_id` 缺口表示 whole-set drop，而不是 message 内部损坏自动修复

### 3. recording 边界

- recording 位于 sync 之后、transport 之前
- 一个 recorded dataset step 必须来自一个内存中的 `AlignedFrameSet`
- recording 使用服务器原始 frame buffer，不依赖 `jpeg` payload decode

## 协议版本与兼容规则

- `protocol_version` 为整数，v1 固定为 `1`
- 在同一 major version 内：
  - producer 可以增加未知字段
  - consumer 必须忽略未知字段
- 以下任一变化都必须 bump `protocol_version`
  - multipart part 排列变化
  - 已有字段语义变化
  - 必填字段集合变化
  - payload 编码默认值变化
- v1 consumer 必须拒绝不支持的 `protocol_version`

## Multipart v1 布局

每个 aligned set 按以下顺序发送 multipart parts：

1. `envelope_json`
2. `camera_0_metadata_json`
3. `camera_0_payload_jpeg`
4. `camera_1_metadata_json`
5. `camera_1_payload_jpeg`
6. ...
7. `camera_n_metadata_json`
8. `camera_n_payload_jpeg`

约束：

- 第一个 part 永远是 envelope metadata
- 后续 part 必须严格按 `camera_order` 重复出现 metadata/payload 成对结构
- 不允许在中间插入额外 binary part
- `camera_count` 必须和 `camera_order` 长度一致
- 总 part 数必须满足 `1 + camera_count * 2`

## Envelope Metadata

`envelope_json` 是 UTF-8 JSON object，v1 必填字段如下：

```json
{
  "protocol": "sensor_proto.aligned_set",
  "protocol_version": 1,
  "set_id": 123,
  "reference_camera_id": "rs-00",
  "reference_timestamp_s": 1710331200.125,
  "skew_ms": 8.417,
  "camera_count": 2,
  "camera_order": ["rs-00", "rs-01"]
}
```

字段语义：

- `protocol`: 固定字符串，便于快速识别 payload 类型
- `protocol_version`: wire contract major version
- `set_id`: 当前 stream 进程生命周期内单调递增的 aligned-set 序号；进程重启后允许重置
- `reference_camera_id`: 当前 aligned set 的参考相机
- `reference_timestamp_s`: 该 aligned set 的统一参考时间语义
- `skew_ms`: 当前 aligned set 的最大相机间偏差
- `camera_count`: 当前 message 内的相机数量
- `camera_order`: 后续 camera parts 的固定顺序

## Per-Camera Metadata

每个 `camera_metadata_json` 是 UTF-8 JSON object，v1 必填字段如下：

```json
{
  "camera_id": "rs-00",
  "device_timestamp_ms": 123456.789,
  "offset_ms": 0.0,
  "width": 640,
  "height": 480,
  "pixel_format": "bgr8",
  "payload_encoding": "jpeg",
  "payload_size_bytes": 48213
}
```

字段语义：

- `camera_id`: 该帧所属相机；必须与 `camera_order` 中当前位置一致
- `device_timestamp_ms`: 原始设备时间戳；允许为 `null`
- `offset_ms`: 相对 `reference_timestamp_s` 的偏移
- `width`: 原图宽度
- `height`: 原图高度
- `pixel_format`: 服务器内存中源图像的像素格式语义，不表示 wire payload 的编码方式
- `payload_encoding`: v1 固定为 `jpeg`
- `payload_size_bytes`: 紧随其后的 binary payload 长度

可选字段可以后续增加，但 v1 consumer 必须忽略未知字段。

## Binary Payload

每个 `camera_payload_jpeg` 是与其前一个 metadata 对应的单路图像 payload。

v1 规则：

- payload 编码固定为 `jpeg`
- payload 必须和 `payload_size_bytes` 一致
- payload 顺序必须与 `camera_order` 一致
- consumer 解码失败必须显式报错，不能静默跳过该相机

## 发布与丢帧语义

publisher 规则：

- 只发布完整 aligned set
- 在 backpressure 下可以丢弃旧 aligned set，但必须整组丢弃
- 不允许发布 half-old / half-new 的混合相机集合
- preview 失败不能阻塞 ZMQ aligned-set 发布

subscriber 规则：

- 每个 multipart message 独立解析
- 不做跨 message camera reassembly
- `set_id` 不连续只表示消息级丢失
- 收到 malformed message 时应整条拒绝

## 下游可依赖的稳定字段

下游 consumer 可以依赖以下字段语义稳定：

- `set_id`
- `reference_timestamp_s`
- `reference_camera_id`
- `skew_ms`
- `camera_order`
- 每路 `camera_id`
- 每路 `device_timestamp_ms`
- 每路 `offset_ms`
- 每路 `width`
- 每路 `height`
- 每路 `pixel_format`
- 每路 `payload_encoding`

补充约束：

- `camera_id` 在单次运行时配置生成后的 session 内必须稳定
- 一个收到的 multipart message 必须能直接映射成一个 in-memory aligned bundle
- transport contract 不引入 `lerobot` 专有命名

## 错误处理要求

以下情况必须作为硬错误处理，不能静默降级：

- `protocol` 不匹配
- `protocol_version` 不支持
- `camera_count` 与实际 part 数不一致
- `camera_order` 与 per-camera metadata 顺序不一致
- `payload_size_bytes` 与实际 binary part 不一致
- 缺少任意 camera metadata 或 payload
- 不支持的 `payload_encoding`
- metadata JSON 非法
- JPEG 解码失败

## 迁移边界

v1 实施期间的代码边界如下：

- HTTP:
  - 保留 `/api/health`
  - 保留 `/api/preview.jpg`
  - 保留 `/` dashboard
  - `/api/latest-set` 仅作为兼容迁移路径，后续可降级为 debug-only 或移除
- ZMQ:
  - 承担 aligned-set data-plane
- Recording:
  - 保持为 transport 无关的独立 sink

## 对实现的直接要求

后续实现必须满足：

1. `SynchronizedStreamRunner` 的 aligned-set 回调对 transport 使用完整 aligned-set sink 抽象，而不是 per-camera callback。
2. 编码逻辑必须可在不打开 socket 的情况下单元测试。
3. publisher/subscriber round-trip 必须能仅凭本文档互操作，不依赖 side-channel。
4. recording regression test 必须能证明 recording 没有被移动到 transport decode 之后。
