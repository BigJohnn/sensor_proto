# RealSense 多路显示延迟讨论纪要

日期：2026-03-11

## 背景

当前 `8` 路相机的 host 侧显示已经跑通，但主观观感上明显慢于官方 RealSense Viewer。

本次讨论聚焦的问题是：

- 当前显示变慢最可能由哪些环节引起
- 是否需要直接转 `C++`
- 是否需要尽快改成多进程/多核推流
- 是否存在更合理的优化路径

## 结论摘要

结论很明确：

1. 当前慢于 RealSense Viewer，首先不是“必须转 `C++`”的问题。
2. 当前链路比官方 Viewer 多了多层额外开销，属于架构路径更长，而不是单纯语言慢。
3. 现阶段不建议优先上 `C++`，也不建议第一步就切多进程。
4. 更高性价比的方向是先优化现有 Python 路径中的明显冗余。
5. 最值得优先做的是单独增加一个低延迟 preview 通道，而不是继续拿“完整同步分发链路”直接做实时预览。

## 当前路径与官方 Viewer 的本质差异

官方 RealSense Viewer 更接近：

- SDK 直采
- 直出
- 直显

当前项目里的显示路径则是：

1. 相机采集
2. 多路软同步，等待成组
3. 服务端为每路图像重新编码为 BMP
4. client 先拉一份同步帧集元数据
5. client 再逐路拉取每张 BMP
6. client 逐张做 `cv2.imdecode`
7. viewer 端做 resize、拼图、渲染

因此两者不应直接按“同样显示延迟”来预期。

## 代码层面的主要可疑点

### 1. Viewer 当前被双重限速

在 [stream_viewer.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_viewer.py#L149) 到 [stream_viewer.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_viewer.py#L154) 之间：

- 已经调用了 `cv2.waitKey(poll_interval_ms)`
- 后面又额外执行了一次 `time.sleep(poll_interval_ms / 1000.0)`

这会把一次轮询周期进一步拉长，直接增加显示延迟。

### 2. Client 目前是串行多请求

在 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py#L34) 到 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py#L41)：

- 先请求 `/api/latest-set`
- 再按相机顺序逐路请求 `/api/sets/{set_id}/frames/{camera_id}.bmp`

这意味着每轮显示并不是一次取回全部图像，而是 `1 + N` 次串行请求。  
在 `8` 路情况下，这个成本已经非常可观。

### 3. 服务端存在额外编码成本

在 [stream_server.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_server.py#L16) 到 [stream_server.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_server.py#L55)：

- 每张图都会在 Python 里重新组装 BMP
- 包括逐行翻转、padding、header 拼接、内存复制

这对“能传”是足够的，但对“低延迟预览”不是最优路径。

### 4. Client 还要再解码一次

在 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py#L75) 到 [stream_client.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_client.py#L87)：

- 服务端先 encode 成 BMP
- client 再 decode 回 OpenCV `ndarray`

这是一条非常典型的“为了通用性牺牲预览时延”的路径。

### 5. 软同步本身会引入等待

在 [synchronization.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/synchronization.py#L82) 到 [synchronization.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/synchronization.py#L120)：

- 系统不是拿各路最新帧直接显示
- 而是等待一组满足容差窗口的对齐帧集

当前容差为 `45ms`，所以天然就不是“最低显示延迟优先”的策略。

## 对 C++ 的判断

当前阶段不建议直接转 `C++`。

理由：

1. 当前慢路径已经可以从架构上解释清楚，未到语言极限。
2. 如果串行 HTTP、重复 encode/decode、双重 sleep 这些问题不先处理，转 `C++` 只是在加速一条本身偏重的路径。
3. `C++` 会显著提高维护成本、调试复杂度和交付门槛。

只有在以下条件都成立时，才建议认真评估 `C++`：

- 已经完成协议与渲染链路瘦身
- 已经做过 profile
- 证明确实是 Python 端编码/拷贝/解码成为主要瓶颈
- 目标明确要求极低延迟、长时间稳定、多路高帧率显示

## 对多进程/多核的判断

当前阶段也不建议把多进程作为第一优先级。

理由：

1. 当前最明显的问题不是“单核不够”，而是链路结构本身有冗余。
2. 多进程会引入额外的数据交换、共享内存设计、生命周期管理和调试成本。
3. 如果显示路径仍然是 `1 + N` 串行拉图和 BMP 往返，多进程收益有限。

多进程更适合作为第二阶段选项，例如：

- 采集/同步进程
- 编码/发布进程
- viewer 渲染进程

前提是第一阶段优化已经完成，并且 profile 显示 CPU 或 GIL 已经成为明确瓶颈。

## 团队推荐的更优方案

### 第一阶段：先修现有链路中的明显低效点

优先做：

1. 去掉 viewer 中的双重 sleep
2. 降低显示路径的轮询延迟
3. 补充 profile，量化每轮显示耗时拆分

### 第二阶段：把“显示路径”和“算法路径”分离

这是本次讨论里最重要的建议。

推荐做法：

- 保留现有 `AlignedFrameBundle` 分发路径，供代码消费
- 新增单独的 preview 通道，专门服务于人眼预览

也就是说：

- `data path`：高保真、保留同步元数据、适合算法
- `preview path`：低延迟、允许丢帧、只追最新、适合显示

### 第三阶段：新增单次 preview 输出

比起当前每轮 `1 + N` 拉图，更推荐服务端直接生成：

- 一张 mosaic preview 图
- 一个专门的 `/api/preview` 或类似 endpoint

这样显示链路可以从多次请求变成一次请求。

这比直接切 `C++` 或一开始就上多进程更务实。

### 第四阶段：如果仍不够，再考虑并发与进程拆分

在 preview 通道仍不足够快时，再考虑：

- client 并发拉取
- 编码与采集分离
- 多进程/共享内存

### 第五阶段：最后再考虑 C++

只有当以上优化都完成，且 profile 仍显示瓶颈集中在 Python 端热路径时，才建议推进 C++。

## 最终判断

当前慢于 RealSense Viewer，**更可能是以下组合导致**：

- viewer 双重限速
- 串行多请求
- 服务端 BMP encode
- client BMP decode
- 软同步等待成组

因此当前最合理的路线不是立刻转 `C++`，也不是马上改成多进程，而是：

1. 修 viewer 双重 sleep
2. 建立 preview 专用低延迟通道
3. 让显示路径与数据路径分离
4. 再根据 profile 决定是否需要并发、多进程或 C++

## 建议的下一步

推荐下一步立项为：

**新增低延迟 preview mosaic 通道，并修复 viewer 当前的双重 sleep。**

这是当前性价比最高、工程风险最低、最可能立刻缩小与 RealSense Viewer 体验差距的方案。
