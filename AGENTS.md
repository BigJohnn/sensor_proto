# Repository Guidelines

## Preferred Skill

For debugging, strange runtime behavior, sync drift, frame drops, hardware-vs-mock mismatches, Docker/runtime issues, or architecture-preserving fixes in this repository, prefer using `$sensor-sync`.

The skill lives at [agent_skills/sensor-sync/SKILL.md](/home/hanyu/Codes/sensor_proto/agent_skills/sensor-sync/SKILL.md) and is the project-specific guide for:

- understanding the current sensor evaluation architecture
- localizing issues by layer
- preserving the adapter/factory/pipeline OOP boundaries
- validating fixes with the project's standard commands

## Project Structure & Module Organization

This repository is a sensor performance evaluation system with mock and real-hardware capture paths. Keep repository-level guidance files such as [`AGENTS.md`](/home/hanyu/Codes/sensor_proto/AGENTS.md) at the root.

Keep code organized by responsibility and avoid mixing runtime code with container assets:

- `src/sensor_proto/` for runtime code
- `src/sensor_proto/cameras/` for camera adapters and adapter factory wiring
- `tests/` for automated tests
- `configs/` for mock and hardware session configs
- `docker/` for image build and runtime definitions
- `docs/` for runbooks and architecture notes
- `agent_skills/` for project-local Codex skills

## Build, Test, and Development Commands

Use these commands as the stable developer entry points:

- `make test` to run the automated test suite, including stream service, host client, CLI, and viewer layout coverage
- `make mock-run` to run the mock capture flow
- `make stream-up` to start the hardware stream service with automatic camera detection and runtime config generation
- `make stream-viewer` to open the host-side OpenCV multi-camera viewer
- `make stream-shot` to fetch the latest aligned frame set and save per-camera PNGs
- `make stream-record-10s` to record one LeRobot v3 episode from the currently connected RealSense cameras, stopping after the default target of 300 aligned frame sets
- `make episode-rerun EPISODE=artifacts/lerobot/<episode_dir>` to visualize a recorded LeRobot episode on the host using rerun-sdk
- `make stream-down` to stop the hardware stream service
- `make stream-logs` to follow the hardware stream service logs
- `docker compose -f docker/compose.yaml config` to validate compose config
- `docker compose -f docker/compose.yaml --profile hw config` to validate the hardware profile
- `DOCKER_BUILDKIT=1 docker compose -f docker/compose.yaml --profile hw build sensor-hw` to build the hardware image
- `docker compose -f docker/compose.yaml run --rm sensor-mock` to run the mock container flow
- `docker compose -f docker/compose.yaml --profile hw up sensor-stream` to auto-detect connected RealSense devices, generate the runtime stream config, and run the synchronized hardware stream service plus host dashboard on `http://127.0.0.1:8787`

Update this guide in the same change that adds or changes developer commands.

## Coding Style & Naming Conventions

Prefer small, single-purpose modules and explicit names. Use lowercase snake_case for files and directories unless the language ecosystem strongly prefers another convention. Keep indentation consistent within a file; use 4 spaces for Python and 2 spaces for YAML, JSON, and Markdown examples.

Do not commit generated artifacts, local secrets, or large binaries. Keep Docker-related filenames descriptive, for example `docker/Dockerfile.dev` or `docker/compose.local.yaml`.

## Testing Guidelines

Add automated tests alongside new functionality instead of deferring coverage. Prefer extending [tests/test_pipeline.py](/home/hanyu/Codes/sensor_proto/tests/test_pipeline.py) for pipeline, backpressure, isolation, and synchronization behavior. Mirror the source layout under `tests/` when adding new modules.

For hardware-sensitive fixes, start with mock coverage, then run the smallest representative hardware validation.

## Commit & Pull Request Guidelines

This workspace snapshot does not include `.git` metadata, so local commit history is unavailable. Until a project-specific convention is established, use short imperative commit messages with a clear scope, for example `feat: add docker base image` or `fix: correct sensor config path`.

Pull requests should describe the change, note any setup or runtime impact, link related issues, and include logs or screenshots when behavior changes are user-visible.
