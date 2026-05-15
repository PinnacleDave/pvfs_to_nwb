"""Integration tests using the repository ``video.pvfs`` fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from pvfs_to_nwb import PvfsNWBConverter
from pvfs_to_nwb._metadata import (
    discover_video_stream_bases,
    filter_indexed_channels,
    open_pvfs,
    read_pvfs_metadata,
    resolve_channel_file_base,
)

VIDEO_PVFS = Path(__file__).resolve().parent.parent / "video.pvfs"


@pytest.fixture(scope="module")
def video_pvfs_path() -> Path:
    if not VIDEO_PVFS.exists():
        pytest.skip(f"Fixture not found: {VIDEO_PVFS}")
    return VIDEO_PVFS


def test_video_streams_are_excluded_from_indexed_channels(video_pvfs_path: Path):
    meta = read_pvfs_metadata(video_pvfs_path)
    with open_pvfs(video_pvfs_path) as vfs:
        video_bases = discover_video_stream_bases(vfs)

    assert "Camera_video3" in video_bases
    indexed = filter_indexed_channels(meta.channels, video_bases)
    assert "Camera" not in indexed
    assert {"EEG1", "EEG2", "EMG"}.issubset(indexed.keys())
    assert resolve_channel_file_base(meta.channels["Camera"], "Camera") == "Camera_video3"


def test_video_pvfs_full_conversion(video_pvfs_path: Path, tmp_path: Path):
    pytest.importorskip("av")

    converter = PvfsNWBConverter(
        file_path=video_pvfs_path,
        include_video=True,
        video_output_dir=tmp_path,
    )
    names = list(converter.data_interface_objects.keys())
    assert "Video" in names
    assert "Recording" in names
    recording_names = [n for n in names if n.startswith("Recording")]
    assert all("Camera" not in n for n in recording_names)

    out = tmp_path / "video_out.nwb"
    converter.run_conversion(nwbfile_path=str(out), overwrite=True)
    assert out.exists() and out.stat().st_size > 0

    from pynwb import NWBHDF5IO

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        image_series = [
            obj
            for obj in nwb.acquisition.values()
            if obj.neurodata_type == "ImageSeries"
        ]
        assert image_series, "Expected ImageSeries from Camera_video3"
        assert any("Camera_video3" in es.name for es in image_series)

    webm_files = list(tmp_path.glob("video_Camera_video3.webm"))
    assert webm_files, "Expected exported WebM next to NWB output"
