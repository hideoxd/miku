"""Render a 3D model (.glb/.gltf) into the Miku mascot asset.

Renders the model from a 3/4 front view, removes the background via a Hugging
Face Space, crops, and saves to src/friday/assets/miku.png (what the overlay
shows). Re-run this to change the model or the camera angle.

    pip install trimesh "pyglet<2" gradio_client
    python scripts/render_mascot.py C:\\path\\to\\model.glb --az 25

Needs an HF token (FRIDAY_HF_TOKEN in .env) for background removal, and opens a
brief GL window while rendering.
"""

from __future__ import annotations

import argparse
import os
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a 3D model into the mascot asset")
    ap.add_argument("model", help="path to a .glb/.gltf model")
    ap.add_argument("--az", type=float, default=25, help="azimuth degrees (0 = dead front)")
    ap.add_argument("--width", type=int, default=480, help="output asset width px")
    args = ap.parse_args(argv)

    import numpy as np
    import trimesh
    from PIL import Image
    from trimesh.transformations import rotation_matrix as rot

    print(f"loading {args.model} …")
    scene = trimesh.load(args.model)
    scene.apply_transform(rot(np.radians(args.az), [0, 1, 0], scene.centroid))
    print("rendering (a GL window will flash)…")
    png = scene.save_image(resolution=(640, 900), visible=True)
    rendered = ROOT / "cache" / "mascot_render.png"
    rendered.parent.mkdir(exist_ok=True)
    Image.open(BytesIO(png)).convert("RGB").save(rendered)

    from friday.config import get_settings

    token = get_settings().resolved_hf_token
    if not token:
        print("No HF token — set FRIDAY_HF_TOKEN in .env for background removal.")
        return 1
    os.environ["HF_TOKEN"] = token
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

    from gradio_client import Client, handle_file

    print("removing background via Hugging Face…")
    client = Client("not-lain/background-removal", token=token, verbose=False)
    res = client.predict(handle_file(str(rendered)), api_name="/png")
    path = res if isinstance(res, str) else (res[0] if isinstance(res, (list, tuple)) else res)

    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getchannel("A").getbbox())
    h = int(im.height * args.width / im.width)
    im = im.resize((args.width, h), Image.LANCZOS)
    dest = ROOT / "src" / "friday" / "assets" / "miku.png"
    im.save(dest)
    print(f"saved mascot asset -> {dest}  ({im.size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
