"""Lightweight productivity: todos, sticky notes, and Pomodoro focus timer.

Inspired by Super Productivity / Focus Buddy patterns, kept small and local.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _pomodoro_defaults() -> dict[str, Any]:
    return {
        "work_min": 25,
        "break_min": 5,
        "long_break_min": 15,
        "cycles_before_long": 4,
        "phase": "idle",
        "ends_at": None,
        "cycle_count": 0,
        "paused": False,
        "remaining_sec": 0,
    }


class TodoManager:
    """One board's item list. Boards live in state['todo_lists']."""

    def __init__(self, board: dict) -> None:
        self.board = board
        self.board.setdefault("items", [])

    def list_items(self) -> list[dict]:
        return list(self.board.get("items") or [])

    def add(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return "请填写待办内容。"
        item = {
            "id": _uid(),
            "text": cleaned[:200],
            "done": False,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        self.board.setdefault("items", []).insert(0, item)
        return f"已添加待办：{cleaned[:40]}"

    def toggle(self, item_id: str) -> str:
        for item in self.board.get("items") or []:
            if item.get("id") == item_id:
                item["done"] = not bool(item.get("done"))
                return "已完成。" if item["done"] else "已重新打开。"
        return "未找到该待办。"

    def remove(self, item_id: str) -> str:
        before = len(self.board.get("items") or [])
        self.board["items"] = [t for t in (self.board.get("items") or []) if t.get("id") != item_id]
        return "已删除待办。" if len(self.board["items"]) < before else "未找到该待办。"

    def clear_done(self) -> str:
        todos = self.board.get("items") or []
        kept = [t for t in todos if not t.get("done")]
        removed = len(todos) - len(kept)
        self.board["items"] = kept
        return f"已清除 {removed} 条已完成。"


class TodoBoardsStore:
    """Multiple floating todo boards (like multi sticky notes)."""

    DEFAULT_COLORS = [
        "#fef08a",
        "#bbf7d0",
        "#bfdbfe",
        "#fecaca",
        "#e9d5ff",
        "#fed7aa",
    ]

    def __init__(self, state: dict) -> None:
        self.state = state
        self._migrate()

    def _migrate(self) -> None:
        lists = self.state.get("todo_lists")
        if isinstance(lists, list) and lists:
            return
        # Migrate legacy flat todos[] + todo_board{}
        legacy = list(self.state.get("todos") or [])
        color = str((self.state.get("todo_board") or {}).get("color") or "#fef08a")
        self.state["todo_lists"] = [
            {
                "id": _uid(),
                "title": "待办",
                "color": color,
                "items": legacy,
            }
        ]

    def list_boards(self) -> list[dict]:
        self._migrate()
        return list(self.state.get("todo_lists") or [])

    def add_board(self, title: str | None = None) -> dict:
        self._migrate()
        n = len(self.list_boards()) + 1
        board = {
            "id": _uid(),
            "title": (title or "").strip() or f"待办 {n}",
            "color": self.DEFAULT_COLORS[(n - 1) % len(self.DEFAULT_COLORS)],
            "items": [],
        }
        self.state.setdefault("todo_lists", []).append(board)
        return board

    def get_board(self, board_id: str) -> dict | None:
        for b in self.list_boards():
            if b.get("id") == board_id:
                return b
        return None

    def remove_board(self, board_id: str) -> None:
        self.state["todo_lists"] = [
            b for b in (self.state.get("todo_lists") or []) if b.get("id") != board_id
        ]
        # Do not auto-recreate — user may want zero open boards until they click ＋


class NoteManager:
    def __init__(self, state: dict) -> None:
        self.state = state
        self.state.setdefault("notes", [])

    def list_items(self) -> list[dict]:
        return list(self.state.get("notes") or [])

    def add(self, title: str, body: str = "") -> dict:
        """Create a sticky note; returns the new note dict (empty body allowed)."""
        title = (title or "").strip()[:80] or "便签"
        body = (body or "").strip()[:4000]
        item = {
            "id": _uid(),
            "title": title,
            "body": body,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        self.state.setdefault("notes", []).insert(0, item)
        return item

    def get(self, note_id: str) -> dict | None:
        for item in self.state.get("notes") or []:
            if item.get("id") == note_id:
                return item
        return None

    def update(self, note_id: str, title: str, body: str) -> str:
        for item in self.state.get("notes") or []:
            if item.get("id") == note_id:
                item["title"] = (title or "").strip()[:80] or "便签"
                item["body"] = (body or "").strip()[:4000]
                item["updated"] = datetime.now().isoformat(timespec="seconds")
                return "便签已更新。"
        return "未找到该便签。"

    def remove(self, note_id: str) -> str:
        before = len(self.state.get("notes") or [])
        self.state["notes"] = [n for n in (self.state.get("notes") or []) if n.get("id") != note_id]
        return "已删除便签。" if len(self.state["notes"]) < before else "未找到该便签。"


class PomodoroTimer:
    """Simple focus cycles with work / short break / long break phases."""

    def __init__(self, state: dict) -> None:
        self.state = state
        cfg = self.state.setdefault("pomodoro", _pomodoro_defaults())
        for key, value in _pomodoro_defaults().items():
            cfg.setdefault(key, value)

    @property
    def cfg(self) -> dict[str, Any]:
        return self.state.setdefault("pomodoro", _pomodoro_defaults())

    def configure(
        self,
        work_min: int | None = None,
        break_min: int | None = None,
        long_break_min: int | None = None,
        cycles_before_long: int | None = None,
    ) -> None:
        cfg = self.cfg
        if work_min is not None:
            cfg["work_min"] = max(1, min(120, int(work_min)))
        if break_min is not None:
            cfg["break_min"] = max(1, min(60, int(break_min)))
        if long_break_min is not None:
            cfg["long_break_min"] = max(1, min(90, int(long_break_min)))
        if cycles_before_long is not None:
            cfg["cycles_before_long"] = max(1, min(12, int(cycles_before_long)))

    def status_text(self) -> str:
        cfg = self.cfg
        phase = str(cfg.get("phase") or "idle")
        labels = {
            "idle": "空闲",
            "work": "专注中",
            "break": "短休中",
            "long_break": "长休中",
        }
        label = labels.get(phase, phase)
        if phase == "idle":
            return f"番茄钟：{label} · 专注 {cfg.get('work_min', 25)} 分 / 休息 {cfg.get('break_min', 5)} 分"
        remaining = self.remaining_seconds()
        mm, ss = divmod(max(0, remaining), 60)
        paused = "（已暂停）" if cfg.get("paused") else ""
        return f"番茄钟：{label}{paused} · 剩余 {mm:02d}:{ss:02d} · 完成轮次 {int(cfg.get('cycle_count') or 0)}"

    def remaining_seconds(self) -> int:
        cfg = self.cfg
        if cfg.get("paused"):
            return max(0, int(cfg.get("remaining_sec") or 0))
        ends = cfg.get("ends_at")
        if not ends:
            return 0
        try:
            end_dt = datetime.fromisoformat(str(ends))
        except ValueError:
            return 0
        return max(0, int((end_dt - datetime.now()).total_seconds()))

    def is_running(self) -> bool:
        phase = str(self.cfg.get("phase") or "idle")
        return phase != "idle"

    def start_work(self) -> str:
        cfg = self.cfg
        minutes = int(cfg.get("work_min") or 25)
        cfg["phase"] = "work"
        cfg["paused"] = False
        cfg["remaining_sec"] = 0
        cfg["ends_at"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        return f"开始专注 {minutes} 分钟，加油～"

    def pause(self) -> str:
        cfg = self.cfg
        if not self.is_running() or cfg.get("paused"):
            return "当前没有进行中的番茄钟。"
        cfg["remaining_sec"] = self.remaining_seconds()
        cfg["paused"] = True
        cfg["ends_at"] = None
        return "已暂停番茄钟。"

    def resume(self) -> str:
        cfg = self.cfg
        if not cfg.get("paused"):
            return "番茄钟未暂停。"
        remaining = max(1, int(cfg.get("remaining_sec") or 0))
        cfg["paused"] = False
        cfg["ends_at"] = (datetime.now() + timedelta(seconds=remaining)).isoformat(timespec="seconds")
        cfg["remaining_sec"] = 0
        return "继续番茄钟。"

    def skip(self) -> str | None:
        """Skip current phase; returns announcement or None if idle."""
        if not self.is_running():
            return None
        return self._advance(force=True)

    def stop(self) -> str:
        cfg = self.cfg
        cfg["phase"] = "idle"
        cfg["ends_at"] = None
        cfg["paused"] = False
        cfg["remaining_sec"] = 0
        return "已结束番茄钟。"

    def tick(self) -> str | None:
        """Return announcement when a phase ends; otherwise None."""
        cfg = self.cfg
        if not self.is_running() or cfg.get("paused"):
            return None
        if self.remaining_seconds() > 0:
            return None
        return self._advance(force=False)

    def _advance(self, *, force: bool) -> str:
        cfg = self.cfg
        phase = str(cfg.get("phase") or "idle")
        if phase == "work":
            cfg["cycle_count"] = int(cfg.get("cycle_count") or 0) + 1
            every = max(1, int(cfg.get("cycles_before_long") or 4))
            if cfg["cycle_count"] % every == 0:
                minutes = int(cfg.get("long_break_min") or 15)
                cfg["phase"] = "long_break"
                msg = f"专注结束！完成第 {cfg['cycle_count']} 轮，长休 {minutes} 分钟吧～"
            else:
                minutes = int(cfg.get("break_min") or 5)
                cfg["phase"] = "break"
                msg = f"专注结束！休息 {minutes} 分钟，站起来走走～"
            cfg["paused"] = False
            cfg["remaining_sec"] = 0
            cfg["ends_at"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            return msg
        if phase in {"break", "long_break"}:
            minutes = int(cfg.get("work_min") or 25)
            cfg["phase"] = "work"
            cfg["paused"] = False
            cfg["remaining_sec"] = 0
            cfg["ends_at"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            return f"休息好了，开始下一轮专注 {minutes} 分钟！"
        if force:
            return self.stop()
        cfg["phase"] = "idle"
        cfg["ends_at"] = None
        return "番茄钟已结束。"
