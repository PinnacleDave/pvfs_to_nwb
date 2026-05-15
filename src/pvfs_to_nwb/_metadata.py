"""Helpers for pulling NWB-relevant metadata out of a PVFS file.

A PVFS container always carries an ``experiment.db3`` SQLite database (see
``pvfs_tools.Database.database.ExperimentDatabase``) plus a set of
``IndexedDataFile`` channels.  This module extracts that database to a
temporary file, opens it, and returns plain Python dictionaries that match
NeuroConv's ``metadata`` shape.  It is intentionally small so that the
interfaces can compose it without taking a runtime dependency on the
high-level :class:`pvfs_tools.Core.pvfs_data_file.PvfsDataFile` wrapper.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pvfs_tools.Core.pvfs_binding import HighTime, PvfsFile
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Database.models import (
    Annotation,
    ChannelInformation,
    ExperimentInformation,
)

EXPERIMENT_DB_FILENAME = "experiment.db3"
EXPERIMENT_DB_BACKUP_FILENAME = "experiment_backup.db3"

# PVFS does not record subject age. This ISO-8601 placeholder satisfies NWBInspector;
# override via metadata["Subject"]["age"] or CLI --subject-age when known.
DEFAULT_SUBJECT_AGE = "P0D"

DEFAULT_NWB_KEYWORDS = ("Pinnacle", "PVFS", "EEG")

# PVFS does not record who ran the session; override via metadata or --experimenter.
DEFAULT_EXPERIMENTER = "Robby Researcher"


def decode_pvfs_filename(raw: object) -> str:
    """Decode a PVFS ``get_file_list()`` entry to a UTF-8 path string."""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore").rstrip("\x00")
    return str(raw)


def discover_video_stream_bases(vfs) -> frozenset[str]:
    """Return base names for embedded video streams inside a PVFS container.

    Video tracks are stored as ``{base}_frames`` plus ``{base}_index`` (not
    ``{base}.index`` / ``{base}.idat`` used by :class:`IndexedDataFile`).
    """
    try:
        names = [decode_pvfs_filename(raw) for raw in vfs.get_file_list()]
    except Exception:  # pragma: no cover - depends on native binding
        return frozenset()

    name_set = set(names)
    streams: list[str] = []
    for name in names:
        if name.endswith("_index"):
            base = name[: -len("_index")]
            if f"{base}_frames" in name_set:
                streams.append(base)
    return frozenset(streams)


def resolve_channel_file_base(
    info: ChannelInformation | None,
    channel_name: str,
) -> str:
    """Return the PVFS file stem for a channel (see experiment.db3 ``filename``)."""
    if info is not None and info.filename and str(info.filename).strip():
        return str(info.filename).strip()
    return channel_name


def filter_indexed_channels(
    channels: dict[str, ChannelInformation],
    video_bases: frozenset[str],
) -> dict[str, ChannelInformation]:
    """Drop database channels that reference embedded video streams, not EEG/EMG."""
    if not video_bases:
        return dict(channels)
    return {
        name: info
        for name, info in channels.items()
        if resolve_channel_file_base(info, name) not in video_bases
    }


def hightime_to_datetime(ht: HighTime | None) -> datetime | None:
    """Convert a :class:`HighTime` (POSIX seconds + fractional) to UTC ``datetime``.

    Returns ``None`` if the input is missing or marks the PVFS "no time" sentinel
    (``seconds == 0`` and ``subseconds == 0``).
    """
    if ht is None:
        return None
    seconds = int(ht.seconds)
    subseconds = float(ht.subseconds)
    if seconds == 0 and subseconds == 0.0:
        return None
    return datetime.fromtimestamp(seconds + subseconds, tz=timezone.utc)


def hightime_to_seconds(ht: HighTime | None) -> float | None:
    """Convert a :class:`HighTime` to a plain ``float`` of POSIX seconds."""
    if ht is None:
        return None
    seconds = int(ht.seconds)
    subseconds = float(ht.subseconds)
    if seconds == 0 and subseconds == 0.0:
        return None
    return seconds + subseconds


@dataclass
class PvfsMetadata:
    """Snapshot of everything the interfaces need from ``experiment.db3``.

    The interfaces never re-open the database after this snapshot is taken.
    """

    experiment: ExperimentInformation | None = None
    channels: dict[str, ChannelInformation] = field(default_factory=dict)
    annotations: list[Annotation] = field(default_factory=list)
    session_start_datetime: datetime | None = None
    channel_id_to_name: dict[int, str] = field(default_factory=dict)

    def to_nwb_metadata(self) -> dict:
        """Return a NeuroConv-style ``metadata`` dict prefilled from the DB.

        Subject ``sex`` and ``species`` are required by NeuroConv's metadata
        schema but PVFS does not carry that information.  We default ``sex`` to
        ``"U"`` (unknown) and ``species`` to ``"Mus musculus"`` because
        Pinnacle PVFS files are overwhelmingly rodent EEG recordings; users
        should override these defaults when they know better.

        ``age`` defaults to :data:`DEFAULT_SUBJECT_AGE` because PVFS does not
        store age or date of birth (required by NWBInspector).  Other NWB file
        fields that PVFS cannot populate are filled with conservative defaults
        so converted files pass routine inspection; override any field via the
        metadata dict or CLI flags.
        """
        nwbfile: dict = {}
        if self.session_start_datetime is not None:
            nwbfile["session_start_time"] = self.session_start_datetime
        if self.experiment is not None:
            if self.experiment.description:
                nwbfile["session_description"] = self.experiment.description
                nwbfile["experiment_description"] = self.experiment.description
            if self.experiment.id:
                nwbfile["session_id"] = str(self.experiment.id)

        if not nwbfile.get("experiment_description"):
            nwbfile["experiment_description"] = "Pinnacle PVFS recording"
        nwbfile["keywords"] = list(DEFAULT_NWB_KEYWORDS)
        nwbfile["institution"] = "Not specified in PVFS source file"
        nwbfile["experimenter"] = [DEFAULT_EXPERIMENTER]

        subject: dict = {
            "sex": "U",
            "species": "Mus musculus",
            "age": DEFAULT_SUBJECT_AGE,
        }
        if self.experiment is not None and self.experiment.name:
            subject["subject_id"] = self.experiment.name
            subject["description"] = (
                "Subject identifier from PVFS experiment metadata "
                f"({self.experiment.name})."
            )
        else:
            subject["description"] = (
                "Subject metadata from PVFS; age and other details are not stored "
                "in the source file."
            )

        metadata: dict = {}
        if nwbfile:
            metadata["NWBFile"] = {k: v for k, v in nwbfile.items() if v is not None}
        metadata["Subject"] = subject
        return metadata


def _earliest_session_start_datetime(
    *,
    experiment: ExperimentInformation | None,
    channels: dict[str, ChannelInformation],
    annotations: list[Annotation],
) -> datetime | None:
    """Return the earliest absolute time to use as ``session_start_time``.

    NWB best practice is to align the session clock to the earliest timestamp
    present in the recording so derived tables (e.g. epochs) are non-negative.
    """
    candidates: list[datetime] = []
    if experiment is not None and experiment.start_time is not None:
        dt = hightime_to_datetime(experiment.start_time)
        if dt is not None:
            candidates.append(dt)
    for info in channels.values():
        if info.start_time is not None:
            dt = hightime_to_datetime(info.start_time)
            if dt is not None:
                candidates.append(dt)
    for ann in annotations:
        seconds = hightime_to_seconds(ann.start_time)
        if seconds is not None:
            candidates.append(datetime.fromtimestamp(seconds, tz=timezone.utc))
        end_seconds = hightime_to_seconds(ann.end_time)
        if end_seconds is not None:
            candidates.append(datetime.fromtimestamp(end_seconds, tz=timezone.utc))
    if not candidates:
        return None
    return min(candidates)


def extract_experiment_db(
    pvfs_file: PvfsFile,
    destination_dir: str | os.PathLike | None = None,
) -> Path:
    """Extract ``experiment.db3`` (or its backup) out of *pvfs_file* to disk.

    Returns the path to the extracted SQLite file.  Raises ``FileNotFoundError``
    if neither the primary nor the backup database can be retrieved.
    """
    destination_dir = Path(destination_dir) if destination_dir else Path(tempfile.gettempdir())
    destination_dir.mkdir(parents=True, exist_ok=True)
    out_path = destination_dir / f"pvfs_to_nwb_{uuid.uuid4().hex}.db3"

    for candidate in (EXPERIMENT_DB_FILENAME, EXPERIMENT_DB_BACKUP_FILENAME):
        try:
            rc = pvfs_file.extract(candidate, str(out_path))
        except RuntimeError:
            continue
        if rc == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return out_path

    raise FileNotFoundError(
        "No experiment.db3 (or experiment_backup.db3) found inside the PVFS container."
    )


def _read_metadata_from_db(db_path: str | os.PathLike) -> PvfsMetadata:
    """Open an extracted ``experiment.db3`` and read all metadata of interest."""
    db = ExperimentDatabase(filename=str(db_path), in_memory=False)
    try:
        experiment = db.get_information()
        channel_names = db.get_channel_names()
        channels: dict[str, ChannelInformation] = {}
        channel_id_to_name: dict[int, str] = {}
        for name in channel_names:
            info = db.get_channel_info(name)
            if info is None:
                continue
            channels[name] = info
            channel_id_to_name[int(info.id)] = name

        annotations = db.get_all_annotations()
    finally:
        db.close()

    session_start_datetime = _earliest_session_start_datetime(
        experiment=experiment,
        channels=channels,
        annotations=annotations,
    )

    return PvfsMetadata(
        experiment=experiment,
        channels=channels,
        annotations=annotations,
        session_start_datetime=session_start_datetime,
        channel_id_to_name=channel_id_to_name,
    )


@contextmanager
def open_pvfs(file_path: str | os.PathLike) -> Iterator[PvfsFile]:
    """Context manager wrapping ``PvfsFile.open`` with guaranteed ``close``."""
    file_path = str(Path(file_path))
    vfs = PvfsFile.open(file_path)
    if vfs is None or not getattr(vfs, "is_open", True):
        raise RuntimeError(f"Failed to open PVFS file: {file_path}")
    try:
        yield vfs
    finally:
        try:
            vfs.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


def read_pvfs_metadata(file_path: str | os.PathLike) -> PvfsMetadata:
    """High-level helper: open the PVFS, extract the DB, return a snapshot.

    The extracted database file is removed before returning so callers don't
    have to manage temp files themselves.
    """
    with open_pvfs(file_path) as vfs:
        db_path = extract_experiment_db(vfs)
        try:
            return _read_metadata_from_db(db_path)
        finally:
            try:
                db_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - non-fatal cleanup
                pass
