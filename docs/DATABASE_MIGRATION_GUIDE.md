# 数据库迁移与升级说明

> 适用版本：V0.3 RC
>
> 当前 migration：`v5`
>
> 当前迁移入口：`backend/app/migrations.py::apply_migrations()`
>
> 最后更新：2026-09-23

## 1. 目标与边界

本说明覆盖：

- 全新数据库初始化；
- 旧版本数据库升级；
- migration 幂等验证；
- migration 失败处理；
- 升级操作 SOP；
- 回滚操作 SOP。

当前没有自动 down migration。回滚数据库依赖升级前整库 backup 和停服 restore，而不是逆向执行 SQL。

## 2. 数据库路径

实际数据库路径按以下优先级决定：

```text
PINGPONG_DB_PATH
>
DEMO_DB_PATH（兼容旧变量，主要用于测试）
>
backend/data/demo.db
```

注意：

- 生产部署优先使用 `PINGPONG_DB_PATH`；
- 启动前必须确认实际路径，避免误升级另一套数据库；
- 路径变更不会自动移动已有数据库文件；
- migration 前应先生成对应实际数据库的整库 backup。

PowerShell 示例：

```powershell
$env:PINGPONG_DB_PATH = 'D:\pingpong\data\demo.db'
```

## 3. 当前 migration 链

```text
v1  master baseline
v2  auth_users_and_admins
v3  bootstrap_state_and_user_profile
v4  tournament_format_config
v5  registration_organization_venue
```

规则：

- 每个版本按整数顺序执行；
- 每个版本独立事务；
- 成功后写入 `schema_migrations`；
- 已应用版本不会重复执行；
- 每个版本执行后检查 `PRAGMA foreign_key_check`；
- 新库和旧库最终都应停在 v5；
- v1-v5 不得重写、合并或回退修改。

## 4. 执行时机

后端通过 FastAPI lifespan 在启动时调用：

```python
init_db()
```

`init_db()` 负责：

1. 创建缺失的基线表；
2. 兼容升级旧表的必要列和 CHECK；
3. 创建当前表；
4. 执行 `apply_migrations()`；
5. 提交事务。

因此，正常情况下只需用正确程序和正确 DB path 启动后端，数据库会自动迁移。不要把直接修改数据库结构作为常规升级方式。

## 5. 全新数据库初始化

### 5.1 验证步骤

1. 确保目标路径不存在旧数据库；
2. 设置 `PINGPONG_DB_PATH`；
3. 启动后端一次；
4. 检查健康状态和数据库结构。

```powershell
cd backend
$env:PINGPONG_DB_PATH = 'D:\pingpong\data\demo.db'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```text
GET /api/health
预期：{"status":"ok"}
```

### 5.2 预期结果

```text
schema_migrations = 1, 2, 3, 4, 5
table count = 22
REQUIRED_TABLES missing = 0
PRAGMA integrity_check = ok
PRAGMA foreign_key_check = 0 violations
```

如需只检查 migration，可使用 Python：

```powershell
cd backend
python -c "import sqlite3; c=sqlite3.connect(r'D:\pingpong\data\demo.db'); print(c.execute('select version,name from schema_migrations order by version').fetchall()); c.close()"
```

## 6. 旧数据库升级

### 6.1 支持路径

当前自动升级路径覆盖：

```text
v2 -> v5
v3 -> v5
v4 -> v5
v5 -> v5（no-op）
```

旧库可能没有完整 `schema_migrations`。首次接入时，初始化逻辑先登记 v1 作为 master baseline，再按顺序执行 v2-v5。

### 6.2 升级前必须执行

1. 停止服务；
2. 确认实际 DB path；
3. 执行整库 backup；
4. 保存 backup 路径和文件校验信息；
5. 再更新程序文件并启动。

```powershell
cd backend
python backup_db.py --database D:\pingpong\data\demo.db --backup-dir D:\pingpong\backups
```

成功输出至少应包含：

```text
备份成功
integrity_check：ok
foreign_key_check：0 条违规
schema_migrations：2/3/4/5（以源库实际版本为准）
```

legacy v2/v3/v4 数据库执行升级前备份时，CLI 输出源库自身版本；生成的快照经当前 `restore_db.py` 恢复时会先迁移到 v5。

### 6.3 升级后验证

1. 健康检查返回 200；
2. `schema_migrations` 最大版本为 5；
3. 历史用户和登录状态可读取；
4. 历史赛事、报名、比赛、比分和审计可读取；
5. Organization / Venue 数据可读取；
6. 登录后打开历史赛事并执行只读 smoke；
7. 后端日志无 migration 异常。

## 7. 幂等要求

以下操作可以重复执行：

```text
init_db()
init_db()
init_db()
```

预期：

- Schema 不漂移；
- `schema_migrations` 不重复插入；
- `system_state` 不重复；
- Organization / Venue 不重复；
- 索引不因重复创建报错；
- 已有 Tournament 不被自动改写。

如果重复启动导致表、行或索引变化，应视为发布阻断，在修复前不得继续升级生产库。

## 8. migration 失败处理

migration 按版本独立事务执行。失败时：

- 当前版本回滚；
- 后端启动失败；
- 不应让用户继续操作半升级数据库；
- 不应手工删除 `schema_migrations` 行伪造成功；
- 不应直接改 v5 SQL 来补历史库；
- 应保留现场日志和数据库副本，定位失败版本。

恢复步骤：

1. 停止服务；
2. 确认没有 Python / Uvicorn 进程占用数据库；
3. 选择升级前 backup；
4. 使用 `restore_db.py --service-stopped` 恢复；
5. 验证 integrity、FK 和 migration 版本；
6. 使用与原 backup 兼容的程序版本启动。

## 9. 升级操作 SOP

```text
1. 停止旧版本服务
2. 确认实际数据库路径
3. 执行 backup_db.py
4. 记录备份路径和成功校验结果
5. 更新程序文件
6. 启动一次后端，执行 init_db / migration
7. 检查 /api/health
8. 检查 schema_migrations
9. 验证管理员登录
10. 打开一个历史赛事
11. 检查报名、比赛、排名、比分和 audit
12. 如异常，立即停服并进入 rollback SOP
```

## 10. 回滚操作 SOP

如果新版本启动后出现 P0：

```text
1. 停止新版本服务
2. 保留故障数据库，不要覆盖证据
3. 选择升级前 backup
4. 执行 restore_db.py ... --service-stopped
5. 验证 integrity_check / foreign_key_check / schema_migrations
6. 使用原版本程序启动
7. 做登录、历史赛事和关键业务 smoke
```

命令：

```powershell
cd backend
python restore_db.py `
  D:\pingpong\backups\pingpong-backup-20260923-180000.db `
  --database D:\pingpong\data\demo.db `
  --backup-dir D:\pingpong\backups `
  --service-stopped
```

重要边界：

- 如果数据库已被未来 v6 等 migration 升级，不能只回退代码；
- 必须使用升级前备份恢复数据库；
- restore 不提供在线热恢复；
- restore 会恢复整库，包括 session 数据。

## 11. 验证记录

当前 D7A 验证基线：

```text
v1-v5 clean install：通过
v2/v3/v4/v5 旧库路径：通过
init_db 幂等：通过
migration / backup / restore 定向测试：40 passed，0 failed
backend full pytest：1027 passed、0 failed、0 skipped，退出码 0
```

如后续新增 v6，该记录必须重新执行，不能沿用 v5 的结果。

## 12. 完成标准

- `schema_migrations` 顺序和内容正确；
- 全新数据库与旧数据库都能到达当前版本；
- 重复启动不改变 Schema 和业务数据；
- `integrity_check = ok`；
- `foreign_key_check` 无违规；
- 升级前 backup 可恢复；
- 回滚后旧程序可启动并完成登录与历史赛事 smoke。
