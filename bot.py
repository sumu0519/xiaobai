"""QQ 机器人主程序：OneBot 11 + Agnes AI + WebUI 控制台"""
import time
import asyncio
from collections import deque
from aiocqhttp import Event
from quart import request

import brain
import config
from webui import app
import httpx

# HTTP 模式：NapCat 作服务端(8081)，事件经 HTTP POST 上报到本服务，
# 发消息走 NapCat 的 HTTP API。社区验证的稳定方案，绕开反向 WS 的各类问题。
_api_root = "http://127.0.0.1:8081"
_http = httpx.AsyncClient(timeout=60)


async def call_action(action: str, **params):
    headers = {}
    token = config.load()["access_token"]
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = await _http.post(f"{_api_root}/{action}", json=params, headers=headers)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "failed":
        raise RuntimeError(f"OneBot API {action} 失败: {data.get('message') or data.get('wording')}")
    return data.get("data")


class _BotShim:
    """提供 bot.send(ev, text) / send_private_msg / self_id 兼容接口"""
    self_id = ""

    async def send(self, ev, message):
        if ev.message_type == "group":
            return await call_action("send_group_msg", group_id=ev.group_id, message=message)
        return await call_action("send_private_msg", user_id=ev.user_id, message=message)

    def __getattr__(self, name):
        async def _call(**kwargs):
            return await call_action(name, **kwargs)
        return _call


bot = _BotShim()
app.extensions["onebot_bot"] = bot


@app.post("/onebot/event")
async def onebot_event():
    data = await request.get_json()
    pt = data.get("post_type")
    if pt == "message":
        bot.self_id = str(data.get("self_id") or bot.self_id)
        asyncio.create_task(handle_message(Event(data)))
    elif pt == "notice":
        asyncio.create_task(handle_notice(data))
    return {"status": "ok"}


async def handle_notice(data: dict):
    """群通知事件：欢迎新人"""
    cfg = config.load()
    if data.get("notice_type") == "group_increase" and cfg["welcome_new_member"]:
        try:
            await call_action("send_group_msg", group_id=data["group_id"],
                              message=cfg["welcome_text"])
        except Exception as e:
            print(f"[error] 欢迎语发送失败: {e}")


def strip_cq(text: str) -> str:
    """去掉 CQ 码，得到纯文本"""
    out, i = [], 0
    while i < len(text):
        if text.startswith("[CQ:", i):
            end = text.find("]", i)
            if end == -1:
                break
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out).strip()


_histories: dict[str, tuple[float, deque]] = {}
_rate: dict[str, list[float]] = {}  # user_id -> [timestamps]


def _parse_ids(s: str) -> set[str]:
    return {x.strip() for x in (s or "").replace("，", ",").split(",") if x.strip()}


def check_rate(user_id: str) -> bool:
    """每人每分钟限速，超限返回 False"""
    limit = int(config.load()["rate_limit_per_min"])
    if limit <= 0:
        return True
    now = time.time()
    ts = [t for t in _rate.get(user_id, []) if now - t < 60]
    if len(ts) >= limit:
        _rate[user_id] = ts
        return False
    ts.append(now)
    _rate[user_id] = ts
    return True


def keyword_reply(text: str) -> str | None:
    """关键词自动回复，配置格式：每行一条 '关键词=>回复'"""
    rules = config.load()["keyword_rules"] or ""
    for line in rules.splitlines():
        line = line.strip()
        if "=>" in line:
            kw, rep = line.split("=>", 1)
            if kw.strip() and kw.strip() in text:
                return rep.strip()
    return None


async def handle_admin(ev: Event, text: str) -> bool:
    """管理员指令，返回 True 表示已处理"""
    cfg = config.load()
    if str(ev.user_id) not in _parse_ids(cfg["admin_qq"]):
        return False
    if text in ("状态", "/status"):
        await call_action(
            "send_msg" if ev.message_type != "group" else "send_group_msg",
            **({"group_id": ev.group_id} if ev.message_type == "group" else {"user_id": ev.user_id}),
            message=f"在线 ✅ 登录QQ {bot.self_id or '?'} | 会话数 {len(_histories)} | 限速 {cfg['rate_limit_per_min']}/分钟",
        )
        return True
    if text.startswith("刷新配置"):
        config.reset_to_env() if text == "刷新配置重置" else None
        cfg2 = config.load()
        await call_action(
            "send_msg" if ev.message_type != "group" else "send_group_msg",
            **({"group_id": ev.group_id} if ev.message_type == "group" else {"user_id": ev.user_id}),
            message=f"已重新加载配置：主模型 {cfg2['agnes_model']}",
        )
        return True
    if text == "清空记忆":
        _histories.clear()
        await call_action(
            "send_msg" if ev.message_type != "group" else "send_group_msg",
            **({"group_id": ev.group_id} if ev.message_type == "group" else {"user_id": ev.user_id}),
            message="已清空全部会话记忆",
        )
        return True
    return False


def get_history(key: str) -> deque:
    cfg = config.load()
    now = time.time()
    item = _histories.get(key)
    if not item or now - item[0] > cfg["history_ttl"]:
        item = (now, deque(maxlen=int(cfg["history_len"])))
        _histories[key] = item
    item = (now, item[1])
    _histories[key] = item
    return item[1]


async def handle_message(ev: Event):
    """私聊全部回复；群聊仅被 @ 时回复（可在 WebUI 关闭）"""
    cfg = config.load()
    raw = ev.get("message")
    if isinstance(raw, list):
        at_me = any(
            isinstance(s, dict) and s.get("type") == "at"
            and str(s.get("data", {}).get("qq")) == str(ev.self_id)
            for s in raw
        )
        text = strip_cq("".join(
            s.get("data", {}).get("text", "") if isinstance(s, dict) else str(s)
            for s in raw
        ))
    else:
        msg_str = str(raw)
        at_me = f"[CQ:at,qq={ev.self_id}]" in msg_str
        text = strip_cq(msg_str)

    if not text:
        return

    if ev.message_type == "group":
        if not cfg["reply_group_at"] or not at_me:
            return
    elif not cfg["reply_private"]:
        return

    # 白名单（空 = 不限制）
    wl = _parse_ids(cfg["whitelist"])
    if wl and str(ev.user_id) not in wl:
        return

    # 管理员指令优先
    if await handle_admin(ev, text):
        return

    # 关键词自动回复（不占 AI 调用）
    kw = keyword_reply(text)
    if kw:
        try:
            await bot.send(ev, kw)
        except Exception as e:
            print(f"[error] 关键词回复发送失败: {e}")
        return

    # 速率限制
    if not check_rate(str(ev.user_id)):
        try:
            await bot.send(ev, "消息有点太快啦，稍等一下再聊～")
        except Exception:
            pass
        return

    chat_id = ev.group_id if ev.message_type == "group" else ev.user_id
    key = f"{ev.message_type}_{chat_id}"
    history = get_history(key)

    try:
        reply = await brain.reply(text, list(history), cfg["system_prompt"])
    except Exception as e:
        print(f"[error] LLM 调用失败: {e}")
        return

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    try:
        await bot.send(ev, reply)
    except Exception as e:
        print(f"[error] 发送失败: {e}")
        return
    print(f"[msg] {key} <- {text!r} -> {reply!r}")


if __name__ == "__main__":
    cfg = config.load()
    host, port = cfg["ws_host"], int(cfg["ws_port"])
    print(f"QQ 机器人启动：WebUI  http://{host}:{port}/")
    print(f"NapCat 反向 WS 请指向 ws://{host}:{port}/onebot/event")
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    hconfig = Config()
    hconfig.bind = [f"{host}:{port}"]
    asyncio.run(serve(app, hconfig))
