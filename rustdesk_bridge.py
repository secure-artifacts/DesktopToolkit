"""Locate / launch RustDesk — prefers bundled engine so users need not install separately."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DOWNLOAD_URL = "https://rustdesk.com/"
SOURCE_URL = "https://github.com/rustdesk/rustdesk"
BUNDLED_VERSION = "1.4.9"


@dataclass
class RustDeskStatus:
    installed: bool
    exe: Path | None
    local_id: str
    message: str
    source: str = ""  # bundled | extracted | system | custom


def _bundle_root() -> Path:
    try:
        from skin import bundle_root

        return bundle_root()
    except Exception:
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                return Path(meipass)
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent


def _user_extract_dir() -> Path:
    """Where the official Windows self-extractor unpacks the real client."""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "rustdesk"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/DesktopToolkit/rustdesk"
    return Path.home() / ".local/share/DesktopToolkit/rustdesk"


def bundled_setup_path() -> Path | None:
    """Packaged installer / portable launcher shipped with this app."""
    root = _bundle_root() / "vendor" / "rustdesk"
    names: list[str]
    if sys.platform == "win32":
        names = [
            "win/rustdesk.exe",
            f"win/rustdesk-{BUNDLED_VERSION}-x86_64.exe",
            "win/rustdesk-setup.exe",
        ]
    elif sys.platform == "darwin":
        names = [
            "mac/RustDesk.app/Contents/MacOS/rustdesk",
            "mac/rustdesk",
            f"mac/rustdesk-{BUNDLED_VERSION}-x86_64.dmg",
        ]
    else:
        names = ["linux/rustdesk"]
    for rel in names:
        p = root / rel
        if p.is_file():
            return p
    return None


def _extracted_exe() -> Path | None:
    d = _user_extract_dir()
    for name in ("rustdesk.exe", "RustDesk.exe", "rustdesk"):
        p = d / name
        if p.is_file():
            return p
    return None


def _candidate_exes(extra: str | None = None) -> list[tuple[Path, str]]:
    """Ordered (path, source) candidates."""
    out: list[tuple[Path, str]] = []

    if extra:
        p = Path(extra).expanduser()
        if p.is_file():
            out.append((p, "custom"))
        elif p.is_dir():
            for name in ("rustdesk.exe", "rustdesk", "RustDesk.exe"):
                cand = p / name
                if cand.is_file():
                    out.append((cand, "custom"))

    extracted = _extracted_exe()
    if extracted:
        out.append((extracted, "extracted"))

    bundled = bundled_setup_path()
    if bundled:
        out.append((bundled, "bundled"))

    which = shutil.which("rustdesk") or shutil.which("RustDesk")
    if which:
        out.append((Path(which), "system"))

    if sys.platform == "win32":
        env = os.environ
        roots = [
            Path(env.get("ProgramFiles", r"C:\Program Files")) / "RustDesk",
            Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "RustDesk",
            Path(env.get("LOCALAPPDATA", "")) / "Programs" / "RustDesk",
        ]
        for root in roots:
            for name in ("rustdesk.exe", "RustDesk.exe"):
                cand = root / name
                if cand.is_file():
                    out.append((cand, "system"))
    elif sys.platform == "darwin":
        for p in (
            Path("/Applications/RustDesk.app/Contents/MacOS/rustdesk"),
            Path("/Applications/RustDesk.app/Contents/MacOS/RustDesk"),
            Path.home() / "Applications/RustDesk.app/Contents/MacOS/rustdesk",
        ):
            if p.is_file():
                out.append((p, "system"))

    seen: set[str] = set()
    uniq: list[tuple[Path, str]] = []
    for path, src in out:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((path, src))
    return uniq


def find_rustdesk_exe(extra: str | None = None) -> Path | None:
    for p, _src in _candidate_exes(extra):
        if p.is_file():
            return p
    return None


def find_rustdesk(extra: str | None = None) -> tuple[Path | None, str]:
    for p, src in _candidate_exes(extra):
        if p.is_file():
            return p, src
    return None, ""


def ensure_extracted(extra: str | None = None) -> Path | None:
    """
    Ensure a runnable client exists under the user extract dir.

    Official Windows GitHub builds are self-extractors: first launch unpacks into
    %LOCALAPPDATA%\\rustdesk\\ then runs that copy. We trigger a quiet --get-id
    once so subsequent launches can use the extracted binary.
    """
    extracted = _extracted_exe()
    if extracted:
        return extracted

    setup = bundled_setup_path()
    if extra:
        ep = Path(extra).expanduser()
        if ep.is_file():
            setup = ep
    if setup is None or not setup.is_file():
        return find_rustdesk_exe(extra)

    if sys.platform != "win32":
        # Mac/Linux: bundled .app path is already runnable when present
        return setup if setup.suffix.lower() != ".dmg" else find_rustdesk_exe(extra)

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [str(setup), "--get-id"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(setup.parent),
            creationflags=creationflags,
        )
    except Exception:
        pass

    extracted = _extracted_exe()
    return extracted or setup


def _config_paths() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        return [
            appdata / "RustDesk" / "config" / "RustDesk.toml",
            appdata / "RustDesk" / "RustDesk.toml",
            _user_extract_dir() / "config" / "RustDesk.toml",
        ]
    if sys.platform == "darwin":
        return [
            home / "Library/Preferences/com.carriez.RustDesk/RustDesk.toml",
            home / "Library/Preferences/RustDesk/RustDesk.toml",
        ]
    return [
        home / ".config/RustDesk/RustDesk.toml",
        home / ".config/rustdesk/RustDesk.toml",
    ]


def _parse_id_from_toml(text: str) -> str:
    m = re.search(r'(?m)^\s*id\s*=\s*"([^"]+)"\s*$', text)
    if m:
        val = m.group(1).strip()
        if val and not val.startswith("00"):
            return val
    return ""


def read_id_from_config() -> str:
    for path in _config_paths():
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            got = _parse_id_from_toml(text)
            if got:
                return got
        except Exception:
            continue
    return ""


def get_id_via_cli(exe: Path) -> str:
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [str(exe), "--get-id"],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(exe.parent),
            creationflags=creationflags,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # Self-extractor prints lots of "skip ..." lines; ID is usually the last integer token.
        ids = re.findall(r"(?m)^(\d{6,})\s*$", out)
        if ids:
            return ids[-1]
        m = re.search(r"([A-Za-z0-9][A-Za-z0-9\-]{5,})", out.strip().splitlines()[-1] if out.strip() else "")
        if m and not m.group(1).lower().startswith("skip"):
            return m.group(1)
    except Exception:
        pass
    return ""


def probe(extra_path: str | None = None) -> RustDeskStatus:
    exe, src = find_rustdesk(extra_path)
    if not exe:
        return RustDeskStatus(
            installed=False,
            exe=None,
            local_id="",
            message="未找到远程引擎。安装包应内置 RustDesk；也可点下方官网下载。",
            source="",
        )

    # Prefer extracted client for ID / subsequent launches
    if src == "bundled":
        ensured = ensure_extracted(extra_path)
        if ensured:
            exe = ensured
            src = "extracted" if ensured == _extracted_exe() else src

    local_id = get_id_via_cli(exe) or read_id_from_config()
    # Re-resolve after first extract
    extracted = _extracted_exe()
    if extracted:
        exe = extracted
        src = "extracted"
        if not local_id:
            local_id = get_id_via_cli(exe) or read_id_from_config()

    if src == "bundled":
        label = "内置引擎（首次启动会解压）"
    elif src == "extracted":
        label = "内置引擎（已就绪）"
    elif src == "system":
        label = "系统已安装的 RustDesk"
    else:
        label = "自定义路径"

    if local_id:
        msg = f"{label} · 就绪"
    else:
        msg = f"{label} · 请点「启动远程引擎」后查看本机 ID（或再点刷新）"
    return RustDeskStatus(installed=True, exe=exe, local_id=local_id, message=msg, source=src)


def launch_rustdesk(exe: Path | None = None, extra_path: str | None = None) -> str:
    path = exe or ensure_extracted(extra_path) or find_rustdesk_exe(extra_path)
    if path is None:
        if sys.platform == "darwin":
            try:
                subprocess.Popen(["open", "-a", "RustDesk"])
                return "已尝试启动系统 RustDesk"
            except Exception as e:
                return f"启动失败：{e}"
        return "未找到内置远程引擎"
    try:
        if sys.platform == "darwin" and "RustDesk.app" in str(path):
            app = path
            while app.name != "RustDesk.app" and app.parent != app:
                app = app.parent
            if app.suffix == ".app":
                subprocess.Popen(["open", str(app)])
            else:
                subprocess.Popen(["open", "-a", "RustDesk"])
        else:
            subprocess.Popen([str(path)], cwd=str(path.parent))
        return "已启动远程引擎（RustDesk）"
    except Exception as e:
        return f"启动失败：{e}"


def connect_to(peer: str, exe: Path | None = None, extra_path: str | None = None) -> str:
    peer = (peer or "").strip()
    if not peer:
        return "请填写对方 ID 或局域网 IP"
    path = exe or ensure_extracted(extra_path) or find_rustdesk_exe(extra_path)
    if path is None:
        return "未找到内置远程引擎"
    # Prefer extracted binary for --connect
    extracted = _extracted_exe()
    if extracted:
        path = extracted
    try:
        subprocess.Popen([str(path), "--connect", peer], cwd=str(path.parent))
        return f"正在连接 {peer}…"
    except Exception as e:
        return f"连接失败：{e}"
