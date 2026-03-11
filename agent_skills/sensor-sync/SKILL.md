---
name: sensor-sync
description: Diagnose bugs, strange runtime behavior, sync drift, frame drops, hardware-vs-mock mismatches, Docker/runtime issues, and architecture regressions in the sensor performance evaluation project. Use when working in this repository on mock, RealSense, Orbbec, pipeline, synchronization, config, Docker, or test changes, especially when the goal is to debug, localize, fix, and validate issues while preserving the project's OOP adapter-based design.
---

# Sensor Sync

Load [references/project-architecture.md](references/project-architecture.md) first.

Load [references/debug-playbook.md](references/debug-playbook.md) when the task involves a bug, unexpected behavior, performance regression, sync issue, or a fix.

## Workflow

1. Build context from the current codebase, not from memory.
2. Map the issue to the relevant layer:
   `config` -> `main` -> `pipeline` -> `synchronization` -> camera adapter -> Docker/runtime -> docs/tests.
3. Reproduce with the smallest configuration that still shows the problem.
   Prefer `configs/mock-session.json` first, then move to hardware configs if the issue is hardware-specific.
4. Localize before editing.
   Check whether the symptom is caused by:
   - config parsing or report writing
   - queueing and backpressure
   - sync-window logic or timestamp normalization
   - adapter-specific metadata capture
   - SDK/container/device access
5. Fix the issue in the narrowest layer that owns it.
   Preserve the adapter/factory/pipeline separation and avoid collapsing behavior into ad hoc conditionals.
6. Validate with the lowest-cost checks first.
   Run targeted tests, then a representative runtime command, then broader validation if needed.
7. If the change alters architecture, invariants, entry points, configs, or debugging guidance, update this skill in the same change.

## OOP Guardrails

- Keep camera-specific behavior inside the corresponding adapter or a clearly named integration module.
- Keep cross-camera orchestration in `pipeline.py` or `synchronization.py`, not inside individual adapters.
- Keep shared data contracts in `models.py` and config contracts in `config.py`.
- Prefer extending existing abstractions over adding one-off flags scattered across layers.
- Preserve the `create_camera_adapter()` factory boundary when adding or changing camera kinds.

## Execution Notes

- Prefer `rg` for search and read only the files needed for the current issue.
- Use existing configs, docs, and tests as the source of truth for expected behavior.
- When the symptom appears only on hardware, compare hardware output against a mock baseline before changing logic.
- When a fix changes project behavior or architecture assumptions, refresh the relevant reference file in this skill.
