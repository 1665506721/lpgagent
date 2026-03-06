# 对话质量测试套件（100条）

## 文件
- 用例：`spec/dialog_quality_cases_zh.jsonl`
- 运行器：`tools/run_dialog_quality_cases.py`
- 结果（默认）：
  - `spec/dialog_quality_results.jsonl`
  - `spec/dialog_quality_results.csv`

## 1) 先预览用例
```bash
python tools/run_dialog_quality_cases.py --dry-run
```

## 2) 跑全量100条（推荐）
先设置登录态 token（需要鉴权接口时）：
```powershell
$env:PORTAL_TOKEN="你的portal token"
```

运行：
```bash
python tools/run_dialog_quality_cases.py ^
  --base-url http://localhost:8000 ^
  --provider-model qwen3:4b ^
  --sleep 0.2
```

## 3) 跑指定用例（回归某些问题）
```bash
python tools/run_dialog_quality_cases.py --ids DQ011,DQ035,DQ083,DQ100
```

## 4) 连续上下文模式（同一 run_id 串行）
```bash
python tools/run_dialog_quality_cases.py --continue-run --limit 20
```

## 5) 只跑前20条
```bash
python tools/run_dialog_quality_cases.py --limit 20
```

## 参数说明
- `--base-url`：后端地址，默认 `http://localhost:8000`
- `--provider-model`：模型名，如 `qwen3:4b`
- `--continue-run`：启用后，所有用例共用一个 `run_id`
- `--ids`：只跑指定ID，逗号分隔
- `--limit` / `--offset`：切片执行
- `--sleep`：每条间隔（秒）
- `--fail-fast`：遇到失败立即停止
- `--no-portal-mode`：关闭 `portal_mode`（默认开启）

## 结果字段（CSV/JSONL）
- `id`、`category`、`intent_hint`
- `status_code`、`ok`
- `confirm_required`、`run_id`
- `latency_ms`
- `response`、`error`

