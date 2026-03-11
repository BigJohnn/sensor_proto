# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a minimal scaffold. The only committed directory is [`docker/`](/home/hanyu/Codes/sensor_proto/docker), which should hold container definitions and related setup assets. Keep repository-level guidance files such as [`AGENTS.md`](/home/hanyu/Codes/sensor_proto/AGENTS.md) at the root.

When application code is added, keep it organized by responsibility and avoid mixing runtime code with container assets. A practical default is:

- `src/` for implementation
- `tests/` for automated tests
- `docker/` for container build and runtime files
- `docs/` for design notes or operational runbooks

## Build, Test, and Development Commands

No build, lint, or test commands are committed yet. If you introduce a toolchain, expose the main entry points through documented commands and keep them stable.

Examples to add once supported:

- `docker build -f docker/Dockerfile .` to build the local image
- `make test` or `pytest` to run the test suite
- `make lint` or `ruff check .` to run static checks

Update this guide in the same change that adds new developer commands.

## Coding Style & Naming Conventions

Prefer small, single-purpose modules and explicit names. Use lowercase snake_case for files and directories unless the language ecosystem strongly prefers another convention. Keep indentation consistent within a file; use 4 spaces for Python and 2 spaces for YAML, JSON, and Markdown examples.

Do not commit generated artifacts, local secrets, or large binaries. Keep Docker-related filenames descriptive, for example `docker/Dockerfile.dev` or `docker/compose.local.yaml`.

## Testing Guidelines

There is no test framework configured yet. Add automated tests alongside new functionality instead of deferring coverage. Mirror the source layout under `tests/` and use names that make intent obvious, such as `test_sensor_parser.py` or `sensor_parser.test.ts`.

## Commit & Pull Request Guidelines

This workspace snapshot does not include `.git` metadata, so local commit history is unavailable. Until a project-specific convention is established, use short imperative commit messages with a clear scope, for example `feat: add docker base image` or `fix: correct sensor config path`.

Pull requests should describe the change, note any setup or runtime impact, link related issues, and include logs or screenshots when behavior changes are user-visible.
