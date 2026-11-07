"""Generate one skin part and save it, for end-to-end verification.

Usage:
    python tools/gen_skin.py --part head-base --subject "pigeon head" \
        --reference examples/owl/images/head-base.png --out examples/owl/skins

The prompt actually sent is printed, so the wording can be inspected rather than
guessed at when the result looks wrong. It is printed *before* the request is
made, so a bad prompt can be spotted without spending an API call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from spine_forge.config import load_env
from spine_forge.skins import SkinRequest, build_provider
from spine_forge.skins import prompts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", required=True, help="slot or attachment name")
    parser.add_argument("--subject", required=True, help="what to draw")
    parser.add_argument("--reference", help="image being replaced")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--style", default="flat-vector",
                        help="style key (flat-vector, cartoon, pixel, ...) or free text")
    parser.add_argument("--instruction", help="override the composed prompt")
    parser.add_argument("--provider", help="override SPINE_SKIN_PROVIDER")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the prompt and exit without calling the service")
    parser.add_argument("--no-matte", action="store_true",
                        help="skip background removal on the result")
    parser.add_argument("--no-normalize", action="store_true",
                        help="skip resizing the result against the reference")
    args = parser.parse_args()

    load_env()

    reference = None
    if args.reference:
        reference = Image.open(args.reference).convert("RGBA")

    request = SkinRequest(
        part=args.part,
        subject=args.subject,
        reference=reference,
        width=args.width,
        height=args.height,
        style=args.style,
        instruction=args.instruction,
    )

    print("=== prompt ===")
    print(prompts.compose(request))
    print()
    print("=== negative ===")
    print(prompts.negative(request))
    print()

    if args.dry_run:
        print("(dry run: no request sent)")
        return 0

    provider = build_provider(args.provider)
    print(f"provider : {provider.name}")

    result = provider.generate(request)
    print(f"model    : {result.model}")
    print(f"raw size : {result.image.size[0]}x{result.image.size[1]}")
    for note in result.notes:
        print(f"note     : {note}")

    image = result.image
    if reference is not None and (not args.no_matte or not args.no_normalize):
        from spine_forge.skins.postprocess import prepare

        # reference_scale=1.0: the file on disk is full resolution. Using 0.5
        # here would double the target size, which is what pushed the bone
        # scale to 2.84 in an earlier run.
        image = prepare(
            image,
            reference,
            matte=not args.no_matte,
            mode="height",
            reference_scale=1.0,
        )
        print(f"prepared : {image.size[0]}x{image.size[1]}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{args.part}.png"
    image.save(target)
    print(f"saved    : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
