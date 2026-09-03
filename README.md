# alarm

一个**tmux 注入式闹钟**子项目。到点不走任何 IM，直接 `tmux send-keys` 把提醒
打进你指定的常驻终端 session，消息带前缀标注是闹钟。给常驻 Agent / 终端守护
进程用的自提醒机制。

## 干嘛的

- 你有个长期跑着的终端 session（比如一个常驻 AI），想「到点提醒它干某事」，
  又不想依赖 QQ/微信等外部通道 → 直接注入它自己的终端最稳。
- 支持三种触发：**一次性**（绝对时间 / 从现在起偏移）、**固定间隔**、**cron 循环**。
- 内置两条护栏：间隔类最小 60s（别太频繁）、全局防抖 5s（同刻多个闹钟到点也拉开间隔，不刷屏）。

## 文件

| 文件 | 职责 |
|---|---|
| `alarm.py` | 数据模型、加载/保存、到点判定、状态推进、tmux 注入（核心逻辑） |
| `main.py`  | 常驻 tick 服务入口（每 2s 扫一遍闹钟，到点就注入） |
| `cli.py`   | 命令行增删改查闹钟 |
| `config.yaml` | 配置（session 名 / 前缀 / tick 间隔 / 护栏参数） |

## 配置

`config.yaml`：

| 键 | 默认 | 说明 |
|---|---|---|
| `tmux_session` | `huanri` | 要注入的 tmux session 名（**改成你自己的**） |
| `message_prefix` | `[闹钟提醒]` | 注入消息前缀 |
| `tick_interval_seconds` | 2 | 轮询间隔（秒） |
| `min_interval_seconds` | 60 | 间隔类闹钟最小间隔（护栏） |
| `min_gap_seconds` | 5 | 全局防抖：两条注入最短间隔 |
| `data_file` | `alarms.json` | 闹钟列表存储（运行时状态，建议 gitignore） |

## 用法

### 命令行

```bash
# 一次性：从现在起 30 分钟
python cli.py add "提醒喝水" --in 30m
# 一次性：绝对时间
python cli.py add "明早检查备份" --at "2026-09-02 09:00"
# 固定间隔：每 300 秒
python cli.py add "盯一下XX" --every 300
# cron 循环
python cli.py add "每日早报" --cron "0 9 * * *"

python cli.py list                 # 列出所有
python cli.py rm <id或子串>         # 删
python cli.py enable <id或子串>     # 启用
python cli.py disable <id或子串>    # 停用
```

### 常驻服务

`main.py` 是常驻 tick 循环，由 supervisor / systemd / tmux 保活拉起即可：

```bash
python main.py
```

## 依赖

- Python 3.8+
- `pyyaml`、`croniter`（cron 类型才需要）
- `tmux`（目标 session 必须已存在且可 `send-keys`）

## 设计要点 / 边界

- **到点判定**：`compute_next_fire` 算下一个应触发时刻，`now >= 该时刻` 就注入。
  一次性闹钟若错过太久（服务停了 >5 分钟）不补发，直接作废，避免恢复后爆一堆旧提醒。
- **状态推进**：触发后 `advance` 更新 `last_fired`（interval/cron 重锚定，防补发刷屏），
  once 类型直接停用。每 tick 落盘（数据量小，开销可忽略）。
- 闹钟数据是**本地 JSON 文件**，无数据库、无网络，进程间靠文件 + 原子 `os.replace` 写。

—— 幻日出品
