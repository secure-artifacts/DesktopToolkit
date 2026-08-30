"""Download official RustDesk Windows build into vendor/ for bundling.

Usage:
  python tools/fetch_rustdesk.py
  python tools/fetch_rustdesk.py --version 1.4.9

Mac: place RustDesk.app under vendor/rustdesk/mac/ manually (or extend this script).
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "1.4.9"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    args = ap.parse_args()
    ver = args.version.strip()
    name = f"rustdesk-{ver}-x86_64.exe"
    url = f"https://github.com/rustdesk/rustdesk/releases/download/{ver}/{name}"
    dest_dir = ROOT / "vendor" / "rustdesk" / "win"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "rustdesk.exe"
    versioned = dest_dir / name

    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, versioned)
    # Single name used by rustdesk_bridge.bundled_setup_path()
    versioned.replace(dest) if False else None
    # Keep both: versioned archive name + rustdesk.exe for runtime
    import shutil

    shutil.copy2(versioned, dest)
    print(f"Wrote {dest} ({dest.stat().st_size} bytes)")
    print(f"Kept  {versioned}")
    print("AGPL notice: see vendor/rustdesk/NOTICE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
