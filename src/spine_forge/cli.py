"""Command line entry point.

Every subcommand is a single file-in / file-out step so an agent can drive the
pipeline one call at a time, and a human can edit the JSON in between.

    spine-forge split   <image>          --out ./out
    spine-forge rig     ./out/parts.json --out ./out/rig.json
    spine-forge build   ./out/rig.json   --out ./out/dist
    spine-forge preview ./out/dist/skeleton.json --out ./out/preview.html
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from . import __version__

Command = Callable[[argparse.Namespace], dict[str, Any]]


def _cmd_split(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import split

    return split.run(
        args.image,
        args.out,
        kind=args.splitter,
        previews=not args.no_preview,
    )


def _cmd_rig(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import rig

    return rig.run(args.parts, args.out, name=args.name)


def _cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import build

    return build.run(args.rig, args.out)


def _cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import preview

    # preview expects the rig document; build writes it beside the atlas page.
    return preview.run(args.rig, args.out)


def _cmd_skeleton(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import skeleton

    return skeleton.run(
        args.image,
        args.out,
        marks_path=args.marks,
        spec_path=args.joints,
        name=args.name,
        snap=not args.no_snap,
    )


def _cmd_assemble(args: argparse.Namespace) -> dict[str, Any]:
    from .stages import assemble

    # assemble self-checks the document before writing (see core/verify.py).
    return assemble.run(
        args.parts,
        args.bones,
        args.out,
        name=args.name,
        mode=args.mode,
        warp=args.warp,
        leg_control=args.leg_control,
    )


def _cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    from .core.verify import check_document

    with open(args.skeleton, encoding="utf-8") as handle:
        document = json.load(handle)
    problems = check_document(document)
    if problems:
        raise ValueError("problems:\n  " + "\n  ".join(problems))
    return {"skeleton": args.skeleton, "problems": 0}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spine-forge",
        description="One image -> body parts -> skeleton -> Spine 4.2 project.",
    )
    parser.add_argument("--version", action="version", version=f"spine-forge {__version__}")
    # Emit a machine-readable result object. Accepted both globally and on every
    # subcommand, because agents naturally write `spine-forge split x --json`.
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable result object on stdout",
    )

    # Shared parent so each subcommand accepts --json in the position people
    # actually type it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="emit a machine-readable result object on stdout",
    )

    subs = parser.add_subparsers(dest="command", required=True)

    p_split = subs.add_parser("split", parents=[common], help="split one image into part PNGs")
    p_split.add_argument("image", help="source PNG")
    p_split.add_argument("--out", required=True, help="output directory")
    p_split.add_argument(
        "--splitter",
        choices=("alpha", "colour"),
        default="alpha",
        help="alpha = parts already detached by transparency; colour = flat illustration "
        "separated by fill colour (see docs/parts-splitting.md)",
    )
    p_split.add_argument(
        "--no-preview",
        action="store_true",
        help="skip the contact sheet and reassembly check",
    )
    p_split.set_defaults(func=_cmd_split)

    p_rig = subs.add_parser(
        "rig", parents=[common], help="parts.json -> rig.json (bones, slots, attachments)"
    )
    p_rig.add_argument("parts", help="path to parts.json produced by split")
    p_rig.add_argument("--out", required=True, help="output rig.json path")
    p_rig.add_argument("--name", default="character", help="skeleton name")
    p_rig.set_defaults(func=_cmd_rig)

    p_build = subs.add_parser(
        "build", parents=[common], help="rig.json -> Spine project (skeleton.json + atlas)"
    )
    p_build.add_argument("rig", help="path to rig.json")
    p_build.add_argument("--out", required=True, help="output directory for the Spine project")
    p_build.set_defaults(func=_cmd_build)

    p_preview = subs.add_parser(
        "preview", parents=[common], help="rig.json or skeleton.json -> self-contained HTML"
    )
    p_preview.add_argument("rig", help="path to rig.json, or a built skeleton.json")
    p_preview.add_argument("--out", required=True, help="output .html path")
    p_preview.set_defaults(func=_cmd_preview)

    p_skel = subs.add_parser(
        "skeleton",
        parents=[common],
        help="marked artwork + joint table -> bones.json + review panel",
    )
    p_skel.add_argument("image", help="artwork (or a copy carrying the human's ring marks)")
    p_skel.add_argument("--out", required=True, help="output directory")
    p_skel.add_argument(
        "--marks",
        help="image with ring marks, or a marks JSON; defaults to the artwork itself",
    )
    p_skel.add_argument(
        "--joints",
        help="joint table JSON (name/parent/base/tip); omit to only read the marks",
    )
    p_skel.add_argument("--name", default="character", help="skeleton name")
    p_skel.add_argument(
        "--no-snap",
        action="store_true",
        help="keep the table's coordinates instead of pulling them onto nearby marks",
    )
    p_skel.set_defaults(func=_cmd_skeleton)

    p_assemble = subs.add_parser(
        "assemble",
        parents=[common],
        help="parts.json + bones.json -> Spine project (skeleton.json + atlas + page)",
    )
    p_assemble.add_argument("parts", help="parts.json produced by split")
    p_assemble.add_argument("--bones", required=True, help="bones.json produced by skeleton")
    p_assemble.add_argument("--out", required=True, help="output directory")
    p_assemble.add_argument("--name", help="skeleton name (defaults to the one in bones.json)")
    p_assemble.add_argument(
        "--mode",
        choices=("atlas", "images"),
        default="atlas",
        help="atlas = one packed page + .atlas (web runtime); images = one PNG per part "
        "next to the skeleton (what the Spine editor opens without an atlas)",
    )
    p_assemble.add_argument(
        "--warp",
        choices=("none", "legs"),
        default="none",
        help="legs = one weighted mesh per leg (bends at the knee by warping one "
        "image) instead of two rigid cut halves",
    )
    p_assemble.add_argument(
        "--leg-control",
        choices=("ik", "path"),
        default="ik",
        help="ik = drag the foot target; path = drag a curve the leg follows "
        "(needs the leg bones, replaces their IK)",
    )
    p_assemble.set_defaults(func=_cmd_assemble)

    p_check = subs.add_parser(
        "check",
        parents=[common],
        help="validate a built skeleton.json (mesh weights, uvs, indices, constraints)",
    )
    p_check.add_argument("skeleton", help="skeleton.json / girl.json to validate")
    p_check.set_defaults(func=_cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.func(args)
    except Exception as exc:  # surfaced as a readable message, not a traceback
        print(f"error: {exc}", file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    payload = {"ok": True, **result}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
