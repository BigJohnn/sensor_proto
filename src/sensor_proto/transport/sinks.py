from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from sensor_proto.models import AlignedFrameSet
from sensor_proto.recording import RecordingStatus


@dataclass(slots=True)
class AlignedSetEvent:
    aligned_set: AlignedFrameSet
    sync_snapshot: dict[str, object]
    camera_snapshot: dict[str, object]


class AlignedSetSink(Protocol):
    def publish(self, event: AlignedSetEvent) -> None: ...


class RepositoryAlignedSetSink:
    def __init__(self, repository) -> None:
        self._repository = repository

    def publish(self, event: AlignedSetEvent) -> None:
        self._repository.publish(event.aligned_set, event.sync_snapshot, event.camera_snapshot)


class RecordingAlignedSetSink:
    def __init__(self, repository, recording_sink) -> None:
        self._repository = repository
        self._recording_sink = recording_sink
        self._last_submit_accepted: bool | None = None
        self._last_status = recording_sink.status()
        self._repository.set_recording_status(self._last_status.as_dict())

    @property
    def last_submit_accepted(self) -> bool | None:
        return self._last_submit_accepted

    @property
    def last_status(self) -> RecordingStatus:
        return self._last_status

    def publish(self, event: AlignedSetEvent) -> None:
        accepted = self._recording_sink.submit(event.aligned_set)
        status = self._recording_sink.status()
        self._last_submit_accepted = accepted
        self._last_status = status
        self._repository.set_recording_status(status.as_dict())


class CompositeAlignedSetSink:
    def __init__(self, sinks: Iterable[AlignedSetSink]) -> None:
        self._sinks = tuple(sinks)

    def publish(self, event: AlignedSetEvent) -> None:
        for sink in self._sinks:
            sink.publish(event)
