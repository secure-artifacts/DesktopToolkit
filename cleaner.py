"""Windows deep-clean helpers for browser cache, temp files, recycle bin, etc."""

from __future__ import annotations

import os
import shutil
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class CleanReport:
    bytes_freed: int = 0
    files_removed: int = 0
    folders_touched: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def megabytes(self) -> float:
        return self.bytes_freed / (1024 * 1024)

    def summary(self) -> str:
        mb = self.megabytes
        if mb >= 1024:
            size_text = f"{mb / 1024:.2f} GB"
        else:
            size_text = f"{mb:.1f} MB"
        return (
            f"清理完成！释放约 {size_text}，"
            f"处理 {self.files_removed} 个文件"
            + (f"（{len(self.notes)} 项）" if self.notes else "")
            + "。"
        )


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _force_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _remove_path(path: Path, report: CleanReport) -> None:
    if not path.exists():
        return
    try:
        if path.is_file() or path.is_symlink():
            size = _safe_size(path)
            _force_writable(path)
            path.unlink(missing_ok=True)
            report.bytes_freed += size
            report.files_removed += 1
            return
        if path.is_dir():
            for child in path.iterdir():
                _remove_path(child, report)
            try:
                path.rmdir()
            except OSError:
                pass
            report.folders_touched += 1
    except OSError as exc:
        report.errors.append(f"{path.name}: {exc}")


def _clear_directory_contents(directory: Path, report: CleanReport, label: str) -> None:
    if not directory.exists() or not directory.is_dir():
        return
    before = report.bytes_freed
    try:
        for child in directory.iterdir():
            # Skip locked system-critical names defensively.
            name = child.name.lower()
            if name in {"desktop.ini", "thumbs.db"} and "temp" not in str(directory).lower():
                continue
            _remove_path(child, report)
    except OSError as exc:
        report.errors.append(f"{label}: {exc}")
        return
    freed = report.bytes_freed - before
    if freed > 0 or report.files_removed > 0:
        report.notes.append(label)


def _browser_cache_roots() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    roots: list[tuple[str, Path]] = []
    candidates = [
        ("Chrome 缓存", local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"),
        ("Chrome Code Cache", local / "Google" / "Chrome" / "User Data" / "Default" / "Code Cache"),
        ("Edge 缓存", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"),
        ("Edge Code Cache", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Code Cache"),
        ("Firefox 缓存", local / "Mozilla" / "Firefox" / "Profiles"),
        ("浏览器 GPUCache", local / "Google" / "Chrome" / "User Data" / "Default" / "GPUCache"),
        ("Edge GPUCache", local / "Microsoft" / "Edge" / "User Data" / "Default" / "GPUCache"),
    ]
    # Also clear nested Firefox cache2 folders.
    for label, path in candidates:
        if label.startswith("Firefox") and path.exists():
            for profile in path.glob("*"):
                cache2 = profile / "cache2"
                if cache2.exists():
                    roots.append((f"Firefox {profile.name} 缓存", cache2))
            continue
        roots.append((label, path))
    # roaming IE/legacy leftovers
    ie = local / "Microsoft" / "Windows" / "INetCache"
    roots.append(("IE/兼容缓存", ie))
    del roaming
    return roots


def _temp_roots() -> list[tuple[str, Path]]:
    roots = [
        ("用户临时目录", Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")),
        ("Windows Temp", Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"),
        ("最近临时预览", Path(os.environ.get("LOCALAPPDATA", "")) / "Temp"),
    ]
    # Prefetch is optional and sometimes locked; only clear files, not the folder itself.
    prefetch = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Prefetch"
    roots.append(("预读取缓存", prefetch))
    return roots


def empty_recycle_bin(report: CleanReport) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        flags = 0x00000001 | 0x00000002 | 0x00000004
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        if result in (0, -2147418113):  # S_OK or already empty-ish
            report.notes.append("回收站")
        else:
            # Still count as attempted.
            report.notes.append("回收站")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"回收站: {exc}")


def clean_windows_update_download(report: CleanReport) -> None:
    """Clear Windows Update download cache (safe files only, not the service itself)."""
    root = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "SoftwareDistribution" / "Download"
    if not root.exists():
        return
    before = report.bytes_freed
    try:
        for child in root.iterdir():
            _remove_path(child, report)
    except OSError as exc:
        report.errors.append(f"系统更新缓存: {exc}")
        return
    if report.bytes_freed > before:
        report.notes.append("系统更新下载缓存")


def clean_delivery_optimization(report: CleanReport) -> None:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "SoftwareDistribution" / "DeliveryOptimization"
    _clear_directory_contents(root, report, "传递优化缓存")


# User-facing scopes for the floating cleaner board (id -> label)
CLEAN_SCOPES: list[tuple[str, str, str]] = [
    ("browser", "浏览器缓存", "Chrome / Edge / Firefox 等缓存与 Code Cache"),
    ("temp", "临时文件", "用户 Temp、Windows Temp"),
    ("prefetch", "预读取缓存", "Windows Prefetch（*.pf）"),
    ("thumbs", "缩略图缓存", "Explorer thumbcache_*.db"),
    ("recycle", "回收站", "清空回收站（不可恢复）"),
    ("wu", "系统更新缓存", "SoftwareDistribution\\Download"),
    ("delivery", "传递优化", "Delivery Optimization 缓存"),
]

DEFAULT_SCOPES: list[str] = [s[0] for s in CLEAN_SCOPES]


def _clean_browser(report: CleanReport) -> None:
    for label, path in _browser_cache_roots():
        if "Profiles" in str(path) and path.name == "Profiles":
            continue
        _clear_directory_contents(path, report, label)


def _clean_temp(report: CleanReport) -> None:
    for label, path in _temp_roots():
        if path.name.lower() == "prefetch":
            continue
        _clear_directory_contents(path, report, label)


def _clean_prefetch(report: CleanReport) -> None:
    path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Prefetch"
    if not path.exists():
        return
    before = report.bytes_freed
    try:
        for child in path.glob("*.pf"):
            _remove_path(child, report)
    except OSError as exc:
        report.errors.append(f"预读取缓存: {exc}")
        return
    if report.bytes_freed > before:
        report.notes.append("预读取缓存")


def _clean_thumbs(report: CleanReport) -> None:
    thumb = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Explorer"
    if not thumb.exists():
        return
    before = report.bytes_freed
    for child in thumb.glob("thumbcache_*.db"):
        _remove_path(child, report)
    if report.bytes_freed > before:
        report.notes.append("缩略图缓存")


def run_selective_clean(scopes: list[str] | set[str] | None = None) -> CleanReport:
    """Clean only selected scopes. Empty/None = all default scopes."""
    report = CleanReport()
    chosen = set(scopes) if scopes is not None else set(DEFAULT_SCOPES)
    if not chosen:
        report.notes.append("未选择任何清理范围")
        return report
    if "browser" in chosen:
        _clean_browser(report)
    if "temp" in chosen:
        _clean_temp(report)
    if "prefetch" in chosen:
        _clean_prefetch(report)
    if "thumbs" in chosen:
        _clean_thumbs(report)
    if "recycle" in chosen:
        empty_recycle_bin(report)
    if "wu" in chosen:
        clean_windows_update_download(report)
    if "delivery" in chosen:
        clean_delivery_optimization(report)
    if not report.notes and report.files_removed == 0 and not report.errors:
        report.notes.append("没有找到可清理的垃圾（或文件正在被占用）")
    return report


def run_deep_clean() -> CleanReport:
    """Run a best-effort deep clean (all scopes). Skips locked files without crashing."""
    return run_selective_clean(DEFAULT_SCOPES)


def run_deep_clean_async(
    on_done: Callable[[CleanReport], None],
    scopes: list[str] | set[str] | None = None,
) -> None:
    def worker() -> None:
        report = run_selective_clean(scopes)
        on_done(report)

    threading.Thread(target=worker, daemon=True).start()
