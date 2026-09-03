#!/usr/bin/env python3
"""alarm 子项目命令行：幻日自己增删改查闹钟。

用法（在本项目根目录）:
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py add "提醒喝水" --in 30m
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py add "明早检查备份" --at "2026-09-02 09:00"
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py add "盯一下XX" --every 300
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py add "每日早报" --cron "0 9 * * *"
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py list
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py rm <id或子串>
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py enable <id或子串>
  subprojects/alarm/.venv/bin/python subprojects/alarm/cli.py disable <id或子串>
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import alarm  # noqa: E402


def parse_offset(s: str) -> timedelta:
    """'90s' / '30m' / '2h' / '1h30m' → timedelta。"""
    s = s.strip().lower()
    if not s:
        raise ValueError("偏移量不能为空")
    m = re.fullmatch(r"(\d+[smh])+", s)
    if not m:
        raise ValueError(f"偏移量格式不对: {s!r}（支持 90s / 30m / 2h / 1h30m）")
    total = 0
    for num, unit in re.findall(r"(\d+)([smh])", s):
        total += int(num) * {"s": 1, "m": 60, "h": 3600}[unit]
    return timedelta(seconds=total)


def find_alarm(key: str) -> dict:
    """按 id 或内容的唯一子串找一个闹钟；歧义/找不到就报错退出。"""
    matches = [a for a in alarm.list_alarms() if key in a["id"] or key in a["task"]]
    if not matches:
        sys.exit(f"找不到闹钟（id 或内容含 {key!r}），list 看看")
    if len(matches) > 1:
        ids = "\n".join(f"  {a['id']}  {a['task']}" for a in matches)
        sys.exit(f"{key!r} 匹配到 {len(matches)} 个闹钟，给全 id:\n{ids}")
    return matches[0]


def fmt_next(a: dict) -> str:
    slot = alarm.compute_next_fire(a)
    if slot is None:
        return "—（不再触发）"
    return slot.strftime(alarm.FMT_S)


def cmd_add(p: argparse.Namespace) -> None:
    at = p.at
    if p.offset:
        at = (alarm.now() + parse_offset(p.offset)).strftime(alarm.FMT_S)
    if p.cron:
        repeat, interval = "cron", None
    elif p.every:
        repeat, interval = "interval", p.every
    else:
        if not at:
            sys.exit("一次性闹钟要给时间：--at 'YYYY-MM-DD HH:MM' 或 --in 30m")
        repeat, interval = "once", None
    a = alarm.add_alarm(p.task, repeat=repeat, at=at,
                        interval_seconds=interval, cron=p.cron)
    print(f"已加 {a['id']}  [{a['repeat']}]  下次: {fmt_next(a)}")
    print(f"  内容: {a['task']}")


def cmd_list(_p: argparse.Namespace) -> None:
    rows = alarm.list_alarms()
    if not rows:
        print("（空）一个闹钟都没有")
        return
    for a in rows:
        sched = {"once": a["at"],
                 "interval": f"每 {a['interval_seconds']}s",
                 "cron": a["cron"]}.get(a["repeat"], "?")
        mark = "" if a["enabled"] else " [停用]"
        print(f"{a['id']}{mark}  [{a['repeat']}] {sched}")
        print(f"    内容: {a['task']}")
        print(f"    下次: {fmt_next(a)}   已响: {a.get('fire_count', 0)} 次")


def cmd_rm(p: argparse.Namespace) -> None:
    a = find_alarm(p.id)
    alarm.remove_alarm(a["id"])
    print(f"已删 {a['id']}  {a['task']}")


def cmd_set_enabled(p: argparse.Namespace, on: bool) -> None:
    a = find_alarm(p.id)
    alarm.set_enabled(a["id"], on)
    print(f"{'启用' if on else '停用'} {a['id']}  {a['task']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="闹钟管理（幻日自用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="加闹钟")
    pa.add_argument("task", help="提醒内容")
    pa.add_argument("--in", dest="offset", help="从现在起多久: 90s/30m/2h/1h30m（一次性）")
    pa.add_argument("--at", help="绝对时间 'YYYY-MM-DD HH:MM'（一次性）")
    pa.add_argument("--every", type=int, help="循环间隔秒数（最小 %d）" % alarm.MIN_INTERVAL)
    pa.add_argument("--cron", help="cron 表达式 5 段（如 '0 9 * * *'）")
    pa.set_defaults(fn=cmd_add)

    pl = sub.add_parser("list", help="列闹钟")
    pl.set_defaults(fn=cmd_list)

    pr = sub.add_parser("rm", help="删闹钟")
    pr.add_argument("id", help="闹钟 id 或内容（可用唯一子串）")
    pr.set_defaults(fn=cmd_rm)

    pe = sub.add_parser("enable", help="启用闹钟")
    pe.add_argument("id")
    pe.set_defaults(fn=lambda p: cmd_set_enabled(p, True))

    pd = sub.add_parser("disable", help="停用闹钟")
    pd.add_argument("id")
    pd.set_defaults(fn=lambda p: cmd_set_enabled(p, False))

    p = ap.parse_args()
    try:
        p.fn(p)
    except ValueError as e:
        sys.exit(f"参数不对: {e}")


if __name__ == "__main__":
    main()
