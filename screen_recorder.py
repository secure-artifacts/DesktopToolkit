"""High-performance screen recorder for Windows.

Design goals:
- Real-time encode via ffmpeg pipe (no long freeze when stopping)
- Multi-monitor + window targets
- Mic + system loopback mix
- Cursor highlight drawn on frames
- Optional preview frames for UI
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import sounddevice as sd
import win32api
import win32con
import win32gui
import win32ui

try:
    import mss
except ImportError:
    mss = None  # type: ignore


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def get_monitors() -> list[dict]:
    """Return list of monitors: {id, title, left, top, width, height}."""
    out: list[dict] = []
    if mss is not None:
        with mss.mss() as sct:
            for i, mon in enumerate(sct.monitors):
                # monitors[0] is virtual desktop spanning all
                if i == 0:
                    out.append(
                        {
                            "id": "all",
                            "hwnd": 0,
                            "kind": "screen",
                            "title": f"全部显示器 ({mon['width']}×{mon['height']})",
                            "left": mon["left"],
                            "top": mon["top"],
                            "width": mon["width"],
                            "height": mon["height"],
                        }
                    )
                else:
                    out.append(
                        {
                            "id": f"mon{i}",
                            "hwnd": 0,
                            "kind": "screen",
                            "title": f"显示器 {i} ({mon['width']}×{mon['height']})",
                            "left": mon["left"],
                            "top": mon["top"],
                            "width": mon["width"],
                            "height": mon["height"],
                        }
                    )
        return out
    # Fallback single screen
    w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    return [
        {
            "id": "all",
            "hwnd": 0,
            "kind": "screen",
            "title": f"整个屏幕 ({w}×{h})",
            "left": 0,
            "top": 0,
            "width": w,
            "height": h,
        }
    ]


def get_window_list(*, browsers_only: bool = False) -> list[dict]:
    """Visible top-level windows with title/hwnd/class."""
    browser_classes = {
        "Chrome_WidgetWin_1",
        "MozillaWindowClass",
        "ApplicationFrameWindow",  # Edge UWP shell
    }
    browser_title_keys = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "360", "浏览器", "browser")

    windows: list[dict] = []

    def enum_win(hwnd, result):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title.strip():
            return
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            if style & win32con.WS_CHILD:
                return
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w < 120 or h < 80:
                return
            cls = win32gui.GetClassName(hwnd) or ""
            if cls in ("Progman", "Shell_TrayWnd", "WorkerW", "Button"):
                return
            title_l = title.lower()
            is_browser = cls in browser_classes or any(k in title_l for k in browser_title_keys)
            if browsers_only and not is_browser:
                return
            kind = "browser" if is_browser else "window"
            prefix = "🌐 " if is_browser else "🗔 "
            result.append(
                {
                    "id": f"hwnd:{hwnd}",
                    "hwnd": int(hwnd),
                    "kind": kind,
                    "title": prefix + title[:80],
                    "class": cls,
                    "left": rect[0],
                    "top": rect[1],
                    "width": w,
                    "height": h,
                }
            )
        except Exception:
            return

    try:
        win32gui.EnumWindows(enum_win, windows)
    except Exception:
        pass
    windows.sort(key=lambda x: x["title"].lower())
    return windows


def get_capture_targets() -> list[dict]:
    """Screens + windows for UI combo."""
    return get_monitors() + get_window_list(browsers_only=False)


def get_audio_devices() -> tuple[list[dict], list[dict]]:
    """Return (mics, system_loopback_candidates)."""
    mics: list[dict] = []
    systems: list[dict] = []
    try:
        devices = sd.query_devices()
        for idx, d in enumerate(devices):
            if int(d.get("max_input_channels") or 0) <= 0:
                continue
            name = str(d.get("name") or f"Device {idx}")
            try:
                host = sd.query_hostapis(d["hostapi"])["name"]
            except Exception:
                host = ""
            item = {"index": idx, "name": f"{name} ({host})" if host else name}
            name_l = name.lower()
            if any(
                k in name_l
                for k in (
                    "立体声",
                    "混音",
                    "mix",
                    "loopback",
                    "cable",
                    "virtual",
                    "what u hear",
                    "stereo mix",
                )
            ):
                systems.append(item)
            else:
                mics.append(item)
    except Exception as exc:
        print(f"audio device query failed: {exc}", flush=True)
    return mics, systems


def _ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture_bgr(region: dict | None = None) -> np.ndarray | None:
    """Capture region as BGR uint8 array. region: left,top,width,height or None for primary."""
    if mss is not None:
        try:
            with mss.mss() as sct:
                if region is None:
                    mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    shot = sct.grab(mon)
                else:
                    shot = sct.grab(
                        {
                            "left": int(region["left"]),
                            "top": int(region["top"]),
                            "width": max(2, int(region["width"])),
                            "height": max(2, int(region["height"])),
                        }
                    )
                # BGRA -> BGR
                frame = np.array(shot, dtype=np.uint8)
                return frame[:, :, :3].copy()
        except Exception as exc:
            print(f"mss capture failed: {exc}", flush=True)

    # GDI fallback
    try:
        if region:
            left, top = int(region["left"]), int(region["top"])
            w, h = max(2, int(region["width"])), max(2, int(region["height"]))
        else:
            left = top = 0
            w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        hwnd = win32gui.GetDesktopWindow()
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        save_dc.BitBlt((0, 0), (w, h), mfc_dc, (left, top), win32con.SRCCOPY)
        bits = bmp.GetBitmapBits(True)
        img = np.frombuffer(bits, dtype=np.uint8).reshape((h, w, 4))
        bgr = img[:, :, :3].copy()
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return bgr
    except Exception as exc:
        print(f"gdi capture failed: {exc}", flush=True)
        return None


def resolve_region(target: dict | None) -> dict | None:
    """Compute live capture region from a target dict (screen or hwnd)."""
    if not target:
        return None
    hwnd = int(target.get("hwnd") or 0)
    if hwnd > 0 and win32gui.IsWindow(hwnd):
        try:
            # Prefer restored geometry
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            return {
                "left": left,
                "top": top,
                "width": max(2, right - left),
                "height": max(2, bottom - top),
            }
        except Exception:
            pass
    # Screen region stored on target
    if all(k in target for k in ("left", "top", "width", "height")):
        return {
            "left": int(target["left"]),
            "top": int(target["top"]),
            "width": max(2, int(target["width"])),
            "height": max(2, int(target["height"])),
        }
    return None


def draw_cursor_highlight(
    frame_bgr: np.ndarray,
    region: dict | None,
    *,
    color_bgr: tuple[int, int, int] = (0, 255, 255),
    radius: int = 22,
    show_pointer: bool = True,
) -> None:
    """Draw cursor highlight in-place (BGR)."""
    try:
        cx, cy = win32gui.GetCursorPos()
    except Exception:
        return
    if region:
        rx = cx - int(region["left"])
        ry = cy - int(region["top"])
    else:
        rx, ry = cx, cy
    h, w = frame_bgr.shape[:2]
    if rx < -radius or ry < -radius or rx > w + radius or ry > h + radius:
        return
    overlay = frame_bgr.copy()
    cv2.circle(overlay, (int(rx), int(ry)), radius, color_bgr, -1, lineType=cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.35, frame_bgr, 0.65, 0, frame_bgr)
    cv2.circle(frame_bgr, (int(rx), int(ry)), radius, color_bgr, 2, lineType=cv2.LINE_AA)
    if show_pointer:
        pts = np.array(
            [[rx, ry], [rx + 14, ry + 14], [rx + 4, ry + 16]],
            dtype=np.int32,
        )
        cv2.fillPoly(frame_bgr, [pts], (255, 255, 255))
        cv2.polylines(frame_bgr, [pts], True, (0, 0, 0), 1, lineType=cv2.LINE_AA)


def blend_overlay_rgba(frame_bgr: np.ndarray, overlay_rgba: np.ndarray | None) -> np.ndarray:
    """Alpha-blend RGBA overlay onto BGR frame."""
    if overlay_rgba is None:
        return frame_bgr
    try:
        if overlay_rgba.shape[0] != frame_bgr.shape[0] or overlay_rgba.shape[1] != frame_bgr.shape[1]:
            overlay_rgba = cv2.resize(
                overlay_rgba,
                (frame_bgr.shape[1], frame_bgr.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )
        if overlay_rgba.shape[2] < 4:
            return frame_bgr
        alpha = overlay_rgba[:, :, 3:4].astype(np.float32) / 255.0
        if float(alpha.max()) < 0.01:
            return frame_bgr
        rgb = overlay_rgba[:, :, :3][:, :, ::-1].astype(np.float32)  # RGB->BGR
        base = frame_bgr.astype(np.float32)
        out = base * (1.0 - alpha) + rgb * alpha
        return out.astype(np.uint8)
    except Exception:
        return frame_bgr


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

class AudioRecorder:
    def __init__(self, mic_idx, sys_idx, output_wav_path: str, sample_rate: int = 44100):
        self.mic_idx = mic_idx
        self.sys_idx = sys_idx
        self.output_wav_path = output_wav_path
        self.sample_rate = sample_rate
        self.q_mic: queue.Queue = queue.Queue()
        self.q_sys: queue.Queue = queue.Queue()
        self.is_recording = False
        self.is_paused = False
        self.stream_mic = None
        self.stream_sys = None
        self.wav_file = None
        self.write_thread = None

    def start(self) -> None:
        self.is_recording = True
        self.is_paused = False
        if self.mic_idx is not None:
            try:
                def cb(data, frames, t, status):
                    if not self.is_paused:
                        self.q_mic.put(data.copy())

                self.stream_mic = sd.InputStream(
                    device=self.mic_idx, channels=1, samplerate=self.sample_rate, callback=cb
                )
                self.stream_mic.start()
            except Exception as e:
                print(f"mic failed: {e}", flush=True)
                self.mic_idx = None
                self.stream_mic = None

        if self.sys_idx is not None:
            try:
                def cb(data, frames, t, status):
                    if not self.is_paused:
                        self.q_sys.put(data.copy())

                ch = 2
                try:
                    info = sd.query_devices(self.sys_idx)
                    ch = min(2, max(1, int(info.get("max_input_channels") or 2)))
                except Exception:
                    pass
                self.stream_sys = sd.InputStream(
                    device=self.sys_idx, channels=ch, samplerate=self.sample_rate, callback=cb
                )
                self.stream_sys.start()
            except Exception as e:
                print(f"system audio failed: {e}", flush=True)
                self.sys_idx = None
                self.stream_sys = None

        if self.mic_idx is not None or self.sys_idx is not None:
            self.wav_file = wave.open(self.output_wav_path, "wb")
            self.wav_file.setnchannels(2)
            self.wav_file.setsampwidth(2)
            self.wav_file.setframerate(self.sample_rate)
            self.write_thread = threading.Thread(target=self._write_loop, daemon=True)
            self.write_thread.start()

    def _write_loop(self) -> None:
        while self.is_recording or not self.q_mic.empty() or not self.q_sys.empty():
            chunk_mic = None
            chunk_sys = None
            try:
                if self.mic_idx is not None:
                    chunk_mic = self.q_mic.get(timeout=0.04)
            except queue.Empty:
                pass
            try:
                if self.sys_idx is not None:
                    chunk_sys = self.q_sys.get(timeout=0.04)
            except queue.Empty:
                pass
            if chunk_mic is None and chunk_sys is None:
                time.sleep(0.005)
                continue
            if self.wav_file is None:
                continue
            try:
                if chunk_mic is not None and chunk_sys is None:
                    stereo = np.column_stack((chunk_mic[:, 0], chunk_mic[:, 0]))
                elif chunk_sys is not None and chunk_mic is None:
                    if chunk_sys.ndim == 1:
                        stereo = np.column_stack((chunk_sys, chunk_sys))
                    elif chunk_sys.shape[1] == 1:
                        stereo = np.column_stack((chunk_sys[:, 0], chunk_sys[:, 0]))
                    else:
                        stereo = chunk_sys[:, :2]
                else:
                    m = chunk_mic[:, 0] if chunk_mic.ndim > 1 else chunk_mic
                    if chunk_sys.ndim == 1:
                        s = np.column_stack((chunk_sys, chunk_sys))
                    elif chunk_sys.shape[1] == 1:
                        s = np.column_stack((chunk_sys[:, 0], chunk_sys[:, 0]))
                    else:
                        s = chunk_sys[:, :2]
                    n = min(len(m), len(s))
                    m2 = np.column_stack((m[:n], m[:n]))
                    stereo = np.clip(m2 * 0.5 + s[:n] * 0.5, -1.0, 1.0)
                pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype(np.int16)
                self.wav_file.writeframes(pcm.tobytes())
            except Exception:
                pass

    def pause(self) -> None:
        self.is_paused = True

    def resume(self) -> None:
        self.is_paused = False

    def stop(self) -> None:
        self.is_recording = False
        if self.write_thread:
            self.write_thread.join(timeout=2.0)
        for stream in (self.stream_mic, self.stream_sys):
            if stream is None:
                continue
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if self.wav_file:
            try:
                self.wav_file.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Screen recorder (ffmpeg pipe = fast stop)
# ---------------------------------------------------------------------------

@dataclass
class RecorderConfig:
    target: dict | None = None
    mic_idx: int | None = None
    sys_idx: int | None = None
    fps: int = 24
    resolution: str = "1080p"  # 1080p | 720p
    highlight_cursor: bool = True
    cursor_color_bgr: tuple[int, int, int] = (0, 255, 255)
    cursor_radius: int = 22
    # Called with BGR preview frame (already resized small)
    preview_cb: Callable[[np.ndarray], None] | None = None
    # Optional: returns RGBA numpy overlay matching capture size
    overlay_provider: Callable[[], np.ndarray | None] | None = None


class ScreenRecorder:
    def __init__(self, **kwargs) -> None:
        # Backward-compatible constructor used by old UI
        if "hwnd" in kwargs and "target" not in kwargs:
            hwnd = int(kwargs.get("hwnd") or 0)
            if hwnd > 0:
                kwargs["target"] = {"hwnd": hwnd, "kind": "window"}
            else:
                mons = get_monitors()
                kwargs["target"] = mons[0] if mons else None
        color = kwargs.pop("highlight_color", None)
        if color and "cursor_color_bgr" not in kwargs:
            # may be RGBA or RGB
            if len(color) >= 3:
                # PIL RGB -> BGR
                kwargs["cursor_color_bgr"] = (int(color[2]), int(color[1]), int(color[0]))
        # draw_overlay widget support
        draw_overlay = kwargs.pop("draw_overlay", None)
        if draw_overlay is not None and "overlay_provider" not in kwargs:

            def _prov():
                pil = getattr(draw_overlay, "overlay_pil", None)
                if pil is None:
                    return None
                try:
                    arr = np.array(pil)
                    if arr.ndim == 3 and arr.shape[2] == 4:
                        return arr
                except Exception:
                    return None
                return None

            kwargs["overlay_provider"] = _prov

        self.cfg = RecorderConfig(
            target=kwargs.get("target"),
            mic_idx=kwargs.get("mic_idx"),
            sys_idx=kwargs.get("sys_idx"),
            fps=int(kwargs.get("fps") or 24),
            resolution=str(kwargs.get("resolution") or "1080p"),
            highlight_cursor=bool(kwargs.get("highlight_cursor", True)),
            cursor_color_bgr=kwargs.get("cursor_color_bgr", (0, 255, 255)),
            cursor_radius=int(kwargs.get("cursor_radius") or 22),
            preview_cb=kwargs.get("preview_cb"),
            overlay_provider=kwargs.get("overlay_provider"),
        )
        res_map = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
            "1440p": (2560, 1440),
            "2k": (2560, 1440),
            "4k": (3840, 2160),
            "2160p": (3840, 2160),
        }
        self.target_size = res_map.get(str(self.cfg.resolution).lower(), (1920, 1080))

        self.is_recording = False
        self.is_paused = False
        self.duration_seconds = 0.0
        self._t0 = 0.0
        self._pause_acc = 0.0
        self._pause_at = 0.0

        self._work_dir = Path(tempfile.mkdtemp(prefix="qpp_rec_"))
        self.temp_video = str(self._work_dir / "video.mp4")
        self.temp_audio = str(self._work_dir / "audio.wav")

        self.video_thread: threading.Thread | None = None
        self.audio_recorder: AudioRecorder | None = None
        self._ffmpeg: subprocess.Popen | None = None
        self._last_preview_t = 0.0
        self._error = ""

    # --- control ---
    def start(self) -> None:
        self.is_recording = True
        self.is_paused = False
        self.duration_seconds = 0.0
        self._t0 = time.time()
        self._pause_acc = 0.0
        self._error = ""

        if self.cfg.mic_idx is not None or self.cfg.sys_idx is not None:
            self.audio_recorder = AudioRecorder(self.cfg.mic_idx, self.cfg.sys_idx, self.temp_audio)
            self.audio_recorder.start()

        self.video_thread = threading.Thread(target=self._video_loop, daemon=True, name="RecVideo")
        self.video_thread.start()

    def pause(self) -> None:
        if self.is_paused:
            return
        self.is_paused = True
        self._pause_at = time.time()
        if self.audio_recorder:
            self.audio_recorder.pause()

    def resume(self) -> None:
        if not self.is_paused:
            return
        self.is_paused = False
        self._pause_acc += time.time() - self._pause_at
        if self.audio_recorder:
            self.audio_recorder.resume()

    def stop(self, final_output_path: str) -> str:
        """Stop capture and mux. Returns status message. Fast path: stream-copy video."""
        self.is_recording = False
        if self.video_thread:
            self.video_thread.join(timeout=8.0)
        if self.audio_recorder:
            self.audio_recorder.stop()
        if self._ffmpeg:
            try:
                if self._ffmpeg.stdin:
                    self._ffmpeg.stdin.close()
            except Exception:
                pass
            try:
                self._ffmpeg.wait(timeout=15)
            except Exception:
                try:
                    self._ffmpeg.kill()
                except Exception:
                    pass
            self._ffmpeg = None

        out = Path(final_output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        has_audio = os.path.exists(self.temp_audio) and os.path.getsize(self.temp_audio) > 44
        has_video = os.path.exists(self.temp_video) and os.path.getsize(self.temp_video) > 1000

        if not has_video:
            self._cleanup_temp()
            return self._error or "录制失败：没有生成视频帧。"

        ok = fast_mux(self.temp_video, self.temp_audio if has_audio else None, str(out))
        self._cleanup_temp()
        if ok and out.exists():
            return f"已保存：{out}"
        return f"保存失败（{self._error or 'mux error'}）"

    def _cleanup_temp(self) -> None:
        try:
            shutil.rmtree(self._work_dir, ignore_errors=True)
        except Exception:
            pass

    def _update_duration(self) -> None:
        if not self.is_recording:
            return
        if self.is_paused:
            self.duration_seconds = max(0.0, self._pause_at - self._t0 - self._pause_acc)
        else:
            self.duration_seconds = max(0.0, time.time() - self._t0 - self._pause_acc)

    def _start_ffmpeg(self, w: int, h: int) -> bool:
        ffmpeg = _ffmpeg_bin()
        # ultrafast + yuv420p for quick encode and wide player compatibility
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            str(self.cfg.fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            self.temp_video,
        ]
        try:
            self._ffmpeg = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            self._error = f"ffmpeg 启动失败: {exc}"
            print(self._error, flush=True)
            return False

    def _video_loop(self) -> None:
        tw, th = self.target_size
        # ensure even dimensions for yuv420p
        tw -= tw % 2
        th -= th % 2
        self.target_size = (tw, th)

        use_ffmpeg = self._start_ffmpeg(tw, th)
        writer = None
        if not use_ffmpeg:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(self.temp_video, fourcc, self.cfg.fps, (tw, th))
            if not writer.isOpened():
                self._error = "无法打开视频写入器"
                self.is_recording = False
                return

        frame_delay = 1.0 / max(1, self.cfg.fps)
        frames = 0
        while self.is_recording:
            t0 = time.time()
            self._update_duration()
            if self.is_paused:
                time.sleep(0.05)
                continue

            region = resolve_region(self.cfg.target)
            frame = capture_bgr(region)
            if frame is None:
                time.sleep(0.02)
                continue

            # Overlay annotations
            if self.cfg.overlay_provider:
                try:
                    ov = self.cfg.overlay_provider()
                    frame = blend_overlay_rgba(frame, ov)
                except Exception:
                    pass

            if self.cfg.highlight_cursor:
                draw_cursor_highlight(
                    frame,
                    region,
                    color_bgr=self.cfg.cursor_color_bgr,
                    radius=self.cfg.cursor_radius,
                )

            if frame.shape[1] != tw or frame.shape[0] != th:
                frame = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)

            # Write
            try:
                if self._ffmpeg and self._ffmpeg.stdin:
                    self._ffmpeg.stdin.write(frame.tobytes())
                elif writer is not None:
                    writer.write(frame)
                frames += 1
            except Exception as exc:
                self._error = f"写帧失败: {exc}"
                break

            # Preview ~8 fps
            if self.cfg.preview_cb and (time.time() - self._last_preview_t) > 0.12:
                self._last_preview_t = time.time()
                try:
                    small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
                    self.cfg.preview_cb(small)
                except Exception:
                    pass

            elapsed = time.time() - t0
            time.sleep(max(0.0, frame_delay - elapsed))

        if writer is not None:
            writer.release()
        if self._ffmpeg and self._ffmpeg.stdin:
            try:
                self._ffmpeg.stdin.close()
            except Exception:
                pass
            try:
                self._ffmpeg.wait(timeout=20)
            except Exception:
                try:
                    self._ffmpeg.kill()
                except Exception:
                    pass
            self._ffmpeg = None
        if frames == 0 and not self._error:
            self._error = "未捕获到任何画面"


def fast_mux(video_path: str, audio_path: str | None, output_path: str) -> bool:
    """Mux with stream copy for video — nearly instant."""
    ffmpeg = _ffmpeg_bin()
    try:
        if audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 44:
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                video_path,
                "-i",
                audio_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                output_path,
            ]
        else:
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                video_path,
                "-c:v",
                "copy",
                "-an",
                "-movflags",
                "+faststart",
                output_path,
            ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(output_path):
            return True
        # fallback copy video only
        shutil.copy2(video_path, output_path)
        return os.path.exists(output_path)
    except Exception as exc:
        print(f"mux failed: {exc}", flush=True)
        try:
            shutil.copy2(video_path, output_path)
            return True
        except Exception:
            return False


# Keep old name used elsewhere
merge_audio_video = fast_mux
