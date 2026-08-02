"""Check for application updates from GitHub Releases."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

# Bump when shipping a new installer.
APP_VERSION = "1.0.5"
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
    download = ""
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "").lower()
        url = str(asset.get("browser_download_url") or "")
        if url and ("setup" in name or name.endswith(".exe") or name.endswith(".7z") or name.endswith(".zip")):
            download = url
            break
    if not download:
        download = html_url

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
    )
