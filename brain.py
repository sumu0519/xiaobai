"""Agnes 多模型大脑：3.0 Flash 主对话 + Tavily 搜索 + 图像/视频生成路由"""
import re
import asyncio
import httpx
import config

client = httpx.AsyncClient(timeout=60)
# 视频生成是异步任务，轮询专用客户端（超时要长）
video_client = httpx.AsyncClient(timeout=30)


def _auth(cfg) -> dict:
    return {"Authorization": f"Bearer {cfg['agnes_api_key']}"}


async def tavily_search(query: str, max_results: int = 5) -> str:
    """调用 Tavily 搜索，返回整理好的文本摘要"""
    resp = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": config.load()["tavily_api_key"],
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    parts = []
    if data.get("answer"):
        parts.append(f"直接答案：{data['answer']}")
    for r in data.get("results", []):
        parts.append(f"- {r.get('title', '')}：{r.get('content', '')[:200]}")
    return "\n".join(parts) if parts else "没有搜索到相关结果。"


def needs_search(text: str) -> bool:
    cfg = config.load()
    if not cfg["search_enabled"] or not cfg["tavily_api_key"]:
        return False
    return bool(re.search(cfg["search_hints"], text))


# ---------- 图像生成 ----------

IMG_TRIGGERS = re.compile(
    r"画(一|一張|一张|幅|个|张)?|画图|绘图|生成(一)?张|来(一)?张|画：|画:|image:", re.I
)


def wants_image(text: str) -> bool:
    cfg = config.load()
    if not cfg.get("image_enabled") or not cfg.get("image_model"):
        return False
    return bool(IMG_TRIGGERS.search(text))


async def generate_image(prompt: str) -> str:
    """调用 Agnes 图像模型文生图，返回图片 URL"""
    cfg = config.load()
    resp = await client.post(
        f"{cfg['agnes_base_url']}/images/generations",
        headers=_auth(cfg),
        json={
            "model": cfg["image_model"],
            "prompt": prompt[:4000],
            "size": "1024x1024",
            "response_format": "url",
        },
    )
    resp.raise_for_status()
    data = resp.json()["data"][0]
    url = data.get("url") or (data.get("b64_json") and f"base64://{data['b64_json']}")
    if not url:
        raise RuntimeError(f"图像模型未返回图片: {str(data)[:200]}")
    return url


# ---------- 视频生成（异步任务 + 轮询） ----------

VID_TRIGGERS = re.compile(r"生成视频|做个视频|来个视频|视频：|视频:|一段视频|video:", re.I)


def wants_video(text: str) -> bool:
    cfg = config.load()
    if not cfg.get("video_enabled") or not cfg.get("video_model"):
        return False
    return bool(VID_TRIGGERS.search(text))


async def generate_video(prompt: str, timeout_sec: int = 300) -> str:
    """调用 Agnes 视频模型文生视频，轮询直到完成，返回视频 URL"""
    cfg = config.load()
    model = cfg["video_model"]
    payload = {"model": model, "prompt": prompt[:3000]}
    # 2.5 系列为 OpenAI Videos 兼容接口：mode 必填、size 固定 720P
    if "2.5" in model:
        payload.update({"mode": "text", "size": "720P", "seconds": "5"})
    resp = await video_client.post(
        f"{cfg['agnes_base_url']}/videos",
        headers=_auth(cfg),
        json=payload,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"创建任务 HTTP {resp.status_code}: {resp.text[:200]}")
    task = resp.json()
    task_id = task.get("video_id") or task.get("task_id") or task.get("id")
    if not task_id:
        raise RuntimeError(f"视频任务创建失败: {str(task)[:200]}")

    # 2.5 系列推荐用 agnesapi?video_id=&model_name= 查询；v2.0 用 /videos/<id>
    if "2.5" in model:
        poll_url = (f"{cfg['agnes_base_url'].rsplit('/v1', 1)[0]}"
                    f"/agnesapi?video_id={task_id}&model_name={model}")
    else:
        poll_url = f"{cfg['agnes_base_url']}/videos/{task_id}"

    elapsed = 0
    while elapsed < timeout_sec:
        await asyncio.sleep(10)
        elapsed += 10
        r = await video_client.get(poll_url, headers=_auth(cfg))
        if r.status_code != 200:
            continue
        info = r.json()
        status = (info.get("status") or "").lower()
        if status in ("success", "completed"):
            url = info.get("video_url") or info.get("url")
            if not url:
                raise RuntimeError(f"视频完成但未返回地址: {str(info)[:200]}")
            return url
        if status == "failed":
            raise RuntimeError(f"视频生成失败: {info.get('error') or status}")
    raise RuntimeError("视频生成超时（超过5分钟）")


# ---------- 主对话 ----------

async def chat(messages: list, system_prompt: str = "") -> str:
    """调用 Agnes 3.0 Flash 生成回复（messages 支持 image_url 内容块）"""
    cfg = config.load()
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.extend(messages)

    resp = await client.post(
        f"{cfg['agnes_base_url']}/chat/completions",
        headers=_auth(cfg),
        json={
            "model": cfg["agnes_model"],
            "messages": msgs,
            "temperature": 0.8,
            "max_tokens": 1024,
        },
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    return content[: int(cfg["max_reply_chars"])]


async def reply(text: str, history: list, system_prompt: str) -> str:
    """完整流程：图像/视频请求 → 专门模型；其余 → 联网搜索 + 主模型"""
    cfg = config.load()
    messages = history + [{"role": "user", "content": text}]

    # 去掉触发词后作为生成提示词
    def strip_trigger(s: str) -> str:
        return IMG_TRIGGERS.sub("", s, count=1).strip() or s

    if wants_image(text):
        prompt = strip_trigger(text)
        try:
            url = await generate_image(prompt)
            return f"给你画好啦~\n[CQ:image,file={url}]"
        except Exception as e:
            return f"画画失败了……（{str(e)[:80]}）"

    if wants_video(text):
        prompt = VID_TRIGGERS.sub("", text, count=1).strip() or text
        try:
            url = await generate_video(prompt)
            return f"视频生成好啦（可能需要一点时间加载）\n[CQ:video,file={url}]"
        except Exception as e:
            return f"视频生成失败了……（{str(e)[:80]}）"

    system = system_prompt
    if needs_search(text):
        try:
            search_result = await tavily_search(text, int(cfg["search_max_results"]))
            system += (
                "\n以下是你在网络上搜索到的实时资料，回答时参考它（不要提及搜索一词）：\n"
                + search_result
            )
        except Exception as e:
            system += f"\n（联网搜索失败：{e}，请基于已有知识回答并说明信息可能不是最新的）"

    return await chat(messages, system)


async def describe_image(image_url: str, question: str, system_prompt: str) -> str:
    """图片理解：把图片 URL 交给 3.0 多模态输入看图回答"""
    cfg = config.load()
    content = [
        {"type": "image_url", "image_url": {"url": image_url}},
        {"type": "text", "text": question or "请描述这张图片。"},
    ]
    return await chat(
        [{"role": "user", "content": content}],
        system_prompt + "\n（用户发来了一张图片，请根据图片内容自然地回复）",
    )


async def summarize_url(url: str) -> str:
    """链接摘要：抓取网页正文并让模型总结"""
    cfg = config.load()
    try:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        return f"网页打不开……（{str(e)[:80]}）"
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return "这是一个文件链接，不是网页，没法总结哦。"
    import re as _re
    text = _re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", r.text)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()[:6000]
    if len(text) < 50:
        return "这个网页没有抓到什么正文内容。"
    try:
        return await chat(
            [{"role": "user", "content": f"请用简短的几句话总结这篇网页文章的核心内容：\n\n{text}"}],
            "你是一个摘要助手，输出简洁的中文总结，不超过150字。",
        )
    except Exception as e:
        return f"总结失败……（{str(e)[:80]}）"


async def test_agnes() -> tuple[bool, str]:
    """AI 连接测试"""
    try:
        out = await chat([{"role": "user", "content": "回复“连接成功”四个字"}])
        return True, out
    except Exception as e:
        return False, str(e)


async def test_tavily() -> tuple[bool, str]:
    """Tavily 连接测试"""
    try:
        out = await tavily_search("今天日期", max_results=1)
        return True, out[:100]
    except Exception as e:
        return False, str(e)


async def test_image() -> tuple[bool, str]:
    """图像模型连接测试（真实生成一张小图）"""
    try:
        url = await generate_image("一个简单的红色圆形，白色背景")
        return True, url[:80]
    except Exception as e:
        return False, str(e)


async def test_video() -> tuple[bool, str]:
    """视频模型连接测试（只验证任务能创建，不等待生成完成）"""
    try:
        cfg = config.load()
        model = cfg["video_model"]
        payload = {"model": model, "prompt": "a red ball rolling, test"}
        if "2.5" in model:
            payload.update({"mode": "text", "size": "720P", "seconds": "5"})
        resp = await video_client.post(
            f"{cfg['agnes_base_url']}/videos",
            headers=_auth(cfg),
            json=payload,
        )
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        task = resp.json()
        if task.get("task_id") or task.get("video_id") or task.get("id"):
            return True, "视频任务创建成功（未等待完成）"
        return False, f"未返回任务ID: {str(task)[:120]}"
    except Exception as e:
        return False, str(e)
