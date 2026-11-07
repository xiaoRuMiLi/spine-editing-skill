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

    return split.run(args.image, args.out)


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
    p_split.add_argument("image", help="source PNG with a transparent background")
    p_split.add_argument("--out", required=True, help="output directory")
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
