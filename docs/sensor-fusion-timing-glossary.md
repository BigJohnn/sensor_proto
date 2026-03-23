# Sensor Fusion Timing Glossary

Date: 2026-03-23

## Goal

Capture the working terminology and timing decisions used in the current architecture discussions around:

- multi-camera rigs
- multi-sensor fusion
- software sync vs hardware sync
- cross-machine time alignment

## Core Terms

### Rig

A `rig` is a physically mounted sensor assembly with stable relative geometry.

Typical examples:

- `camera rig`: multiple cameras mounted on the same frame
- `sensor rig`: camera + IMU + LiDAR mounted on one bracket or platform
- `robot rig`: the collection of sensors mounted on a robot body

Why it matters:

- sensors in the same rig usually share stable extrinsics
- synchronization requirements are often strongest inside one rig
- a multi-rig system usually implies multiple machines, multiple frames, and more complicated fusion

### Intrinsics

Per-sensor internal calibration parameters.

For cameras, this typically includes:

- focal length
- principal point
- distortion parameters

### Extrinsics

The rigid transform between sensors or frames.

Examples:

- camera-to-camera transform
- camera-to-IMU transform
- rig-to-robot-base transform

### Timestamp Domain

The clock origin that a timestamp belongs to.

Common domains:

- device-local clock
- host system clock
- PTP-disciplined real time
- simulated clock

Timestamps from different domains must not be treated as directly comparable until explicitly normalized.

### Observation Step

A single logically coherent fused observation event used downstream.

In this repository, the current observation-step abstraction is an `AlignedFrameSet`, not a bag of unrelated per-camera frames.

### Hard Sync

Hardware-level synchronization that forces sensors to sample from a shared electrical or hardware timing event.

Examples:

- camera trigger line
- master/slave exposure signal
- shared PPS

Hard sync is about causing acquisition to happen together, not just describing timing afterward.

### Soft Sync

Software alignment performed after capture using timestamps, buffering, and matching logic.

This repository currently uses a software synchronizer based on device timestamps and host receive timestamps.

## What Hard Sync Is For

Hard sync is justified when the acceptable timing error is smaller than the uncertainty left by:

- device clock differences
- USB or driver buffering
- host scheduling jitter
- software queueing

The smaller the timing budget, the more likely hard sync is needed.

## Practical Timing Budget Heuristic

- if the system tolerates `5-20ms` level error, software sync is often enough
- if the system needs around `1-5ms`, first use disciplined host clocks plus source timestamps plus delay modeling
- if the system needs below `1ms`, especially true simultaneity, start evaluating hard sync
- if the system needs reliable event ordering during fast contact, impact, or high-speed control, hard sync becomes much more likely

## Sensor Pair Guidance

### Camera to Camera

This pair most often needs hard sync.

Use hard sync when:

- the scene has fast motion
- the baseline is large
- stereo or multiview geometry depends on near-simultaneous exposure
- precise 3D reconstruction or triangulation quality matters

Use soft sync when:

- motion is slow
- the use case is visualization, rough perception, or low-speed analysis
- small residual skew is acceptable

### Camera to IMU

This pair often benefits from stronger sync, but not always hardware trigger-level sync on day one.

Hard or near-hard sync becomes important for:

- tightly coupled VIO
- rolling-shutter correction
- fast platform motion
- high-rate inertial compensation

For lower-speed or loosely coupled fusion, disciplined clocks plus accurate timestamps may be enough.

### Camera to LiDAR

Usually start with:

- disciplined clocks
- accurate per-sensor timestamps
- delay characterization
- strong extrinsic calibration

Hard sync becomes more valuable when:

- motion distortion is significant
- precise point-to-image projection matters
- the platform moves quickly

### Camera to Tactile / Force / Contact Sensors

Usually this is not a default hard-sync problem.

Start with:

- disciplined host clocks
- precise sample timestamps
- known transport and filtering delays

Consider stronger synchronization only if the task depends on very exact ordering between:

- first contact
- force transient
- visible deformation or motion in images

### Camera to Robot State

This usually does not need hardware sync first.

More important are:

- controller timestamps
- disciplined machine clocks
- transport-delay characterization
- consistent frame transforms

Hard sync becomes relevant only for high-speed visual servoing, impact analysis, or other very tight real-time coupling.

### IMU to LiDAR

Often can work well without hardware trigger sync if:

- both are accurately timestamped
- clocks are disciplined
- calibration is solid

But higher-end fusion stacks may still benefit from tighter timing guarantees.

## Summary Matrix

| Sensor Pair | Default Starting Point | Hard Sync Likelihood |
|---|---|---|
| camera-camera | soft sync plus source timestamps | high |
| camera-IMU | disciplined clocks plus source timestamps | medium to high |
| camera-LiDAR | disciplined clocks plus delay modeling | medium |
| camera-tactile | disciplined clocks plus precise sample timestamps | low to medium |
| camera-robot-state | disciplined clocks plus controller timestamps | low to medium |
| IMU-LiDAR | disciplined clocks plus calibration | medium |

## Multi-Machine Rule

Cross-machine deployment does not automatically mean hard sync.

Handle timing in layers:

1. machine-to-machine clock alignment with `PTP`
2. sensor-native timestamp preservation
3. per-sensor or per-rig normalization
4. observation-step construction
5. downstream ROS2 transport and fusion

Hard sync is a sensor-layer decision, not a substitute for cross-machine clock discipline.

## Repository-Specific Guidance

Within this repository:

- `sensor_proto` should keep owning capture-time truth
- cross-machine time alignment should be built on disciplined machine clocks
- ROS2 should be introduced as a bridge and fusion ecosystem layer
- hard sync should be introduced only where the timing budget proves that software alignment is no longer sufficient

## Bottom Line

- not every sensor pair needs hard sync
- multi-camera rigs are the most common place where hard sync is worth the effort
- camera-IMU may also need it for high-dynamics estimation
- tactile sensors and robot state usually start with good timestamps, not hard triggers
- `PTP` and hard sync solve different layers of the timing problem
