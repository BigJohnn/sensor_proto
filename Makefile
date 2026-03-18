SHELL := /bin/bash

PYTEST_DISABLE_PLUGIN_AUTOLOAD ?= 1

.PHONY: test mock-run stream-up stream-down stream-logs stream-viewer stream-shot stream-record-10s episode-rerun episode-mosaic hikrobot-stream-up hikrobot-stream-down hikrobot-stream-logs hikrobot-stream-shot hikrobot-stream-viewer hikrobot-stream-record-10s

test:
	source $$HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTEST_DISABLE_PLUGIN_AUTOLOAD=$(PYTEST_DISABLE_PLUGIN_AUTOLOAD) PYTHONPATH=src uv run --no-project --python "$$(command -v python3)" python -m pytest

mock-run:
	source $$HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run --no-project --python "$$(command -v python3)" python -m sensor_proto.main --config configs/mock-session.json

hikrobot-stream-up:
	bash scripts/run_hikrobot_stream_service.sh

hikrobot-stream-down:
	docker compose -f docker/compose.yaml --profile hikrobot stop sensor-hikrobot-stream

hikrobot-stream-logs:
	docker compose -f docker/compose.yaml --profile hikrobot logs -f sensor-hikrobot-stream

hikrobot-stream-shot:
	bash scripts/save_latest_frames.sh

hikrobot-stream-viewer:
	bash scripts/run_stream_viewer.sh

hikrobot-stream-record-10s:
	bash scripts/record_hikrobot_stream_episode.sh 10

stream-up:
	bash scripts/run_stream_service.sh

stream-down:
	bash scripts/stop_stream_service.sh

stream-logs:
	docker compose -f docker/compose.yaml --profile hw logs -f sensor-stream

stream-viewer:
	bash scripts/run_stream_viewer.sh

stream-shot:
	bash scripts/save_latest_frames.sh

stream-record-10s:
	bash scripts/record_stream_episode.sh 10

episode-rerun:
	@if [[ -z "$(EPISODE)" ]]; then echo "Usage: make episode-rerun EPISODE=artifacts/lerobot/<episode_dir>"; exit 1; fi
	bash scripts/run_episode_rerun.sh "$(EPISODE)"

episode-mosaic:
	@if [[ -z "$(EPISODE)" ]]; then echo "Usage: make episode-mosaic EPISODE=artifacts/lerobot/<episode_dir> [OUTPUT=/path/to/output.mp4]"; exit 1; fi
	if [[ -n "$(OUTPUT)" ]]; then \
		bash scripts/render_episode_mosaic.sh "$(EPISODE)" --output "$(OUTPUT)"; \
	else \
		bash scripts/render_episode_mosaic.sh "$(EPISODE)"; \
	fi
