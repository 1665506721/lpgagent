# 14-Agent构建路径.md

# 该项目的 Agent 构建路径

## 1. 一句话概括
这个项目的 Agent 不是单纯的“LLM + function calling”，而是一个面向 LPG 客服场景的编排式 Agent。

它的核心设计不是让模型自由决定一切，而是：
- 先做路由和风险判断
- 再区分 query / action / smalltalk / safety
- 写操作统一进入 pending_action 状态机
- 工具执行和回复生成解耦
- 高风险场景优先走规则与安全模板
- 全链路事件化记录，便于审计和回放

所以从工程视角看，它更像一个：
- `规则编排器 + 状态机 + 工具层 + RAG + LLM表达层`
而不是一个纯 Prompt 驱动 Agent。

## 2. Agent 主入口在哪里
### 2.1 API 入口
用户消息从这里进入：
- `backend/core/views.py -> ChatView`
- API 路径：`/api/chat`

这个入口负责：
- 读取请求参数
- 处理 `portal_mode`
- 解析 provider 配置和 API key
- 获取或创建 `run`
- 记录 `INIT` 事件
- 调用 `run_orchestrator(...)`

### 2.2 编排入口
统一编排入口是：
- `backend/agent/orchestrator.py -> run_orchestrator(...)`

这个文件相当于总入口分发器：
- 普通模式走传统编排逻辑
- `portal_mode` 下主要转到：
  - `backend/agent/portal_orchestrator.py -> run_portal_orchestrator(...)`

面试里可以这样讲：
- `/api/chat` 只做接入层和上下文组装
- 真正的 Agent 决策在 orchestrator 层
- Portal 模式和普通模式共用统一入口，但分支编排逻辑不同

## 3. Agent 的整体分层
我会把这个 Agent 体系分成 6 层来讲。

### 3.1 接入层
位置：
- `backend/core/views.py`

职责：
- 接收 HTTP 请求
- 用户身份与 provider 配置注入
- run 生命周期管理
- 错误转 HTTP response

### 3.2 编排层
位置：
- `backend/agent/orchestrator.py`
- `backend/agent/portal_orchestrator.py`

职责：
- 路由决策
- 状态机推进
- 选择 query / action / rag / safety / smalltalk
- 决定何时调工具、何时直接回复、何时进入确认态

### 3.3 工具层
位置：
- `backend/agent/tools.py`

职责：
- 把编排层的动作落到具体业务方法
- 查询订单、改址、下单、购物车、通知、反馈、RAG 检索等
- 统一记录工具执行事件

### 3.4 知识层
位置：
- `backend/knowledge_base/*`

职责：
- RAG 检索
- safety / biz 双域知识召回
- query rewrite 后的召回和轻量重排

### 3.5 生成层
位置：
- `backend/agent/llm_router.py`
- `backend/agent/prompts.py`
- `portal_orchestrator` 内的 `_llm_compose_kb_reply(...)`、`_llm_general_reply(...)`

职责：
- 负责自然语言表达
- 不直接越权执行写操作
- 在 evidence 足够时组织“证据型回答”
- 在弱命中时做兜底表达

### 3.6 审计与记忆层
位置：
- `core.models.AgentRun`
- `core.models.AgentEvent`
- `customer_portal.CustomerConversationMemory`

职责：
- 保存会话 run
- 保存每一步 event
- 保存 pending_action 与长期偏好/上下文记忆

## 4. Agent 的核心设计思想
### 4.1 不是自由对话，而是“任务编排”
这个 Agent 的重点不是让模型尽可能自由聊天，而是保证：
- 能查事
- 能办事
- 高风险可控
- 写操作可确认
- 全链路可追溯

### 4.2 Query 和 Action 是强区分的
系统把用户输入大致分成：
- `QUERY`：查询类
- `ACTION`：写操作类
- `RAG`：知识问答类
- `SMALLTALK`：闲聊类
- `SAFETY`：高风险安全类

在代码里能看到这些设计痕迹：
- `QUERY_INTENT_CODES`
- `WRITE_ACTION_TYPES`
- `PORTAL_LANE_CTX`
- `_set_lane(...)`

也就是说，这个项目不是收到一句话后就直接让 LLM 判断 function call，而是先把消息分流到明确 lane。

## 5. 在线执行路径是怎样的
一条典型消息的处理链路可以概括为：

1. 用户请求进入 `/api/chat`
2. 创建或续用 `AgentRun`
3. 写一条 `INIT` event
4. 进入 `run_orchestrator(...)`
5. 在 Portal 模式下进入 `run_portal_orchestrator(...)`
6. 编排层先读取：
   - 当前消息
   - 历史 run/event
   - `pending_action`
   - portal memory
   - provider / model source
7. 做路由与意图判断
8. 根据 lane 决定：
   - 调工具
   - 走 RAG
   - 走安全模板
   - 或直接 smalltalk
9. 若是写操作，则先进入确认式状态机
10. 最终返回：
   - `final_response`
   - `routing`
   - `pending_action`
   - `confirm_required`
11. 同时写入 `RESPOND / DONE / TOOL_EXEC / PLANNING` 等事件

## 6. 意图识别和路由是怎么做的
### 6.1 多信号混合路由
这个项目不是单靠一个 classifier，而是混合了：
- 规则关键词
- query override
- task/entity signal
- LLM route
- 当前 pending_action 状态

你可以把它理解成“多阶段路由”。

### 6.2 LLM-first 但不是 LLM-only
在 `portal_orchestrator.py` 中可以看到：
- `_llm_route_turn(...)`
- `_intent_from_text(...)`
- `_build_stage0_signal(...)`

这说明它并不是完全规则死写，也不是完全让 LLM 自由判断，而是：
- 先让 LLM 给出 lane 倾向
- 再用规则和当前状态做纠偏
- 最终合成一个比较稳的路由决策

### 6.3 为什么这样做
因为客服 Agent 里常见问题是：
- LLM 容易把查询误判成办理
- 容易把 side query 打断当前办理流程
- 容易把高风险安全问题回答得太自由

所以这里用了“规则 + LLM 协同路由”的方式，提升稳定性。

## 7. pending_action 状态机怎么做的
这是项目里最重要的 Agent 设计点之一。

### 7.1 什么是 pending_action
当用户发起一个办理类任务时，不会直接执行，而是先构造一个 `pending_action`，里面通常包含：
- `type`
- `status`
- `payload`
- `draft`
- `id`
- `summary`
- 是否需要 `confirm_required`

### 7.2 状态机价值
它解决的是：
- 多轮收集槽位
- 执行前确认
- 组合操作分步骤推进
- side query 不打断主任务

### 7.3 典型状态
虽然项目里不是单独抽成一个 enum 文件，但从逻辑上可分成：
- `COLLECTING`
- `AWAIT_CONFIRM`
- `DONE / CLEARED / CANCELED`
- 某些复杂动作还会有 `PARTIAL_DONE` 的概念

### 7.4 典型流程
以改地址为例：
1. 用户说“把这单改址到 xx”
2. 系统先判断订单是否明确
3. 若缺信息，进入 `COLLECTING`
4. 信息齐全后，生成摘要
5. 设置 `confirm_required=True`
6. 用户回复“确认”后才真正执行工具

也就是说，写操作不是由 LLM 直接一句话触发，而是受状态机保护。

## 8. 工具调用路径怎么走
### 8.1 统一入口
工具统一入口在：
- `backend/agent/tools.py -> execute_tool(run, tool_name, tool_input)`

### 8.2 工具类型
当前工具大致有三类：
- 通用 mock/legacy 工具
  - `create_order`
  - `query_order`
  - `modify_order_address`
  - `create_ticket`
- Portal 业务工具
  - `portal_list_orders`
  - `portal_get_order`
  - `portal_create_order`
  - `portal_modify_address`
  - `portal_create_feedback`
  - `portal_list_notifications`
  - `portal_change_password`
  - 等等
- 知识工具
  - `kb_search`
  - `safety_search`

### 8.3 调用模式
编排层不会直接操作数据库，而是：
- 先 `_append_event(..., STATE_EXEC_TOOL)`
- 再 `execute_tool(...)`
- 工具执行后记录 `STATE_TOOL_EXEC`

这让工具调用具备：
- 可追踪
- 可回放
- 可审计

## 9. Agent 和 RAG 是怎么接起来的
### 9.1 不是所有问题都走 RAG
编排层会先判断这个问题是不是：
- 动作问题
- 查询问题
- 小聊问题
- 高风险安全问题
- 强事实知识问题

只有适合走知识库的问题才会进入 RAG。

### 9.2 接入方式
Portal 编排层通过：
- `_rewrite_kb_query(...)`
- `_collect_kb_hits(...)`
- `_llm_compose_kb_reply(...)`
把 RAG 接进主链路

### 9.3 关键点
- query rewrite 先改写检索 query
- `_collect_kb_hits(...)` 实际调用 `kb_search` 或 `safety_search`
- `retriever.py` 会做向量召回 + 轻量重排
- 命中足够时，再让 LLM 基于 bullets 生成证据型回复
- 命中不足时，走澄清或 fallback

所以这里的 Agent 和 RAG 关系是：
- Agent 负责决定何时检索、检什么、检索结果怎么用
- RAG 只是 Agent 能力层里的一个知识工具，不是整个系统的唯一中心

## 10. 安全和风控是怎么做的
### 10.1 安全优先
LPG 场景最重要的是安全，所以安全问题不是普通 FAQ。

系统对安全场景做了单独 lane：
- `safety`

并区分：
- 高风险安全应急
- 一般安全问答
- 是否可以自由回答

### 10.2 高风险控制
如果命中高风险词，比如：
- 漏气
- 异味
- 报警
- 火灾
- 中毒

编排层会优先：
- 输出应急步骤
- 抑制自由生成
- 强制热线提醒或更保守的回复策略

### 10.3 禁止危险建议
对于：
- 自己拆
- 绕过安全装置
- 自行维修燃气关键部件

这类场景系统会做拒答或强提醒，而不是让 LLM自由出主意。

## 11. 记忆是怎么做的
### 11.1 短期记忆
短期记忆主要来自：
- `AgentRun`
- `AgentEvent`
- 最近对话上下文
- 当前 `pending_action`

### 11.2 门户用户记忆
Portal 模式下还有：
- `CustomerConversationMemory`

存的通常是：
- 用户最近办理草稿
- 偏好
- 上轮上下文
- hotline 状态
- order draft

### 11.3 价值
这样做的效果是：
- 用户中途插一个 side query，不会把当前办理任务丢掉
- 用户补充信息时，不需要每轮重来
- 多轮对话更接近真实客服体验

## 12. 可观测性怎么做的
这是这个项目很强的一点。

### 12.1 核心对象
- `AgentRun`
- `AgentEvent`

### 12.2 记录内容
每一轮会记录：
- 用户输入
- 路由决策
- 工具调用输入输出
- policy_result
- 回复内容
- 状态推进

### 12.3 事件状态
常见 event state 包括：
- `INIT`
- `PLANNING`
- `EXEC_TOOL`
- `TOOL_EXEC`
- `RESPOND`
- `DONE`
- `ERROR`

### 12.4 为什么重要
在 Agent 项目里，难点不是写个 demo，而是：
- 为什么这么路由
- 为什么执行了这个工具
- 为什么这次回答是 fallback

事件化记录让这套系统能回放、排错、做质量分析。

## 13. 为什么说这是“编排式 Agent”而不是“函数调用 Demo”
原因主要有五点：

1. 有明确的分层
- 接入层、编排层、工具层、知识层、生成层、审计层是分开的

2. 有状态机
- 写操作不是收到消息就执行，而是要经过收集、摘要、确认

3. 有领域化路由
- query / action / rag / smalltalk / safety 是分 lane 处理的

4. 有可观测性
- run 和 event 让整个 Agent 可追溯

5. 有风控约束
- 高风险场景和写操作都不是交给 LLM 自由处理

## 14. 这个 Agent 的优点
### 工程优点
- 可维护
- 可扩展
- 调试成本低
- 更适合业务落地

### 业务优点
- 能查也能办
- 写操作更安全
- side query 不会把办理任务打断
- 安全问题响应更稳

## 15. 当前限制
这套 Agent 也有边界：
- `portal_orchestrator.py` 逻辑比较大，后续可以继续拆子模块
- LLM 路由仍然是轻量协同式，不是完整的学习型 planner
- 工具层目前仍有一部分 mock / 半真实逻辑混在一起
- 多动作组合任务还可以进一步标准化成更统一的 action graph

## 16. 面试时可以直接复述的版本
你可以直接这样说：

> 这个项目里的 Agent 不是一个纯 prompt 驱动的 function calling demo，我把它做成了一个编排式 Agent。入口在 `/api/chat`，接入层只负责拿请求、建 run、注入上下文，真正的决策在 orchestrator 层，Portal 模式主要走 `portal_orchestrator`。编排层会先做意图和 lane 路由，把请求分成 action、query、rag、smalltalk、safety 这些类型。对于写操作，我没有让模型直接调用工具，而是统一进入 `pending_action` 状态机，先收集槽位、生成摘要、等待确认，再执行工具。工具层通过统一 `execute_tool` 入口封装业务操作和知识检索，同时写 `AgentEvent` 做审计。RAG 只是 Agent 的一个能力模块，编排层会决定何时做 query rewrite、何时召回知识、何时用 LLM基于证据组织回答。高风险安全场景则优先走规则和模板，不交给 LLM 自由发挥。整个系统的重点是可控、可追溯、能办事，而不是只会聊天。`

## 17. 相关代码位置
- 接入层：`backend/core/views.py`
- 总入口：`backend/agent/orchestrator.py`
- Portal 主编排：`backend/agent/portal_orchestrator.py`
- 工具层：`backend/agent/tools.py`
- LLM 路由：`backend/agent/llm_router.py`
- Prompt：`backend/agent/prompts.py`
- RAG：`backend/knowledge_base/*`
- 事件与 run：`backend/core/models.py`
