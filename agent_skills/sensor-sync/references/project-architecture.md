# Project Architecture

## Purpose

This repository is a sensor performance evaluation system.

Current goals:

- compare mock and real hardware capture behavior
- evaluate throughput, latency, backpressure, isolation, and synchronization behavior
- support multiple camera families through an adapter-based architecture

Current camera kinds:

- `mock`
- `realsense`
- `orbbec`

## Main Runtime Path

Read these files first when building context:

- `src/sensor_proto/main.py`
- `src/sensor_proto/config.py`
- `src/sensor_proto/pipeline.py`
- `src/sensor_proto/synchronization.py`
- `src/sensor_proto/models.py`
- `src/sensor_proto/cameras/base.py`
- `src/sensor_proto/cameras/factory.py`
- `src/sensor_proto/cameras/mock.py`
- `src/sensor_proto/cameras/realsense.py`
- `src/sensor_proto/cameras/orbbec.py`

Runtime flow:

1. `main.py` parses `--config`, loads a `RunConfig`, runs `MultiCameraRunner`, and writes the JSON report.
2. `config.py` defines `CameraConfig`, `SyncConfig`, and `RunConfig`.
3. `pipeline.py` owns producer/consumer orchestration, queueing, latency metrics, and report assembly.
4. `synchronization.py` owns device-clock normalization and multi-camera windowed alignment.
5. `models.py` defines the shared `Frame`, `CameraMetrics`, `SyncMetrics`, and `RunReport` contracts.
6. `factory.py` selects the concrete adapter by `CameraConfig.kind`.
7. camera adapters emit `Frame` objects with payload size and timing metadata.

## Current Sync Model

Do not assume hardware sync is active by default.

Current default:

- `sync.strategy = device-clock-soft-sync`
- `sync.hardware_sync_mode = disabled`

Current sync behavior:

- preserve `host_received_at`
- preserve `device_timestamp_ms` when available
- preserve `timestamp_domain`, `frame_counter`, and `hardware_sync_group`
- normalize device clocks onto a shared host timeline
- align frames within a tolerance window
- count incomplete sets and dropped sync frames when frames fall outside the window
- report per-camera offset and drift estimates
- emit sync-health warnings for host-clock fallback, repeated sync-window drops, and severe estimated drift

Reserved but not defaulted:

- `hardware_sync_mode`
- `mock_sync_group`
- `Frame.hardware_sync_group`

These are placeholders for future mock trigger simulation or real GPIO-based sync experiments.

## Configs, Docs, and Tests

Primary config files:

- `configs/mock-session.json`
- `configs/mock-8cam-sync-stress.json`
- `configs/hw-session.example.json`
- `configs/realsense-d435i-session.json`
- `configs/realsense-2cam-session.example.json`
- `configs/realsense-4cam-session.example.json`

Primary docs:

- `docs/real-hardware-test.md`
- `docs/realsense-sync-architecture-evaluation.md`

Primary tests:

- `tests/test_pipeline.py`

Use the docs to understand intended operator flow and use the tests to understand required behavioral invariants.

## Docker Surface

Primary files:

- `docker/Dockerfile`
- `docker/compose.yaml`

Current assumptions:

- default hardware image installs both RealSense and Orbbec SDKs
- the Orbbec SDK repo may need HTTPS override if SSH access is unavailable
- mock runs are the lowest-cost validation path
- hardware runs require mounted USB devices and privileged container execution

## Architecture Boundaries

Respect these boundaries when debugging or fixing:

- adapter-specific SDK interactions stay in `src/sensor_proto/cameras/`
- shared orchestration stays in `src/sensor_proto/pipeline.py`
- synchronization logic stays in `src/sensor_proto/synchronization.py`
- shared schemas stay in `src/sensor_proto/models.py`
- configuration parsing stays in `src/sensor_proto/config.py`

If a change crosses one of these boundaries, pause and verify that the move is architectural and not a shortcut.

## Update Rule

If the project adds new camera kinds, new runtime layers, new reports, new configs, or a different sync strategy, update this reference in the same change.
