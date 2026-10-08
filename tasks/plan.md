# Plan: 群聊技能路由框架（chat-skills）

对应规格：SPEC-roast.md（已批准）

## 组件与依赖

1. **config.py** — 新增 3 个默认项（无依赖，先行）
   - `skills_enabled`: True
   - `roast_words`: 触发词正则 `帮我(骂|怼|喷|损|整|教育|吐槽|输出)|骂(一?下|他)|怼(一?下|他)|喷(一?下|他)|吐槽(一?下|他)`
   - `roast_prompt`: 吐槽风格 system 指令（损友玩梗、一句话、不辱骂不脏话不歧视）

2. **bot.py — SKILLS 注册表 + route_skill()**（依赖 1）
   - `SKILLS: list[dict]`：每项 `{name, pattern, handler, system_hint}`
   - `route_skill(text, group_id, user_id, targets, cfg) -> str | None`：
     遍历注册表，`pattern.search(text)` 命中且 targets 非空 → 调 handler，异常统一兜底返回 None 前先记日志；未命中返回 None
   - roast 技能 handler：调用现有 `_member_names(group_id, targets)` 解析昵称 → 拼「针对昵称的玩梗指令」→ `brain.reply(text, [], cfg["system_prompt"] + roast_prompt + 昵称语境)`

3. **bot.py — handle_message 接入**（依赖 2）
   - 位置：限速检查之后、图片理解/普通对话之前（群聊、at_me、有 at_others 时才路由）
   - 命中：`_send_logged(ev, reply, reply_to=..., at_list=at_others)` 发送并 return
   - 未命中：走现有链路，行为零变化

## 实施顺序
config.py → bot.py 路由+roast → handle_message 接入 → 验证

## 风险与缓解
- 误触发普通消息 → pattern 限定「帮我/给我 + 动词」类明确指使句式，且必须有 @ 第三人
- 昵称解析失败（拿不到群成员信息）→ `_member_names` 已有兜底（返回 QQ 号），handler 内再 try/except
- LLM 输出过长 → 复用 `max_reply_chars` 截断
- 技能异常 → route_skill 统一捕获，返回 None 落回普通对话（不崩、不发空消息）

## 并行性
全部改 bot.py/config.py，串行执行。

## 验证检查点
- 每步后 `python -m py_compile`
- 最终：导入冒烟 + route_skill 命中/不命中单测式脚本 + 人工群聊实测
