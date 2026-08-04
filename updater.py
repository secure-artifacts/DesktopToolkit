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

# Bump when shipping a new installer.
APP_VERSION = "1.1.1"
# Public releases channel (organization repo — no personal account)
GITHUB_REPO = "secure-artifacts/DesktopToolkit"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


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
    current = APP_VERSION
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"DesktopToolkit/{APP_VERSION}",
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
            message=f"检查更新失败：{exc}",
            release_url=RELEASES_PAGE,
        )

    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest = tag.lstrip("vV")
    html_url = str(payload.get("html_url") or RELEASES_PAGE)
    # Prefer setup.exe, then portable zip, then any asset
    download = ""
    asset_name = ""
    candidates: list[tuple[int, str, str]] = []
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        low = name.lower()
        if "setup" in low and low.endswith(".exe"):
            candidates.append((0, url, name))
        elif low.endswith(".exe"):
            candidates.append((1, url, name))
        elif "portable" in low and low.endswith(".zip"):
            candidates.append((2, url, name))
        elif low.endswith(".zip") or low.endswith(".7z"):
            candidates.append((3, url, name))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        download, asset_name = candidates[0][1], candidates[0][2]

    if not latest:
        return UpdateCheckResult(
            ok=False,
            current=current,
            latest="",
            has_update=False,
            message="未找到发布版本信息。",
            release_url=html_url,
        )

    has_update = _normalize_version(latest) > _normalize_version(current)
    if has_update:
        msg = f"发现新版本 {latest}（当前 {current}）。"
    else:
        msg = f"已是最新版本 {current}。"
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
        raise ValueError("没有可下载的安装包地址，请打开下载页手动获取。")
    low = str(url).lower()
    if "/releases/tag/" in low and not any(low.endswith(ext) for ext in (".exe", ".zip", ".7z")):
        raise ValueError("没有可下载的安装包地址，请打开下载页手动获取。")
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
        raise RuntimeError("下载文件无效或过小。")
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
