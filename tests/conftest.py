"""Shared pytest fixtures for the pvfs-to-nwb test suite.

The fixtures construct tiny synthetic PVFS files using
:class:`pvfs_tools.Core.pvfs_data_file.PvfsDataFile` so the unit tests do not
need to ship binary fixtures.  Two indexed channels at different sampling
rates plus a couple of annotations are produced; video is *not* included here
(authoring a valid in-PVFS VP8 stream requires PyAV and is exercised in
``test_video_interface.py``).
"""

from __future__ import annotations

import gc
import math
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

try:  # pragma: no cover - import guard, real failure surfaces at fixture time
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile
    from pvfs_tools.Database.exceptions import TableError
    from pvfs_tools.Database.models import ExperimentInformation
    from sqlalchemy import text

    _PYPVFS_AVAILABLE = True
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised when pypvfs is missing
    _PYPVFS_AVAILABLE = False
    _IMPORT_ERROR = exc


def _skip_without_pypvfs() -> None:
    if not _PYPVFS_AVAILABLE:
        pytest.skip(
            "pypvfs (pvfs_tools) is not importable in this environment "
            f"({_IMPORT_ERROR!r})."
        )


ANNOTATION_DDL = """
CREATE TABLE experiment_annotation_table (
    unique_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    start_time_seconds INTEGER,
    start_time_sub_seconds REAL,
    end_time_seconds INTEGER,
    end_time_sub_seconds REAL,
    comment TEXT,
    type TEXT,
    creator TEXT,
    last_edited TEXT,
    uuid TEXT
)
"""


@dataclass
class SyntheticPvfsConfig:
    """Description of the fixture PVFS that the tests will read back."""

    fast_channel_name: str = "EEG0"
    fast_rate_hz: float = 400.0
    fast_samples: int = 800  # 2 seconds at 400 Hz

    slow_channel_name: str = "EMG0"
    slow_rate_hz: float = 100.0
    slow_samples: int = 200  # 2 seconds at 100 Hz

    subject_id: str = "mouse_01"
    description: str = "synthetic pvfs-to-nwb fixture"
    session_start_epoch: float = 1_700_000_000.0  # fixed for reproducibility


@dataclass
class AnnotationSpec:
    channel_id: int
    start_offset_s: float
    end_offset_s: float | None
    comment: str
    type: str = "test"
    creator: str = "pytest"


DEFAULT_ANNOTATIONS = [
    AnnotationSpec(channel_id=0, start_offset_s=0.25, end_offset_s=0.75, comment="seizure"),
    AnnotationSpec(channel_id=1, start_offset_s=1.10, end_offset_s=None, comment="point-event"),
]


def _build_pvfs(path: Path, config: SyntheticPvfsConfig) -> None:
    """Create *path* on disk, populated with 2 indexed channels + annotations."""
    pdf = PvfsDataFile()
    try:
        assert pdf.create(str(path)), f"failed to create PVFS at {path}"

        start_time = HighTime.from_seconds(config.session_start_epoch)

        info = ExperimentInformation(
            id="experiment-1",
            name=config.subject_id,
            description=config.description,
            start_time=start_time,
        )
        try:
            pdf._database.set_information(info)
        except TableError:
            pass  # best-effort; tests will fall back to channel-derived start time

        idf_fast = pdf.create_channel(
            channel_name=config.fast_channel_name,
            data_rate=config.fast_rate_hz,
            unit="uV",
        )
        assert idf_fast is not None
        idf_fast._delta_time = HighTime(0, 1.0 / config.fast_rate_hz)
        fast_values = [
            50.0 * math.sin(2 * math.pi * 10.0 * i / config.fast_rate_hz)
            for i in range(config.fast_samples)
        ]
        assert idf_fast.append_block(start_time, fast_values) == 0

        idf_slow = pdf.create_channel(
            channel_name=config.slow_channel_name,
            data_rate=config.slow_rate_hz,
            unit="mV",
        )
        assert idf_slow is not None
        idf_slow._delta_time = HighTime(0, 1.0 / config.slow_rate_hz)
        slow_values = [
            0.5 * math.cos(2 * math.pi * 4.0 * i / config.slow_rate_hz)
            for i in range(config.slow_samples)
        ]
        assert idf_slow.append_block(start_time, slow_values) == 0

        _seed_annotations(pdf, start_epoch=config.session_start_epoch)

        pdf.flush(synchronous=True)
    finally:
        pdf.close()

    # Windows / native-binding file handles can linger briefly; give the OS a
    # moment so subsequent reads of the .pvfs do not race.
    gc.collect()
    time.sleep(0.1)


def _seed_annotations(pdf: PvfsDataFile, start_epoch: float) -> None:
    """Drop & re-create ``experiment_annotation_table`` with full schema, then insert rows."""
    db = pdf._database
    with db.session() as session:
        session.execute(text("DROP TABLE IF EXISTS experiment_annotation_table"))
        session.execute(text(ANNOTATION_DDL))
        for idx, spec in enumerate(DEFAULT_ANNOTATIONS):
            start_abs = start_epoch + spec.start_offset_s
            end_abs = (
                start_epoch + spec.end_offset_s if spec.end_offset_s is not None else None
            )
            session.execute(
                text(
                    """
                    INSERT INTO experiment_annotation_table (
                        unique_id, channel_id,
                        start_time_seconds, start_time_sub_seconds,
                        end_time_seconds, end_time_sub_seconds,
                        comment, type, creator, last_edited, uuid
                    ) VALUES (
                        :unique_id, :channel_id,
                        :start_sec, :start_sub,
                        :end_sec, :end_sub,
                        :comment, :type, :creator, :last_edited, :uuid
                    )
                    """
                ),
                {
                    "unique_id": idx + 1,
                    "channel_id": spec.channel_id,
                    "start_sec": int(start_abs),
                    "start_sub": float(start_abs - int(start_abs)),
                    "end_sec": int(end_abs) if end_abs is not None else None,
                    "end_sub": (
                        float(end_abs - int(end_abs)) if end_abs is not None else None
                    ),
                    "comment": spec.comment,
                    "type": spec.type,
                    "creator": spec.creator,
                    "last_edited": "",
                    "uuid": f"ann-{idx + 1}",
                },
            )


@pytest.fixture(scope="session")
def pvfs_config() -> SyntheticPvfsConfig:
    return SyntheticPvfsConfig()


@pytest.fixture()
def synthetic_pvfs(tmp_path: Path, pvfs_config: SyntheticPvfsConfig) -> Path:
    """Return the path of a freshly built synthetic .pvfs in *tmp_path*."""
    _skip_without_pypvfs()
    pvfs_path = tmp_path / "synthetic.pvfs"
    _build_pvfs(pvfs_path, pvfs_config)
    assert pvfs_path.exists() and pvfs_path.stat().st_size > 0
    return pvfs_path


@pytest.fixture()
def annotation_specs() -> list[AnnotationSpec]:
    """Expose the annotation specs used when building ``synthetic_pvfs``."""
    return list(DEFAULT_ANNOTATIONS)
