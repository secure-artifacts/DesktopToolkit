"""Cross-network P2P / zero-storage transfer via Cloudflare Worker signaling.

Architecture:
  - Cloudflare Worker = room WebSocket fan-out only (signaling + optional chunk relay)
  - No files stored on Cloudflare (stream forward, discard)
  - Room code pairs two clients; sender streams file chunks to receiver

Protocol (JSON text frames + binary frames):
  {"type":"hello","role":"send|recv","name":"..."}
  {"type":"offer","name":"file.mp4","size":12345,"sha1":"..."}
  {"type":"accept"} / {"type":"reject"}
  {"type":"chunk","index":0,"total":10}  + following binary payload
  {"type":"done"}
  {"type":"error","message":"..."}
  {"type":"progress","index":0,"total":10}
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
from pathlib import Path
from typing import Callable

# websockets is optional at import; install via requirements
try:
    import websockets
    from websockets.sync.client import connect as ws_connect
except Exception:
    websockets = None
    ws_connect = None


# User-configured Worker URL (leave empty — fill in app settings after self-deploy)
DEFAULT_SIGNAL_URL = ""
CHUNK = 256 * 1024  # 256 KiB
# Cloudflare Workers Free plan (account-wide, shared across all Workers)
FREE_DAILY_REQUEST_LIMIT = 100_000


def make_room_code(n: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def normalize_ws_url(url: str, room: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ValueError("请填写 Cloudflare Worker 地址（wss://xxx.workers.dev）")
    if u.startswith("https://"):
        u = "wss://" + u[len("https://") :]
    elif u.startswith("http://"):
        u = "ws://" + u[len("http://") :]
    elif not u.startswith("ws://") and not u.startswith("wss://"):
        u = "wss://" + u
    # ensure /ws path
    if "/ws" not in u:
        u = u + "/ws"
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}room={room.upper()}"


def normalize_http_base(url: str) -> str:
    """Turn wss/ws/https worker URL into https base (no /ws)."""
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ValueError("请填写 Cloudflare Worker 地址")
    if u.startswith("wss://"):
        u = "https://" + u[len("wss://") :]
    elif u.startswith("ws://"):
        u = "http://" + u[len("ws://") :]
    elif u.startswith("http://") or u.startswith("https://"):
        pass
    else:
        u = "https://" + u
    # strip /ws and query
    if "?" in u:
        u = u.split("?", 1)[0]
    if u.endswith("/ws"):
        u = u[: -len("/ws")]
    return u.rstrip("/")


def fetch_worker_health(signal_url: str, timeout: float = 8.0) -> dict:
    """GET /health — verify Worker is up and Durable Object rooms are bound."""
    import urllib.error
    import urllib.request

    base = normalize_http_base(signal_url)
    req = urllib.request.Request(
        f"{base}/health",
        headers={"Accept": "application/json", "User-Agent": "DesktopToolkit-P2P/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"健康检查 HTTP {e.code}: {body[:200] or e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"无法访问中转：{e}") from e

    data = json.loads(raw)
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError("中转 /health 返回异常，请确认地址与部署是否正确")
    # Old workers omit this field — treat missing as False (pairing often fails)
    if "durable_rooms" not in data:
        data["durable_rooms"] = False
    return data


def fetch_worker_usage(signal_url: str, timeout: float = 8.0) -> dict:
    """GET /usage from Worker. Returns dict with used/remaining or raises."""
    import urllib.error
    import urllib.request

    base = normalize_http_base(signal_url)
    req = urllib.request.Request(
        f"{base}/usage",
        headers={"Accept": "application/json", "User-Agent": "DesktopToolkit-P2P/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"额度接口 HTTP {e.code}: {body[:200] or e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"无法查询额度: {e}") from e

    data = json.loads(raw)
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError("额度接口返回异常（请重新部署 Worker 到含 /usage 的版本）")
    # Normalize fields with safe defaults
    limit = int(data.get("daily_limit") or FREE_DAILY_REQUEST_LIMIT)
    used = int(data.get("worker_requests_today") or 0)
    remaining = int(data.get("remaining_estimate") if data.get("remaining_estimate") is not None else max(0, limit - used))
    return {
        "ok": True,
        "plan": str(data.get("plan") or "free"),
        "daily_limit": limit,
        "day_utc": str(data.get("day_utc") or ""),
        "worker_requests_today": used,
        "remaining_estimate": remaining,
        "percent_used": float(data.get("percent_used") or 0),
        "note": str(data.get("note") or ""),
        "raw": data,
    }


def format_usage_line(info: dict) -> str:
    """Short Chinese status line for the UI."""
    used = int(info.get("worker_requests_today") or 0)
    limit = int(info.get("daily_limit") or FREE_DAILY_REQUEST_LIMIT)
    rem = int(info.get("remaining_estimate") if info.get("remaining_estimate") is not None else max(0, limit - used))
    day = info.get("day_utc") or ""
    pct = info.get("percent_used")
    if pct is None:
        pct = round(used * 1000 / max(1, limit)) / 10
    # Color-ish hint via emoji only (QLabel is plain text)
    if rem <= 0:
        flag = "⛔"
    elif rem < limit * 0.1:
        flag = "⚠️"
    else:
        flag = "✅"
    day_s = f" · UTC {day}" if day else ""
    return (
        f"{flag} 今日约已用 {used:,} / {limit:,} 次请求，"
        f"剩余约 {rem:,}（{pct}%）{day_s}\n"
        f"提示：建连计请求，传文件块不计；一次传输双方各连 ≈ 扣 2 次。额度全账户共享。"
    )


class P2PSession:
    def __init__(
        self,
        signal_url: str,
        room: str,
        *,
        on_status: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self.signal_url = signal_url
        self.room = room.upper().strip()
        self.on_status = on_status or (lambda m: None)
        self.on_progress = on_progress or (lambda a, b, c: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def stop(self) -> None:
        self._stop.set()

    def send_file_async(self, path: str | Path) -> None:
        self._thread = threading.Thread(target=self._send_file, args=(Path(path),), daemon=True)
        self._thread.start()

    def receive_file_async(self, dest_dir: str | Path) -> None:
        self._thread = threading.Thread(target=self._recv_file, args=(Path(dest_dir),), daemon=True)
        self._thread.start()

    def _send_file(self, path: Path) -> None:
        if ws_connect is None:
            self.on_status("缺少 websockets 库，请 pip install websockets")
            return
        if not path.is_file():
            self.on_status("文件不存在")
            return
        url = normalize_ws_url(self.signal_url, self.room)
        size = path.stat().st_size
        total = max(1, (size + CHUNK - 1) // CHUNK)
        sha = hashlib.sha1()
        self.on_status(f"连接中转… 房间 {self.room}")
        try:
            with ws_connect(url, open_timeout=20, max_size=CHUNK * 4) as ws:
                hello = json.dumps({"type": "hello", "role": "send", "name": path.name})
                offer = json.dumps(
                    {
                        "type": "offer",
                        "name": path.name,
                        "size": size,
                        "chunks": total,
                    }
                )
                ws.send(hello)
                self.on_status(
                    f"已进入房间 {self.room}，等待对方点「等待接收」…\n"
                    "请确认双方中转地址与房间号完全一致。"
                )
                # Wait for peer hello / accept. Re-hello periodically so late joiners work.
                peer_ready = False
                offer_sent = False
                for i in range(1800):  # ~3 min (0.1s * 1800)
                    if self._stop.is_set():
                        return
                    # every ~2s re-announce so receiver who joined first still pairs
                    if i % 20 == 0:
                        try:
                            ws.send(hello)
                            if offer_sent:
                                ws.send(offer)
                        except Exception:
                            pass
                    try:
                        msg = ws.recv(timeout=0.1)
                    except Exception:
                        continue
                    if isinstance(msg, bytes):
                        continue
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    t = data.get("type")
                    if t == "hello" and data.get("role") == "recv":
                        ws.send(offer)
                        offer_sent = True
                        self.on_status("已发现接收方，已发送文件信息，等待确认…")
                    elif t == "accept":
                        peer_ready = True
                        break
                    elif t == "reject":
                        self.on_status("对方拒绝接收")
                        return
                    elif t == "hello" and data.get("role") == "send":
                        self.on_status("房间里已有另一个发送方，请换一个房间号")
                        return
                    elif t == "ping":
                        try:
                            ws.send(json.dumps({"type": "pong"}))
                        except Exception:
                            pass
                if not peer_ready:
                    self.on_status(
                        "等待对方超时（约 3 分钟）。\n"
                        "请检查：\n"
                        "① 双方房间号是否完全相同（建议一方生成后口述/复制给另一方）\n"
                        "② 双方中转地址是否完全相同（同一 *.workers.dev）\n"
                        "③ 对方是否已先点「等待接收」且仍显示在房间内\n"
                        "④ 浏览器打开 https://你的地址/health ，确认 durable_rooms 为 true\n"
                        "   （false 时双方会被分到不同服务器，永远等不到对方）\n"
                        "⑤ 若 durable_rooms=false：在 cloudflare/ 执行 wrangler deploy 更新 Worker"
                    )
                    return

                self.on_status(f"开始发送 {path.name} ({size} 字节)")
                with path.open("rb") as f:
                    for i in range(total):
                        if self._stop.is_set():
                            ws.send(json.dumps({"type": "error", "message": "cancelled"}))
                            return
                        chunk = f.read(CHUNK)
                        sha.update(chunk)
                        meta = json.dumps({"type": "chunk", "index": i, "total": total, "n": len(chunk)})
                        ws.send(meta)
                        ws.send(chunk)
                        self.on_progress(i + 1, total, path.name)
                ws.send(json.dumps({"type": "done", "sha1": sha.hexdigest()}))
                self.on_status(f"✅ 发送完成：{path.name}")
        except Exception as exc:
            err = str(exc)
            if "timed out" in err.lower() or "timeout" in err.lower():
                self.on_status(
                    f"连接中转超时：{exc}\n"
                    "请检查中转地址是否可访问（wss://…workers.dev），以及本机网络/代理。"
                )
            else:
                self.on_status(f"发送失败：{exc}")

    def _recv_file(self, dest_dir: Path) -> None:
        if ws_connect is None:
            self.on_status("缺少 websockets 库，请 pip install websockets")
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        url = normalize_ws_url(self.signal_url, self.room)
        self.on_status(f"连接中转… 房间 {self.room}")
        try:
            with ws_connect(url, open_timeout=20, max_size=CHUNK * 4) as ws:
                hello = json.dumps({"type": "hello", "role": "recv"})
                ws.send(hello)
                self.on_status(
                    f"已进入房间 {self.room}，等待对方发送文件…\n"
                    "请确认双方中转地址与房间号完全一致。"
                )
                offer = None
                for i in range(1800):  # ~3 min
                    if self._stop.is_set():
                        return
                    # re-hello so sender who joined earlier still sees us
                    if i % 20 == 0:
                        try:
                            ws.send(hello)
                        except Exception:
                            pass
                    try:
                        msg = ws.recv(timeout=0.1)
                    except Exception:
                        continue
                    if isinstance(msg, bytes):
                        continue
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    t = data.get("type")
                    if t == "offer":
                        offer = data
                        break
                    if t == "hello" and data.get("role") == "send":
                        # 发送方先到时：再发一次 hello，触发对方回 offer
                        try:
                            ws.send(hello)
                        except Exception:
                            pass
                        self.on_status("已发现发送方，等待文件信息…")
                        continue
                    if t == "hello" and data.get("role") == "recv":
                        self.on_status("房间里已有另一个接收方，请换一个房间号")
                        return
                if not offer:
                    self.on_status(
                        "等待文件信息超时（约 3 分钟）。\n"
                        "请检查：\n"
                        "① 双方房间号 + 中转地址是否完全相同\n"
                        "② 发送方是否已点「发送文件」且未先超时\n"
                        "③ https://你的地址/health 是否 durable_rooms=true\n"
                        "④ 若为 false：cd cloudflare && npx wrangler deploy 后重试"
                    )
                    return
                name = Path(str(offer.get("name") or "received.bin")).name
                size = int(offer.get("size") or 0)
                total = int(offer.get("chunks") or 1)
                self.on_status(f"对方要发送：{name} ({size} 字节)，开始接收…")
                ws.send(json.dumps({"type": "accept"}))

                out_path = dest_dir / name
                # avoid overwrite
                if out_path.exists():
                    stem, suf = out_path.stem, out_path.suffix
                    out_path = dest_dir / f"{stem}_recv{suf}"
                sha = hashlib.sha1()
                with out_path.open("wb") as f:
                    idx_expect = 0
                    while idx_expect < total:
                        if self._stop.is_set():
                            return
                        try:
                            meta_raw = ws.recv(timeout=60)
                        except Exception as exc:
                            self.on_status(
                                f"接收中断：{exc}\n"
                                "可能是网络不稳、对方取消，或中转连接断开。请双方重试。"
                            )
                            return
                        if isinstance(meta_raw, bytes):
                            # unexpected binary without meta
                            f.write(meta_raw)
                            sha.update(meta_raw)
                            idx_expect += 1
                            self.on_progress(idx_expect, total, name)
                            continue
                        meta = json.loads(meta_raw)
                        t = meta.get("type")
                        if t == "error":
                            self.on_status(f"对方取消：{meta.get('message')}")
                            return
                        if t == "done":
                            break
                        if t != "chunk":
                            continue
                        try:
                            blob = ws.recv(timeout=60)
                        except Exception as exc:
                            self.on_status(f"读数据块失败：{exc}")
                            return
                        if not isinstance(blob, (bytes, bytearray)):
                            self.on_status("协议错误：期望二进制块")
                            return
                        f.write(blob)
                        sha.update(blob)
                        idx_expect = int(meta.get("index") or idx_expect) + 1
                        self.on_progress(idx_expect, total, name)
                self.on_status(f"✅ 已保存：{out_path}")
        except Exception as exc:
            err = str(exc)
            if "timed out" in err.lower() or "timeout" in err.lower():
                self.on_status(
                    f"连接中转超时：{exc}\n"
                    "请检查中转地址、网络/代理，以及 Cloudflare Worker 是否已部署。"
                )
            else:
                self.on_status(f"接收失败：{exc}")
