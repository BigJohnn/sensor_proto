from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sensor_proto.episode_rerun_viewer import (
    EpisodeMetadata,
    discover_video_streams,
    load_episode_metadata,
    resolve_timeline_timestamps_ns,
)


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
            (root / "meta" / "aligned_timestamps.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "timeline": "aligned_reference_timestamp_s",
                        "unit": "seconds_from_episode_start",
                        "frame_count": 52,
                        "timestamps_s": [index * 0.05 for index in range(52)],
                    }
                ),
                encoding="utf-8",
            )

            metadata = load_episode_metadata(root)

        self.assertEqual(metadata.fps, 30.0)
        self.assertEqual(metadata.total_frames, 52)
        self.assertEqual(metadata.camera_ids, ["rs_00", "rs_01", "rs_02"])
        self.assertEqual(metadata.aligned_timestamps_s[:3], [0.0, 0.05, 0.1])

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

    def test_resolve_timeline_timestamps_prefers_aligned_sidecar(self) -> None:
        metadata = EpisodeMetadata(
            root_dir=Path("/tmp/episode"),
            fps=30.0,
            camera_ids=["rs_00"],
            total_frames=3,
            aligned_timestamps_s=[0.0, 0.1, 0.25],
        )

        timeline_ns = resolve_timeline_timestamps_ns(metadata, [0, 33_333_333, 66_666_667])

        self.assertEqual(timeline_ns, [0, 100_000_000, 250_000_000])

    def test_resolve_timeline_timestamps_falls_back_to_video_pts(self) -> None:
        metadata = EpisodeMetadata(
            root_dir=Path("/tmp/episode"),
            fps=30.0,
            camera_ids=["rs_00"],
            total_frames=2,
            aligned_timestamps_s=None,
        )

        timeline_ns = resolve_timeline_timestamps_ns(metadata, [0, 33_333_333])

        self.assertEqual(timeline_ns, [0, 33_333_333])


if __name__ == "__main__":
    unittest.main()
