# Plan: 画图追问会话（image-followup）

对应规格：SPEC-image-followup.md（已批准）

## 组件与依赖

1. **config.py**（无依赖，先行）
   - 新增 `image_followup_ttl`: 300（秒，0=关闭追问生图）

2. **bot.py — 记录与追问路由**（依赖 1）
   - `_last_image: dict[str, tuple[float, str]]`（chat_key → 上次生图时间 + prompt）
   - 记录点：`handle_message` 里现有 `if image_urls:` 图片理解分支之外，在 `brain.reply` 返回 `[CQ:image` 开头的画图结果后记录。具体做法：`wants_image(text)` 命中路径在 bot.py 现有代码里位于 `brain.reply` 内部——为了最小改动，改为在 `handle_message` 调 `brain.reply` 前先判 `brain.wants_image(text)`，命中则把去掉触发词的 prompt 传给 reply 并在成功返回后记录 `_last_image`
   - 追问路由（位于限速检查后、技能路由后、图片理解前）：
     条件 = `wants_image(text)` 为 False 且 `_last_image` 未过期且消息没命中关键词/技能/链接摘要（这些分支在 handle_message 里本来就先 return）
     行为 = 新 prompt = f"{上次prompt}；调整要求：{text}" → `brain.generate_image(新prompt)` → 发送，失败走兜底文案
   - `_cleanup_loop` 增加清理过期 `_last_image`

3. **验证**（依赖 2）
   - py_compile、导入冒烟
   - 冒烟脚本：记录→TTL 内追问命中；过期后不触发；TTL=0 关闭；普通对话不误触发（无 _last_image 时）

## 实施顺序
config.py → bot.py 记录 + 追问路由 + 清理 → 验证

## 风险与缓解
- 追问误触发（TTL 内聊别的）→ 验证不误触发用例 + TTL 可调；误触发代价只是一张图
- `brain.reply` 内部才判 wants_image，无法拿到 prompt → 改在 handle_message 先判并显式传 prompt，`brain.reply` 兼容
- 重复生图费用 → TTL 有限 + 限速已有

## 验证检查点
每步 py_compile；最终冒烟脚本 5 条路径；人工群聊实测
