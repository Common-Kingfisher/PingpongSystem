# 前端浏览器验收

冠军之路测试通过拦截 API 返回固定签表，验证 7 场比赛、7 条真实依赖连线、3 段冠军高亮路线及窄屏横向浏览。

在 `frontend` 目录启动预览服务后运行：

```powershell
python -m pip install -r e2e/requirements.txt
$env:PINGPONG_E2E_URL = "http://127.0.0.1:4173"
python e2e/test_champion_journey.py
```

默认使用本机 Microsoft Edge；可通过 `PLAYWRIGHT_CHANNEL` 改为其他已安装的 Chromium 通道。
