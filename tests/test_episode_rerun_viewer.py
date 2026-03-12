from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sensor_proto.episode_rerun_viewer import discover_video_streams, load_episode_metadata


class EpisodeRerunViewerTests(unittest.TestCase):
    def test_load_episode_metadata_extracts_camera_ids_and_fps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "meta").mkdir(parents=True)
            (root / "meta" / "info.json").write_text(
                json.dumps(
                    {
                        "fps": 30,
                        "total_frames": 52,
                        "features": {
                            "observation.images.rs_02": {"dtype": "video"},
                            "observation.images.rs_00": {"dtype": "video"},
                            "observation.images.rs_01": {"dtype": "image"},
                            "timestamp": {"dtype": "float32"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            metadata = load_episode_metadata(root)

        self.assertEqual(metadata.fps, 30.0)
        self.assertEqual(metadata.total_frames, 52)
        self.assertEqual(metadata.camera_ids, ["rs_00", "rs_01", "rs_02"])

    def test_discover_video_streams_requires_each_camera_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "meta").mkdir(parents=True)
            (root / "meta" / "info.json").write_text(
                json.dumps(
                    {
                        "fps": 30,
                        "total_frames": 2,
                        "features": {
                            "observation.images.rs_00": {"dtype": "video"},
                            "observation.images.rs_01": {"dtype": "video"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            video_path = root / "videos" / "observation.images.rs_00" / "chunk-000"
            video_path.mkdir(parents=True)
            (video_path / "file-000.mp4").write_bytes(b"stub")

            metadata = load_episode_metadata(root)

            with self.assertRaises(ValueError):
                discover_video_streams(metadata)


if __name__ == "__main__":
    unittest.main()
