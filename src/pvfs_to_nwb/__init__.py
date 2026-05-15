"""Top-level package for ``pvfs-to-nwb``.

This package converts Pinnacle PVFS (Virtual File System) recordings into the
Neurodata Without Borders (NWB) format using NeuroConv conventions.

The public surface mirrors what a NeuroConv-style integration would expose:

* :class:`PvfsRecordingInterface` -- wraps the indexed time-series channels.
* :class:`PvfsAnnotationsInterface` -- writes per-channel annotations as epochs.
* :class:`PvfsVideoInterface` -- exports embedded video tracks as ImageSeries.
* :class:`PvfsNWBConverter` -- orchestrates all of the above.
* :class:`PvfsRecordingExtractor` -- low level SpikeInterface ``BaseRecording``
  that backs :class:`PvfsRecordingInterface`.
"""

from .extractors.pvfs_recording_extractor import PvfsRecordingExtractor
from .pvfsannotationsinterface import PvfsAnnotationsInterface
from .pvfsnwbconverter import PvfsNWBConverter
from .pvfsrecordinginterface import PvfsRecordingInterface
from .pvfsvideointerface import PvfsVideoInterface

__all__ = [
    "PvfsAnnotationsInterface",
    "PvfsNWBConverter",
    "PvfsRecordingExtractor",
    "PvfsRecordingInterface",
    "PvfsVideoInterface",
]

__version__ = "0.1.0"
