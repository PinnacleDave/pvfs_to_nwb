"""Unit tests for :class:`pvfs_to_nwb.PvfsVideoInterface`.

The synthetic PVFS produced by ``conftest.py`` does **not** contain a video
stream, so most assertions here verify graceful no-op behaviour.  When a real
PVFS with video becomes available (e.g. via a CI fixture), drop it next to
this test file and the additional tests below will exercise the real path.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pynwb import NWBFile

from pvfs_to_nwb import PvfsVideoInterface


def _make_nwbfile() -> NWBFile:
    return NWBFile(
        session_description="video test",
        identifier="vid-test",
        session_start_time=datetime.now(tz=timezone.utc),
    )


def test_has_video_returns_false_for_synthetic_pvfs(synthetic_pvfs):
    iface = PvfsVideoInterface(file_path=str(synthetic_pvfs))
    assert iface.has_video() is False


def test_add_to_nwbfile_is_noop_when_no_video(synthetic_pvfs):
    iface = PvfsVideoInterface(file_path=str(synthetic_pvfs))
    nwbfile = _make_nwbfile()
    iface.add_to_nwbfile(nwbfile=nwbfile)
    assert "ImageSeries" not in {
        type(o).__name__ for o in nwbfile.acquisition.values()
    }


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        PvfsVideoInterface(file_path=str(tmp_path / "nope.pvfs"))


# Optional integration test: only runs when the user drops a real PVFS with a
# video stream alongside this test file (or sets the PVFS_VIDEO_FILE env var).
REAL_VIDEO_PVFS = os.environ.get("PVFS_VIDEO_FILE")


@pytest.mark.skipif(
    REAL_VIDEO_PVFS is None or not Path(REAL_VIDEO_PVFS).exists(),
    reason="Set PVFS_VIDEO_FILE to a .pvfs containing a video track to enable.",
)
def test_real_video_pvfs_writes_image_series(tmp_path: Path):
    av = pytest.importorskip("av")
    del av

    iface = PvfsVideoInterface(
        file_path=REAL_VIDEO_PVFS,  # type: ignore[arg-type]
        video_output_dir=str(tmp_path),
    )
    assert iface.has_video() is True

    nwbfile = _make_nwbfile()
    iface.add_to_nwbfile(nwbfile=nwbfile)

    image_series = [
        obj for obj in nwbfile.acquisition.values()
        if obj.neurodata_type == "ImageSeries"
    ]
    assert image_series, "Expected at least one ImageSeries to be attached"
    es = image_series[0]
    assert es.external_file is not None
    for path in es.external_file:
        assert Path(path).exists(), f"WebM file should have been written at {path}"
