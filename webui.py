"""WebUI：配置管理后台（Quart 蓝图）"""
import asyncio
import quart
from aiocqhttp import CQHttp

import brain
import config

app = quart.Quart(__name__, template_folder="templates", static_folder="static")


def get_bot() -> CQHttp:
    return quart.current_app.extensions["onebot_bot"]


# ---------- API ----------

@app.get("/api/config")
async def api_get_config():
    cfg = config.load()
    # 打码密钥，前端仅显示尾 4 位
    def mask(v: str) -> str:
        return ("*" * 8 + v[-4:]) if len(v) > 4 else ("*" * len(v) if v else "")
    out = dict(cfg)
    out["agnes_api_key_masked"] = mask(cfg["agnes_api_key"])
    out["tavily_api_key_masked"] = mask(cfg["tavily_api_key"])
    out.pop("agnes_api_key")
    out.pop("tavily_api_key")
    return {"ok": True, "config": out}


@app.post("/api/config")
async def api_save_config():
    data = await quart.request.get_json()
    # 空密码字段 = 不修改（前端在密钥未改动时传空）
    for k in ("agnes_api_key", "tavily_api_key", "access_token"):
        if data.get(k) == "":
            data.pop(k)
    cfg = config.save(data)
    return {"ok": True, "config": cfg}


@app.post("/api/config/reset")
async def api_reset_config():
    cfg = config.reset_to_env()
    return {"ok": True, "config": cfg}


@app.get("/api/status")
async def api_status():
    bot = get_bot()
    qq = bot.self_id if isinstance(getattr(bot, "self_id", ""), str) else ""
    return {"ok": True, "bot_connected": bool(qq), "qq": qq}


@app.get("/api/models")
async def api_models():
    """从 Agnes 云端拉取可用模型名单（OpenAI 兼容 /v1/models）"""
    import httpx
    cfg = config.load()
    if not cfg["agnes_api_key"]:
        return {"ok": False, "message": "请先配置 Agnes API Key", "models": []}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{cfg['agnes_base_url'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {cfg['agnes_api_key']}"},
            )
            r.raise_for_status()
            data = r.json()
        raw = data.get("data") or data.get("models") or []
        models = []
        for m in raw:
            mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
            if mid:
                models.append(mid)
        return {"ok": True, "models": sorted(models)}
    except Exception as e:
        return {"ok": False, "message": str(e), "models": []}


@app.post("/api/test/agnes")
async def api_test_agnes():
    ok, msg = await brain.test_agnes()
    return {"ok": ok, "message": msg}


@app.post("/api/test/tavily")
async def api_test_tavily():
    ok, msg = await brain.test_tavily()
    return {"ok": ok, "message": msg}


@app.post("/api/test/image")
async def api_test_image():
    ok, msg = await brain.test_image()
    return {"ok": ok, "message": msg}


@app.post("/api/test/video")
async def api_test_video():
    ok, msg = await brain.test_video()
    return {"ok": ok, "message": msg}


@app.post("/api/test/send")
async def api_test_send():
    """给指定 QQ 发一条测试消息"""
    data = await quart.request.get_json()
    qq = str(data.get("qq", "")).strip()
    if not qq.isdigit():
        return {"ok": False, "message": "请输入有效的 QQ 号"}, 400
    try:
        await get_bot().send_private_msg(user_id=int(qq), message="你好！这是一条来自机器人的测试消息 ✅")
        return {"ok": True, "message": f"已发送给 {qq}"}
    except Exception as e:
        return {"ok": False, "message": f"发送失败：{e}"}


# ---------- 页面 ----------

@app.get("/")
async def page_index():
    return await quart.render_template("index.html")
