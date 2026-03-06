# LPG 企业用户端平台 MVP 需求与开发约束

目标：在不重构现有 `chat/run/rag/forms/tools/orchestrator` 主链路的前提下，为 LPG-AI-Agent-Platform 增量扩展一个“可直接用”的企业用户端平台，并嵌入安燃助手作为下单与客服入口。

## 0. 强约束与边界
- **不改主链路**：现有 `rules`、`forms` 协议、`orchestrator`、事件链保持不动，仅做增量扩展。
- **规则优先**：状态机与业务规则在后端可验证、可测试，LLM 仅写作。
- **新增独立业务域**：新增 Django app（见后文建议命名），通过 tools 接入给 agent 使用。
- **前端隔离**：新增用户端页面/路由，不影响现有 SupportConsole 客服台。

## 1. MVP 功能清单
- 用户注册/登录（手机号 + 验证码 + 密码），登录：手机号 + 密码，验证码用于找回/验证。
- 个人资料管理：用户名、手机号、密码管理。
- 地址管理：多地址、可设默认地址。
- 选择服务类型并下单：  
  选择服务类型 → 填写地址/时间/备注 → 选择加急 → 去支付并下单。
- **支付为 mock**：点击支付视为成功，但保留“先支付后成立”的状态机与事件。
- AI 客服嵌入下单：  
  - 我自己操作：返回 `ui_action=SHOW_FORM`（对应服务表单）。  
  - 让 AI 帮我操作：读取默认地址/手机号，逐步确认关键字段，确认后调用 `create_order`。
- 订单查询/详情：登录态下拉取历史订单列表并查看详情。

## 2. 明确不做（MVP 非目标）
- 不做运力/撮合/派单/抢单。
- 不接真实支付渠道（仅 mock）。
- 不做城市/区域级别的可用时段差异。
- 不做地图/经纬度（仅文本地址）。

## 3. 业务类型与表单字段（最小必填）
### 通用字段（所有服务类型）
- 联系人姓名（`contact_name`，必填）
- 联系电话（`contact_phone`，必填）
- 服务地址（`address_full`，必填）
- 期望时间窗（`eta_window`，必填，支持“尽快/今日/明日/指定时段”）
- 是否加急（`is_urgent`，可选，默认 false）
- 备注（`notes`，可选）

### 服务类型枚举（MVP 全支持）
1) **LPG_CYLINDER_DELIVERY 瓶装配送**  
   - `cylinder_type`（必填，如 15kg/5kg/45kg）  
   - `quantity`（必填）
2) **CYLINDER_EXCHANGE 换瓶**  
   - `cylinder_type`（必填）  
   - `quantity`（必填）  
   - `return_empty`（必填，是否回收空瓶）
3) **INSTALLATION 安装**  
   - `install_item`（必填，例如热水器/灶具/报警器等）  
4) **SAFETY_CHECK 安检**  
   - `check_scope`（必填，例如全屋/厨房/管道）  
5) **REPAIR 报修**  
   - `issue_desc`（必填）  
6) **ACCESSORIES 配件**  
   - `accessory_item`（必填，例如软管/减压阀/报警器）  
   - `quantity`（必填）

> TODO: 细化各服务类型字段枚举（如瓶型列表、安装/安检/配件的具体可选项）。  
> TODO: 价格表、加急费规则（用于前端展示与订单金额计算）。

### 表单协议要求
- 每个服务类型都有独立表单 schema（可复用现有 `forms` 协议结构）。
- 支持动态字段（由后端 schema 提供，前端表单渲染）。
- `ui_action=SHOW_FORM` 时前端弹窗填写，提交后进入 `create_order`。

## 4. 订单状态机与规则（强约束）
### 状态机
- `PENDING_PAYMENT`：已提交待支付（30 分钟后过期 → `EXPIRED`）
- `PAID`：支付成功（mock 即刻成功，但字段/事件保留）
- `SCHEDULED`：已排期/已预约（预约类服务）
- `IN_SERVICE`：配送开始/服务开始
- `COMPLETED`：完成
- `CANCELED`：取消
- `EXPIRED`：未支付过期

### 过期规则
- `PENDING_PAYMENT` 超过 30 分钟自动进入 `EXPIRED`（后端定时任务或查询时触发校验）。

### 取消规则（强约束）
仅当满足以下条件允许取消：  
- `now <= eta_start - 60min`  
- 且状态 ∈ {`PENDING_PAYMENT`, `PAID`, `SCHEDULED`}

### 改址规则（强约束）
仅当满足以下条件允许改址：  
- `now <= eta_start - 60min`  
- 且状态 ∈ {`PENDING_PAYMENT`, `PAID`, `SCHEDULED`}

### ETA 规则（强约束）
- 引入“服务时段”概念（全局一致）。  
- 下单时间不在服务时段内，则 ETA 自动滚动到下一可用时段。

> TODO: 服务时段默认值（建议 09:00–21:00）。  
> TODO: 时间窗粒度（如 2 小时/4 小时/指定时间段）。

## 5. 后端模块划分建议（新增 app）
### 新 app 命名（建议）
- `backend/customer_portal/` 或 `backend/consumer_portal/`  
  原则：独立于现有 `agent`、`core`，仅通过 tools 交互。

### 模型草图（示意）
- `CustomerProfile`：user 关联、手机号、用户名、默认地址、账号状态。  
- `CustomerAddress`：`contact_name`、`contact_phone`、`address_full`、`door_note`、`is_default`。  
- `ServiceType`：枚举/配置（code、name、active）。  
- `ServiceFormSchema`：服务类型 -> JSON schema（动态字段）。  
- `Order`：  
  - 核心字段：`service_type`、`status`、`eta_start/eta_end`、`is_urgent`、`notes`  
  - 用户字段：`contact_name/phone/address_snapshot`  
  - 金额字段：`amount_total`、`amount_payable`、`currency`  
  - 风险字段：`cancel_deadline`、`address_edit_deadline`
- `OrderItem`（可选）：存储服务类型相关字段（如 `cylinder_type`、`quantity` 等）。  
- `OrderEvent`：状态变更与业务动作（用于审计链）。  
- `PaymentTransaction`：支付 mock 记录（保留后续真实支付扩展位）。

### API 草图（示意）
- 认证与用户
  - `POST /api/portal/auth/register`
  - `POST /api/portal/auth/login`
  - `POST /api/portal/auth/sms`（验证码）
  - `GET /api/portal/me`
- 地址
  - `GET/POST /api/portal/addresses`
  - `PUT /api/portal/addresses/{id}`
  - `POST /api/portal/addresses/{id}/default`
- 服务与表单
  - `GET /api/portal/services`（服务类型列表）
  - `GET /api/portal/services/{code}/form`（返回 JSON schema）
- 订单
  - `POST /api/portal/orders`（创建订单 → `PENDING_PAYMENT`）
  - `POST /api/portal/orders/{id}/pay`（mock 支付 → `PAID`）
  - `POST /api/portal/orders/{id}/cancel`
  - `POST /api/portal/orders/{id}/modify-address`
  - `GET /api/portal/orders`
  - `GET /api/portal/orders/{id}`

### 工具函数草图（供 agent 使用）
- `list_services()`：返回服务类型及入口文案。
- `get_service_form(service_type, prefill)`：返回表单 schema。
- `create_order(payload)`：创建订单、回写状态与 ETA。
- `get_orders()`：登录态查询历史订单。
- `get_order_detail(order_id)`：订单详情。
- `cancel_order(order_id)`：校验规则后取消。
- `modify_order_address(order_id, new_address)`：校验规则后改址。

## 6. 前端页面草图（用户端）
- 首页：服务类型入口、搜索/常见服务、客服入口。
- 下单：服务类型选择 → 表单填写 → 确认 → 支付结果页（mock）。
- 订单列表：按状态筛选、最近订单。
- 订单详情：状态、ETA、地址、取消/改址入口。
- 客服入口：嵌入安燃助手对话（下单/咨询/查询）。
- 我的：个人资料、账号安全。
- 地址管理：新增/编辑/设默认。
- 登录/注册/找回：手机号 + 验证码流程。

## 7. 与安燃助手集成点
### Tools 接入
- 新 app 通过 `tools` 暴露创建订单、查询订单、改址、取消等能力。

### Forms 接入
- 新增多服务类型表单 schema（遵循现有 `forms` 协议）。
- 当用户说“我要订一个煤气罐”：  
  1) 先给两种选择：**自己操作** / **我帮你操作**  
  2) 自己操作：返回 `ui_action=SHOW_FORM`（瓶装配送表单）  
  3) 我帮你操作：AI 读取默认地址/手机号，询问瓶型/数量/时间窗/是否加急/备注，确认后调用 `create_order`

### 对话触发规则
- 订单查询：登录态下直接列历史订单，用户选择后返回详情。
- 表单与工具调用均要写入事件链，保持可审计。

## 8. 交付顺序
1) 完成本文档（已完成）。  
2) 按文档实现后端模型/API。  
3) 前端页面与路由。  
4) 工具接入 agent。

## 9. 待确认事项（实现前需要补齐）
- 服务时段默认值与时间窗粒度。  
- 价格表与加急费规则。  
- 各服务类型的字段枚举细化。  

## 10. 默认采用（若无异议）
- 服务时段：09:00–21:00。时间窗粒度：2 小时。  
- ASAP 规则：`eta_start=now+60min`，`eta_end=now+180min`。  
- 非服务时段下单：ETA 自动滚动到次日 09:00–11:00。  
- 加急规则：  
  - `eta_start` 提前 30min（不早于 `now+30min`）  
  - `eta_end` 提前 60min（不早于 `eta_start+60min`）  
  - `urgent_fee=max(10, subtotal*0.1)`，上限 50  
- 价格表 MVP：  
  - 配送按瓶型单价：5kg 60 / 15kg 120 / 45kg 280  
  - 安装 199  
  - 安检 99  
  - 报修 99 起  
  - 配件按 SKU 单价 * 数量  
- 订单模型：`Order.service_payload` 存不同服务字段，保留 `address_snapshot` / `contact_snapshot`。  
- API 统一响应：`{ok,data,error}`；错误码至少包含 `ORDER_NOT_CANCELABLE` / `ORDER_EXPIRED` / `AUTH_REQUIRED`。  
- 订单列表：支持 `status` 过滤与分页。  
- AI 代操作：三段式确认，用户明确“确认”后才调用 `create_order`。  
