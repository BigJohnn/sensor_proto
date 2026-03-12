# RealSense 推流快速使用

## 适用对象

这份文档给第一次上手的同事使用。目标只有一个：尽快把多相机同步流跑起来，并在 host 上看到实时画面。

## 约定

- 仓库路径：`/home/corenetic/Code/sensor_proto`
- 推流服务地址：`http://127.0.0.1:8787`
- 推流服务会自动探测当前有效连接的 RealSense，并自动生成运行时配置

## 最短路径

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

保存当前最新一组同步帧到本地：

```bash
make stream-shot
```

停止推流服务：

```bash
make stream-down
```

查看推流日志：

```bash
make stream-logs
```

## 会发生什么

`make stream-up` 会自动完成这些事情：

1. 启动 `sensor-stream` 容器
2. 探测当前在线 RealSense
3. 提取序列号、型号、USB 端口等信息
4. 生成运行时配置：
   [realsense-8cam-stream-runtime.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-stream-runtime.json)
5. 启动 host 可访问的推流接口

## 预览窗口说明

- 预览窗口会自动按网格布局缩放，尽量在屏幕内完整显示
- 窗口顶部会显示：
  - `set_id`
  - 统一 `timestamp`
  - `skew_ms`
  - 相机数量
- 每个子画面会显示对应 `camera_id` 和 `offset`
- 按 `q` 或 `ESC` 退出预览

## 常用输出位置

- 运行时配置：
  [realsense-8cam-stream-runtime.json](/home/corenetic/Code/sensor_proto/artifacts/realsense-8cam-stream-runtime.json)
- 手动抓拍输出目录：
  [latest-aligned-frames](/home/corenetic/Code/sensor_proto/artifacts/latest-aligned-frames)

## 常见问题

### 1. `make stream-viewer` 提示连不上 `127.0.0.1:8787`

先确认服务是否已启动：

```bash
make stream-logs
```

正常日志里应看到：

- `Detected ... RealSense camera(s)`
- `Generated runtime config ...`
- `Serving synchronized stream on http://0.0.0.0:8787`

### 2. 画面窗口打不开，但服务是通的

这通常是 host 图形环境问题，不是推流服务本身失败。先确认：

```bash
make stream-shot
```

如果抓拍成功，说明同步流和 host client 正常，问题只在 GUI 显示链路。

### 3. 当前不是 8 台，而是 7 台或更少

这是允许的。推流服务默认按当前在线相机数自适应生成运行时配置，不会因为少一台就拒绝启动。

### 4. 想核对当前在线设备到底是哪几台

打开运行时配置文件，查看：

- `cameras`
- `device_inventory`

### 5. 想看 preview 当前是否是编码瓶颈

直接查看 health：

```bash
curl -s http://127.0.0.1:8787/api/health | python3 -m json.tool
```

重点看：

- `preview.last_encode_ms`
- `preview.avg_encode_ms`
- `preview.max_encode_ms`
- `preview.last_size_bytes`
- `preview.publish_rate_hz`

## 推荐做法

- 日常使用优先记住 `make stream-up` 和 `make stream-viewer`
- 不要手写长串 `uv`/`PYTHONPATH`/`QT_QPA_PLATFORM` 命令
- 排查问题时优先看：
  1. `make stream-logs`
  2. 运行时配置文件
  3. `make stream-shot` 是否成功
