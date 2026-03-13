# TODO

## 2026-03-12

- [x] Support recording synchronized camera streams and save them in LeRobot v3 format.

### Recording Stabilization And Replay Follow-Up

- [x] Move LeRobot dataset writes off the main aligned-set consumer path via `RecordingSink` with a dedicated worker and bounded queue.
- [x] Keep the stream service alive when the recording queue overflows, while surfacing degraded recording status through the health payload and process exit code.
- [x] Prefer LeRobot streaming video encoding over per-frame image staging so recording throughput is not dominated by temporary PNG writes.
- [x] Persist aligned timestamp sidecar data for recorded episodes so host-side replay can preserve the original capture cadence.
- [x] Update the episode rerun tooling to use the recorded aligned timeline when available and fall back to decoded video timestamps otherwise.
- [x] Harden host-side replay compatibility by avoiding AV1-only assumptions and using a time-based Rerun timeline.

### ZMQ Multipart Cutover

Scope for this phase: `sensor_proto` only.

- [x] Keep all implementation tasks in this section limited to `sensor_proto`.
- [x] Defer LeRobot-side robot/client integration work until the `sensor_proto` transport contract is stable.

#### Status Snapshot

- [x] Phase 0 contract freeze is documented in [docs/zmq-transport-contract.md](/home/corenetic/Code/sensor_proto/docs/zmq-transport-contract.md).
- [ ] Current implementation still serves aligned-set data primarily over HTTP `/api/latest-set`.
- [ ] Current focus: land the smallest ZMQ vertical slice without changing recording semantics.

#### Phase 0. Contract Freeze

- [x] Freeze the transport split: HTTP stays control-plane only (`/`, `/api/health`, `/api/preview.jpg`); ZMQ multipart becomes aligned-set data-plane only.
- [x] Freeze the atomicity invariant: one ZMQ message represents exactly one `AlignedFrameSet`; subscribers must never reassemble cameras across messages.
- [x] Freeze metadata serialization and compatibility rules.
  - [x] Select UTF-8 `json` metadata for v1.
  - [x] Ignore unknown fields within the same protocol major version.
  - [x] Bump `protocol_version` on breaking layout or semantic changes.
- [x] Freeze the v1 multipart wire layout.
  - [x] Envelope metadata includes `protocol_version`, `set_id`, `reference_camera_id`, `reference_timestamp_s`, `skew_ms`, and ordered camera list.
  - [x] Per-camera metadata includes `camera_id`, `device_timestamp_ms`, `offset_ms`, `width`, `height`, `pixel_format`, and payload encoding details.
  - [x] Image payload encoding is `jpeg` in v1.
- [x] Freeze publisher/subscriber drop semantics.
  - [x] Publisher may drop whole aligned sets under backpressure, but never split a set.
  - [x] Subscriber treats each multipart message as atomic and accepts `set_id` gaps as whole-set loss.
- [x] Freeze downstream-visible field semantics.
  - [x] Stable fields: `set_id`, `reference_timestamp_s`, `offsets_ms`, per-camera metadata, and image encoding.
  - [x] `camera_id` remains stable for the generated runtime config session.
  - [x] One received message maps to one downstream observation step.
- [x] Freeze recording-path invariants before transport implementation.
  - [x] Recording stays attached to the in-memory `AlignedFrameSet` immediately after sync and before transport.
  - [x] One recorded dataset step must come from exactly one aligned set.
  - [x] Recording must continue to use raw server-side frame buffers, not transport-decoded JPEG payloads.

#### Phase 1. Minimal Server Vertical Slice

- [x] Introduce a server-side transport sink abstraction around complete aligned sets.
- [ ] Extract HTTP-specific aligned-set publishing responsibilities out of [stream_main.py](/home/corenetic/Code/sensor_proto/src/sensor_proto/stream_main.py).
- [ ] Add `sensor_proto.transport.zmq` package skeleton.
  - [ ] `protocol.py`
  - [ ] `encoding.py`
  - [ ] `publisher.py`
  - [ ] `config.py` if transport-specific parsing is needed
- [ ] Implement multipart encoder from the frozen contract.
- [ ] Implement ZMQ publisher lifecycle and bind configuration.
- [ ] Choose a latest-only/backpressure strategy that preserves whole-message atomicity.
- [ ] Keep preview generation decoupled from ZMQ publishing.
- [ ] Keep recording as a separate server-side sink.

#### Phase 2. Invariants And Round-Trip Tests

- [ ] Add unit tests for metadata encoding/decoding, including unknown-field compatibility.
- [ ] Add unit tests for image payload encoding/decoding and metadata/payload count mismatches.
- [ ] Add an aligned-set atomicity test: one published set decodes as exactly one aligned set.
- [ ] Add a latest-only/backpressure test with a slow consumer and whole-set drops only.
- [ ] Add malformed-message tests: missing camera parts, bad payload sizes, unsupported encodings, invalid protocol version, malformed metadata blob.
- [ ] Add localhost publisher/subscriber integration tests independent of HTTP preview endpoints.
- [ ] Keep existing HTTP preview and health tests passing during the migration.
- [ ] Add recording-invariant regression tests so transport changes cannot move recording behind wire decode.

#### Phase 3. Config And Minimal Client

- [ ] Extend run config with an explicit `transport` section.
  - [ ] `transport.kind = "zmq"`
  - [ ] `transport.bind_host`
  - [ ] `transport.port`
  - [ ] `transport.topic` if needed
  - [ ] `transport.jpeg_quality`
  - [ ] `transport.max_queue`
- [ ] Keep `stream` config for HTTP preview/control-plane settings only.
- [ ] Add a ZMQ stream-serving entrypoint instead of overloading the current HTTP-only semantics.
- [ ] Decide whether `make stream-up` runs HTTP preview/control-plane and ZMQ data-plane in one process or two cooperating services.
- [ ] Add a ZMQ aligned-set client centered on `recv_aligned_set()` / `get_next_aligned_set()`.
- [ ] Add local decode helpers for multipart image payloads and camera-order validation.
- [ ] Decide whether the client supports blocking receive only or also latest-only polling with timeout.
- [ ] Keep the current HTTP client temporarily for `health` and `preview`.

#### Phase 4. Tooling Migration

- [ ] Update viewer and snapshot CLI to consume ZMQ data-plane frames while optionally still reading preview from HTTP.
- [ ] Migrate viewer and capture tooling to the new client once parity is reached.

#### Phase 5. Cutover Gate And Cleanup

- [ ] Ship ZMQ as an opt-in transport first; do not delete the HTTP data path before parity is verified.
- [ ] Benchmark current HTTP BMP path vs ZMQ multipart JPEG path on localhost.
- [ ] Benchmark end-to-end LAN throughput with representative camera counts and resolutions.
- [ ] Measure CPU cost of server-side JPEG encode under target load.
- [ ] Verify preview path still behaves acceptably while ZMQ publishing is active.
- [ ] Run the smallest mock config first, then a representative RealSense hardware config.
- [ ] Validate that `set_id`, `reference_timestamp_s`, `offsets_ms`, and per-camera device timestamps remain stable across the new transport.
- [ ] Validate that server-side LeRobot v3 recording output remains unchanged in structure and camera feature mapping after the ZMQ cutover.
- [ ] Update docs and quickstart commands for dual-machine setup.
- [ ] Decide whether to keep `/api/latest-set` and per-frame BMP endpoints for debugging only or remove them after the ZMQ path is proven.
- [ ] After cutover, simplify the codebase into explicit control-plane HTTP, data-plane ZMQ, and downstream integration boundaries.
