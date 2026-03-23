# PTP Multi-Machine Time Synchronization Plan

Date: 2026-03-23

## Goal

Provide a production-oriented time synchronization plan for:

- multi-machine deployment
- camera + IMU + LiDAR + robot-state fusion
- `sensor_proto` capture nodes plus ROS2 bridge / ROS2-native nodes

The intent is to make timestamps across machines meaningfully comparable before downstream fusion.

## Core Principle

- `PTP` aligns machine clocks.
- `sensor_proto` preserves capture-time truth.
- ROS2 transports timestamps and metadata to downstream nodes.

`PTP` does not replace sensor-side timestamp modeling or `sensor_proto` synchronization logic.

## Scope

This is the recommended **formal production path**.

It assumes:

- wired Ethernet
- NICs with hardware timestamping support
- Linux hosts
- ROS2 used as a downstream interoperability layer, not as the capture-time truth source

## Target Outcome

After rollout:

- all participating machines share one disciplined wall clock
- each machine keeps `CLOCK_REALTIME` aligned to a PTP-disciplined NIC hardware clock
- `sensor_proto` continues to preserve `device_timestamp_ms`, `host_received_at`, and aligned-set timing semantics
- ROS2 messages use disciplined timestamps without erasing source timing metadata

## Recommended Topology

- 1 machine acts as `Grandmaster (GM)` or is attached to a better upstream time source
- all capture, fusion, and control machines are on the same wired PTP-capable network
- prefer switches that support `Boundary Clock (BC)` or `Transparent Clock (TC)`
- avoid Wi-Fi for the PTP path

Example layout:

- Machine A: camera rig running `sensor_proto`
- Machine B: IMU / LiDAR rig with ROS2-native publishers
- Machine C: robot-control / state publisher
- Machine D: fusion / planning / recording

## Hardware Requirements

Each machine should provide at least:

- a NIC that supports hardware timestamping
- a wired connection into the PTP domain

Check capability on each host:

```bash
ethtool -T <iface>
```

Expected capabilities include:

- `hardware-transmit`
- `hardware-receive`
- `hardware-raw-clock`

If these are missing, the host is not suitable for the formal production path and will likely fall back to software-timestamp behavior.

## Software Stack

Install the base tooling on each Ubuntu 22.04 host:

```bash
sudo apt-get update
sudo apt-get install -y linuxptp ethtool
```

Key tools:

- `ptp4l`: synchronizes the NIC PHC using PTP
- `phc2sys`: synchronizes the system clock to the PHC
- `pmc`: queries PTP state and health

## Time Model

Use this chain of authority:

1. `PTP` synchronizes each NIC PHC
2. `phc2sys` synchronizes each machine's `CLOCK_REALTIME` from the PHC
3. `sensor_proto` preserves sensor-native timestamps and host receive timestamps
4. ROS2 messages publish disciplined observation timestamps plus source timing metadata

This keeps machine time, host time, and device time conceptually separate.

## Recommended `ptp4l` Configuration

Create `/etc/linuxptp/ptp4l.conf`:

```ini
[global]
twoStepFlag             1
time_stamping           hardware
network_transport       UDPv4
delay_mechanism         E2E
tx_timestamp_timeout    20
summary_interval        0
logging_level           6
slaveOnly               0
domainNumber            42
uds_address             /var/run/ptp4l
```

Notes:

- Use `E2E` by default.
- If the switch fabric is known-good for peer delay, evaluate `P2P`.
- Keep `domainNumber` explicit so the timing domain is isolated from unrelated PTP traffic.

## Grandmaster Configuration

If no GPS or external clock source is available yet, designate one stable wired machine as the temporary grandmaster.

On that machine, extend the config with:

```ini
priority1               10
priority2               10
clockClass              128
clockAccuracy           0x22
offsetScaledLogVariance 0x436A
```

Start services manually for validation:

```bash
sudo ptp4l -i <iface> -f /etc/linuxptp/ptp4l.conf -m
sudo phc2sys -s <iface> -c CLOCK_REALTIME -O 0 -m
```

## Slave Configuration

On all other participating machines, use lower priority:

```ini
priority1               128
priority2               128
```

Start:

```bash
sudo ptp4l -i <iface> -f /etc/linuxptp/ptp4l.conf -m
sudo phc2sys -s <iface> -c CLOCK_REALTIME -O 0 -m
```

Meaning:

- `ptp4l` disciplines the NIC PHC
- `phc2sys` disciplines the Linux system clock from that PHC

This is required because most application code, logs, ROS2 nodes, and file timestamps depend on the system clock rather than the raw PHC.

## systemd Rollout

Prefer systemd-managed services instead of shell sessions.

Example `ptp4l@.service`:

```ini
[Unit]
Description=PTP4L on %I
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/sbin/ptp4l -i %I -f /etc/linuxptp/ptp4l.conf -m
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Example `phc2sys@.service`:

```ini
[Unit]
Description=PHC2SYS on %I
After=ptp4l@%i.service
Requires=ptp4l@%i.service

[Service]
ExecStart=/usr/sbin/phc2sys -s %I -c CLOCK_REALTIME -O 0 -m
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable on each host:

```bash
sudo systemctl enable --now ptp4l@<iface>
sudo systemctl enable --now phc2sys@<iface>
```

## Validation Commands

Check PTP state:

```bash
pmc -u -b 0 'GET TIME_STATUS_NP'
pmc -u -b 0 'GET PORT_DATA_SET'
```

Follow logs:

```bash
journalctl -u ptp4l@<iface> -f
journalctl -u phc2sys@<iface> -f
```

Important fields:

- `master_offset`
- `gmPresent`
- `stepsRemoved`
- `portState`

## Acceptance Targets

Recommended targets for the formal path:

- production goal: steady-state `master_offset` within `+/-100us`
- strong result: `+/-10us` to `+/-50us`
- warning zone: persistent millisecond-scale offsets

Millisecond-scale offsets usually indicate one or more of:

- switch limitations
- NIC/driver limitations
- wrong interface selection
- software timestamping fallback
- network-path instability

## Integration With `sensor_proto`

`PTP` should strengthen the host-clock layer, not replace `sensor_proto` timing semantics.

Recommended rules:

- keep preserving `device_timestamp_ms`
- keep preserving `host_received_at`
- keep publishing aligned-set-level `reference_timestamp_s`
- do not collapse all timing semantics into a single ROS2 header timestamp

Suggested future observability fields:

- `ptp.gm_present`
- `ptp.port_state`
- `ptp.master_offset_ns`
- `ptp.clock_domain = ptp-disciplined-realtime`

These can be emitted into health, metrics, or structured logs.

## Integration With ROS2 Bridge

The ROS2 bridge should:

- publish `header.stamp` using the disciplined observation time
- preserve source timing metadata in custom message fields
- avoid rewriting source time semantics as if ROS2 created them

Recommended bridge metadata:

- `clock_domain`
- `source_reference_timestamp_s`
- `per_sensor.device_timestamp_ms`
- optional host receive timestamps where useful for diagnostics

## ROS2 Node Requirements

All ROS2-native sensor nodes participating in fusion should also run on PTP-disciplined hosts.

That includes:

- IMU publishers
- LiDAR publishers
- robot state publishers
- fusion nodes
- recording / bagging nodes

Fusion should align using disciplined timestamps and source metadata, not message arrival order.

## Deployment Order

Use this rollout order:

1. deploy `ptp4l + phc2sys` on all hosts
2. validate `master_offset` and port roles
3. start `sensor_proto` capture nodes
4. start ROS2-native IMU / LiDAR / robot-state publishers
5. start the ROS2 bridge
6. run cross-machine record / replay / fusion validation

## Common Failure Modes

- running the PTP path over Wi-Fi
- using NICs without hardware timestamp support
- assuming PTP solves camera exposure simultaneity
- running PTP only inside containers and not disciplining the host clock
- mixing simulation time and real capture time in the same deployment
- relying on ROS2 message arrival order instead of disciplined observation time

## Important Boundary

`PTP` solves:

- machine-to-machine clock alignment
- better comparability of host timestamps across machines

`PTP` does not solve:

- sensor-native clock drift by itself
- camera trigger simultaneity
- USB bus jitter
- capture-pipeline backpressure
- alignment semantics for a multi-camera observation step

Those remain the responsibility of sensor drivers and `sensor_proto`.

## Summary

Use this production mental model:

- `PTP` aligns the distributed clock foundation
- `sensor_proto` establishes capture truth
- ROS2 bridge publishes that truth into the distributed compute graph
- fusion operates on disciplined time, not arrival time
