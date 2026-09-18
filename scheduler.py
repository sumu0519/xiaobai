"""定时推送：按 scheduled_push 配置每日定时向指定 QQ/群发送内容
配置格式（每行一条）：HH:MM=>私聊:QQ号=>内容  或  HH:MM=>群:群号=>内容
"""
import asyncio
import datetime
import config


def _parse_rules() -> list[tuple[str, str, str]]:
    """返回 [(time_str, target, message)]，target 形如 '私聊:123' 或 '群:456'"""
    rules = []
    raw = config.load()["scheduled_push"] or ""
    for line in raw.splitlines():
        line = line.strip()
        parts = line.split("=>")
        if len(parts) == 3 and parts[0].strip() and parts[1].strip():
            rules.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rules


async def _send(call_action, target: str, message: str):
    kind, _, qid = target.partition(":")
    qid = qid.strip()
    if not qid.isdigit():
        return
    if kind == "群":
        await call_action("send_group_msg", group_id=int(qid), message=message)
    else:
        await call_action("send_private_msg", user_id=int(qid), message=message)


async def run_scheduler(call_action):
    """每 30 秒检查一次，HH:MM 匹配当前时间（每条规则每天只发一次）"""
    sent: set[str] = set()  # 规则行 -> 上次发送日期
    while True:
        try:
            now = datetime.datetime.now().strftime("%H:%M")
            today = datetime.date.today().isoformat()
            for t, target, message in _parse_rules():
                key = f"{t}|{target}"
                if t == now and sent.get(key) != today:
                    try:
                        await _send(call_action, target, message)
                        print(f"[push] 已定时推送 -> {target}")
                    except Exception as e:
                        print(f"[error] 定时推送失败 {target}: {e}")
                    sent[key] = today
        except Exception as e:
            print(f"[error] 调度器异常: {e}")
        await asyncio.sleep(30)
