# TODO

已完成事项已从此文件清理，归档结论见 `docs/` 下相关文档。

## ZMQ Cutover Remaining Work

- [ ] Measure CPU cost of server-side JPEG encode under target load.
- [ ] Validate that server-side LeRobot v3 recording output remains unchanged in structure and camera feature mapping after the ZMQ cutover.
- [ ] After cutover, simplify the codebase into explicit control-plane HTTP, data-plane ZMQ, and downstream integration boundaries.

## Post-LAN Follow-Up

- [ ] Run the `rs-07` hardware swap experiment using the current dual-machine LAN setup and compare before/after `id -> serial` mapping plus sync drift metrics.
- [ ] Determine whether the persistent positive offset follows serial `152222070161` or the original USB path / cable / controller lane.
- [ ] Run recording parity validation on the Docker-based `sensor-stream` server after the `rs-07` hardware path is characterized.
