from __future__ import annotations

import argparse
import asyncio
import json

from sensor_proto.config import ensure_parent_dir, load_run_config
from sensor_proto.pipeline import MultiCameraRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mock or hardware multi-camera capture.")
    parser.add_argument("--config", required=True, help="Path to JSON run configuration.")
    return parser.parse_args()


async def _run(config_path: str) -> dict[str, object]:
    run_config = load_run_config(config_path)
    report = await MultiCameraRunner(run_config).run()
    payload = report.as_dict()
    if run_config.report_path:
        ensure_parent_dir(run_config.report_path)
        with open(run_config.report_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    return payload


def main() -> None:
    args = parse_args()
    payload = asyncio.run(_run(args.config))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

