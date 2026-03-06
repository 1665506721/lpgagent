# 前端说明（安燃助手客服台）

## 1. 这个前端做什么
这是一个面向客服的对话工作台，目标是：
- 与后端对话接口对接，完成咨询与业务闭环。
- 当后端返回表单协议时自动弹窗，补齐信息并提交。
- 可选查看 run 回放，便于解释“系统做了什么”。

## 2. 页面结构（单页）
- 顶部：标题与“智能引擎”选择（model_provider）。
- 左侧：聊天区（消息流 + 输入框 + 发送按钮）。
- 右侧：运行回放（默认收起，需要时再展开）。

## 3. 数据流（关键）
1) 用户发消息 → `POST /api/chat`。  
2) 后端返回 `final_response` 与 `run_id` → UI 渲染回复并拉取事件。  
3) 如返回 `ui_action=SHOW_FORM` → 弹窗表单补齐并再次提交：
   - 提交格式：`提交表单：{ "form_id": "...", "payload": {...} }`

## 4. 主要组件与职责
- `src/pages/SupportConsole.tsx`：页面编排与数据流入口。
- `src/components/ChatPanel.tsx`：消息流展示与发送逻辑（支持 Enter 发送）。
- `src/components/FormDialog.tsx`：表单协议弹窗渲染与提交。
- `src/components/RunInspector.tsx`：run 回放（默认收起）。
- `src/lib/api.ts`：后端请求封装与错误处理。
- `src/lib/schemaForm.ts`：轻量 JSON Schema 渲染（string/number/boolean/enum）。

## 5. 文案与体验要点
- 全中文 UI 文案，面向客服使用场景。
- 对话区域优先呈现“可执行信息”，回放信息默认收起。
- 表单字段支持完整手机号或后四位，具体以后台校验为准。

## 6. 本地运行
```bash
cd frontend
npm install
npm run dev
```

## 7. 维护约定
- 如调整页面结构、表单协议或 API 对接方式，请同步更新本 README。
