import re
import os
import urllib.parse
import requests
from pathlib import Path
from typing import Callable
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QByteArray
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QAudioDevice
from skin import bundle_root

def decode_text(data: bytes) -> str:
    """Detect and decode lyrics content using common encodings to avoid garbled Chinese characters."""
    for enc in ["utf-8", "gbk", "gb2312", "utf-16", "big5", "latin-1"]:
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def parse_lrc(lrc_text: str) -> list[tuple[int, str]]:
    """Parse LRC format lyrics into sorted list of (timestamp_ms, lyric_text)."""
    lines = lrc_text.splitlines()
    lyrics = []
    # Match standard LRC timestamps like [01:23.45] or [01:23]
    pattern = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        stamps = pattern.findall(line)
        if not stamps:
            continue
        # Remove timestamps to get clean lyric line text
        text = pattern.sub("", line).strip()
        for m, s, f in stamps:
            try:
                minutes = int(m)
                seconds = int(s)
                frac = int(f) if f else 0
                if f and len(f) == 2:
                    ms_fraction = frac * 10
                elif f and len(f) == 1:
                    ms_fraction = frac * 100
                else:
                    ms_fraction = frac
                time_ms = (minutes * 60 + seconds) * 1000 + ms_fraction
                lyrics.append((time_ms, text))
            except ValueError:
                continue
                
    lyrics.sort(key=lambda x: x[0])
    return lyrics


class LyricsEngine(QObject):
    """Core media player and lyrics synchronizer using QMediaPlayer."""
    position_changed = pyqtSignal(int)          # Current time in ms
    duration_changed = pyqtSignal(int)          # Duration in ms
    lyric_changed = pyqtSignal(str, str)        # Current line, Next line
    playback_state_changed = pyqtSignal(bool)   # True if playing, False if paused/stopped
    song_ended = pyqtSignal()                   # Fired when song reaches end
    
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)  # Ensure default output volume is 100%
        self._preferred_device_id: bytes | None = None
        self._auto_switch = True

        self.lyrics_list: list[tuple[int, str]] = []
        self.current_index = -1
        self.active_audio_path: Path | None = None

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self.duration_changed.emit)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        try:
            QMediaDevices.audioOutputsChanged.connect(self._on_outputs_changed)
        except Exception:
            pass
        
    def _on_player_error(self, error, error_string) -> None:
        print(f"Player Error: {error} (String: {error_string})", flush=True)
        
    def _on_state_changed(self, state) -> None:
        print(f"Player State changed to: {state}", flush=True)
        
    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        # Check if media has finished playing
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.song_ended.emit()
            
    def load_song(self, audio_path: Path, lrc_path: Path | None = None) -> bool:
        """Load audio file and attempt to parse its matching lyric file."""
        if not audio_path.exists():
            return False
            
        self.player.stop()
        self.active_audio_path = audio_path
        self.player.setSource(QUrl.fromLocalFile(str(audio_path)))
        
        # Resolve LRC path automatically if not specified
        if lrc_path is None:
            lrc_path = audio_path.with_suffix(".lrc")
            
        self.lyrics_list.clear()
        self.current_index = -1
        
        if lrc_path.exists():
            try:
                raw_data = lrc_path.read_bytes()
                lrc_content = decode_text(raw_data)
                self.lyrics_list = parse_lrc(lrc_content)
            except Exception as e:
                print(f"Error reading lyric file: {e}")
                
        # Emit initial state
        self.lyric_changed.emit("🎵 播放器就绪", "")
        return True
        
    def play(self) -> None:
        self.player.play()
        self.playback_state_changed.emit(True)
        
        # Output status to confirm playback start
        print(f"Playback started for: {self.active_audio_path.name if self.active_audio_path else 'None'}", flush=True)
        
    def pause(self) -> None:
        self.player.pause()
        self.playback_state_changed.emit(False)
        
    def stop(self) -> None:
        self.player.stop()
        self.playback_state_changed.emit(False)
        self.current_index = -1
        self.lyric_changed.emit("", "")
        
    def set_position(self, ms: int) -> None:
        self.player.setPosition(ms)
        
    def set_volume(self, volume: float) -> None:
        """Volume from 0.0 to 1.0."""
        self.audio_output.setVolume(volume)

    def get_volume(self) -> float:
        return self.audio_output.volume()

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @staticmethod
    def list_audio_outputs() -> list[tuple[str, bytes]]:
        """Return (description, device_id_bytes) for each audio output."""
        result: list[tuple[str, bytes]] = []
        try:
            for dev in QMediaDevices.audioOutputs():
                desc = str(dev.description() or "Audio device")
                did = bytes(dev.id()) if dev.id() else b""
                result.append((desc, did))
        except Exception as exc:
            print(f"list_audio_outputs: {exc}", flush=True)
        return result

    def set_auto_switch(self, enabled: bool) -> None:
        self._auto_switch = bool(enabled)

    def set_output_device(self, device_id: bytes | str | None) -> str:
        """Switch QAudioOutput to a specific device id (or default if None/empty)."""
        try:
            devices = list(QMediaDevices.audioOutputs())
            if not devices:
                return "未找到音频输出设备。"
            target: QAudioDevice | None = None
            if not device_id:
                target = QMediaDevices.defaultAudioOutput()
                self._preferred_device_id = None
            else:
                raw = device_id if isinstance(device_id, (bytes, bytearray)) else str(device_id).encode("utf-8", errors="ignore")
                # Also try matching description
                for dev in devices:
                    did = bytes(dev.id()) if dev.id() else b""
                    if did == bytes(raw) or str(dev.description()) == str(device_id):
                        target = dev
                        self._preferred_device_id = did
                        break
            if target is None or target.isNull():
                return "找不到指定的音频设备。"
            vol = self.audio_output.volume()
            was_playing = self.is_playing()
            pos = self.player.position()
            self.audio_output = QAudioOutput(target, self)
            self.audio_output.setVolume(vol)
            self.player.setAudioOutput(self.audio_output)
            if was_playing and self.active_audio_path:
                self.player.setPosition(pos)
                self.player.play()
            return f"已切换到：{target.description()}"
        except Exception as exc:
            return f"切换音频设备失败：{exc}"

    def _on_outputs_changed(self) -> None:
        if not self._auto_switch:
            return
        try:
            devices = list(QMediaDevices.audioOutputs())
            if not devices:
                return
            # Prefer previously chosen device if still present; else default
            if self._preferred_device_id:
                for dev in devices:
                    if bytes(dev.id() or b"") == self._preferred_device_id:
                        self.set_output_device(self._preferred_device_id)
                        return
            # Preferred gone (e.g. BT dead) → fall back to system default
            default = QMediaDevices.defaultAudioOutput()
            self.set_output_device(bytes(default.id()) if default and not default.isNull() else None)
            print("Audio outputs changed — auto-switched to default.", flush=True)
        except Exception as exc:
            print(f"auto switch audio failed: {exc}", flush=True)
        
    def _on_position_changed(self, position_ms: int) -> None:
        self.position_changed.emit(position_ms)
        
        if not self.lyrics_list:
            return
            
        # Binary search or scan to find active lyric index
        idx = -1
        for i, (time_ms, text) in enumerate(self.lyrics_list):
            if position_ms >= time_ms:
                idx = i
            else:
                break
                
        if idx != self.current_index:
            self.current_index = idx
            curr_text = self.lyrics_list[idx][1] if idx != -1 else "..."
            next_text = ""
            if idx + 1 < len(self.lyrics_list):
                next_text = self.lyrics_list[idx + 1][1]
            self.lyric_changed.emit(curr_text, next_text)


def _parse_gospel_ajax(html: str) -> tuple[str, str] | None:
    """Extract WordPress admin-ajax URL + security nonce from page HTML."""
    m = re.search(
        r"gospelAjax\s*=\s*\{[^}]*\"ajaxurl\"\s*:\s*\"([^\"]+)\"[^}]*\"security\"\s*:\s*\"([^\"]+)\"",
        html,
        re.I | re.S,
    )
    if not m:
        m = re.search(
            r"gospelAjax\s*=\s*\{[^}]*\"security\"\s*:\s*\"([^\"]+)\"[^}]*\"ajaxurl\"\s*:\s*\"([^\"]+)\"",
            html,
            re.I | re.S,
        )
        if m:
            return m.group(2).replace("\\/", "/"), m.group(1)
        return None
    return m.group(1).replace("\\/", "/"), m.group(2)


def fetch_recital_category_audios(page_url: str) -> list[tuple[str, str]]:
    """Fetch (title, audio_url) list via gp_home_ajax for a readings/recital category page."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": page_url,
    }
    r = requests.get(page_url, headers=headers, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    html = r.text
    parsed = _parse_gospel_ajax(html)
    if not parsed:
        return []
    ajaxurl, security = parsed
    slug = page_url.rstrip("/").split("/")[-1].replace(".html", "")
    # Prefer explicit slug if present in page
    mslug = re.search(r'category_slug["\']?\s*[:=]\s*["\']([^"\']+)', html)
    if mslug:
        slug = mslug.group(1)
    data = {
        "action": "gp_home_ajax",
        "page_name": "page-recitals",
        "taxonomy": "category",
        "page_method": "get_list_category_data",
        "category_slug": slug,
        "tab_slug": "all",
        "page_no": "-1",
        "security": security,
    }
    resp = requests.post(ajaxurl, data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data") or []
    out: list[tuple[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        audio = str(it.get("audio") or "").strip()
        if not audio:
            continue
        title = str(it.get("title") or it.get("slug") or audio.split("/")[-1]).strip()
        out.append((title, audio))
    return out


def _is_recital_catalog(url: str, html: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith("/recital.html") or path.rstrip("/").endswith("recital"):
        return True
    if "page-recitals-list" in html and html.lower().count("readings-") >= 5:
        return True
    return False


def _is_recital_category_page(url: str, html: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if re.search(r"/(readings?|recital|audio)-.+\.html$", path):
        if _parse_gospel_ajax(html):
            return True
    if "get_list_category_data" in html or "page-recitals" in html:
        if _parse_gospel_ajax(html) and "category_slug" in html:
            return True
    return bool(_parse_gospel_ajax(html) and re.search(r"readings?-|recital-", path))


def scan_page_for_songs(url: str) -> list[str]:
    """Scan a webpage and extract downloadable song/audio targets.

    Supports:
      - classic Gmedia song pages (path contains shxg\\d+)
      - hidden-advent recital catalog → category HTML pages
      - recital category pages → direct .m4a/.mp3 CDN URLs (via admin-ajax)
      - pages that already embed direct audio links
    """
    try:
        parsed_url = urllib.parse.urlparse(url)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        # Direct file URL
        if any(parsed_url.path.lower().endswith(ext) for ext in (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac")):
            return [url]

        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        html = r.text

        # Classic single Gmedia song page
        if re.search(r"shxg\d+", parsed_url.path):
            return [url]

        # Recital category: expand to CDN audio URLs
        if _is_recital_category_page(url, html):
            try:
                pairs = fetch_recital_category_audios(url)
                if pairs:
                    return [audio for _title, audio in pairs]
            except Exception as e:
                print(f"recital category ajax failed: {e}", flush=True)

        song_urls: set[str] = set()

        # Direct audio URLs embedded in HTML/JS
        for m in re.findall(r"https?://[^\s\"'<>]+\.(?:mp3|m4a|wav|ogg|flac|aac)", html, re.I):
            song_urls.add(m.split("#")[0])

        # Recital catalog: collect category pages for further expansion
        if _is_recital_catalog(url, html):
            hrefs = re.findall(r'href=["\'](.*?)["\']', html)
            for href in hrefs:
                abs_url = urllib.parse.urljoin(url, href)
                p = urllib.parse.urlparse(abs_url)
                if p.netloc and p.netloc != parsed_url.netloc:
                    continue
                path = p.path.lower()
                if re.search(r"/(readings?|recital|audio)-.+\.html$", path) or re.search(
                    r"/(readings?|recital).+\.html$", path
                ):
                    if "recital.html" not in path:
                        song_urls.add(abs_url.split("#")[0])

        # Classic Gmedia song links
        hrefs = re.findall(r'href=["\'](.*?)["\']', html)
        for href in hrefs:
            abs_url = urllib.parse.urljoin(url, href)
            parsed_abs = urllib.parse.urlparse(abs_url)
            if parsed_abs.netloc != parsed_url.netloc:
                continue
            if re.search(r"shxg\d+", parsed_abs.path):
                song_urls.add(abs_url.split("#")[0])

        return sorted(song_urls)
    except Exception as e:
        print(f"Error scanning page for songs: {e}")
        return []


def download_media(
    url: str,
    output_dir: Path,
    *,
    pause_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> tuple[Path | None, Path | None]:
    """Download audio and matching LRC. Supports pause + HTTP Range resume for audio bytes."""
    from download_queue import download_file_resumable

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        parsed_url = urllib.parse.urlparse(url)

        path_segments = [seg for seg in parsed_url.path.split("/") if seg]
        last_seg = path_segments[-1] if path_segments else ""
        base = last_seg.replace(".html", "")
        if not base:
            base = "downloaded_song"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        # Title from page
        title = base
        try:
            r_page = requests.get(url, headers=headers, timeout=10)
            r_page.raise_for_status()
            r_page.encoding = r_page.apparent_encoding
            html = r_page.text
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
        except Exception:
            pass

        title = re.split(r"\s+-\s+|\s+\|\s+", title)[0]
        title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or base

        lrc_dest = output_dir / f"{title}.lrc"
        m4a_dest = output_dir / f"{title}.m4a"
        mp3_dest = output_dir / f"{title}.mp3"

        audio_exists = (m4a_dest.exists() and m4a_dest.stat().st_size > 1000) or (
            mp3_dest.exists() and mp3_dest.stat().st_size > 1000
        )
        lrc_exists = lrc_dest.exists() and lrc_dest.stat().st_size > 10
        if audio_exists and lrc_exists:
            existing_audio = m4a_dest if m4a_dest.exists() and m4a_dest.stat().st_size > 1000 else mp3_dest
            print(f"Skipping {title} (already exists)", flush=True)
            return existing_audio, lrc_dest

        # Direct CDN / file URL (recital AJAX expands to these)
        if any(parsed_url.path.lower().endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")):
            ext = Path(parsed_url.path).suffix.lower() or ".m4a"
            stem = title
            # Avoid title.m4a.m4a when base/title already includes extension
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
            stem = re.sub(r'[\\/*?:"<>|]', "", stem).strip() or "track"
            audio_dest = output_dir / f"{stem}{ext}"
            if audio_dest.exists() and audio_dest.stat().st_size > 1000:
                return audio_dest, (lrc_dest if lrc_exists else None)
            ok = download_file_resumable(
                url,
                audio_dest,
                headers=headers,
                pause_check=pause_check,
                progress_cb=progress_cb,
                timeout=60,
            )
            return (audio_dest if ok else None), (lrc_dest if lrc_exists else None)

        origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
        lrc_url = f"{origin}/wp-content/grand-media/lrc/{base}.lrc"
        m4a_url = f"{origin}/wp-content/grand-media/audio/{base}.m4a"
        mp3_url = f"{origin}/wp-content/grand-media/audio/{base}.mp3"

        lrc_success = False
        if not lrc_exists:
            try:
                r_lrc = requests.get(lrc_url, headers=headers, timeout=10)
                if r_lrc.status_code == 200 and r_lrc.content:
                    lrc_dest.write_bytes(r_lrc.content)
                    lrc_success = True
            except Exception as e:
                print(f"Failed to download LRC file: {e}")
        else:
            lrc_success = True

        if pause_check and pause_check():
            return None, (lrc_dest if lrc_success else None)

        audio_dest = m4a_dest
        audio_success = False
        for audio_url, dest in ((m4a_url, m4a_dest), (mp3_url, mp3_dest)):
            if pause_check and pause_check():
                return None, (lrc_dest if lrc_success else None)
            ok = download_file_resumable(
                audio_url,
                dest,
                headers=headers,
                pause_check=pause_check,
                progress_cb=progress_cb,
                timeout=30,
            )
            if ok:
                audio_dest = dest
                audio_success = True
                break

        # Fallback: page may expose a direct audio URL in HTML / AJAX category
        if not audio_success:
            try:
                pairs = fetch_recital_category_audios(url)
                for title2, audio_url in pairs:
                    if pause_check and pause_check():
                        return None, (lrc_dest if lrc_success else None)
                    safe = re.sub(r'[\\/*?:"<>|]', "", title2).strip() or "track"
                    ext = Path(urllib.parse.urlparse(audio_url).path).suffix.lower() or ".m4a"
                    dest = output_dir / f"{safe}{ext}"
                    ok = download_file_resumable(
                        audio_url,
                        dest,
                        headers=headers,
                        pause_check=pause_check,
                        progress_cb=progress_cb,
                        timeout=60,
                    )
                    if ok:
                        # For a category page opened as a single job, download first track only
                        # (expansion path downloads all). Keep first success as return.
                        audio_dest = dest
                        audio_success = True
                        break
            except Exception as e:
                print(f"recital fallback failed: {e}", flush=True)

        return (audio_dest if audio_success else None), (lrc_dest if lrc_success else None)
    except Exception as e:
        print(f"Failed downloading song from URL: {e}")
        return None, None
