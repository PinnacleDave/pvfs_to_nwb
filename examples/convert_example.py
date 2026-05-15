"""Minimal end-to-end example: convert a Pinnacle PVFS recording to NWB.

Run from the repo root after ``pip install -e .[video]``::

    python examples/convert_example.py /path/to/recording.pvfs \
        --out /path/to/recording.nwb \
        --subject-id mouse_01

Equivalent to invoking the ``pvfs-to-nwb`` console script -- this file exists
mainly to demonstrate the Python API surface.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pvfs_to_nwb import PvfsNWBConverter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pvfs_file", type=Path, help="Input .pvfs file")
    parser.add_argument("--out", type=Path, default=None, help="Output .nwb path")
    parser.add_argument("--subject-id", type=str, default="subject_01")
    parser.add_argument(
        "--session-description", type=str, default="Pinnacle PVFS recording"
    )
    parser.add_argument(
        "--no-video", action="store_true", help="Skip video conversion"
    )
    args = parser.parse_args()

    out_path = args.out or args.pvfs_file.with_suffix(".nwb")

    converter = PvfsNWBConverter(
        file_path=args.pvfs_file,
        include_video=not args.no_video,
    )

    metadata = converter.get_metadata()
    metadata["NWBFile"]["session_description"] = args.session_description
    metadata["Subject"]["subject_id"] = args.subject_id

    converter.run_conversion(
        nwbfile_path=str(out_path), metadata=metadata, overwrite=True
    )
    print(f"Wrote NWB file: {out_path}")


if __name__ == "__main__":
    main()
