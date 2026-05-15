"""End-to-end round-trip tests for :class:`pvfs_to_nwb.PvfsNWBConverter`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pvfs_to_nwb import PvfsNWBConverter


def test_converter_discovers_two_rate_groups(synthetic_pvfs, pvfs_config):
    converter = PvfsNWBConverter(file_path=str(synthetic_pvfs))
    names = list(converter.data_interface_objects.keys())
    recording_names = [n for n in names if n.startswith("Recording")]
    assert len(recording_names) == 2, f"expected two rate groups, got {names}"
    assert "Annotations" in names


def test_converter_round_trip_writes_valid_nwb(
    synthetic_pvfs, pvfs_config, annotation_specs, tmp_path: Path
):
    converter = PvfsNWBConverter(
        file_path=str(synthetic_pvfs),
        include_video=True,  # no video in fixture; should still succeed
    )

    metadata = converter.get_metadata()
    metadata["NWBFile"]["session_description"] = "round-trip test"
    metadata["Subject"]["subject_id"] = pvfs_config.subject_id
    metadata["Subject"]["species"] = "Mus musculus"

    out = tmp_path / "round_trip.nwb"
    converter.run_conversion(
        nwbfile_path=str(out), metadata=metadata, overwrite=True
    )
    assert out.exists() and out.stat().st_size > 0

    from pynwb import NWBHDF5IO, validate

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()

        es_objects = [
            obj for obj in nwb.acquisition.values()
            if obj.neurodata_type == "ElectricalSeries"
        ]
        assert len(es_objects) == 2

        rates = sorted({float(es.rate) for es in es_objects})
        assert pytest.approx(rates[0]) == min(
            pvfs_config.fast_rate_hz, pvfs_config.slow_rate_hz
        )
        assert pytest.approx(rates[-1]) == max(
            pvfs_config.fast_rate_hz, pvfs_config.slow_rate_hz
        )

        for es in es_objects:
            data = es.data[:]
            assert data.ndim == 2 and data.shape[1] == 1
            assert np.isfinite(data).all()

        electrodes_df = nwb.electrodes.to_dataframe()
        assert len(electrodes_df) == 2

        epochs_df = nwb.epochs.to_dataframe()
        assert len(epochs_df) == len(annotation_specs)
        assert "label" in epochs_df.columns
        assert "channel" in epochs_df.columns
        assert "seizure" in str(epochs_df.iloc[0]["label"])

        assert nwb.subject is not None
        assert nwb.subject.subject_id == pvfs_config.subject_id
        assert nwb.subject.species == "Mus musculus"
        assert nwb.subject.age is not None
        assert nwb.subject.description is not None
        assert nwb.experiment_description is not None
        assert nwb.keywords is not None
        assert nwb.experimenter is not None
        assert "Robby Researcher" in nwb.experimenter

        assert (epochs_df["start_time"] >= 0).all()
        assert (epochs_df["stop_time"] > epochs_df["start_time"]).all()

    # The NWB file should validate against the core schema.
    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        validation_errors = list(validate(io=io))
    assert validation_errors == [], f"NWB validation failed: {validation_errors}"


def test_cli_runs_end_to_end(synthetic_pvfs, tmp_path: Path):
    from pvfs_to_nwb._cli import main

    out = tmp_path / "cli.nwb"
    rc = main(
        [
            str(synthetic_pvfs),
            "--out",
            str(out),
            "--no-video",
            "--subject-id",
            "cli_mouse",
            "--session-description",
            "cli session",
            "--overwrite",
        ]
    )
    assert rc == 0
    assert out.exists()

    from pynwb import NWBHDF5IO

    with NWBHDF5IO(str(out), "r") as io:
        nwb = io.read()
        assert nwb.subject.subject_id == "cli_mouse"
        assert nwb.session_description == "cli session"
