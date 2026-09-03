#!/usr/bin/env python3
"""alarm 子项目共享逻辑：闹钟数据模型、加载/保存、到点判定、触发(注入终端)。

本体 2026-09-01 设计：闹钟到点不走 QQ，直接 tmux send-keys 注入幻日常驻终端
（huanri session），消息前缀标注「闹钟提醒」，幻日看到后自己处理。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
FMT = "%Y-%m-%d %H:%M"
FMT_S = "%Y-%m-%d %H:%M:%S"


def load_config() -> dict:
    with open(HERE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


CFG = load_config()
DATA_FILE = HERE / str(CFG.get("data_file", "alarms.json"))
TMUX_SESSION = str(CFG.get("tmux_session", "huanri"))
PREFIX = str(CFG.get("message_prefix", "[闹钟提醒]"))
MIN_INTERVAL = int(CFG.get("min_interval_seconds", 60))
MIN_GAP = int(CFG.get("min_gap_seconds", 5))


def parse(s: str) -> datetime:
    if not s:
        raise ValueError("时间字符串为空")
    s = s.strip()
    fmt = FMT_S if len(s) >= 19 and s[10] == " " and len(s.split()) == 3 else FMT
    # 简单判断：含秒就按秒格式
    parts = s.split(":")
    fmt = FMT_S if (len(parts) == 3) else FMT
    return datetime.strptime(s, fmt)


def now() -> datetime:
    return datetime.now()


def _load() -> dict:
    if not DATA_FILE.exists():
        return {"alarms": []}
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"alarms": []}
    if not isinstance(data, dict) or "alarms" not in data:
        return {"alarms": []}
    return data


def _save(data: dict) -> None:
    tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


def list_alarms() -> list:
    return _load()["alarms"]


def _default_at() -> str:
    return now().strftime(FMT_S)


def add_alarm(task: str, repeat: str = "once", at: str | None = None,
              interval_seconds: int | None = None, cron: str | None = None) -> dict:
    """新增闹钟。
    repeat=once:     需要 at（绝对时间）
    repeat=interval: 需要 interval_seconds（>= MIN_INTERVAL），at 缺省=现在
    repeat=cron:     需要 cron（5 段），at 作锚点（缺省=现在）
    """
    task = task.strip()
    if not task:
        raise ValueError("任务内容不能为空")
    if repeat == "interval":
        sec = int(interval_seconds or 0)
        if sec < MIN_INTERVAL:
            raise ValueError(f"间隔太频繁：最小 {MIN_INTERVAL} 秒（你要 {sec} 秒）")
    if repeat == "once" and not at:
        raise ValueError("一次性闹钟需要指定时间 at（如 '2026-09-01 15:00'）或用 --in")
    # 校验时间/cron 格式
    if repeat == "once" and at:
        parse(at)
    if repeat == "interval":
        if at:
            parse(at)
    if repeat == "cron":
        if not cron:
            raise ValueError("循环(cron)闹钟需要指定 cron 表达式（如 '0 9 * * *'）")
        from croniter import croniter
        croniter(cron)  # 校验格式

    data = _load()
    a = {
        "id": "a-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
        "task": task,
        "repeat": repeat,
        "at": at or _default_at(),
        "interval_seconds": int(interval_seconds) if interval_seconds else None,
        "cron": cron,
        "enabled": True,
        "created_at": now().strftime(FMT_S),
        "last_fired": None,
        "fire_count": 0,
    }
    data["alarms"].append(a)
    _save(data)
    return a


def remove_alarm(aid: str) -> bool:
    data = _load()
    before = len(data["alarms"])
    data["alarms"] = [a for a in data["alarms"] if a["id"] != aid]
    _save(data)
    return len(data["alarms"]) != before


def set_enabled(aid: str, enabled: bool) -> bool:
    data = _load()
    for a in data["alarms"]:
        if a["id"] == aid:
            a["enabled"] = enabled
            _save(data)
            return True
    return False


def get_alarm(aid: str):
    for a in _load()["alarms"]:
        if a["id"] == aid:
            return a
    return None


def compute_next_fire(a: dict):
    """返回该闹钟下一个应触发时间点；不再触发（停用 / once 已响）返回 None。"""
    if not a.get("enabled"):
        return None
    r = a["repeat"]
    if r == "once":
        return None if a.get("last_fired") else parse(a["at"])
    if r == "interval":
        sec = int(a["interval_seconds"])
        if not a.get("last_fired"):
            return parse(a["at"])
        return parse(a["last_fired"]) + timedelta(seconds=sec)
    if r == "cron":
        from croniter import croniter
        anchor = parse(a["last_fired"]) if a.get("last_fired") else parse(a["at"])
        return croniter(a["cron"], anchor).get_next(datetime)
    return None


def advance(a: dict) -> None:
    """触发后推进状态：once → 停用；interval/cron → last_fired=now（重锚定，防补发刷屏）。"""
    if a["repeat"] == "once":
        a["enabled"] = False
    a["last_fired"] = now().strftime(FMT_S)
    a["fire_count"] = int(a.get("fire_count", 0)) + 1


def make_message(a: dict) -> str:
    return f"{PREFIX} {a['task']}（闹钟id:{a['id']}）"


def inject_to_tmux(text: str) -> bool:
    """往幻日常驻终端注入一行（跟 hermes_worker 的 QQ 触发同一手法）。"""
    try:
        r = subprocess.run(
            ["tmux", "send-keys", "-t", TMUX_SESSION, "-l", text],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        subprocess.run(
            ["tmux", "send-keys", "-t", TMUX_SESSION, "Enter"],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False
