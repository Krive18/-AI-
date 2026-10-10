# 寰语部署上线指南

本文档描述把 LinguaSphere 部署到生产服务器的完整步骤。最小拓扑包含 API、Worker、MySQL 和 Redis；MySQL/Redis 可同机或独立部署，API 可直接托管前端静态页面。

## 1. 服务器准备

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows Server / Linux 均可（本项目不依赖 Docker） |
| Python | 3.13+ |
| Node.js | 20+（仅构建前端时需要，服务器上跑成品不需要） |
| MySQL | 8.0+ |
| Redis | **7.2+**（必须，生产强制 RESP3；本地开发的 Redis 3.x 不能用于生产） |
| FFmpeg | 与开发环境一致，需在 PATH 中 |

## 2. 数据库初始化

```bash
# 创建库（utf8mb4）
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS ai_translation DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

# 创建应用账号（参考 backend/migrations/sql 下的权限模板）
# 然后执行迁移
cd backend
alembic upgrade head
```

首次部署用 CLI 创建第一个管理员：

```bash
python -m app.cli create-admin
```

每次升级前先备份数据库和私有媒体目录，再执行 `alembic upgrade head`。不要通过手工改表跳过迁移。

## 3. 配置环境变量

```bash
cp backend/.env.example backend/.env
```

按 `backend/.env.example` 里的注释逐项修改。production 模式启动时会强制校验：

- `SESSION_COOKIE_NAME=__Host-ai_translation_session` 且 `SESSION_COOKIE_SECURE=true`（要求 HTTPS）
- `ADMIN_SESSION_COOKIE_NAME=__Host-ai_translation_admin_session`
- `ALLOWED_ORIGINS` 不允许 `*`；同域部署（配置了 `FRONTEND_DIST`）可留空，前后端分域部署时必须显式填写前端来源
- `SESSION_HASH_KEY` ≥ 32 字节随机串
- `PROVIDER_SECRET_ENCRYPTION_KEY` 为 base64 编码的 32 字节随机密钥
- `REDIS_PROTOCOL=3`（Redis 7.2+）

生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

## 4. 构建与启动

```bash
# 前端打包（在开发机或 CI 上执行，产物为 frontend/dist）
cd frontend && npm ci && npm run build

# 后端依赖（推荐 uv）
cd backend
uv sync --extra dev
```

Windows 启动命令：

```powershell
$env:FRONTEND_DIST = "../frontend/dist"
.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

# 在第二个常驻进程中
.venv\Scripts\python.exe -m app.worker
```

Linux 启动命令：

```bash
# 启动 API（托管前端页面 + 接口，默认 8000）
FRONTEND_DIST=../frontend/dist .venv/bin/python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

# 启动 Worker（翻译流水线，必须常驻）
.venv/bin/python -m app.worker
```

Windows 生产建议用 NSSM 或任务计划把两个进程注册为服务；Linux 用 systemd。

## 5. HTTPS 与域名

生产强制 `SESSION_COOKIE_SECURE=true`，必须有 HTTPS。常见做法是在前方使用 Nginx/IIS/Caddy 终止 TLS，再转发到 `127.0.0.1:8000`。不要让 8000 端口直接暴露到公网。

## 6. 上线检查单

- [ ] `alembic upgrade head` 已执行到最新
- [ ] `.env` 为 production 配置且通过启动校验（启动失败会明确提示哪项不合格）
- [ ] Redis 7.2+ 已启用认证、持久化
- [ ] `PRIVATE_STORAGE_ROOT` 指向的磁盘空间充足、目录不可公网访问
- [ ] 管理端 `/admin/login` 可登录，运营端 `/login` 可登录，两端同时在线互不影响
- [ ] 管理端「接口配置」中实际使用的能力已配置并通过连通性测试（当前最多 7 类）
- [ ] 上传一个短视频走完整翻译流程出片成功
- [ ] 验证成片没有中文原声，目标语言配音与画面基本同步，SRT 为目标语言
- [ ] 用非真人敏感素材分别验证图片生成和图生视频；确认内容审核策略符合业务场景
- [ ] Worker 并发数 `WORKER_MAX_CONCURRENCY` 按服务器规格调整（默认 2，上限 8）

## 7. 进程守护与观测

- Windows 可使用 NSSM 或任务计划分别守护 API 和 Worker；Linux 推荐 systemd。
- API 与 Worker 应输出到独立日志文件，并配置轮转、磁盘告警和进程存活监控。
- 重点监控任务失败率、供应商超时/限流、Worker 租约积压、Redis/MySQL 可用性和私有目录容量。
- 操作日志和供应商调用日志不得记录 API Key、Cookie、密码或完整个人素材。

## 8. 回滚

1. 停止接收新任务并等待正在执行的 Worker 任务结束，或在管理端明确取消。
2. 保存当前应用日志和数据库备份。
3. 回退应用版本；数据库迁移只有在对应迁移明确支持 downgrade 且已验证时才回退。
4. 恢复 API 与 Worker，先用管理员账号执行健康检查，再提交最小任务验证。

供应商字段和常见错误见 [供应商配置与故障排查](provider-configuration.md)。
