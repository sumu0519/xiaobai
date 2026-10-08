"""配置管理：config.json 持久化，优先于 .env"""
import json
import os
import shutil
import threading

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    # AI
    "agnes_api_key": "",
    "agnes_base_url": "https://apihub.agnes-ai.com/v1",
    "agnes_model": "agnes-3.0-flash",
    "temperature": 0.8,
    "max_tokens": 1024,
    "max_reply_chars": 500,
    "system_prompt": "你是一个真实的人类QQ用户，说话口语化、自然、简短，不用markdown格式，不要说自己是AI或模型。回答尽量控制在100字以内。",
    # 图像生成模型（agnes-image-2.1-flash）
    "image_enabled": True,
    "image_model": "agnes-image-2.1-flash",
    # 画图追问：生图后 TTL 秒内的后续消息视为调整要求，合并重新生图（0=关闭）
    "image_followup_ttl": 300,
    # 视频生成模型（agnes-video-v2.0，异步任务）
    "video_enabled": True,
    "video_model": "agnes-video-v2.0",
    # Tavily
    "tavily_api_key": "",
    "search_enabled": True,
    "search_max_results": 5,
    "search_hints": "现在|今天|最新|新闻|天气|热搜|价格|多少|几号|什么时候|近况|比分|开奖|汇率|搜(一)?下|查(一)?下|搜索|实时",
    # OneBot
    "ws_host": "127.0.0.1",
    "ws_port": 8080,
    "access_token": "",
    # 行为
    "reply_private": True,
    "reply_group_at": True,
    "history_len": 10,
    "history_ttl": 3600,
    # 管理员 QQ 号（逗号分隔），可用指令；默认 2811804771 为最高权限负责人
    "admin_qq": "2811804771",
    # 速率限制：每人每分钟最多回复条数，0=不限制
    "rate_limit_per_min": 10,
    # QQ 白名单（逗号分隔，空=不限制），非白名单成员消息忽略
    "whitelist": "",
    # 关键词自动回复："关键词=>回复内容"，多条用换行分隔
    "keyword_rules": "",
    # 群聊欢迎新人（进群事件）
    "welcome_new_member": False,
    "welcome_text": "欢迎新人进群～有问题可以 @ 我哦",
    # 链接摘要：消息含网页链接时自动抓取并总结
    "url_summary": True,
    # 定时推送："HH:MM=>私聊:QQ号|群:群号=>内容"，多条换行分隔；空=禁用
    "scheduled_push": "",
    # 消息日志（SQLite messages.db）
    "message_log_enabled": True,
    # 群聊技能路由（@小白 + 指令类玩法），总开关
    "skills_enabled": True,
    # 吐槽（帮骂）技能触发词正则：含指使句式（帮我骂…）与对骂句式（对骂/互怼…）
    "roast_words": r"帮我(骂|怼|喷|损|整|教育|吐槽|输出|收拾|拳)|给我(骂|怼|喷|损|整|教育|输出|收拾|拳)|(骂|怼|喷|损|吐槽)(一?下|他)|对骂|互怼|互喷|对喷|对线|battle",
    # 吐槽技能风格指令
    "roast_prompt": "（现在是损友互怼玩梗模式：用一句网络梗式的阴阳怪气调侃对方，口语化、简短好笑，像好朋友之间开玩笑。如果指令是「对骂/互怼」类，你就是对骂的一方，要主动出击怼对方，不能回避或劝架。绝对不能出现真正的辱骂、脏话、人身攻击、歧视或威胁内容，只做无伤大雅的调侃。）",
}

_lock = threading.Lock()
_cache: dict | None = None


def load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            cfg = dict(DEFAULTS)
            # .env 兜底（首次没有 config.json 时）
            env_map = {
                "agnes_api_key": "AGNES_API_KEY",
                "agnes_base_url": "AGNES_BASE_URL",
                "agnes_model": "AGNES_MODEL",
                "tavily_api_key": "TAVILY_API_KEY",
                "ws_host": "ONEBOT_WS_HOST",
                "ws_port": "ONEBOT_WS_PORT",
                "access_token": "ACCESS_TOKEN",
                "system_prompt": "SYSTEM_PROMPT",
                "max_reply_chars": "MAX_REPLY_CHARS",
            }
            for k, env in env_map.items():
                v = os.getenv(env)
                if v:
                    cfg[k] = v
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
                except Exception as e:
                    print(f"[config] 读取 config.json 失败: {e}")
            _cache = cfg
        return dict(_cache)


def save(update: dict) -> dict:
    global _cache
    with _lock:
        cfg = dict(_cache or DEFAULTS)
        for k, v in update.items():
            if k in DEFAULTS:
                cfg[k] = v
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _cache = cfg
        return dict(_cache)


def reset_to_env():
    """删除 config.json，回到 .env/默认值"""
    global _cache
    with _lock:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        _cache = None
        return load()
