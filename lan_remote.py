"""LAN-only remote desktop: Host streams screen, Client sends mouse/keyboard.

Protocol over WebSocket (port 8766 by default):
  Client → Host: JSON auth / mouse / key / ping
  Host → Client: JSON auth_ok/auth_fail/frame meta, then binary JPEG bytes
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_PORT = 8766
MIN_PASSWORD_LEN = 4


@dataclass
class HostStatus:
    running: bool
    port: int
    clients: int
    message: str
    password_set: bool = False


def _encode_jpeg(bgr, *, max_side: int, quality: int) -> tuple[bytes, int, int]:
    """BGR numpy → JPEG bytes, optionally scaled. Returns (jpeg, w, h)."""
    from PIL import Image
    import numpy as np

    if bgr is None or getattr(bgr, "size", 0) == 0:
        raise ValueError("empty frame")
    rgb = bgr[:, :, ::-1]
    img = Image.fromarray(np.ascontiguousarray(rgb))
    w, h = img.size
    long_side = max(w, h)
    if long_side > max_side > 0:
        scale = max_side / float(long_side)
        nw = max(2, int(w * scale))
        nh = max(2, int(h * scale))
        img = img.resize((nw, nh), Image.Resampling.BILINEAR)
        w, h = nw, nh
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=int(quality), optimize=False)
    return buf.getvalue(), w, h


def _inject_mouse(action: str, x: float, y: float, button: str = "left", dy: float = 0) -> None:
    from pynput.mouse import Button, Controller

    mouse = Controller()
    # Absolute pixel coords are provided by host after denormalizing
    try:
        mouse.position = (int(x), int(y))
    except Exception:
        pass
    btn = Button.left
    if button == "right":
        btn = Button.right
    elif button == "middle":
        btn = Button.middle
    if action == "move":
        return
    if action == "down":
        mouse.press(btn)
    elif action == "up":
        mouse.release(btn)
    elif action == "click":
        mouse.click(btn, 1)
    elif action == "wheel":
        try:
            mouse.scroll(0, int(dy / 120) if abs(dy) >= 1 else int(dy))
        except Exception:
            pass


def _inject_key(action: str, key: str, modifiers: list[str] | None = None) -> None:
    from pynput.keyboard import Controller, Key

    kb = Controller()
    special = {
        "enter": Key.enter,
        "return": Key.enter,
        "tab": Key.tab,
        "esc": Key.esc,
        "escape": Key.esc,
        "backspace": Key.backspace,
        "delete": Key.delete,
        "space": Key.space,
        "up": Key.up,
        "down": Key.down,
        "left": Key.left,
        "right": Key.right,
        "home": Key.home,
        "end": Key.end,
        "pageup": Key.page_up,
        "pagedown": Key.page_down,
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "alt": Key.alt,
        "shift": Key.shift,
        "cmd": Key.cmd,
        "meta": Key.cmd,
        "win": Key.cmd,
        "f1": Key.f1,
        "f2": Key.f2,
        "f3": Key.f3,
        "f4": Key.f4,
        "f5": Key.f5,
        "f6": Key.f6,
        "f7": Key.f7,
        "f8": Key.f8,
        "f9": Key.f9,
        "f10": Key.f10,
        "f11": Key.f11,
        "f12": Key.f12,
    }
    mods = modifiers or []
    pressed_mods = []
    try:
        for m in mods:
            mk = special.get(str(m).lower())
            if mk is not None:
                kb.press(mk)
                pressed_mods.append(mk)
        k = special.get(str(key).lower())
        if k is None:
            if len(key) == 1:
                k = key
            else:
                return
        if action == "down":
            kb.press(k)
        elif action == "up":
            kb.release(k)
        else:
            kb.press(k)
            kb.release(k)
    finally:
        for mk in reversed(pressed_mods):
            try:
                kb.release(mk)
            except Exception:
                pass


class LanRemoteHost:
    """WebSocket screen-share host (one viewer)."""

    def __init__(self) -> None:
        self._password = ""
        self._port = DEFAULT_PORT
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._stop = threading.Event()
        self._clients = 0
        self._lock = threading.Lock()
        self._max_side = 1440
        self._quality = 72
        self._fps = 16
        self._screen_w = 1920
        self._screen_h = 1080
        self._on_status: Callable[[str], None] | None = None

    def set_status_callback(self, cb: Callable[[str], None] | None) -> None:
        self._on_status = cb

    def _emit(self, msg: str) -> None:
        cb = self._on_status
        if cb:
            try:
                cb(msg)
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> HostStatus:
        return HostStatus(
            running=self.running,
            port=self._port,
            clients=self._clients,
            message="监听中" if self.running else "未开启",
            password_set=bool(self._password),
        )

    def start(
        self,
        password: str,
        *,
        port: int = DEFAULT_PORT,
        max_side: int = 1440,
        quality: int = 72,
        fps: int = 16,
    ) -> str:
        password = (password or "").strip()
        if len(password) < MIN_PASSWORD_LEN:
            return f"密码至少 {MIN_PASSWORD_LEN} 位"
        if self.running:
            return "被控已在运行"
        self._password = password
        self._port = int(port)
        self._max_side = int(max_side)
        self._quality = int(quality)
        self._fps = max(5, min(25, int(fps)))
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="LanRemoteHost", daemon=True)
        self._thread.start()
        self._emit(f"被控已开启 · 端口 {self._port}")
        return f"被控已开启（端口 {self._port}）"

    def stop(self) -> str:
        self._stop.set()
        loop = self._loop
        server = self._server
        if loop and server:
            try:
                fut = asyncio.run_coroutine_threadsafe(server.close(), loop)
                fut.result(timeout=2)
            except Exception:
                pass
        if loop:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._thread = None
        self._loop = None
        self._server = None
        self._clients = 0
        self._emit("被控已关闭")
        return "被控已关闭"

    def _thread_main(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_until_complete(self._run_server())
        except Exception as e:
            self._emit(f"被控异常：{e}")
        finally:
            try:
                loop = self._loop
                if loop and not loop.is_closed():
                    loop.close()
            except Exception:
                pass
            self._loop = None
            self._server = None
            self._clients = 0

    async def _run_server(self) -> None:
        import websockets
        from websockets.server import serve

        async def handler(ws):
            await self._handle_client(ws)

        async with serve(
            handler,
            "0.0.0.0",
            self._port,
            max_size=8 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as server:
            self._server = server
            self._emit(f"正在监听 0.0.0.0:{self._port}")
            while not self._stop.is_set():
                await asyncio.sleep(0.2)
            self._server = None

    async def _handle_client(self, ws) -> None:
        if self._clients >= 1:
            await ws.send(json.dumps({"type": "auth_fail", "error": "已有连接，请稍后"}))
            await ws.close()
            return
        self._clients += 1
        self._emit("有主控正在连接…")
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            if isinstance(raw, bytes):
                await ws.send(json.dumps({"type": "auth_fail", "error": "请先发送认证 JSON"}))
                return
            msg = json.loads(raw)
            if msg.get("type") != "auth" or str(msg.get("password") or "") != self._password:
                await ws.send(json.dumps({"type": "auth_fail", "error": "密码错误"}))
                return

            # Probe screen size
            try:
                from screen_recorder import capture_bgr

                frame = capture_bgr(None)
                if frame is not None:
                    self._screen_h, self._screen_w = int(frame.shape[0]), int(frame.shape[1])
            except Exception:
                pass

            await ws.send(
                json.dumps(
                    {
                        "type": "auth_ok",
                        "w": self._screen_w,
                        "h": self._screen_h,
                        "fps": self._fps,
                        "scale_w": min(self._screen_w, self._max_side),
                        "scale_h": min(
                            self._screen_h,
                            int(self._screen_h * (self._max_side / max(self._screen_w, 1))),
                        ),
                    }
                )
            )
            self._emit("主控已连接，正在推流")
            await self._session_loop(ws)
        except Exception as e:
            self._emit(f"会话结束：{e}")
        finally:
            self._clients = max(0, self._clients - 1)
            if self.running:
                self._emit("等待主控连接…")

    async def _session_loop(self, ws) -> None:
        from screen_recorder import capture_bgr

        frame_n = 0
        max_side = self._max_side
        quality = self._quality
        fps = self._fps
        interval = 1.0 / fps
        pending_input: asyncio.Queue = asyncio.Queue()

        session_done = asyncio.Event()

        async def reader():
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    await pending_input.put(msg)
            except Exception:
                pass
            finally:
                session_done.set()
                await pending_input.put({"type": "_eof"})

        reader_task = asyncio.create_task(reader())
        backlog = 0
        try:
            while not self._stop.is_set() and not session_done.is_set():
                # Drain input
                while True:
                    try:
                        msg = pending_input.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if msg.get("type") == "_eof":
                        return
                    await self._apply_input(msg)

                t0 = time.perf_counter()
                try:
                    bgr = await asyncio.to_thread(capture_bgr, None)
                    jpeg, fw, fh = await asyncio.to_thread(
                        _encode_jpeg, bgr, max_side=max_side, quality=quality
                    )
                    frame_n += 1
                    meta = json.dumps(
                        {"type": "frame", "w": fw, "h": fh, "q": quality, "n": frame_n}
                    )
                    await ws.send(meta)
                    await ws.send(jpeg)
                    backlog = 0
                except Exception as e:
                    backlog += 1
                    if backlog > 30:
                        self._emit(f"推流失败：{e}")
                        return
                    # Adaptive degrade
                    max_side = max(960, max_side - 80)
                    quality = max(50, quality - 5)
                    fps = max(8, fps - 2)
                    interval = 1.0 / fps

                elapsed = time.perf_counter() - t0
                await asyncio.sleep(max(0.01, interval - elapsed))
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except Exception:
                pass

    async def _apply_input(self, msg: dict[str, Any]) -> None:
        typ = msg.get("type")
        if typ == "mouse":
            x = float(msg.get("x") or 0)
            y = float(msg.get("y") or 0)
            # normalized 0..1 → pixels
            px = x * self._screen_w
            py = y * self._screen_h
            action = str(msg.get("action") or "move")
            button = str(msg.get("button") or "left")
            dy = float(msg.get("dy") or 0)
            await asyncio.to_thread(_inject_mouse, action, px, py, button, dy)
        elif typ == "key":
            await asyncio.to_thread(
                _inject_key,
                str(msg.get("action") or "down"),
                str(msg.get("key") or ""),
                list(msg.get("modifiers") or []),
            )
        elif typ == "ping":
            pass


class LanRemoteClient:
    """Connect to a LAN remote host and receive frames / send input."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._stop = threading.Event()
        self._screen_w = 1
        self._screen_h = 1
        self._connected = False
        self.on_status: Callable[[str], None] | None = None
        self.on_frame: Callable[[bytes, int, int], None] | None = None
        self.on_closed: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, host: str, password: str, *, port: int = DEFAULT_PORT) -> str:
        host = (host or "").strip()
        password = (password or "").strip()
        if not host:
            return "请填写对方 IP"
        if len(password) < MIN_PASSWORD_LEN:
            return f"密码至少 {MIN_PASSWORD_LEN} 位"
        if self._thread and self._thread.is_alive():
            return "已在连接中"
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(host, int(port), password),
            name="LanRemoteClient",
            daemon=True,
        )
        self._thread.start()
        return f"正在连接 {host}:{port}…"

    def disconnect(self) -> None:
        self._stop.set()
        loop = self._loop
        ws = self._ws
        if loop and ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop).result(timeout=2)
            except Exception:
                pass
        if loop:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._thread = None
        self._ws = None
        self._loop = None
        self._connected = False

    def send_mouse(
        self,
        action: str,
        nx: float,
        ny: float,
        *,
        button: str = "left",
        dy: float = 0,
    ) -> None:
        self._send_json(
            {
                "type": "mouse",
                "action": action,
                "x": max(0.0, min(1.0, float(nx))),
                "y": max(0.0, min(1.0, float(ny))),
                "button": button,
                "dy": dy,
            }
        )

    def send_key(self, action: str, key: str, modifiers: list[str] | None = None) -> None:
        self._send_json(
            {
                "type": "key",
                "action": action,
                "key": key,
                "modifiers": modifiers or [],
            }
        )

    def _send_json(self, obj: dict) -> None:
        loop = self._loop
        ws = self._ws
        if not loop or ws is None or not self._connected:
            return
        try:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(obj)), loop)
        except Exception:
            pass

    def _emit_status(self, msg: str) -> None:
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _thread_main(self, host: str, port: int, password: str) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_until_complete(self._run(host, port, password))
        except Exception as e:
            self._emit_status(f"连接失败：{e}")
        finally:
            self._connected = False
            self._ws = None
            if self.on_closed:
                try:
                    self.on_closed()
                except Exception:
                    pass
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.close()
            except Exception:
                pass
            self._loop = None

    async def _run(self, host: str, port: int, password: str) -> None:
        import websockets

        uri = f"ws://{host}:{port}"
        self._emit_status(f"连接 {uri} …")
        async with websockets.connect(uri, max_size=8 * 1024 * 1024, open_timeout=8) as ws:
            self._ws = ws
            await ws.send(
                json.dumps(
                    {
                        "type": "auth",
                        "password": password,
                        "role": "viewer",
                        "name": secrets.token_hex(3),
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            if isinstance(raw, bytes):
                self._emit_status("认证响应异常")
                return
            msg = json.loads(raw)
            if msg.get("type") != "auth_ok":
                self._emit_status(f"认证失败：{msg.get('error') or msg}")
                return
            self._screen_w = max(1, int(msg.get("w") or 1))
            self._screen_h = max(1, int(msg.get("h") or 1))
            self._connected = True
            self._emit_status("已连接，接收画面中")

            expect_jpeg = False
            meta_w = meta_h = 0
            async for raw in ws:
                if self._stop.is_set():
                    break
                if isinstance(raw, str):
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("type") == "frame":
                        expect_jpeg = True
                        meta_w = int(m.get("w") or 0)
                        meta_h = int(m.get("h") or 0)
                    continue
                if expect_jpeg and isinstance(raw, (bytes, bytearray)):
                    expect_jpeg = False
                    if self.on_frame:
                        try:
                            self.on_frame(bytes(raw), meta_w, meta_h)
                        except Exception:
                            pass
