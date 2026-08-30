"""Check for application updates from GitHub Releases; optional download + run installer."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Bump when shipping a new installer (keep in sync with VERSION file).
APP_VERSION = "1.7.1"

# Public releases channel (organization repo)
GITHUB_REPO = "secure-artifacts/DesktopToolkit"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


def get_app_version() -> str:
    """Prefer packaged VERSION file, then APP_VERSION constant."""
    try:
        from skin import bundle_root

        vf = bundle_root() / "VERSION"
        if vf.is_file():
            text = vf.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
    except Exception:
        pass
    return APP_VERSION


@dataclass
class UpdateCheckResult:
    ok: bool
    current: str
    latest: str
    has_update: bool
    message: str
    release_url: str
    download_url: str = ""
    asset_name: str = ""


def _normalize_version(text: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", text or "0")]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:4])


def check_for_update(timeout: float = 8.0) -> UpdateCheckResult:
    """Query GitHub latest release. Network failures return ok=False (no crash)."""
    current = get_app_version()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"DesktopToolkit/{current}",
    }
    try:
        req = urllib.request.Request(RELEASES_API, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return UpdateCheckResult(
            ok=False,
            current=current,
            latest="",
            has_update=False,
            message=f"妫€鏌ユ洿鏂板け璐ワ細{exc}",
            release_url=RELEASES_PAGE,
        )

    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest = tag.lstrip("vV")
    html_url = str(payload.get("html_url") or RELEASES_PAGE)
    # Prefer platform-matching assets (Mac must not pick Windows setup.exe)
    download = ""
    asset_name = ""
    candidates: list[tuple[int, str, str]] = []
    is_mac = sys.platform == "darwin"
    is_win = sys.platform.startswith("win")
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        low = name.lower()
        if is_mac:
            if "macos" in low and low.endswith(".zip"):
                candidates.append((0, url, name))
            elif low.endswith(".dmg"):
                candidates.append((1, url, name))
            elif low.endswith(".zip") and "windows" not in low and "win" not in low:
                candidates.append((2, url, name))
        elif is_win:
            if "setup" in low and low.endswith(".exe"):
                candidates.append((0, url, name))
            elif low.endswith(".exe"):
                candidates.append((1, url, name))
            elif "portable" in low and low.endswith(".zip"):
                candidates.append((2, url, name))
            elif low.endswith(".zip") or low.endswith(".7z"):
                candidates.append((3, url, name))
        else:
            if low.endswith(".zip") or low.endswith(".7z") or low.endswith(".exe"):
                candidates.append((5, url, name))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        download, asset_name = candidates[0][1], candidates[0][2]

    if not latest:
        return UpdateCheckResult(
            ok=False,
            current=current,
            latest="",
            has_update=False,
            message="鏈壘鍒板彂甯冪増鏈俊鎭€?,
            release_url=html_url,
        )

    has_update = _normalize_version(latest) > _normalize_version(current)
    if has_update:
        msg = f"鍙戠幇鏂扮増鏈?{latest}锛堝綋鍓?{current}锛夈€?
    else:
        msg = f"宸叉槸鏈€鏂扮増鏈?{current}銆?
    return UpdateCheckResult(
        ok=True,
        current=current,
        latest=latest,
        has_update=has_update,
        message=msg,
        release_url=html_url,
        download_url=download,
        asset_name=asset_name,
    )


def download_update(
    url: str,
    *,
    dest_dir: Path | None = None,
    filename: str | None = None,
    timeout: float = 120.0,
    progress_cb=None,
) -> Path:
    """Download installer/asset to a local file. Raises on failure."""
    if not url or not str(url).startswith("http"):
        raise ValueError("娌℃湁鍙笅杞界殑瀹夎鍖呭湴鍧€锛岃鎵撳紑涓嬭浇椤垫墜鍔ㄨ幏鍙栥€?)
    low = str(url).lower()
    if "/releases/tag/" in low and not any(low.endswith(ext) for ext in (".exe", ".zip", ".7z")):
        raise ValueError("娌℃湁鍙笅杞界殑瀹夎鍖呭湴鍧€锛岃鎵撳紑涓嬭浇椤垫墜鍔ㄨ幏鍙栥€?)
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "DesktopToolkitUpdates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = (filename or "").strip() or urllib_parse_unquote_name(url) or "DesktopToolkit-update.exe"
    # sanitize
    name = re.sub(r"[^\w.\-]+", "_", name)[:120] or "update.bin"
    dest = dest_dir / name
    headers = {"User-Agent": f"DesktopToolkit/{APP_VERSION}"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        chunk = 256 * 1024
        with dest.open("wb") as f:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                f.write(block)
                done += len(block)
                if progress_cb and total > 0:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    if not dest.is_file() or dest.stat().st_size < 1024:
        raise RuntimeError("涓嬭浇鏂囦欢鏃犳晥鎴栬繃灏忋€?)
    return dest


def urllib_parse_unquote_name(url: str) -> str:
    try:
        from urllib.parse import unquote, urlparse

        path = urlparse(url).path
        return unquote(path.rsplit("/", 1)[-1])
    except Exception:
        return "update.bin"


def launch_installer(path: Path) -> None:
    """Start setup.exe / open zip folder. Caller may exit the app afterward."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if sys.platform == "win32":
        # Detached process so install can replace running files after exit
        subprocess.Popen(
            [str(path)],
            cwd=str(path.parent),
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    else:
        subprocess.Popen([str(path)], cwd=str(path.parent))

