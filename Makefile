PYTEST_DISABLE_PLUGIN_AUTOLOAD ?= 1

.PHONY: test mock-run

test:
	PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=$(PYTEST_DISABLE_PLUGIN_AUTOLOAD) python3 -m pytest

mock-run:
	PYTHONPATH=src python3 -m sensor_proto.main --config configs/mock-session.json

