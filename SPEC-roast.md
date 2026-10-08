# Capability Map: 群聊技能路由（chat-skills）

| Module id | Responsibility | Depends on |
|---|---|---|
| skill-router | 意图检测与技能分发：匹配群聊指令意图 → 调用对应技能，未命中走普通对话 | — |
| roast | 玩梗吐槽技能：帮骂/怼/整某人，输出调侃文本 | skill-router |
| (future) | 后续技能按同一接口挂载（如成语接龙、抽奖、点歌…） | skill-router |

Build order: skill-router → roast → (future skills 逐个追加)

# Spec: 群聊技能路由框架（chat-skills）

## Objective
把「@小白 + 指令」类群聊玩法做成可扩展框架：每类玩法是一个「技能」，由统一的路由层识别意图并分发；未被技能识别的消息照常走现有 AI 对话链路。第一个技能是「玩梗吐槽（帮骂）」。

用户故事：
- 群友 A：「@小白 帮我骂 @小狗」→ 路由命中 roast 技能 → 输出针对小狗的调侃 + @小狗 + 引用原消息
- 群友 A：「@小白 今天天气如何」→ 未命中任何技能 → 走原对话链路，行为不变
- 开发者：新增一个技能 = 新建一个函数 + 注册一行，不改路由核心

## 被吐槽目标的解析（重要）
- 指令里被 @ 的人可以是群里任意成员，不限于某个固定 ID；机器人收到的是其 QQ 号（`at_others` 已解析）
- 生成调侃前，用现有 `_member_names()` 把 QQ 号解析为「群名片(昵称)」，以昵称语境交给模型，保证调侃内容针对「这个人」（如「小狗」是他的群昵称就用小狗称呼）
- 发送时 @ 的也是该成员的真实 QQ 号（现有 `at_list` 机制）

## 技能接口约定（核心设计）
每个技能是一个 dict/对象，含：
- `name`：技能名（唯一 id）
- `pattern`：触发正则（匹配用户指令文本）
- `handler(group_id, user_id, text, targets, cfg) -> str`：生成回复文本（抛异常由路由统一兜底）
- `system_hint`：可选，命中后追加到 system_prompt 的风格指令

路由顺序：管理员指令 → 关键词回复 → 技能路由 → 普通对话。

## 非目标
- 不支持私聊技能（无 @ 语境）
- roast 不生成真正辱骂/攻击/歧视内容
- 不引入插件目录/热加载等重机制（保持单文件简洁，注册即用）

## 实现要点
- `bot.py`：新增 `SKILLS: list` 注册表 + `route_skill()` 函数；`handle_message` 在限速之后、普通对话之前调用路由
- roast 作为第一个技能实现于 `bot.py` 内（或 skills 小节），handler 调 `brain.reply` 生成调侃，system_hint 约束损友玩梗语气、一句话以内
- 发送复用 `_send_logged(ev, reply, reply_to=..., at_list=at_others)`（已支持 @ 第三人）
- `config.py` 新增：`skills_enabled`(True)、`roast_words`（触发词正则）、`roast_prompt`（风格指令）

## Commands
- 语法检查：`python -m py_compile bot.py config.py`
- 冒烟：`python -c "import bot"` + 群聊人工实测

## Testing Strategy
py_compile + 导入冒烟 + 人工群聊实测（命中/不命中/关闭开关三条路径）。

## Boundaries
- Always：技能异常统一 try/except 兜底，绝不阻断普通对话；新技能走注册表
- Ask first：新增技能、修改路由顺序、调整 roast 力度
- Never：技能输出真辱骂/脏话/歧视；技能对私聊生效

## Success Criteria
1. 「@小白 帮我骂 @小狗」→ 调侃文本 + @小狗 + 引用
2. 普通提问不误触发技能，行为与现在完全一致
3. `skills_enabled=False` 时所有技能关闭，等价于现状
4. 新技能只需：写 handler + 往 SKILLS 加一行（≤5 文件）
5. 技能 handler 抛异常时回复兜底文案，不崩溃

## Open Questions
- 第一个上线的除 roast 外还要不要别的技能？（可先只上 roast，框架留好扩展点）
