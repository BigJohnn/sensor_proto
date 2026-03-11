# Debug Playbook

## Triage Order

Follow this order unless there is a strong reason not to:

1. reproduce
2. isolate the owning layer
3. inspect the narrowest relevant code path
4. patch the owning layer
5. validate with focused tests and a representative runtime command
6. update docs or this skill if the fix changes project knowledge

## Reproduction Ladder

Start from the cheapest reproduction:

1. unit or integration test in `tests/test_pipeline.py`
2. `PYTHONPATH=src python3 -m sensor_proto.main --config configs/mock-session.json`
3. single-device hardware config such as `configs/realsense-d435i-session.json`
4. multi-device hardware config copied from `configs/hw-session.example.json`
5. containerized reproduction through `docker compose`

Do not jump straight to multi-camera hardware runs if mock or single-camera runs can reveal the issue.

## Symptom Mapping

### Config or report problems

Look at:

- `src/sensor_proto/main.py`
- `src/sensor_proto/config.py`
- `src/sensor_proto/models.py`

Typical signs:

- config keys ignored
- invalid defaults
- report JSON missing fields
- output schema drift after refactors

### Queueing, latency, and drop problems

Look at:

- `src/sensor_proto/pipeline.py`
- `tests/test_pipeline.py`

Typical signs:

- drops increase after `processing_delay_ms`
- one camera starves others
- failure isolation regresses
- latency metrics no longer track the right timestamp

### Sync, skew, and timestamp problems

Look at:

- `src/sensor_proto/synchronization.py`
- `src/sensor_proto/models.py`
- adapter metadata capture in `src/sensor_proto/cameras/`
- `docs/realsense-sync-architecture-evaluation.md`

Typical signs:

- `sync.aligned_sets` collapses
- `sync.incomplete_sets` spikes
- `sync.max_skew_ms` grows unexpectedly
- `sync.per_camera.*.avg_offset_ms` or `drift_ppm` jumps unexpectedly
- `sync.warnings` starts emitting repeated drop or drift alerts
- device timestamp metadata is absent or inconsistent

### Adapter-specific hardware problems

Look at:

- `src/sensor_proto/cameras/realsense.py`
- `src/sensor_proto/cameras/orbbec.py`
- `src/sensor_proto/cameras/mock.py`
- `src/sensor_proto/cameras/factory.py`

Typical signs:

- one SDK fails while others still work
- device enumeration issues
- frame metadata missing from one adapter only
- runtime issue appears only for one `kind`

### Container or environment problems

Look at:

- `docker/Dockerfile`
- `docker/compose.yaml`
- `docs/real-hardware-test.md`

Typical signs:

- SDK import failures
- repository clone failures during image build
- USB devices visible on host but not in container
- mock works locally but not in container

## Fix Strategy

Prefer these patterns:

- extend `Frame`, `SyncMetrics`, or config dataclasses when the data contract changes
- add behavior to the owning adapter for SDK-specific quirks
- add behavior to `FrameSynchronizer` for cross-camera sync logic
- add tests in `tests/test_pipeline.py` for regressions in queueing, failure isolation, or synchronization

Avoid these patterns:

- embedding camera-specific logic in `pipeline.py`
- duplicating report fields across multiple layers
- fixing a hardware-only symptom by silently weakening mock expectations
- burying architecture changes in docs without updating the code-facing references

## Validation Commands

Use the smallest relevant set:

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_pipeline.py
```

```bash
PYTHONPATH=src python3 -m sensor_proto.main --config configs/mock-session.json
```

```bash
PYTHONPATH=src python3 -m sensor_proto.main --config configs/mock-8cam-sync-stress.json
```

```bash
docker compose -f docker/compose.yaml config
```

```bash
docker compose -f docker/compose.yaml --profile hw config
```

For hardware-specific fixes, add the smallest hardware run that proves the fix.

## OOP Review Checklist

Before finalizing a fix, verify:

- the change did not bypass `CameraAdapter` or `create_camera_adapter()`
- shared contracts are still centralized
- sync logic is still separated from adapter logic
- new configuration is parsed in one place
- tests cover the changed behavior at the lowest useful level

## Skill Maintenance Rule

Update this skill when any of these change:

- file layout under `src/sensor_proto/`
- main runtime flow
- report schema
- sync strategy or hardware sync policy
- Docker build or run workflow
- standard validation commands

Keep the skill current in the same change rather than leaving a stale skill behind.
