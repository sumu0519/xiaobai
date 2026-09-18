# 小白 QQ AI 机器人（xiaobai）

让 QQ 小号变成 AI 机器人：**小号本人**直接收发消息（非官方机器人接口），支持 AI 对话、联网搜索、AI 画图、AI 生成视频，并带暗色主题 WebUI 控制台，所有参数可视化配置。

架构：`QQ服务器 ⇄ NapCat（小号登录）⇄ OneBot 11 (HTTP) ⇄ bot.py ⇄ Agnes 多模型 + Tavily`

## 功能一览

| 功能 | 说明 |
|---|---|
| AI 对话 | Agnes 3.0 Flash，私聊全回复，群里被 @ 才回 |
| 联网搜索 | Tavily，消息含"今天/天气/新闻/搜一下"等词自动触发 |
| AI 画图 | 发"画一张……"触发（agnes-image-2.5-flash） |
| AI 视频 | 发"生成视频：……"触发（agnes-video-2.5-flash，异步任务约几分钟） |
| 云端模型列表 | WebUI 一键拉取 Agnes 全部可用模型，下拉直接切换 |
| 管理员指令 | 发 `状态` 查看运行情况，`清空记忆` 重置上下文 |
| 防滥用 | 每人限速、QQ 白名单、关键词自动回复、新人进群欢迎 |
| WebUI 控制台 | 人设/温度/上下文/模型/限速等全部可视化配置，保存即生效 |

---

## 部署步骤

### 第 1 步：安装 Python 依赖（一次性）

需要 Python 3.10+：

```bash
cd xiaobai
pip install -r requirements.txt
```

### 第 2 步：准备 API Key（两个，都免费）

1. **Agnes AI Key**（AI 对话/画图/视频）：到 Agnes AI 官网注册，在控制台 API Key 管理页创建并复制
2. **Tavily Key**（联网搜索）：https://tavily.com 注册，每月 1000 次免费额度

### 第 3 步：启动机器人服务

```bash
python bot.py
```

看到以下输出即为成功：

```
QQ 机器人启动：WebUI  http://127.0.0.1:8080/
```

### 第 4 步：在 WebUI 填入 Key

浏览器打开 **http://127.0.0.1:8080/**

1. 🧠 AI 模型卡片 → 粘贴 Agnes API Key → 点 **测试连接**（回复"连接成功"即通）
2. 🌐 联网搜索卡片 → 粘贴 Tavily Key → 点 **测试连接**
3. 点 **💾 保存配置**（保存即生效，无需重启）

### 第 5 步：安装 NapCat 并登录小号

1. 下载 **NapCat.Shell**（Windows 免安装 QQ 协议端）：
   https://github.com/NapNeko/NapCatQQ/releases （下载 `NapCat.Shell.zip`）
2. 解压到 `NapCat/NapCat.Shell/` 目录
3. 双击 `NapCat/NapCat.Shell/launcher.bat`（自动请求管理员权限）
4. 弹出二维码后，用**手机 QQ 扫码登录你的小号**（仅第一次需要）

### 第 6 步：配置 NapCat 连接（仅第一次）

登录成功后，NapCat 会输出 WebUI 地址（默认 `http://127.0.0.1:6099/webui?token=xxx`），打开它：

**网络配置 → 新建 → HTTP 服务器**，按如下填写后保存：

| 配置项 | 值 |
|---|---|
| 名称 | bot-http-api（随意） |
| 端口 | 8081 |
| 主机 | 127.0.0.1 |
| 启用 | ✅ 勾选 |

再新建一个 **HTTP 客户端**（事件上报）：

| 配置项 | 值 |
|---|---|
| URL | `http://127.0.0.1:8080/onebot/event` |
| 消息格式 | array |
| 启用 | ✅ 勾选 |

也可以不用 WebUI，直接把本仓库 `doc/onebot11_示例.json` 的内容写入 `NapCat/NapCat.Shell/config/onebot11_<你的QQ号>.json`（把示例里的配置改好账号后重启 NapCat）。

### 第 7 步：测试

用另一个 QQ 号：
- 给小号**发私聊消息** → 应收到 AI 回复
- 在群里 **@小号** 说话 → 群聊回复
- 发 `画一张夕阳下的猫` → 收到图片
- 发 `生成视频：海浪拍打沙滩` → 稍等几分钟收到视频
- 发 `今天天气怎么样` → 触发联网搜索回答

---

## 日常启动（之后每次）

```bat
start_bot.bat
```

双击即可：自动提权 → 启动 bot 服务 → NapCat 自动登录小号（**免扫码**）。关闭两个窗口即停止。

> 快速登录说明：官方 `launcher.bat -q QQ号` 在部分版本有参数不转发 bug（NapCatQQ Issue #1477）。本项目通过 `NAPCAT_QQ` 环境变量 + napcat.mjs 补丁实现免扫码自动登录，详见 `start_bot.bat` 注释。

---

## 管理员指令

在 WebUI「🛡️ 管理与安全 → 管理员 QQ」填入你的大号 QQ 后（默认已含 2811804771），给小号发：

| 指令 | 作用 |
|---|---|
| `状态` | 在线状态、登录 QQ、会话数、限速配置 |
| `清空记忆` | 清空全部会话的对话上下文 |

## 常用配置项（WebUI）

| 位置 | 配置 |
|---|---|
| 🧠 AI 模型 | API 地址/Key/模型（可下拉选云端模型）、温度、人设提示词、回复字数、私聊/群聊开关 |
| 🎨 图像/视频 | 两个生成模型的名称与独立开关 |
| 🌐 联网搜索 | Tavily Key、开关、结果条数、触发关键词正则 |
| 🛡️ 管理与安全 | 管理员 QQ、每人限速、白名单、关键词回复规则、进群欢迎语 |
| 🔗 连接与记忆 | 监听端口、Token、上下文条数与有效期、发送测试消息 |

配置保存在 `config.json`（含密钥，**勿提交到 git**），保存即生效；改监听端口需重启 bot.py。

## 常见问题

**Q：私聊没有回复？**
按顺序检查：① bot.py 是否在跑（WebUI 能打开吗）② NapCat 是否登录并启动了 8081 HTTP 服务器（NapCat 窗口日志找 `HTTP Server Adapter Start`）③ NapCat 的 HTTP 客户端上报 URL 是否为 `http://127.0.0.1:8080/onebot/event` ④ 群聊是否忘了 @ 小号。

**Q：快速登录提示"未找到该 QQ 历史登录记录"？**
该 QQ 在这台机器从未成功登录过，先扫码登录一次即可；之后就能自动登录。

**Q：报 404 / 400 WebSocket 连接错误？**
说明你配的是"反向 WebSocket"，本项目用的是 **HTTP 模式**——请按第 6 步删除 WebSocket 配置，改配 HTTP 服务器 + HTTP 客户端。

**Q：二维码不刷新/过期？**
NapCat 已知 bug（Issue #1962，新版已修）；关掉 NapCat 重新双击 launcher.bat 生成新码即可。

**Q：视频一直收不到？**
视频生成本身需要几分钟；超过 5 分钟看 bot 窗口日志的报错信息（如 `size must be 720P`，检查模型名是否 2.5 系列）。

**Q：想换模型？**
WebUI 点「↻ 获取云端模型列表」→ 三个模型输入框下拉选择 → 保存即生效。

## 目录结构

```
xiaobai/
├── bot.py            # 主程序：OneBot HTTP 事件处理 + 消息逻辑
├── brain.py          # AI 大脑：Agnes 多模型 + Tavily + 图像/视频路由
├── config.py         # 配置持久化（config.json）
├── webui.py          # WebUI 后端 API
├── templates/ + static/   # WebUI 前端
├── start_bot.bat     # 一键启动脚本（Windows）
├── requirements.txt  # Python 依赖
└── .env.example      # 环境变量配置模板（可选，WebUI 配置优先）
```

## ⚠️ 免责声明

本项目基于 NapCat 等第三方协议端实现个人自动化，非腾讯官方接口，存在账号被限制的风险。请勿用于垃圾营销、批量群发等场景，仅供个人学习与技术交流。
