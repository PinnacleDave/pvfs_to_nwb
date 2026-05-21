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
from dataclasses import dataclass, field
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


# Mirror the schema that Pinnacle's PVFS uses for sleep-stage scoring (see
# the four-table layout in :mod:`pvfs_to_nwb._metadata`).  Real PVFS files
# store start_time_sub_seconds / end_time_sub_seconds as VARCHAR, so we do too.
SCORES_VALUES_DDL = """
CREATE TABLE scores_values_table (
    session_number INTEGER,
    score INTEGER,
    score_name VARCHAR,
    color VARCHAR,
    flags INTEGER
)
"""

SLEEP_SCORING_SESSION_DDL = """
CREATE TABLE sleep_scoring_session_table (
    user_id VARCHAR,
    epoch_length VARCHAR,
    session_number INTEGER,
    data_file_name VARCHAR,
    experiment_id VARCHAR,
    animal_id VARCHAR
)
"""

SLEEP_SCORES_DDL = """
CREATE TABLE sleep_scores_table (
    session_number INTEGER,
    start_time_seconds INTEGER,
    start_time_sub_seconds VARCHAR,
    end_time_seconds INTEGER,
    end_time_sub_seconds VARCHAR,
    score INTEGER,
    uid VARCHAR
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


# ---------------------------------------------------------------------------
# Sleep-scoring fixtures
# ---------------------------------------------------------------------------

# Default legend used by ``_seed_sleep_scoring`` -- mirrors what Pinnacle
# writes for a fresh scoring session.
DEFAULT_SCORE_LEGEND: list[tuple[int, str, int]] = [
    (0, "Artifact", 0),
    (1, "Wake", 0),
    (2, "Non REM", 1),
    (3, "REM", 1),
    (6, "Sleep", 1),
    (129, "Wake X", 2),
    (130, "Non REM X", 2),
    (131, "REM X", 2),
    (255, "Unscored", 0),
]


@dataclass
class SleepEpochSpec:
    """A single synthetic scored epoch, expressed as offsets from session_start."""

    start_offset_s: float
    duration_s: float
    score: int
    uid: str = ""


@dataclass
class SleepScoringSpec:
    """One synthetic Pinnacle scoring session."""

    session_number: int = 6
    user_id: str = "pytest-scorer"
    epoch_length_seconds: float = 10.0
    animal_id: str = "mouse_01"
    experiment_id: str = "experiment-1"
    data_file_name: str = "synthetic.pvfs"
    epochs: list[SleepEpochSpec] = field(default_factory=list)
    legend: list[tuple[int, str, int]] = field(default_factory=lambda: list(DEFAULT_SCORE_LEGEND))


def _default_sleep_scoring_specs() -> list[SleepScoringSpec]:
    """One 6-epoch session covering Wake -> Non REM -> REM -> Wake -> Artifact -> Unscored."""
    return [
        SleepScoringSpec(
            session_number=6,
            epochs=[
                SleepEpochSpec(start_offset_s=0.0, duration_s=10.0, score=1, uid="ep-1"),
                SleepEpochSpec(start_offset_s=10.0, duration_s=10.0, score=2, uid="ep-2"),
                SleepEpochSpec(start_offset_s=20.0, duration_s=10.0, score=3, uid="ep-3"),
                SleepEpochSpec(start_offset_s=30.0, duration_s=10.0, score=1, uid="ep-4"),
                SleepEpochSpec(start_offset_s=40.0, duration_s=10.0, score=0, uid="ep-5"),
                SleepEpochSpec(start_offset_s=50.0, duration_s=10.0, score=255, uid="ep-6"),
            ],
        )
    ]


def _multi_session_sleep_scoring_specs() -> list[SleepScoringSpec]:
    """Two populated sessions, used to verify multi-session export."""
    return [
        SleepScoringSpec(
            session_number=4,
            user_id="alice",
            epoch_length_seconds=10.0,
            epochs=[
                SleepEpochSpec(start_offset_s=0.0, duration_s=10.0, score=1, uid="A1"),
                SleepEpochSpec(start_offset_s=10.0, duration_s=10.0, score=2, uid="A2"),
            ],
        ),
        SleepScoringSpec(
            session_number=6,
            user_id="bob",
            epoch_length_seconds=10.0,
            epochs=[
                SleepEpochSpec(start_offset_s=0.0, duration_s=10.0, score=2, uid="B1"),
                SleepEpochSpec(start_offset_s=10.0, duration_s=10.0, score=3, uid="B2"),
                SleepEpochSpec(start_offset_s=20.0, duration_s=10.0, score=1, uid="B3"),
            ],
        ),
    ]


def _build_pvfs(
    path: Path,
    config: SyntheticPvfsConfig,
    *,
    sleep_scoring: list[SleepScoringSpec] | None = None,
) -> None:
    """Create *path* on disk, populated with 2 indexed channels + annotations.

    When *sleep_scoring* is provided, the synthetic PVFS additionally gets
    fully-populated ``scores_values_table`` / ``sleep_scoring_session_table``
    / ``sleep_scores_table`` rows so it round-trips through
    :class:`PvfsSleepScoringInterface`.
    """
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

        if sleep_scoring:
            _seed_sleep_scoring(
                pdf,
                start_epoch=config.session_start_epoch,
                sessions=sleep_scoring,
            )

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


def _seed_sleep_scoring(
    pdf: PvfsDataFile,
    *,
    start_epoch: float,
    sessions: list[SleepScoringSpec],
) -> None:
    """Drop & re-create the four sleep-scoring tables, then insert rows.

    The synthetic PVFS does not have these tables to begin with, so we just
    ``CREATE TABLE IF NOT EXISTS`` against the SQLAlchemy session that pypvfs
    exposes -- exactly mirroring the production schema documented in
    :mod:`pvfs_to_nwb._metadata`.
    """
    db = pdf._database
    with db.session() as session:
        session.execute(text("DROP TABLE IF EXISTS scores_values_table"))
        session.execute(text("DROP TABLE IF EXISTS sleep_scoring_session_table"))
        session.execute(text("DROP TABLE IF EXISTS sleep_scores_table"))
        session.execute(text(SCORES_VALUES_DDL))
        session.execute(text(SLEEP_SCORING_SESSION_DDL))
        session.execute(text(SLEEP_SCORES_DDL))

        for spec in sessions:
            for score, name, flags in spec.legend:
                session.execute(
                    text(
                        """
                        INSERT INTO scores_values_table
                            (session_number, score, score_name, color, flags)
                        VALUES (:session, :score, :name, :color, :flags)
                        """
                    ),
                    {
                        "session": spec.session_number,
                        "score": score,
                        "name": name,
                        "color": "FFFFFFFF",
                        "flags": flags,
                    },
                )

            session.execute(
                text(
                    """
                    INSERT INTO sleep_scoring_session_table
                        (user_id, epoch_length, session_number,
                         data_file_name, experiment_id, animal_id)
                    VALUES (:user, :length, :session, :file, :exp, :animal)
                    """
                ),
                {
                    "user": spec.user_id,
                    "length": str(spec.epoch_length_seconds),
                    "session": spec.session_number,
                    "file": spec.data_file_name,
                    "exp": spec.experiment_id,
                    "animal": spec.animal_id,
                },
            )

            for idx, epoch in enumerate(spec.epochs):
                start_abs = start_epoch + epoch.start_offset_s
                end_abs = start_abs + epoch.duration_s
                uid = epoch.uid or f"sess{spec.session_number}-ep{idx}"
                session.execute(
                    text(
                        """
                        INSERT INTO sleep_scores_table (
                            session_number,
                            start_time_seconds, start_time_sub_seconds,
                            end_time_seconds, end_time_sub_seconds,
                            score, uid
                        ) VALUES (
                            :session,
                            :start_sec, :start_sub,
                            :end_sec, :end_sub,
                            :score, :uid
                        )
                        """
                    ),
                    {
                        "session": spec.session_number,
                        "start_sec": int(start_abs),
                        "start_sub": f"{start_abs - int(start_abs):.6f}",
                        "end_sec": int(end_abs),
                        "end_sub": f"{end_abs - int(end_abs):.6f}",
                        "score": epoch.score,
                        "uid": uid,
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
def synthetic_pvfs_with_scoring(
    tmp_path: Path, pvfs_config: SyntheticPvfsConfig
) -> Path:
    """Synthetic .pvfs that also carries one populated sleep-scoring session."""
    _skip_without_pypvfs()
    pvfs_path = tmp_path / "synthetic_scoring.pvfs"
    _build_pvfs(
        pvfs_path,
        pvfs_config,
        sleep_scoring=_default_sleep_scoring_specs(),
    )
    assert pvfs_path.exists() and pvfs_path.stat().st_size > 0
    return pvfs_path


@pytest.fixture()
def synthetic_pvfs_with_multi_session_scoring(
    tmp_path: Path, pvfs_config: SyntheticPvfsConfig
) -> Path:
    """Synthetic .pvfs with two populated sleep-scoring sessions."""
    _skip_without_pypvfs()
    pvfs_path = tmp_path / "synthetic_multi_scoring.pvfs"
    _build_pvfs(
        pvfs_path,
        pvfs_config,
        sleep_scoring=_multi_session_sleep_scoring_specs(),
    )
    assert pvfs_path.exists() and pvfs_path.stat().st_size > 0
    return pvfs_path


@pytest.fixture()
def annotation_specs() -> list[AnnotationSpec]:
    """Expose the annotation specs used when building ``synthetic_pvfs``."""
    return list(DEFAULT_ANNOTATIONS)


@pytest.fixture()
def sleep_scoring_specs() -> list[SleepScoringSpec]:
    """Expose the default scoring specs used by ``synthetic_pvfs_with_scoring``."""
    return _default_sleep_scoring_specs()


@pytest.fixture()
def multi_session_sleep_scoring_specs() -> list[SleepScoringSpec]:
    """Expose the scoring specs used by ``synthetic_pvfs_with_multi_session_scoring``."""
    return _multi_session_sleep_scoring_specs()
