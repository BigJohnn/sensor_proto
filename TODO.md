# TODO

## 2026-03-12

- [x] Support recording synchronized camera streams and save them in LeRobot v3 format.

### ZMQ Multipart Cutover

Scope for this phase: `sensor_proto` only.

- [ ] Keep all implementation tasks in this section limited to `sensor_proto`.
- [ ] Defer LeRobot-side robot/client integration work until the `sensor_proto` transport contract is stable.

#### 1. Protocol And Boundaries

- [ ] Freeze the transport direction: keep HTTP for control-plane endpoints (`/`, `/api/health`, `/api/preview.jpg`) and move aligned-set data-plane delivery to ZMQ multipart.
- [ ] Define one transport invariant: one ZMQ message must represent exactly one `AlignedFrameSet`; never split cameras into independently fetched streams.
- [ ] Write a versioned wire contract for multipart messages with:
  - [ ] envelope metadata (`protocol_version`, `set_id`, `reference_camera_id`, `reference_timestamp_s`, `skew_ms`)
  - [ ] per-camera metadata (`camera_id`, `device_timestamp_ms`, `offset_ms`, `width`, `height`, `pixel_format`)
  - [ ] payload encoding (`jpeg` initially, optional raw/BMP only for debug)
- [ ] Choose serialization for metadata (`msgpack` preferred, JSON acceptable only if kept small) and document forward/backward compatibility rules.
- [ ] Define consumer behavior for dropped/late frames: publisher sends latest complete aligned set only; subscriber treats each multipart message as atomic and never reassembles across messages.

#### 2. Server-Side Refactor

- [ ] Introduce a transport abstraction so `SynchronizedStreamRunner` publishes aligned sets through a sink interface instead of calling HTTP-specific repository code directly.
- [ ] Extract HTTP-specific code out of [stream_main.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_main.py) into a dedicated transport module boundary.
- [ ] Add `sensor_proto.transport.zmq` package with:
  - [ ] publisher lifecycle
  - [ ] multipart encoder
  - [ ] socket config
  - [ ] protocol constants
- [ ] Implement a ZMQ publisher that emits one multipart message per aligned set.
- [ ] Enable `CONFLATE` or equivalent latest-only behavior only if it preserves whole-message atomicity for subscribers.
- [ ] Keep preview generation decoupled from ZMQ publishing so preview failures do not block aligned-set transport.
- [ ] Preserve current recording path as a separate server-side sink; do not couple LeRobot dataset writing to the ZMQ publisher.
- [ ] Keep recording attached to the in-memory `AlignedFrameSet` path after sync and before transport, not to any transport callback side effect.
- [ ] Ensure recording continues to consume original frame buffers from server memory, not JPEG/ZMQ payloads decoded back from the wire.
- [ ] Decide whether recording needs its own queue/thread boundary so slow dataset writes cannot stall ZMQ publishing.

#### 3. Client-Side Refactor

- [ ] Add a ZMQ aligned-set client that receives one multipart message and returns one in-memory aligned bundle.
- [ ] Keep the client API centered on `get_next_aligned_set()` or `recv_aligned_set()`, not per-camera reads.
- [ ] Add local decode helpers for multipart image payloads and validate camera ordering against metadata.
- [ ] Decide whether the ZMQ client exposes blocking receive only or also latest-only polling with timeout.
- [ ] Keep the current HTTP client temporarily for control-plane access (`health`, `preview`) during migration.
- [ ] Update viewer and snapshot CLI to consume ZMQ data-plane frames while optionally still reading preview from HTTP.

#### 4. Config And Entrypoints

- [ ] Extend run config with an explicit transport section, e.g.:
  - [ ] `transport.kind = "zmq"`
  - [ ] `transport.bind_host`
  - [ ] `transport.port`
  - [ ] `transport.topic` or stream name if needed
  - [ ] `transport.jpeg_quality`
  - [ ] `transport.max_queue`
- [ ] Keep stream config for HTTP preview/control-plane settings only; stop overloading it as the main data-plane config.
- [ ] Add a new app entrypoint for ZMQ stream serving instead of overloading the current HTTP-only semantics.
- [ ] Decide whether `make stream-up` should start both HTTP preview/control-plane and ZMQ data-plane in one process or two cooperating services.

#### 5. Downstream Compatibility Contract

- [ ] Keep downstream-specific naming out of core capture/sync code and transport internals.
- [ ] Document the fields downstream consumers can rely on (`set_id`, `reference_timestamp_s`, `offsets_ms`, per-camera metadata, image encoding).
- [ ] Ensure the data-plane contract stays aligned-set atomic so downstream systems can map one received message to one observation step.
- [ ] Preserve stable `camera_id` semantics across runtime config generation and transport publishing.
- [ ] Preserve the server-side recording invariant: one recorded dataset step must come from exactly one aligned set.

#### 6. Tests

- [ ] Add unit tests for multipart metadata encoding/decoding.
- [ ] Add unit tests for multipart image payload encoding/decoding.
- [ ] Add a transport invariant test: one published aligned set is decoded as one aligned set with matching `set_id` and camera list.
- [ ] Add a latest-only/backpressure test so slow consumers do not observe mixed-camera sets.
- [ ] Add failure-path tests for malformed multipart messages, missing camera parts, bad payload sizes, and unsupported pixel formats.
- [ ] Add integration tests for publisher/subscriber round-trip on localhost.
- [ ] Keep current HTTP preview and health tests passing during the migration.
- [ ] Add tests that recording still writes one dataset step per aligned set after the transport refactor.
- [ ] Add tests that recording input remains raw server-side frame data rather than transport-encoded JPEG payloads.

#### 7. Validation

- [ ] Benchmark current HTTP BMP path vs ZMQ multipart JPEG path on localhost.
- [ ] Benchmark end-to-end LAN throughput with representative camera counts and resolutions.
- [ ] Measure CPU cost of server-side JPEG encode under target load.
- [ ] Verify preview path still behaves acceptably while ZMQ publishing is active.
- [ ] Run the smallest mock config first, then a representative RealSense hardware config.
- [ ] Validate that `set_id`, `reference_timestamp_s`, `offsets_ms`, and per-camera device timestamps remain stable across the new transport.
- [ ] Validate that server-side LeRobot v3 recording output remains unchanged in structure and camera feature mapping after the ZMQ cutover.

#### 8. Cutover And Cleanup

- [ ] Ship ZMQ as an opt-in transport first; do not delete the HTTP data path before parity is verified.
- [ ] Migrate viewer and capture tooling to the new client once parity is reached.
- [ ] Update docs and quickstart commands for dual-machine setup.
- [ ] Decide whether to keep `/api/latest-set` and per-frame BMP endpoints for debugging only or remove them after the ZMQ path is proven.
- [ ] After cutover, simplify the codebase by separating:
  - [ ] control-plane HTTP
  - [ ] data-plane ZMQ
  - [ ] downstream integration boundaries
