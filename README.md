# pvfs-to-nwb

Convert Pinnacle PVFS (Virtual File System) recordings to the
[Neurodata Without Borders (NWB)](https://www.nwb.org/) standard, using
[NeuroConv](https://neuroconv.readthedocs.io/) conventions.

This package reads `.pvfs` files produced by Pinnacle Technology hardware (via
[`pypvfs`](https://github.com/Pinnacle-Technology-Inc/pypvfs)) and maps their
contents into a single `.nwb` file:

| PVFS content                                  | NWB target                                |
| --------------------------------------------- | ----------------------------------------- |
| Indexed time-series channels (`.index`/`.idat`) | One `ElectricalSeries` per sampling rate  |
| Per-channel annotations (`experiment.db3`)    | `epochs` table (with `label` and `channel` columns) |
| Sleep-stage scoring (`experiment.db3`)        | One `TimeIntervals` per scoring session under `nwbfile.intervals` |
| Embedded video (`VideoDataFile`)              | `ImageSeries` linking an exported `.webm` |
| Experiment metadata (`experiment.db3`)        | `NWBFile` and `Subject` fields            |

## Installation

```bash
pip install pvfs-to-nwb
```

For video conversion you also need PyAV (and the `pypvfs[video]` extra):

```bash
pip install "pvfs-to-nwb[video]"
```

> Note: `pypvfs` only ships wheels for `linux_x86_64` and `win_amd64`. On other
> platforms it must be built from source (requires CMake and a C++17 compiler).
> Editable installs of `pypvfs` are unreliable because of how its native
> libraries are loaded; install a real wheel.

## Usage

Python API:

```python
from pvfs_to_nwb import PvfsNWBConverter

converter = PvfsNWBConverter(
    file_path="recording.pvfs",
    include_video=True,
    video_output_dir="./videos",
)
metadata = converter.get_metadata()
metadata["NWBFile"]["session_description"] = "example session"
metadata["Subject"]["subject_id"] = "mouse_01"
converter.run_conversion(nwbfile_path="recording.nwb", metadata=metadata)
```

Command line:

```bash
pvfs-to-nwb recording.pvfs --out recording.nwb \
    --subject-id mouse_01 \
    --session-description "example session"
```

Pass `--no-video` to skip video conversion entirely.  Pass `--no-sleep-scoring`
to skip sleep-stage export (otherwise every populated scoring session in the
PVFS file is written as a `TimeIntervals` table named
`sleep_stages_session_<n>` with `stage_label`, `stage_value`, `flags`, and
`epoch_uid` columns).

## Architecture

The package follows the same structure used by NeuroConv interfaces so that the
`pvfs_to_nwb` subpackage can later be promoted into
`neuroconv/datainterfaces/ecephys/pvfs/`:

- `PvfsRecordingExtractor` — a SpikeInterface `BaseRecording` wrapping one or
  more `IndexedDataFile` channels that share a sampling rate.
- `PvfsRecordingInterface(BaseRecordingExtractorInterface)` — exposes the
  extractor to NeuroConv and emits an `ElectricalSeries` per rate group.
- `PvfsAnnotationsInterface(BaseDataInterface)` — reads annotations through
  `ExperimentDatabase.get_all_annotations()` and writes them as NWB epochs.
- `PvfsSleepScoringInterface(BaseDataInterface)` — reads
  `scores_values_table`, `sleep_scores_table`, and `sleep_scoring_session_table`
  via raw SQLite (pypvfs does not yet expose them) and writes one
  `TimeIntervals` per scoring session.
- `PvfsVideoInterface(BaseDataInterface)` — exports each `VideoDataFile` track
  as a `.webm` via `WebMWriter` and attaches it as an external-file
  `ImageSeries`.
- `PvfsNWBConverter(NWBConverter)` — orchestrates the four interfaces.

See [neuroconv's "Build a DataInterface" guide](https://neuroconv.readthedocs.io/en/main/developer_guide/build_data_interface.html)
for the long-term upstreaming path.

## Limitations

- All channels in a sampling-rate group are truncated to the shortest length so
  that they share a uniform time axis.
- Annotations whose `end_time` is missing are stored as point events with a
  minimal duration (`stop_time = start_time + 1e-6` s).
- The default video path produces an external `.webm`; if you need the frames
  inlined, set `embed_frames=True` on `PvfsVideoInterface` (this can be very
  large).

## License

BSD 3-Clause; see [LICENSE](LICENSE).
