# 前端浏览器验收

冠军之路测试通过拦截 API 返回固定签表，验证 7 场比赛、7 条真实依赖连线及其来源拓扑、3 段冠军高亮路线，并实际滚动窄屏画布。完整排位测试验证季军、9–16、13–16、15–16 等区间不会混成一张难以识别的比赛列表。

`test_operation_mode.py` 连接真实本地前后端，验证正式/演示标识、演示按钮隔离及后端拒绝正式赛事调用演示接口。

在 `frontend` 目录启动预览服务后运行：

```powershell
python -m pip install -r e2e/requirements.txt
$env:PINGPONG_E2E_URL = "http://127.0.0.1:4173"
python e2e/test_champion_journey.py
python e2e/test_placement_bracket.py
```

默认使用本机 Microsoft Edge；可通过 `PLAYWRIGHT_CHANNEL` 改为其他已安装的 Chromium 通道。
