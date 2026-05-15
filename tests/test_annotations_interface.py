"""Unit tests for :class:`pvfs_to_nwb.PvfsAnnotationsInterface`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pynwb import NWBFile

from pvfs_to_nwb import PvfsAnnotationsInterface
from pvfs_to_nwb.pvfsannotationsinterface import POINT_EVENT_MIN_DURATION_S


def _make_nwbfile(session_start_epoch: float) -> NWBFile:
    return NWBFile(
        session_description="annotations test",
        identifier="ann-test",
        session_start_time=datetime.fromtimestamp(session_start_epoch, tz=timezone.utc),
    )


def test_annotations_are_attached_as_epochs(
    synthetic_pvfs, pvfs_config, annotation_specs
):
    iface = PvfsAnnotationsInterface(file_path=str(synthetic_pvfs))
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)

    iface.add_to_nwbfile(nwbfile=nwbfile)

    assert nwbfile.epochs is not None
    df = nwbfile.epochs.to_dataframe()
    assert len(df) == len(annotation_specs)

    # Spec 0 is a span, spec 1 is a point event.
    span = df.iloc[0]
    point = df.iloc[1]
    assert span["start_time"] == pytest.approx(annotation_specs[0].start_offset_s)
    assert span["stop_time"] == pytest.approx(annotation_specs[0].end_offset_s)
    assert "seizure" in str(span["label"])

    assert point["start_time"] == pytest.approx(annotation_specs[1].start_offset_s)
    assert point["stop_time"] > point["start_time"]
    assert point["stop_time"] == pytest.approx(
        point["start_time"] + POINT_EVENT_MIN_DURATION_S
    )
    assert "point-event" in str(point["label"])


def test_explicit_session_start_time_overrides_pvfs(
    synthetic_pvfs, pvfs_config, annotation_specs
):
    """Annotations should honour an explicit session_start_time."""
    iface = PvfsAnnotationsInterface(file_path=str(synthetic_pvfs))
    # Shift the reference time forward by 100s; epoch start_time values should
    # shift by the same amount.
    shifted = datetime.fromtimestamp(
        pvfs_config.session_start_epoch + 100.0, tz=timezone.utc
    )
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch + 100.0)

    iface.add_to_nwbfile(nwbfile=nwbfile, session_start_time=shifted)

    df = nwbfile.epochs.to_dataframe()
    assert len(df) == len(annotation_specs)
    expected_first = annotation_specs[0].start_offset_s - 100.0
    assert df.iloc[0]["start_time"] == pytest.approx(expected_first)


def test_epoch_times_are_non_negative(synthetic_pvfs, pvfs_config):
    iface = PvfsAnnotationsInterface(file_path=str(synthetic_pvfs))
    nwbfile = _make_nwbfile(pvfs_config.session_start_epoch)
    iface.add_to_nwbfile(nwbfile=nwbfile)
    df = nwbfile.epochs.to_dataframe()
    assert (df["start_time"] >= 0).all()
    assert (df["stop_time"] >= 0).all()
    assert (df["stop_time"] > df["start_time"]).all()
