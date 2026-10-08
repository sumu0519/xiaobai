"""QQ 机器人主程序：OneBot 11 + Agnes AI + WebUI 控制台"""
import re
import time
import asyncio
from collections import deque
from aiocqhttp import Event
from quart import request

import brain
import config
import scheduler
import msglog
import memory
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
_last_image: dict[str, tuple[float, str]] = {}  # chat_key -> (时间戳, 上次生图prompt)
_last_seen_image: dict[str, tuple[float, str]] = {}  # chat_key -> (时间戳, 用户最近发图的URL)


async def _cleanup_loop():
    """每小时清扫过期的会话历史和限速时间戳，防止长期运行内存膨胀"""
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        ttl = int(config.load()["history_ttl"])
        for key in [k for k, (t, _) in _histories.items() if now - t > ttl]:
            _histories.pop(key, None)
        for uid in [u for u, ts in _rate.items() if not ts or now - ts[-1] > 60]:
            _rate.pop(uid, None)
        for k in [k for k, (t, _) in _last_image.items() if now - t > 3600]:
            _last_image.pop(k, None)
        for k in [k for k, (t, _) in _last_seen_image.items() if now - t > 3600]:
            _last_seen_image.pop(k, None)


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


async def _member_names(group_id, qids: list[str]) -> list[str]:
    """尽力获取群成员昵称，用于 prompt 语境"""
    names = []
    for q in qids:
        try:
            info = await call_action("get_group_member_info",
                                     group_id=int(group_id), user_id=int(q), no_cache=True)
            names.append(f"{info.get('card') or info.get('nickname') or '成员'}({q})")
        except Exception:
            names.append(f"QQ{q}")
    return names


async def _send_logged(ev: Event, reply, reply_to=None, at_list: list[str] | None = None):
    """发送回复并写消息日志（out）
    reply_to=原消息ID 时以引用段开头；at_list 里的 QQ 会紧跟 @（用于消息里提到的第三人）"""
    try:
        segs = []
        if reply_to:
            segs.append({"type": "reply", "data": {"id": str(reply_to)}})
        for q in (at_list or []):
            segs.append({"type": "at", "data": {"qq": str(q)}})
        if segs:
            segs.append({"type": "text", "data": {"text": str(reply)}})
            message = segs
        else:
            message = reply
        await bot.send(ev, message)
        msglog.log_message(ev.message_type,
                           ev.group_id if ev.message_type == "group" else ev.user_id,
                           ev.user_id, "out", reply)
    except Exception as e:
        print(f"[error] 发送失败: {e}")


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
    if text.startswith("刷新配置") or text == "重置配置":
        if text == "重置配置":
            config.reset_to_env()
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
    if text.startswith("忘了我") or text.startswith("清空我的记忆"):
        n = memory.clear(str(ev.user_id))
        await call_action(
            "send_msg" if ev.message_type != "group" else "send_group_msg",
            **({"group_id": ev.group_id} if ev.message_type == "group" else {"user_id": ev.user_id}),
            message=f"已删除关于你的 {n} 条记忆",
        )
        return True
    return False


# ---------- 群聊技能路由（SPEC-roast.md）----------
# 每个技能: {name, handler}；触发条件在 route_skill 内按技能名匹配配置正则
# handler(text, group_id, user_id, targets, cfg) -> 回复文本；异常由 route_skill 统一兜底


async def _roast_handler(text: str, group_id, user_id, targets: list[str], cfg: dict) -> str:
    """玩梗吐槽：把被 @ 者解析成群昵称，让模型生成针对这个人的调侃。
    「帮我骂」类=受指使怼人；「对骂/互怼」类=小白自己是对骂一方，主动出击。"""
    names = await _member_names(group_id, targets)
    who = "、".join(names) if names else "、".join(targets)
    if re.search(r"对骂|互怼|互喷|对喷|对线|battle", text):
        stance = (f"（有人起哄让你和 {who} 对骂/互怼，你是对骂的一方，"
                  f"直接主动开怼 {who}，一句犀利好笑的玩梗调侃，不要回避、不要劝架）")
    else:
        stance = (f"（你在群里被 @，指使你调侃/怼的人是 QQ{user_id}，"
                  f"让你调侃的对象是：{who}。用户原话：{text}）")
    prompt = f"{stance}\n用户原话：{text}"
    return await brain.reply(prompt, [], cfg["system_prompt"] + cfg["roast_prompt"])


SKILLS: list[dict] = [
    {"name": "roast", "handler": _roast_handler},
]


def route_skill(text: str, group_id, user_id, targets: list[str], cfg: dict):
    """技能路由：命中返回执行协程（调用后得到回复文本），未命中返回 None。
    技能 handler 异常时记日志并返回 None，落回普通对话（不崩、不发空消息）。"""
    if not cfg.get("skills_enabled", True) or not targets:
        return None
    matched = None
    for skill in SKILLS:
        if skill["name"] == "roast":
            try:
                pat = re.compile(cfg.get("roast_words", ""))
            except re.error:
                print("[error] roast_words 正则无效，技能停用")
                pat = None
            if pat and pat.search(text):
                matched = skill
            break
    if not matched:
        return None

    async def _run():
        try:
            return await matched["handler"](text, group_id, user_id, targets, cfg)
        except Exception as e:
            print(f"[error] 技能 {matched['name']} 执行失败: {e}")
            return None
    return _run


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
    image_urls: list[str] = []
    at_others: list[str] = []  # 消息里 @ 的其他人（非小号自己）
    if isinstance(raw, list):
        at_me = any(
            isinstance(s, dict) and s.get("type") == "at"
            and str(s.get("data", {}).get("qq")) == str(ev.self_id)
            for s in raw
        )
        parts = []
        for s in raw:
            if not isinstance(s, dict):
                parts.append(str(s))
                continue
            if s.get("type") == "text":
                parts.append(s.get("data", {}).get("text", ""))
            elif s.get("type") == "image":
                url = s.get("data", {}).get("url") or s.get("data", {}).get("file", "")
                if url.startswith("http"):
                    image_urls.append(url)
            elif s.get("type") == "at":
                q = str(s.get("data", {}).get("qq", ""))
                if q and q != str(ev.self_id) and q != "all":
                    at_others.append(q)
        text = strip_cq("".join(parts))
    else:
        msg_str = str(raw)
        at_me = f"[CQ:at,qq={ev.self_id}]" in msg_str
        text = strip_cq(msg_str)

    if not text:
        return

    msglog.log_message(ev.message_type,
                       ev.group_id if ev.message_type == "group" else ev.user_id,
                       ev.user_id, "in", text)

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

    # 链接摘要：消息含网页链接时自动总结
    m = re.search(r"https?://[^\s\]\[]+", text)
    if m and cfg.get("url_summary", True):
        summary = await brain.summarize_url(m.group(0))
        try:
            await bot.send(ev, summary)
        except Exception as e:
            print(f"[error] 摘要发送失败: {e}")
        return

    # 速率限制
    if not check_rate(str(ev.user_id)):
        try:
            await bot.send(ev, "消息有点太快啦，稍等一下再聊～")
        except Exception:
            pass
        return

    # 群聊技能路由：@ 小白 + 指使句式（如「帮我骂 @某人」），未命中走普通对话
    if ev.message_type == "group" and at_others:
        run = route_skill(text, ev.group_id, str(ev.user_id), at_others, cfg)
        if run is not None:
            reply = await run()
            if reply:
                await _send_logged(ev, reply, reply_to=ev.get("message_id"), at_list=at_others)
                print(f"[skill] group_{ev.group_id} <- {text!r}")
                return
            # 技能失败/无输出 → 落回普通对话

    # 图片理解：消息带图片时让模型看图回复
    if image_urls:
        try:
            reply = await brain.describe_image(
                image_urls[0], text or "", cfg["system_prompt"]
            )
        except Exception as e:
            print(f"[error] 图片理解失败: {e}")
            reply = "图片我好像看不懂……（加载失败了）"
            return
        chat_id = ev.group_id if ev.message_type == "group" else ev.user_id
        seen_key = f"{ev.message_type}_{chat_id}"
        _last_seen_image[seen_key] = (time.time(), image_urls[0])
        await _send_logged(ev, reply)
        print(f"[img] {seen_key} -> 看图回复")
        return

    chat_id = ev.group_id if ev.message_type == "group" else ev.user_id
    key = f"{ev.message_type}_{chat_id}"

    # 画图触发：显式生图并记录 prompt（供后续追问调整）
    if brain.wants_image(text):
        img_prompt = brain.IMG_TRIGGERS.sub("", text, count=1).strip() or text
        try:
            url = await brain.generate_image(img_prompt)
        except Exception as e:
            print(f"[error] 生图失败: {e}")
            await _send_logged(ev, f"画画失败了……（{str(e)[:80]}）")
            return
        _last_image[key] = (time.time(), img_prompt)
        await _send_logged(ev, f"给你画好啦~\n[CQ:image,file={url}]")
        print(f"[img] {key} -> 生图 {img_prompt!r}")
        return

    # 画图追问：TTL 内对上次生图的调整要求，合并 prompt 重新生图
    # 提问守卫：疑问句（这是谁/是什么…）不重绘，落入普通对话让模型结合上下文回答
    QUESTION_RE = re.compile(r"[?？]|吗|呢|什么|谁|怎么|哪|为啥|为什么")
    ttl = int(cfg.get("image_followup_ttl", 300))
    last = _last_image.get(key)
    if (ttl > 0 and last and time.time() - last[0] <= ttl
            and not image_urls and not QUESTION_RE.search(text)):
        new_prompt = f"{last[1]}；调整要求：{text}"
        try:
            url = await brain.generate_image(new_prompt)
        except Exception as e:
            print(f"[error] 追问生图失败: {e}")
            await _send_logged(ev, f"改图失败了……（{str(e)[:80]}）")
            return
        _last_image[key] = (time.time(), new_prompt)
        await _send_logged(ev, f"重新画好啦~\n[CQ:image,file={url}]")
        print(f"[img] {key} -> 追问生图 {new_prompt!r}")
        return

    history = get_history(key)

    # 群聊里 @ 了别人：获取昵称并注入语境，让 AI 知道在跟谁说话
    prompt_text = text
    if ev.message_type == "group" and at_others:
        names = await _member_names(ev.group_id, at_others)
        if names:
            prompt_text = f"（你在群里被 @，这条消息同时 @ 了：{', '.join(names)}）\n{text}"

    try:
        seen = _last_seen_image.get(key)
        if (not image_urls and seen
                and time.time() - seen[0] <= int(cfg.get("image_followup_ttl", 300))):
            # 看图追问：TTL 内用户发过图，把那张图附进本轮继续对话
            reply = await brain.chat_with_image(
                seen[1], prompt_text, list(history),
                cfg["system_prompt"] + memory.inject(str(ev.user_id)),
            )
        else:
            reply = await brain.reply(prompt_text, list(history),
                                      cfg["system_prompt"] + memory.inject(str(ev.user_id)))
    except Exception as e:
        print(f"[error] LLM 调用失败: {e}")
        await _send_logged(ev, "……（我刚才卡了一下，再发一遍？）")
        return

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    # 异步抽取记忆要点（不阻塞回复）
    asyncio.create_task(_remember(str(ev.user_id), text, reply))

    # 群聊以"引用原消息 + @ 消息里提到的第三人"形式发送
    await _send_logged(ev, reply,
                       reply_to=ev.get("message_id") if ev.message_type == "group" else None,
                       at_list=at_others if ev.message_type == "group" else None)
    print(f"[msg] {key} <- {text!r} -> {reply!r}")


async def _remember(user_id: str, user_text: str, bot_reply: str):
    """对话后异步抽取值得长期记住的用户信息，交给 LLM 判断是否入库"""
    try:
        out = await brain.chat(
            [{"role": "user", "content":
              f"用户消息：{user_text[:500]}\n机器人回复：{bot_reply[:300]}\n\n"
              "从这段对话中提取值得长期记住的用户信息（称呼、喜好、身份、明确要求等）。"
              "只输出一条最值得记的简短事实，一行以内；没有就只输出：无"}],
            "你是信息抽取器，只输出提取结果本身。",
        )
        out = out.strip()
        if out and out != "无":
            memory.add(user_id, out)
    except Exception as e:
        print(f"[error] 记忆抽取失败: {e}")


async def _main():
    asyncio.create_task(scheduler.run_scheduler(call_action))
    asyncio.create_task(_cleanup_loop())
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    hconfig = Config()
    hconfig.bind = [f"{cfg['ws_host']}:{int(cfg['ws_port'])}"]
    await serve(app, hconfig)


if __name__ == "__main__":
    cfg = config.load()
    print(f"QQ 机器人启动：WebUI  http://{cfg['ws_host']}:{cfg['ws_port']}/")
    print(f"NapCat 反向 WS 请指向 ws://{cfg['ws_host']}:{cfg['ws_port']}/onebot/event")
    asyncio.run(_main())
