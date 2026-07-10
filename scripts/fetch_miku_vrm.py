"""Fetch a rigged Hatsune Miku VRM model for the real-time 3D mascot.

Downloads a free fan-made Miku VRM (5 MB 7z archive), extracts it, and installs
it as models/miku.vrm — the file the mascot3d Electron app animates. Re-run with
--force to refresh, or point --file at a .vrm/.7z you downloaded yourself.

    pip install py7zr        (or: pip install -e .[mascot3d])
    python scripts/fetch_miku_vrm.py

License: the model is fan-made (character (c) Crypton Future Media). Personal,
non-commercial use only; do not redistribute or use in VRChat.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "models" / "miku.vrm"
CACHE = ROOT / "cache"

# Tried in order; each is a ~5 MB 7z containing a .vrm somewhere inside.
URLS = [
    "https://raw.githubusercontent.com/outrine/HatsuneMiku_VRM_Model/main/Model_Miku_V2.7z",
    "https://raw.githubusercontent.com/outrine/HatsuneMiku_VRM_Model/main/Model_Miku.7z",
]

LICENSE_NOTE = (
    "Note: fan-made model, character (c) Crypton Future Media. Personal,\n"
    "non-commercial use only — do not redistribute or use in VRChat."
)


def _download(url: str, dest: Path) -> None:
    print(f"downloading {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": "friday-mascot-setup"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    if dest.stat().st_size < 1_000_000:
        raise RuntimeError(f"downloaded file suspiciously small ({dest.stat().st_size} bytes)")


def _extract_vrm(archive: Path) -> Path:
    """Extract the 7z and return the largest .vrm found inside."""
    try:
        import py7zr
    except ImportError:
        sys.exit("py7zr is required to extract the model archive:  pip install py7zr")

    out = CACHE / "miku_vrm_extract"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    print(f"extracting {archive.name} …")
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(out)

    vrms = sorted(out.rglob("*.vrm"), key=lambda p: p.stat().st_size, reverse=True)
    if not vrms:
        listing = "\n  ".join(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
        raise RuntimeError(f"no .vrm inside the archive; contents were:\n  {listing}")
    return vrms[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch the rigged Miku VRM for the 3D mascot")
    ap.add_argument("--url", help="override download URL (a .7z or .vrm)")
    ap.add_argument("--file", help="use a local .vrm or .7z instead of downloading")
    ap.add_argument("--force", action="store_true", help="overwrite an existing models/miku.vrm")
    args = ap.parse_args(argv)

    if DEST.exists() and not args.force:
        print(f"already installed: {DEST} ({DEST.stat().st_size / 1e6:.1f} MB) — use --force to refresh")
        return 0

    CACHE.mkdir(exist_ok=True)
    DEST.parent.mkdir(exist_ok=True)

    src: Path | None = None
    if args.file:
        src = Path(args.file)
        if not src.exists():
            sys.exit(f"no such file: {src}")
    else:
        archive = CACHE / "miku_vrm.7z"
        errors = []
        for url in [args.url] if args.url else URLS:
            try:
                _download(url, archive)
                src = archive
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
        if src is None:
            print("all downloads failed:\n  " + "\n  ".join(errors))
            print("\nManual fallback: download any rigged Miku .vrm (e.g. BOOTH/VRoid)")
            print(f"and run:  python scripts/fetch_miku_vrm.py --file path\\to\\model.vrm")
            return 1

    vrm = src if src.suffix.lower() == ".vrm" else _extract_vrm(src)
    shutil.copyfile(vrm, DEST)
    print(f"installed {vrm.name} -> {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
    print(LICENSE_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
