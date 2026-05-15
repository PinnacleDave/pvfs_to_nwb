"""Unit tests for :class:`pvfs_to_nwb.PvfsRecordingExtractor`."""

from __future__ import annotations

import numpy as np
import pytest

from pvfs_to_nwb import PvfsRecordingExtractor


def test_default_picks_most_common_rate(synthetic_pvfs, pvfs_config):
    extractor = PvfsRecordingExtractor(file_path=str(synthetic_pvfs))
    # Fast and slow groups each have one channel; auto-pick is deterministic
    # in our fixture because Counter.most_common ties are broken by insertion
    # order.  Either rate is acceptable here; we only assert it's one of them.
    assert extractor.selected_sampling_rate in (
        pvfs_config.fast_rate_hz,
        pvfs_config.slow_rate_hz,
    )
    assert extractor.get_num_channels() == 1


def test_can_select_specific_rate(synthetic_pvfs, pvfs_config):
    fast = PvfsRecordingExtractor(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.fast_rate_hz
    )
    assert fast.selected_sampling_rate == pvfs_config.fast_rate_hz
    assert fast.get_num_channels() == 1
    assert fast.get_channel_ids().tolist() == [pvfs_config.fast_channel_name]
    assert fast.get_num_samples() == pvfs_config.fast_samples

    slow = PvfsRecordingExtractor(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.slow_rate_hz
    )
    assert slow.selected_sampling_rate == pvfs_config.slow_rate_hz
    assert slow.get_num_channels() == 1
    assert slow.get_channel_ids().tolist() == [pvfs_config.slow_channel_name]
    assert slow.get_num_samples() == pvfs_config.slow_samples


def test_get_traces_shape_and_dtype(synthetic_pvfs, pvfs_config):
    extractor = PvfsRecordingExtractor(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.fast_rate_hz
    )
    traces = extractor.get_traces()
    assert traces.dtype == np.float32
    assert traces.shape == (pvfs_config.fast_samples, 1)


def test_get_traces_slice(synthetic_pvfs, pvfs_config):
    extractor = PvfsRecordingExtractor(
        file_path=str(synthetic_pvfs), sampling_rate_hz=pvfs_config.fast_rate_hz
    )
    sub = extractor.get_traces(start_frame=10, end_frame=20)
    assert sub.shape == (10, 1)
    full = extractor.get_traces()
    np.testing.assert_array_equal(sub[:, 0], full[10:20, 0])


def test_unknown_channel_raises(synthetic_pvfs):
    with pytest.raises(ValueError):
        PvfsRecordingExtractor(file_path=str(synthetic_pvfs), channel_names=["no_such"])
