# QQ 小号 AI 机器人（NapCat + Agnes 3.0 Flash + Tavily）

让 QQ 小号"本人"直接收发消息并使用 Agnes 3.0 Flash 智能回复，需要时自动用 Tavily 联网搜索。

## 架构

```
QQ服务器 ⇄ NapCat(小号登录) ⇄ OneBot 11 反向WS ⇄ bot.py (Quart)
                                                  ├─ brain.py: Agnes 3.0 Flash
                                                  └─ Tavily 联网搜索（需要时）
```

## 部署步骤

### 1. 安装 NapCat 并登录小号

- 下载：https://napneko.github.io/guide/boot-shell （Windows 用 NapCat.Shell，无需装 QQ）
- 启动后用小号扫码登录。
- 在 NapCat 的 WebUI（默认 http://localhost:6099）→ 网络配置 → 新建 **反向 WebSocket**：
  - URL：`ws://127.0.0.1:8080/onebot/event`
  - 若配置了 Access Token，与 `.env` 中 `ACCESS_TOKEN` 保持一致。

### 2. 配置本项目

```bash
pip install -r requirements.txt
copy .env.example .env   # 然后编辑 .env 填入以下 Key
```

| 变量 | 说明 |
|---|---|
| `AGNES_API_KEY` | Agnes AI 的 API Key（apihub.agnes-ai.com） |
| `TAVILY_API_KEY` | https://tavily.com 免费注册，每月 1000 次免费 |
| `SYSTEM_PROMPT` | 机器人人设 |

### 3. 启动

```bash
python bot.py
```

看到 `等待 NapCat 反向连接` 后，NapCat 会自动连上。用另一个号给小号发消息测试。

## 行为规则

- **私聊**：所有消息都回复
- **群聊**：只有被 @ 小号时才回复（不会刷屏）
- 消息包含"现在/今天/最新/天气/新闻/搜一下"等关键词时，先调 Tavily 搜索再回答
- 每个会话保留最近 10 条上下文（1 小时过期）

## 自定义

- 人设：改 `.env` 里的 `SYSTEM_PROMPT`
- 联网触发词：改 `brain.py` 里的 `SEARCH_HINTS` 正则
- 上下文长度：改 `bot.py` 里的 `HISTORY_LEN`

## 注意事项

- 协议端属个人自动化，有轻微封号风险：避免高频群发、频繁加好友，挂常用设备环境。
- 若 8080 端口被占用，改 `.env` 的 `ONEBOT_WS_PORT` 并同步修改 NapCat 的反向 WS 地址。
