# 智能客服深层测试（多轮场景）

## 1) 准备
- 启动后端：`python backend/manage.py runserver 127.0.0.1:8000`
- 准备 token（示例）：
  - `python backend/manage.py shell`
  - 执行：
    - `from customer_portal.auth_helpers import ensure_test_account`
    - `from customer_portal.models import CustomerAuthToken`
    - `u = ensure_test_account(); print(CustomerAuthToken.rotate_token(u).token)`

## 2) 运行多轮深测
```bash
python tools/run_dialog_deep_scenarios.py ^
  --base-url http://127.0.0.1:8000 ^
  --token <YOUR_TOKEN> ^
  --provider-model qwen2.5-7B-instruct ^
  --scenarios spec/dialog_deep_scenarios_zh.json ^
  --out-json spec/dialog_deep_results_v1.json
```

## 3) 场景覆盖
- 多轮下单补槽 + 确认
- 订单查询 + 快照查看
- 改址规则判定
- 账户资料查看 + 昵称修改确认
- 地址新增 + 设默认
- 安全应急回复完整性
- 发票承接
- 配件路径说明
- 支付缺单号引导
- 能力边界说明

## 4) 输出说明
- 输出文件：`spec/dialog_deep_results_v1.json`
- 结果包括：
  - 场景通过率
  - 每步响应状态、intent、confirm_required
  - 每步命中/不命中原因
