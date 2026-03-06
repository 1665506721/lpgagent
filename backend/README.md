# Backend README

`backend/` 是 Django + DRF 服务端，负责：
- `/api/chat` Agent 编排与工具调用
- Portal 账号/地址/订单/通知/反馈业务接口
- 知识库检索（RAG）与事件审计回放

## 1. 启动
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## 2. 常用命令
```bash
python manage.py test
python manage.py rebuild_kb --domain safety --force
python manage.py rebuild_kb --domain biz --force
```

## 3. 配置建议（使用 `.env`）
请在本地创建 `backend/.env`，不要提交到 Git。

示例（仅示意，值请自行替换）：
```env
MODEL_PROVIDER=OLLAMA
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
OPENAI_API_KEY=your_api_key_here
DATABASE_URL=sqlite:///db.sqlite3
```

## 4. 隐私与密钥管理
- 禁止提交：真实 API Key、Token、手机号、邮箱、数据库密码、证书私钥。
- 代码里如果需要示例值，请使用占位符（如 `your_api_key_here` / `TOKEN`）。
- `backend/.env`、本地日志、数据库、向量索引目录应保持未跟踪状态。

## 5. 关键目录
- `agent/`: 编排器、路由、工具、对话规则与测试
- `core/`: 通用模型与 API 视图
- `customer_portal/`: 门户业务域（地址/订单/通知等）
- `knowledge_base/`: 文档、索引与检索
- `config/`: Django settings / urls
