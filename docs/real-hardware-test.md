# Real Hardware Test Guide

## 1. Host preparation

1. Confirm Docker Engine and Compose are available.
2. By default the hardware image installs both `pyrealsense2` and `pyorbbecsdk`. If Orbbec support stays enabled, start an SSH agent and load a key that can access `git@github.com:orbbec/pyorbbecsdk.git`.
3. Connect each camera to a separate USB 3 controller where possible. Check the topology with `lsusb -t`.

## 2. Build and run mock first

```bash
docker compose -f docker/compose.yaml build sensor-mock
docker compose -f docker/compose.yaml run --rm sensor-mock
```

The mock run writes `artifacts/mock-report.json`. Use it to validate queue sizing, processing delay, and the `sync` section before touching hardware.

## 3. Prepare the hardware config

Copy `configs/hw-session.example.json` to `configs/hw-session.json` and fill in the actual serial numbers for the D435i, D455, and Bolt.

Leave `sync.hardware_sync_mode` as `disabled` for the current software-sync phase unless you are explicitly running a later hardware-trigger experiment.

## 4. Build the hardware image

```bash
DOCKER_BUILDKIT=1 docker compose -f docker/compose.yaml --profile hw build sensor-hw
```

This build enables both SDKs by default.

If you only need one camera stack, override the build args through environment variables:

```bash
SENSOR_HW_INSTALL_ORBBEC=0 \
DOCKER_BUILDKIT=1 docker compose -f docker/compose.yaml --profile hw build sensor-hw
```

```bash
SENSOR_HW_INSTALL_REALSENSE=0 \
DOCKER_BUILDKIT=1 docker compose -f docker/compose.yaml --profile hw build sensor-hw
```

You can also point Orbbec to a different repository:

```bash
SENSOR_HW_PYORBBECSDK_REPO=git@github.com:your-org/pyorbbecsdk.git \
DOCKER_BUILDKIT=1 docker compose -f docker/compose.yaml --profile hw build sensor-hw
```

## 5. Run the hardware session

```bash
docker compose -f docker/compose.yaml --profile hw run --rm sensor-hw --config configs/hw-session.json
```

The container runs privileged and mounts `/dev/bus/usb` plus `/run/udev` so both SDKs can enumerate devices.

## 6. What to watch

- Frame drops: increase `queue_size` or lower camera FPS if drops spike.
- Latency: `avg_latency_ms` and `max_latency_ms` should stay stable across all cameras.
- Sync health: watch `sync.aligned_sets`, `sync.incomplete_sets`, `sync.dropped_frames`, and `sync.max_skew_ms`.
- Isolation: unplug one camera and confirm the remaining streams keep processing.
