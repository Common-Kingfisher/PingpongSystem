# D 轨 Day6D 现场模拟第一轮记录

> 本轮目标不是「证明测试很多」，而是：
>
> **一台普通 Windows 电脑 + 普通无线路由器 + 多台手机 + 同一个 PingpongSystem 服务，
> 能不能稳定地完成一场小型赛事的主要现场流程（报名 / 名单 / 抽签 / 录分 / 查看 / 掉线恢复 / 重启续赛）。**

分支：`test/d-day6-field-simulation`
基线：`master @ 50991f1d5e092a21d84765dbb3aa64e9f5e3b8e1`（本 Prompt 给出的 hash 已用 `git rev-parse` 与远端实际一致复核）

## 1. 基线（本轮在最新 master 上真实重跑）

| 项目 | 结果 |
| --- | --- |
| backend `pytest` | **1037 passed**, 4 warnings, 258.64s |
| frontend `pnpm test` | **15 files / 219 tests passed**, 22.75s |
| `pnpm exec tsc --noEmit` | PASS（exit 0） |
| `pnpm build` | PASS（`dist/index.html` + hashed css/js） |
| `pnpm contract:check` | PASS（`openapi-typescript` 重新生成后 `git diff --exit-code` 无差异） |
| `python export_openapi.py --check` | `OpenAPI snapshot is up to date` |
| `git diff --check` | 干净（无空白错误） |

## 2. 现场拓扑

```text
普通 Windows 主机（本机 WLAN 10.144.136.62）
   ↓
production 单服务：.\start_pingpong.ps1 -NoBrowser
   → 同一个 FastAPI 进程同时服务 /api/* 与 frontend/dist（非 Vite 5173 + FastAPI 8000 双服务）
   → 独立赛事库：PINGPONG_DB_PATH=data\d6d_field.db
   ↓
浏览器客户端（真实 Chrome 154 / headless / CDP 9333）
   → 每个「手机」= 一个独立 BrowserContext（独立 cookie jar / localStorage / 缓存）
```

**真实手机数量：0。模拟客户端数量：26。**
本轮没有物理手机与真实无线路由器，因此判定为 `PARTIAL — physical device coverage incomplete`。
所有「手机」均为本机独立浏览器上下文，脚本打印的 `CLIENTS simulated=N` 与「真实手机数」严格区分，
不把浏览器实例写成真实手机。

脚本对 LAN 地址的取向：Public 地址一律从 `window.location.origin` 派生。
用 LAN origin（`http://10.144.136.62:8000`）访问时，报名二维码与文本地址实测为
`http://10.144.136.62:8000/public/t/1/register`，host 与当前访问 host 完全一致；
`frontend/dist` 产物中不含 `localhost` / `127.0.0.1` / `192.168.*` / `10.*` 等硬编码主机。

## 3. E5 全链（Day6D Preflight）

赛事：`SINGLES / GROUP_KNOCKOUT / 16 席 / 4 组 / 每组前 2 出线 / 6 张球台`，全新建、不复用历史脏赛事。

| 环节 | 结果 | 关键事实 |
| --- | --- | --- |
| 管理端 UI 开启报名 | PASS | 仅通过 `/settings → 报名设置` 勾选并「保存报名设置」，服务端 `registration_enabled=true` |
| Public submit | PASS | 手机独立 context 打开 `/public/t/1/register` 真实填表提交 |
| PENDING | PASS | 回执「等待赛事组织者确认」；服务端 `status=PENDING`；回执不回显联系方式 |
| 匿名越权 | PASS | 匿名读报名列表 / confirm / 改报名开关 全部 `401` |
| Admin confirm | PASS | 管理端「待确认报名」逐条点「确认并加入名单」直到列表清空 |
| Player | PASS | 16 名 Player；确认阶段不伪造 Entry（`entries=0`） |
| Entry | PASS | 「确认参赛名单」后建立 16 个正式 Entry，`roster_confirmed=true`，阶段仍为 `REGISTRATION` |
| 名单冻结后 Public 关闭 | PASS | raw 仍为 `true`，但 Public 表现为 CLOSED：无表单、无二维码、0 次 `POST /registrations` |
| 分组 / 抽签 | PASS | 「生成分组」→ 4 组；「生成小组比赛」→ 24 场 |
| 排台 | PASS | 管理端「自动安排下一批比赛」→ 6 场 PLAYING，球台占用数 = 进行中比赛数 |
| Match / Mobile score（正常） | PASS | 3:1 落库，`games=0`（未伪造小比分），球台释放 |
| Match / Mobile score（异常） | PASS | `FORFEIT` + 二次确认，`result_type=FORFEIT`，无逐局小分，球台释放 |
| Public live / BigScreen | PASS | 两者进度读数一致（`比赛进度 2 / 24（8%）`），「正在进行」列出当前对阵 |

**E5 FULL CHAIN PASS**（自动门：`backend/day6d_field_simulation.mjs` = **113/113 PASS**）

## 4. 现场终端矩阵

| 设备/客户端 | 页面 | 操作 | 结果 | 异常 |
| --- | --- | --- | --- | --- |
| 管理电脑（1280×900，独立 context） | `/settings`、`/players`、`/draw`、`/console` | 开启报名 / 确认报名 / 确认名单 / 生成分组 / 生成比赛 / 自动排台 | PASS | 无 |
| 手机 A（390×844） | `/public/t/1/register` | 真实填表提交 | PASS | 无 |
| 手机 B（390×844，已登录） | `/admin/t/1/matches/{id}/score` | 正常结果 + 异常结果录分 | PASS | 无 |
| 手机（只读）×4 并发 | `/public/t/1/live` `/rankings` `/bracket` `/schedule` | 同时打开 + 各自刷新 | PASS | 无 |
| 手机 ×2 并发 | Mobile Score（两场不同比赛） | 同时提交 3:2 / 1:3 | PASS | 无串场、无错误放台 |
| 手机 ×2 并发 | Mobile Score（同一场比赛） | 同时提交不同比分 | PASS | 最终只有一方事实，审计仅 1 条 RECORD |
| 大屏（1440×900，独立 context） | `/bigscreen`（管理端）与 `/public/t/1/live` | 随录分/结束同步刷新 | PASS | 组件内部写操作入口 = 0 |

## 5. 网络 / 恢复

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 刷新（F5 / 独立 context，无 localStorage） | PASS | live / schedule / rankings / bracket / register / Mobile Score / BigScreen / Console 深链接 + 刷新均可用，无 `undefined` tid |
| 深链接 | PASS | `/`, `/public/t/1/*`, `/bigscreen`, `/admin/t/1/matches/1/score` 在 127.0.0.1 与真实 LAN IP 上都返回 200 SPA；`/api/*` 未知路径仍为 404（未被 SPA fallback 吞掉） |
| Public 断网 | PASS | 断网 7s 后不白屏、已有内容保留、无 `undefined`；恢复后无需清缓存/重登 |
| Mobile Score 断网提交 | PASS | 不假装成功、明确提示「网络连接失败，请检查局域网连接后重试」、输入未被清空、服务端未写入 |
| 恢复网络重新提交 | PASS | 重新提交成功，服务端最终比分正确 |
| 「已保存但刷新失败」 | PASS | 注入 reload 失败后显示「比分已保存…刷新失败」，`.ms-error` 为空，不再诱导重复提交 |
| 手机后台 35s → 回前台 | PASS | Public 页面与录分页恢复后均可用，无无限 loading，可继续完成一次录分 |
| 服务重启 | PASS | 见第 7 节 |

## 6. 并发

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 不同 Match 并发 | PASS | 两台手机同时提交两场不同比赛，比分不串场，球台各自正确释放 |
| 同 Match 并发 | PASS | 两端同时提交不同比分 → 最终只落一方（3:2），审计 `RECORD` 条数 = 1，不静默覆盖 |
| 重复提交 | PASS | 已结束比赛的录分页不再渲染提交入口；服务端对新的 `request_id` 返回 409 且比分不变；同一 `request_id` 重放不产生第二条事实 |

规则层证据仍由 `backend/tests/test_d6a_concurrency.py`（A6/D6A 冻结）承担，本脚本只补「现场形态」层。

## 7. 服务重启（Phase 7）

重启前后快照逐字段比对（`backend/day6d_restart_check.py`，只读 GET）：

```text
stage=GROUP_STAGE  roster_confirmed=True
players=16  entries=16  groups=4  matches=24
finished=9  playing=3  waiting=12
```

**15/15 PASS**：赛事/名称/阶段/赛制/名单确认状态、Player、Entry、报名台账、分组与逐组晋级人数、
比赛场次、9 场已结束比赛的比分与结果类型、`FINISHED` 不回退、进行中比赛与球台占用、
比分审计条数、进度统计 —— 全部一致。

重启使用**同一条正式命令**（`.\start_pingpong.ps1`）与**同一个数据库**；
没有重新生成 Demo 数据、没有清库、没有 `seed`。

## 8. 缺陷

### P1（本轮已修）

**Public 实况页「正在进行」卡片被超长无断点姓名撑破，并被静默裁切**

- **复现**：360 / 375 / 390 / 430px 打开 `/public/t/{tid}/live`，赛事中存在一个 26 字符的英文姓名
  （`AlexandertheGreatWangXiaomingZhangSanfeng`）。
  实测卡片 `right = 847.5px`，而视口只有 360px；`.pub-shell { overflow-x: hidden }` 把超出部分裁掉，
  且**无法横向滚动过去** —— 手机上看不全对阵。
- **根因**（两处 CSS 默认值语义，都在 `frontend/src/index.css`）：
  1. `@media (max-width: 720px)` 里 `.bigscreen-tables { grid-template-columns: 1fr }`。
     `1fr` 等价于 `minmax(auto, 1fr)`，`auto` 的下限是 min-content —— 长姓名把整列撑到 835px
     （实测 `gridTemplateColumns = "835.469px"`）。桌面规则本来就用 `minmax(0, 1fr)`，窄屏这条漏了下限。
  2. `.bigscreen-pair` 是 flex 行，flex 子项默认 `min-width: auto`（同样 = min-content），
     长姓名把这一行顶出卡片。
- **修改文件**：`frontend/src/index.css`（仅此一个文件）
- **修复**：窄屏列定义改为 `minmax(0, 1fr)`；给 `.bigscreen-pair > div:not(.bigscreen-vs)` 加
  `flex: 1 1 0; min-width: 0; overflow-wrap: anywhere`。
- **回归**：`backend/day6d_public_viewport_check.mjs` 新增网格轨道与「完整落在视口内」断言。
  修复前 152/164（12 条失败全部指向该 P1），修复后 **168/168 PASS**；
  网格轨道由 `835.469px` 变为 `336px / 351px / 366px / 406px`（= 视口宽减内边距）。

### P2（仅记录，本轮不改）

1. **`.bigscreen-header h1` 的超长无断点串被硬裁切**
   实测 360px 下 `client=336 / scroll=593`。页面无横向溢出、按钮不受影响，属非阻塞视觉问题。
   已作为 `[NOTE]` 留在视口脚本输出中。后续如要修，最小改法是给该标题加 `overflow-wrap: anywhere`。
2. **Mobile Score「已保存但刷新失败」提示语重复**
   页面上 `<strong>比分已保存</strong>` 与 `refreshWarning`（本身也以「比分已保存，但…」开头）相邻渲染，
   读起来是「比分已保存 比分已保存，但最新状态刷新失败…」。
   语义正确（**不是**「本次提交失败」），仅文案冗余。
3. **确认完最后一条报名后管理端仍停在「待确认报名」tab**
   要确认正式名单需手动切回「正式名单」tab。属可用性问题，不影响数据。

### P0

无。

## 9. 修改文件

| 文件 | 说明 |
| --- | --- |
| `frontend/src/index.css` | P1 最小修复（同第 8 节） |
| `backend/day6d_field_fixture.py` | 新建干净赛事（16 人 4 组，SINGLES/GROUP_KNOCKOUT，6 球台），刻意不预设报名开关 |
| `backend/day6d_field_simulation.mjs` | 现场模拟自动门（真实 Chrome 多 BrowserContext × production 单服务，113/113） |
| `backend/day6d_longname_fixture.py` | 小屏/长文本检查用数据（报名表单态 + 已排台的长名字赛事） |
| `backend/day6d_public_viewport_check.mjs` | 360/375/390/430 布局事实门（含本 P1 的回归断言，168/168） |
| `backend/day6d_restart_check.py` | 服务重启前后现场事实只读比对（15/15） |

## 10. 本轮判定

```text
PARTIAL — physical device coverage incomplete
```

理由：

- 基线、E5 全链、production 单服务 + LAN、Public 深链接刷新、Mobile Score 正常/异常/断网/恢复、
  多客户端并发读写、BigScreen 同步、后台恢复、服务重启数据保留、360/375/390/430 小屏 —— 全部通过；
- 发现的 1 个 P1 已按「最小必要修复」修掉并补了回归；
- 没有 P0；
- **但没有物理手机、没有真实无线路由器、没有第二台终端**，
  因此「5-6 个现场手机用户」这一条只能用独立浏览器上下文模拟，不能声明为完全达标。

## 11. 下一轮 Day6D 建议

1. 用真实手机（至少 3 台）+ 普通无线路由器复跑第 3、5、7 节，把 `PARTIAL` 补成 `PASS`；
   重点验证 Windows 防火墙入站路径（本机访问自身 LAN 地址不经过该路径）。
2. 物理断网（关 Wi-Fi / 走出覆盖范围）而非 CDP `Network.emulateNetworkConditions`。
3. 补测多网卡/多网段现场选错地址的用户体验（`start_pingpong.ps1` 已降权虚拟网卡，但未验证误选后果）。
4. 视情况清理第 8 节 P2 中的第 1、2 条（均为 1-3 行的最小改动，不属本轮阻塞项）。
