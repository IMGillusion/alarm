#!/usr/bin/env python3
"""alarm 子项目入口：常驻 tick 服务。

由 supervisor 拉起:  .venv/bin/python subprojects/alarm/main.py
每 tick_interval 秒扫一遍闹钟，到点的通过 tmux send-keys 注入幻日常驻终端，
消息前缀 [闹钟提醒]，幻日看到后自己处理。
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import alarm  # noqa: E402

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [alarm] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "alarm.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("alarm.main")

TICK = int(alarm.CFG.get("tick_interval_seconds", 2))
MIN_GAP = int(alarm.CFG.get("min_gap_seconds", 5))


def run() -> None:
    last_global_fire = 0.0  # 防抖：两条注入之间最短 MIN_GAP 秒
    log.info("alarm 服务启动：session=%s 前缀=%s tick=%ss min_gap=%ss",
             alarm.TMUX_SESSION, alarm.PREFIX, TICK, MIN_GAP)
    while True:
        try:
            data = alarm._load()
            now_dt = alarm.now()
            ts = time.time()
            for a in data["alarms"]:
                if not a.get("enabled"):
                    continue
                slot = alarm.compute_next_fire(a)
                if slot is None or now_dt < slot:
                    continue
                # 一次性闹钟过期太久（服务停了错过），不补发，直接作废
                if a["repeat"] == "once" and (now_dt - slot) > timedelta(minutes=5):
                    a["enabled"] = False
                    log.info("一次性闹钟 %s 错过太久，作废不补发（原定 %s）",
                             a["id"], a["at"])
                    continue
                # 全局防抖：同刻多个闹钟一起到点时，拉开间隔，别连发刷屏
                if ts - last_global_fire < MIN_GAP:
                    continue
                msg = alarm.make_message(a)
                ok = alarm.inject_to_tmux(msg)
                alarm.advance(a)
                last_global_fire = time.time()
                log.info("闹钟触发 %s | %s | ok=%s", a["id"], a["task"], ok)
            # 本轮推进过状态（有 last_fired 变化）或一次性停用才落盘
            # 简化：每 tick 都落盘（数据量小，开销可忽略，且保证状态一致）
            alarm._save(data)
        except Exception:
            log.exception("alarm 主循环异常")
        time.sleep(TICK)


if __name__ == "__main__":
    run()
