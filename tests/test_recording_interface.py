"""Unit tests for :class:`pvfs_to_nwb.PvfsRecordingInterface`."""

from __future__ import annotations

import numpy as np
import pytest

from pvfs_to_nwb import PvfsRecordingInterface


def test_interface_metadata_has_pvfs_device_and_subject(synthetic_pvfs, pvfs_config):
    iface = PvfsRecordingInterface(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.fast_rate_hz
    )
    metadata = iface.get_metadata()

    assert "Ecephys" in metadata
    device_names = [d.get("name") for d in metadata["Ecephys"].get("Device", [])]
    assert "DevicePVFS" in device_names

    groups = metadata["Ecephys"].get("ElectrodeGroup", [])
    group_names = [g.get("name") for g in groups]
    assert "PVFSGroup" in group_names
    assert groups[0].get("location") == "root"

    assert metadata.get("Subject", {}).get("subject_id") == pvfs_config.subject_id
    assert metadata.get("NWBFile", {}).get("session_start_time") is not None


def test_interface_writes_electrical_series(synthetic_pvfs, pvfs_config, tmp_path):
    iface = PvfsRecordingInterface(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.fast_rate_hz
    )
    metadata = iface.get_metadata()
    metadata["NWBFile"]["session_description"] = "unit-test"

    out = tmp_path / "out.nwb"
    iface.run_conversion(nwbfile_path=str(out), metadata=metadata, overwrite=True)
    assert out.exists() and out.stat().st_size > 0

    from pynwb import NWBHDF5IO

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        # Exactly one ElectricalSeries should be present in acquisition.
        es_list = [
            obj for obj in nwb.acquisition.values()
            if obj.neurodata_type == "ElectricalSeries"
        ]
        assert len(es_list) == 1
        es = es_list[0]
        assert es.rate == pytest.approx(pvfs_config.fast_rate_hz)
        # data shape is (n_samples, n_channels)
        data = es.data[:]
        assert data.shape == (pvfs_config.fast_samples, 1)
        assert np.isfinite(data).all()
