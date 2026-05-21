"""Unit + round-trip tests for :class:`pvfs_to_nwb.PvfsSleepScoringInterface`.

The tests exercise the interface against synthetic PVFS files produced by
``conftest._build_pvfs`` -- no real Pinnacle data is required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pynwb import NWBFile

from pvfs_to_nwb import PvfsNWBConverter, PvfsSleepScoringInterface
from pvfs_to_nwb._metadata import (
    SleepScoringSession,
    read_sleep_scoring_sessions_from_pvfs,
)


def _make_nwbfile(session_start_epoch: float) -> NWBFile:
    return NWBFile(
        session_description="sleep scoring test",
        identifier="scoring-test",
        session_start_time=datetime.fromtimestamp(session_start_epoch, tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Reader (no NWB involvement) — proves the SQLite layer is correct first.
# ---------------------------------------------------------------------------

def test_reader_returns_empty_when_no_scoring_tables(synthetic_pvfs):
    """The plain synthetic fixture has no scoring tables -> empty result."""
    sessions = read_sleep_scoring_sessions_from_pvfs(str(synthetic_pvfs))
    assert sessions == {}


def test_reader_round_trips_legend_and_metadata(
    synthetic_pvfs_with_scoring, sleep_scoring_specs
):
    sessions = read_sleep_scoring_sessions_from_pvfs(
        str(synthetic_pvfs_with_scoring)
    )

    assert len(sessions) == 1
    spec = sleep_scoring_specs[0]
    session = sessions[spec.session_number]
    assert isinstance(session, SleepScoringSession)

    # Legend should cover every entry we seeded.
    assert session.legend[1].score_name == "Wake"
    assert session.legend[2].score_name == "Non REM"
    assert session.legend[3].score_name == "REM"
    assert session.legend[2].flags == 1  # sleep stage
    assert session.legend[129].flags == 2  # the 'X' variants

    # Session metadata round-trips intact.
    assert session.user_id == spec.user_id
    assert session.epoch_length_seconds == pytest.approx(spec.epoch_length_seconds)
    assert session.animal_id == spec.animal_id
    assert session.experiment_id == spec.experiment_id

    # Epochs round-trip in start order with the seeded count.
    assert len(session.epochs) == len(spec.epochs)
    for actual, expected in zip(session.epochs, spec.epochs):
        assert actual.score == expected.score
        # Duration should match (allow fractional sub-second noise).
        assert (actual.stop_abs_seconds - actual.start_abs_seconds) == pytest.approx(
            expected.duration_s, abs=1e-3
        )


def test_reader_skips_unpopulated_sessions(synthetic_pvfs_with_scoring):
    """Legend rows for sessions w/ no scores must not appear in the result."""
    sessions = read_sleep_scoring_sessions_from_pvfs(
        str(synthetic_pvfs_with_scoring)
    )
    # Only the session we seeded with epochs should come back.
    assert all(session.epochs for session in sessions.values())


def test_reader_handles_multi_session_files(
    synthetic_pvfs_with_multi_session_scoring, multi_session_sleep_scoring_specs
):
    sessions = read_sleep_scoring_sessions_from_pvfs(
        str(synthetic_pvfs_with_multi_session_scoring)
    )
    expected = {spec.session_number for spec in multi_session_sleep_scoring_specs}
    assert set(sessions.keys()) == expected
    for spec in multi_session_sleep_scoring_specs:
        assert len(sessions[spec.session_number].epochs) == len(spec.epochs)


# ---------------------------------------------------------------------------
# Interface behaviour (in-memory NWBFile, no on-disk write).
# ---------------------------------------------------------------------------

def test_has_scoring_reports_false_for_plain_synthetic(synthetic_pvfs):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs))
    assert not iface.has_scoring()


def test_has_scoring_reports_true_when_present(synthetic_pvfs_with_scoring):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs_with_scoring))
    assert iface.has_scoring()


def test_add_to_nwbfile_creates_time_intervals(
    synthetic_pvfs_with_scoring, pvfs_config, sleep_scoring_specs
):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs_with_scoring))
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)

    iface.add_to_nwbfile(nwbfile=nwbfile)

    spec = sleep_scoring_specs[0]
    table_name = f"sleep_stages_session_{spec.session_number}"
    assert table_name in nwbfile.intervals
    table = nwbfile.intervals[table_name]

    expected_columns = {
        "start_time",
        "stop_time",
        "stage_label",
        "stage_value",
        "flags",
        "epoch_uid",
    }
    assert expected_columns.issubset({col.name for col in table.columns})

    df = table.to_dataframe()
    assert len(df) == len(spec.epochs)

    # First epoch in the spec is at offset 0 with score 1 ("Wake").
    first = df.iloc[0]
    assert first["start_time"] == pytest.approx(0.0)
    assert first["stop_time"] == pytest.approx(spec.epochs[0].duration_s, abs=1e-3)
    assert str(first["stage_label"]) == "Wake"
    assert int(first["stage_value"]) == spec.epochs[0].score
    assert int(first["flags"]) == 0  # Wake has flags=0

    # Non REM (score=2) carries flags=1.
    non_rem = df.iloc[1]
    assert str(non_rem["stage_label"]) == "Non REM"
    assert int(non_rem["flags"]) == 1

    # Round-trip of the GUID column.
    assert list(df["epoch_uid"]) == [e.uid for e in spec.epochs]


def test_add_to_nwbfile_writes_one_table_per_session(
    synthetic_pvfs_with_multi_session_scoring,
    pvfs_config,
    multi_session_sleep_scoring_specs,
):
    iface = PvfsSleepScoringInterface(
        file_path=str(synthetic_pvfs_with_multi_session_scoring)
    )
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)

    iface.add_to_nwbfile(nwbfile=nwbfile)

    for spec in multi_session_sleep_scoring_specs:
        table_name = f"sleep_stages_session_{spec.session_number}"
        assert table_name in nwbfile.intervals
        assert len(nwbfile.intervals[table_name].to_dataframe()) == len(spec.epochs)


def test_add_to_nwbfile_is_a_no_op_when_no_scoring(synthetic_pvfs, pvfs_config):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs))
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)
    iface.add_to_nwbfile(nwbfile=nwbfile)
    # No TimeIntervals beyond the default epochs slot should have been created.
    assert all(
        not name.startswith("sleep_stages_session_") for name in nwbfile.intervals
    )


def test_explicit_session_start_time_shifts_relative_times(
    synthetic_pvfs_with_scoring, pvfs_config, sleep_scoring_specs
):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs_with_scoring))
    shifted_epoch = pvfs_config.session_start_epoch + 100.0
    nwbfile = _make_nwbfile(shifted_epoch)
    shifted_dt = datetime.fromtimestamp(shifted_epoch, tz=timezone.utc)

    iface.add_to_nwbfile(nwbfile=nwbfile, session_start_time=shifted_dt)

    spec = sleep_scoring_specs[0]
    df = nwbfile.intervals[f"sleep_stages_session_{spec.session_number}"].to_dataframe()
    # The first epoch is at offset 0 from the PVFS session start; shifting the
    # reference forward by 100s should put it at -100s.
    assert df.iloc[0]["start_time"] == pytest.approx(-100.0)


def test_relative_times_are_monotonically_increasing(
    synthetic_pvfs_with_scoring, pvfs_config
):
    iface = PvfsSleepScoringInterface(file_path=str(synthetic_pvfs_with_scoring))
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)
    iface.add_to_nwbfile(nwbfile=nwbfile)

    df = next(iter(
        nwbfile.intervals[name].to_dataframe()
        for name in nwbfile.intervals
        if name.startswith("sleep_stages_session_")
    ))
    assert (df["stop_time"] > df["start_time"]).all()
    assert df["start_time"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Full converter round-trip through HDF5.
# ---------------------------------------------------------------------------

def test_converter_attaches_sleep_scoring_when_present(
    synthetic_pvfs_with_scoring, sleep_scoring_specs
):
    converter = PvfsNWBConverter(file_path=str(synthetic_pvfs_with_scoring))
    assert "SleepScoring" in converter.data_interface_objects


def test_converter_skips_sleep_scoring_when_absent(synthetic_pvfs):
    converter = PvfsNWBConverter(file_path=str(synthetic_pvfs))
    assert "SleepScoring" not in converter.data_interface_objects


def test_converter_skips_sleep_scoring_when_flag_off(synthetic_pvfs_with_scoring):
    converter = PvfsNWBConverter(
        file_path=str(synthetic_pvfs_with_scoring),
        include_sleep_scoring=False,
    )
    assert "SleepScoring" not in converter.data_interface_objects


def test_converter_round_trip_writes_sleep_stages_to_disk(
    synthetic_pvfs_with_scoring,
    pvfs_config,
    sleep_scoring_specs,
    tmp_path: Path,
):
    converter = PvfsNWBConverter(
        file_path=str(synthetic_pvfs_with_scoring),
        include_video=False,
    )
    metadata = converter.get_metadata()
    metadata["NWBFile"]["session_description"] = "scoring round-trip"
    metadata["Subject"]["subject_id"] = pvfs_config.subject_id

    out = tmp_path / "scoring_round_trip.nwb"
    converter.run_conversion(
        nwbfile_path=str(out), metadata=metadata, overwrite=True
    )
    assert out.exists() and out.stat().st_size > 0

    from pynwb import NWBHDF5IO, validate

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        spec = sleep_scoring_specs[0]
        table_name = f"sleep_stages_session_{spec.session_number}"
        assert table_name in nwb.intervals
        df = nwb.intervals[table_name].to_dataframe()
        assert len(df) == len(spec.epochs)
        assert str(df.iloc[0]["stage_label"]) == "Wake"

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        validation_errors = list(validate(io=io))
    assert validation_errors == [], f"NWB validation failed: {validation_errors}"


def test_cli_supports_no_sleep_scoring_flag(synthetic_pvfs_with_scoring, tmp_path: Path):
    from pvfs_to_nwb._cli import main

    out = tmp_path / "no_scoring.nwb"
    rc = main(
        [
            str(synthetic_pvfs_with_scoring),
            "--out",
            str(out),
            "--no-video",
            "--no-sleep-scoring",
            "--overwrite",
        ]
    )
    assert rc == 0
    assert out.exists()

    from pynwb import NWBHDF5IO

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        assert all(
            not name.startswith("sleep_stages_session_") for name in nwb.intervals
        )
