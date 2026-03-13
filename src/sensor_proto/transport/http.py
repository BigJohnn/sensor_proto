from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sensor_proto.config import RunConfig
from sensor_proto.recording import RecordingSink
from sensor_proto.stream_server import AlignedSetRepository, StreamHttpServer, build_dashboard_html
from sensor_proto.transport.sinks import CompositeAlignedSetSink, RecordingAlignedSetSink, RepositoryAlignedSetSink


@dataclass(slots=True)
class HttpStreamRuntime:
    repository: AlignedSetRepository
    server: object
    aligned_set_sink: CompositeAlignedSetSink
    recording_publish_sink: RecordingAlignedSetSink | None


def build_http_stream_runtime(
    config: RunConfig,
    recording_sink: RecordingSink | None,
    *,
    server_factory: Callable[[tuple[str, int], AlignedSetRepository, str], object] = StreamHttpServer,
) -> HttpStreamRuntime:
    repository = AlignedSetRepository(
        camera_ids=[camera.id for camera in config.cameras],
        recent_sets=config.stream.recent_sets,
        preview_max_width=config.stream.preview_max_width,
        preview_max_height=config.stream.preview_max_height,
        preview_jpeg_quality=config.stream.preview_jpeg_quality,
    )
    repository_sink = RepositoryAlignedSetSink(repository)
    recording_publish_sink = RecordingAlignedSetSink(repository, recording_sink) if recording_sink is not None else None
    aligned_set_sink = CompositeAlignedSetSink(
        [repository_sink, *([recording_publish_sink] if recording_publish_sink is not None else [])]
    )
    if recording_sink is None:
        repository.set_recording_status(RecordingSink.disabled().as_dict())
    server = server_factory(
        (config.stream.host, config.stream.port),
        repository,
        build_dashboard_html(f"RealSense {len(config.cameras)}-Camera Sync Viewer", config.stream.client_refresh_ms),
    )
    return HttpStreamRuntime(
        repository=repository,
        server=server,
        aligned_set_sink=aligned_set_sink,
        recording_publish_sink=recording_publish_sink,
    )
