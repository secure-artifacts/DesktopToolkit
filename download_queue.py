"""Parallel download queue with pause/resume and daily source scan list."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

from lyrics_engine import download_media, scan_page_for_songs


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _user_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    root = Path(base) / "DesktopToolkit"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class SourceItem:
    """A page/URL kept in the daily scan list."""

    id: str
    url: str
    label: str = ""
    enabled: bool = True
    last_scan: str = ""
    last_status: str = ""

    @staticmethod
    def from_dict(d: dict) -> "SourceItem":
        return SourceItem(
            id=str(d.get("id") or _uid()),
            url=str(d.get("url") or "").strip(),
            label=str(d.get("label") or ""),
            enabled=bool(d.get("enabled", True)),
            last_scan=str(d.get("last_scan") or ""),
            last_status=str(d.get("last_status") or ""),
        )


@dataclass
class JobItem:
    """One concrete download job (usually a song page or direct file URL)."""

    id: str
    url: str
    title: str = ""
    status: str = "pending"  # pending|downloading|paused|done|error|skipped
    progress: float = 0.0
    message: str = ""
    bytes_done: int = 0
    bytes_total: int = 0
    audio_path: str = ""

    @staticmethod
    def from_dict(d: dict) -> "JobItem":
        return JobItem(
            id=str(d.get("id") or _uid()),
            url=str(d.get("url") or "").strip(),
            title=str(d.get("title") or ""),
            status=str(d.get("status") or "pending"),
            progress=float(d.get("progress") or 0),
            message=str(d.get("message") or ""),
            bytes_done=int(d.get("bytes_done") or 0),
            bytes_total=int(d.get("bytes_total") or 0),
            audio_path=str(d.get("audio_path") or ""),
        )


class DownloadQueueManager(threading.Thread):
    """Background queue: multi-worker downloads with pause/resume and source list."""

    status_changed: Callable[[], None] | None = None
    song_ready: Callable[[Path, Path | None], None] | None = None
    log: Callable[[str], None] | None = None

    def __init__(self, music_dir: Path, max_workers: int = 3) -> None:
        super().__init__(daemon=True, name="DownloadQueue")
        self.music_dir = Path(music_dir)
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max(1, min(8, int(max_workers)))
        self.data_path = _user_data_root() / "download_list.json"
        self.sources: list[SourceItem] = []
        self.jobs: list[JobItem] = []
        self.daily_scan = True
        self.scan_hour = 9
        self._lock = threading.RLock()
        self._pause_flags: dict[str, threading.Event] = {}
        self._expand_flags: dict[str, bool] = {}
        self._cancel = threading.Event()
        self._wake = threading.Event()
        self._last_daily_key = ""
        self._load()
        # Pool sized for max allowed concurrency; self.max_workers throttles active jobs.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dl")
        self._futures: dict[str, Future] = {}

    # --- persistence ---
    def _load(self) -> None:
        if not self.data_path.exists():
            return
        try:
            raw = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.sources = [SourceItem.from_dict(x) for x in (raw.get("sources") or []) if x.get("url")]
        # Only restore unfinished jobs; completed ones clutter UI
        jobs = []
        for x in raw.get("jobs") or []:
            job = JobItem.from_dict(x)
            if job.status in {"done", "skipped"}:
                continue
            if job.status == "downloading":
                job.status = "pending"
                job.message = "等待继续"
            jobs.append(job)
            # On resume: expand page URLs again; direct audio skips expand
            self._expand_flags[job.id] = not self._is_direct_audio(job.url)
        self.jobs = jobs
        self.daily_scan = bool(raw.get("daily_scan", True))
        self.scan_hour = int(raw.get("scan_hour") or 9)
        self.max_workers = max(1, min(8, int(raw.get("max_workers") or self.max_workers)))

    def save(self) -> None:
        with self._lock:
            payload = {
                "sources": [asdict(s) for s in self.sources],
                "jobs": [asdict(j) for j in self.jobs[-200:]],
                "daily_scan": self.daily_scan,
                "scan_hour": self.scan_hour,
                "max_workers": self.max_workers,
            }
        try:
            self.data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _notify(self) -> None:
        if self.status_changed:
            try:
                self.status_changed()
            except Exception:
                pass

    def _log(self, msg: str) -> None:
        if self.log:
            try:
                self.log(msg)
            except Exception:
                pass

    # --- sources ---
    def add_source(self, url: str, label: str = "") -> str:
        url = (url or "").strip()
        if not url:
            return "请填写链接。"
        with self._lock:
            for s in self.sources:
                if s.url == url:
                    s.enabled = True
                    self.save()
                    return "链接已在列表中，已启用。"
            item = SourceItem(id=_uid(), url=url, label=(label or url)[:80], enabled=True)
            self.sources.insert(0, item)
            self.save()
        self._notify()
        return f"已加入下载列表：{item.label}"

    def remove_source(self, source_id: str) -> str:
        with self._lock:
            before = len(self.sources)
            self.sources = [s for s in self.sources if s.id != source_id]
            self.save()
        self._notify()
        return "已删除。" if len(self.sources) < before else "未找到。"

    def set_source_enabled(self, source_id: str, enabled: bool) -> None:
        with self._lock:
            for s in self.sources:
                if s.id == source_id:
                    s.enabled = enabled
                    break
            self.save()
        self._notify()

    def set_daily_scan(self, enabled: bool, hour: int | None = None) -> None:
        with self._lock:
            self.daily_scan = bool(enabled)
            if hour is not None:
                self.scan_hour = max(0, min(23, int(hour)))
            self.save()

    # --- jobs ---
    def enqueue_url(self, url: str, *, expand_page: bool = True) -> str:
        """Add one URL to the queue (non-blocking). Page expansion happens in a worker."""
        url = (url or "").strip()
        if not url:
            return "请填写链接。"
        with self._lock:
            existing = {j.url for j in self.jobs if j.status not in {"done", "error", "skipped"}}
            if url in existing:
                return "链接已在队列中。"
            title = url.split("/")[-1][:60] or url[:60]
            do_expand = bool(expand_page) and not self._is_direct_audio(url)
            job = JobItem(
                id=_uid(),
                url=url,
                title=title,
                status="pending",
                message="等待扫描展开…" if do_expand else "等待下载…",
            )
            self.jobs.append(job)
            self._expand_flags[job.id] = do_expand
            self.save()
        self._wake.set()
        self._notify()
        return f"已加入队列：{title}"

    def enqueue_many(self, urls: list[str]) -> str:
        count = 0
        for u in urls:
            msg = self.enqueue_url(u, expand_page=True)
            if msg.startswith("已加入"):
                count += 1
        return f"批量入队完成，{count} 个新任务。"

    @staticmethod
    def _is_direct_audio(url: str) -> bool:
        lower = (url or "").lower().split("?", 1)[0]
        return any(lower.endswith(ext) for ext in (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"))

    def pause_job(self, job_id: str) -> None:
        with self._lock:
            for j in self.jobs:
                if j.id == job_id and j.status in {"pending", "downloading"}:
                    j.status = "paused"
                    j.message = "已暂停"
            ev = self._pause_flags.get(job_id)
            if ev:
                ev.set()
            self.save()
        self._notify()

    def resume_job(self, job_id: str) -> None:
        with self._lock:
            for j in self.jobs:
                if j.id == job_id and j.status == "paused":
                    j.status = "pending"
                    j.message = "等待继续"
            ev = self._pause_flags.get(job_id)
            if ev:
                ev.clear()
            self.save()
        self._wake.set()
        self._notify()

    def pause_all(self) -> None:
        with self._lock:
            for j in self.jobs:
                if j.status in {"pending", "downloading"}:
                    j.status = "paused"
                    j.message = "已暂停"
            for ev in self._pause_flags.values():
                ev.set()
            self.save()
        self._notify()

    def resume_all(self) -> None:
        with self._lock:
            for j in self.jobs:
                if j.status == "paused":
                    j.status = "pending"
                    j.message = "等待继续"
            for ev in self._pause_flags.values():
                ev.clear()
            self.save()
        self._wake.set()
        self._notify()

    def clear_finished(self) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.status not in {"done", "skipped", "error"}]
            self.save()
        self._notify()

    def remove_job(self, job_id: str) -> str:
        """Remove one job; pauses it first if still downloading."""
        with self._lock:
            job = next((j for j in self.jobs if j.id == job_id), None)
            if not job:
                return "未找到该任务。"
            if job.status in {"pending", "downloading"}:
                job.status = "paused"
                ev = self._pause_flags.get(job_id)
                if ev:
                    ev.set()
            self.jobs = [j for j in self.jobs if j.id != job_id]
            self._pause_flags.pop(job_id, None)
            self._futures.pop(job_id, None)
            self.save()
        self._notify()
        return "已从队列移除。"

    def remove_jobs(self, job_ids: list[str]) -> str:
        n = 0
        for jid in job_ids:
            msg = self.remove_job(jid)
            if "移除" in msg:
                n += 1
        return f"已移除 {n} 个任务。"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sources": [asdict(s) for s in self.sources],
                "jobs": [asdict(j) for j in self.jobs],
                "daily_scan": self.daily_scan,
                "scan_hour": self.scan_hour,
                "max_workers": self.max_workers,
                "active": sum(1 for j in self.jobs if j.status == "downloading"),
                "pending": sum(1 for j in self.jobs if j.status == "pending"),
            }

    def scan_source_now(self, source_id: str | None = None) -> str:
        """Enqueue enabled sources (workers expand pages and download)."""
        with self._lock:
            targets = [s for s in self.sources if s.enabled and (source_id is None or s.id == source_id)]
        if not targets:
            return "没有启用的订阅源。"
        total_jobs = 0
        for s in targets:
            self._log(f"扫描：{s.url}")
            try:
                # Enqueue page itself; expand+download runs in workers (non-blocking here)
                before = len(self.snapshot()["jobs"])
                msg = self.enqueue_url(s.url, expand_page=True)
                after = len(self.snapshot()["jobs"])
                added = max(0, after - before)
                total_jobs += added
                with self._lock:
                    s.last_scan = datetime.now().isoformat(timespec="seconds")
                    s.last_status = msg
                    self.save()
            except Exception as exc:
                with self._lock:
                    s.last_scan = datetime.now().isoformat(timespec="seconds")
                    s.last_status = f"失败：{exc}"
                    self.save()
        self._notify()
        return f"已将 {len(targets)} 个订阅源加入队列（展开与下载在后台进行）。"

    # --- worker loop ---
    def run(self) -> None:
        while not self._cancel.is_set():
            self._maybe_daily_scan()
            job = self._pick_job()
            if job is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            # Submit to pool without blocking the picker too long
            if len(self._futures) >= self.max_workers:
                self._cleanup_futures()
                time.sleep(0.2)
                continue
            pause_ev = threading.Event()
            self._pause_flags[job.id] = pause_ev
            fut = self._executor.submit(self._run_job, job.id, pause_ev)
            self._futures[job.id] = fut
            self._cleanup_futures()

    def stop(self) -> None:
        self._cancel.set()
        self._wake.set()
        self.pause_all()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _cleanup_futures(self) -> None:
        done = [jid for jid, f in self._futures.items() if f.done()]
        for jid in done:
            self._futures.pop(jid, None)
            self._pause_flags.pop(jid, None)

    def _pick_job(self) -> JobItem | None:
        with self._lock:
            active = {jid for jid, f in self._futures.items() if not f.done()}
            for j in self.jobs:
                if j.status == "pending" and j.id not in active:
                    j.status = "downloading"
                    j.message = "下载中…"
                    self.save()
                    self._notify()
                    return j
        return None

    def _maybe_daily_scan(self) -> None:
        if not self.daily_scan:
            return
        now = datetime.now()
        key = now.strftime("%Y-%m-%d")
        if now.hour < self.scan_hour:
            return
        if self._last_daily_key == key:
            return
        # Avoid re-scan if any source already scanned today
        with self._lock:
            already = all(
                (s.last_scan or "").startswith(key) for s in self.sources if s.enabled
            ) and bool(self.sources)
        if already:
            self._last_daily_key = key
            return
        self._last_daily_key = key
        self._log("每日自动扫描下载列表…")
        self.scan_source_now()

    def _run_job(self, job_id: str, pause_ev: threading.Event) -> None:
        with self._lock:
            job = next((j for j in self.jobs if j.id == job_id), None)
            expand = bool(getattr(self, "_expand_flags", {}).get(job_id, False))
        if not job:
            return
        try:
            if pause_ev.is_set():
                with self._lock:
                    job.status = "paused"
                    job.message = "已暂停"
                    self.save()
                self._notify()
                return

            # Page URL: scan for song links, enqueue children, mark this done.
            if expand and not self._is_direct_audio(job.url):
                with self._lock:
                    job.message = "扫描页面中…"
                self._notify()
                found = scan_page_for_songs(job.url)
                if pause_ev.is_set():
                    with self._lock:
                        job.status = "paused"
                        job.message = "已暂停（扫描中断）"
                        self.save()
                    self._notify()
                    return
                if len(found) > 1 or (len(found) == 1 and found[0] != job.url):
                    # Expand into child download jobs (no further expand)
                    added = 0
                    with self._lock:
                        existing = {j.url for j in self.jobs if j.status not in {"done", "error", "skipped"}}
                        for u in found:
                            if u in existing:
                                continue
                            child = JobItem(
                                id=_uid(),
                                url=u,
                                title=u.split("/")[-1][:60],
                                status="pending",
                                message="等待下载…",
                            )
                            self.jobs.append(child)
                            if not hasattr(self, "_expand_flags"):
                                self._expand_flags = {}
                            self._expand_flags[child.id] = False
                            existing.add(u)
                            added += 1
                        job.status = "done"
                        job.progress = 100.0
                        job.message = f"已展开 {len(found)} 链，新任务 {added}"
                        job.title = (job.title or "页面")[:40]
                        self.save()
                    self._notify()
                    self._wake.set()
                    return
                # Single or none — fall through to download this URL itself
                with self._lock:
                    if hasattr(self, "_expand_flags"):
                        self._expand_flags[job_id] = False

            def progress(done: int, total: int) -> None:
                if pause_ev.is_set():
                    raise _Paused()
                with self._lock:
                    job.bytes_done = done
                    job.bytes_total = total
                    job.progress = (done / total * 100.0) if total else 0.0
                    job.message = f"{done // 1024}KB" + (f" / {total // 1024}KB" if total else "")
                self._notify()

            with self._lock:
                job.message = "下载中…"
            self._notify()

            audio, lrc = download_media(
                job.url,
                self.music_dir,
                pause_check=lambda: pause_ev.is_set(),
                progress_cb=progress,
            )
            if pause_ev.is_set():
                with self._lock:
                    job.status = "paused"
                    job.message = "已暂停（可继续）"
                    self.save()
                self._notify()
                return
            if audio:
                with self._lock:
                    job.status = "done"
                    job.progress = 100.0
                    job.audio_path = str(audio)
                    job.title = audio.stem
                    job.message = "完成"
                    self.save()
                if self.song_ready:
                    try:
                        self.song_ready(audio, lrc)
                    except Exception:
                        pass
            else:
                with self._lock:
                    job.status = "error"
                    job.message = "下载失败"
                    self.save()
        except _Paused:
            with self._lock:
                job.status = "paused"
                job.message = "已暂停"
                self.save()
        except Exception as exc:
            with self._lock:
                job.status = "error"
                job.message = str(exc)[:120]
                self.save()
        self._notify()
        self._wake.set()


class _Paused(Exception):
    pass


def download_file_resumable(
    url: str,
    dest: Path,
    *,
    headers: dict | None = None,
    pause_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    timeout: int = 30,
) -> bool:
    """HTTP GET with Range resume support. Returns True on success."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    try:
        with requests.get(url, headers=headers, stream=True, timeout=timeout) as resp:
            if resp.status_code == 416:
                return existing > 1000
            if resp.status_code not in (200, 206):
                return False
            total = existing
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                total = existing + int(cl) if resp.status_code == 206 else int(cl)
            mode = "ab" if resp.status_code == 206 and existing else "wb"
            if mode == "wb":
                existing = 0
            written = existing
            with dest.open(mode) as handle:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if pause_check and pause_check():
                        return False
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    if progress_cb:
                        progress_cb(written, total)
            return dest.exists() and dest.stat().st_size > 1000
    except Exception as exc:
        print(f"resumable download failed: {exc}", flush=True)
        return False
