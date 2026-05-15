"""Command-line entry point for ``pvfs-to-nwb``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pvfsnwbconverter import PvfsNWBConverter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pvfs-to-nwb",
        description="Convert a Pinnacle PVFS recording to a Neurodata Without Borders (NWB) file.",
    )
    parser.add_argument(
        "pvfs_file",
        type=Path,
        help="Input .pvfs file produced by Pinnacle hardware.",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Output .nwb path. Defaults to '<input>.nwb' next to the .pvfs file.",
    )
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Skip video conversion entirely (no .webm or ImageSeries).",
    )
    parser.add_argument(
        "--no-annotations",
        action="store_true",
        help="Skip PVFS annotations (no NWB epochs).",
    )
    parser.add_argument(
        "--embed-frames",
        action="store_true",
        help=(
            "Decode and inline video frames into the NWB file instead of "
            "writing an external .webm. Can produce very large NWB files."
        ),
    )
    parser.add_argument(
        "--video-output-dir",
        type=Path,
        default=None,
        help="Directory for exported .webm files. Defaults to the NWB output directory.",
    )
    parser.add_argument(
        "--subject-id",
        type=str,
        default=None,
        help="Override the NWB Subject.subject_id field.",
    )
    parser.add_argument(
        "--subject-age",
        type=str,
        default=None,
        help=(
            "Override Subject.age (ISO 8601 duration, e.g. P90D). "
            "Defaults to P0D when not specified."
        ),
    )
    parser.add_argument(
        "--session-description",
        type=str,
        default=None,
        help="Override the NWB session_description field.",
    )
    parser.add_argument(
        "--experimenter",
        type=str,
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "Experimenter name in DANDI form 'Last, First'. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--institution",
        type=str,
        default=None,
        help="Override NWBFile.institution.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output NWB file if it already exists.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress information.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    pvfs_path = args.pvfs_file.expanduser().resolve()
    if not pvfs_path.exists():
        print(f"error: PVFS file not found: {pvfs_path}", file=sys.stderr)
        return 2

    out_path = (
        args.out.expanduser().resolve()
        if args.out is not None
        else pvfs_path.with_suffix(".nwb")
    )

    converter = PvfsNWBConverter(
        file_path=pvfs_path,
        include_annotations=not args.no_annotations,
        include_video=not args.no_video,
        video_output_dir=args.video_output_dir,
        embed_frames=args.embed_frames,
        verbose=args.verbose,
    )

    metadata = converter.get_metadata()
    if args.session_description is not None:
        metadata.setdefault("NWBFile", {})
        metadata["NWBFile"]["session_description"] = args.session_description
        metadata["NWBFile"]["experiment_description"] = args.session_description
    if args.subject_id is not None:
        metadata.setdefault("Subject", {})
        metadata["Subject"]["subject_id"] = args.subject_id
    if args.subject_age is not None:
        metadata.setdefault("Subject", {})
        metadata["Subject"]["age"] = args.subject_age
    if args.experimenter:
        metadata.setdefault("NWBFile", {})
        metadata["NWBFile"]["experimenter"] = list(args.experimenter)
    if args.institution is not None:
        metadata.setdefault("NWBFile", {})
        metadata["NWBFile"]["institution"] = args.institution

    converter.run_conversion(
        nwbfile_path=str(out_path),
        metadata=metadata,
        overwrite=args.overwrite,
    )

    if args.verbose:
        print(f"Wrote NWB file: {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
