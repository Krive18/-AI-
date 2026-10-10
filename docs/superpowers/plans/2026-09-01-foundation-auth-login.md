# 基础设施、登录认证与账号管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可运行、可测试的首阶段系统，使管理员能够安全初始化账号，员工能够通过独立登录页登录、首次改密，并按角色进入运营工作台或管理后台。

**Architecture:** 使用单仓库组织 Vue SPA 和 FastAPI 模块化单体，本地依赖直接连接现有 MySQL 与 Redis，不使用 Docker。认证采用 Redis 服务端会话、HttpOnly Cookie 和会话绑定 CSRF Token；账号与审计使用 MySQL，所有权限判断同时落在前端路由和后端依赖层。

**Tech Stack:** Node.js 24 LTS、Vue 3.5.42、Vite 8.2.2、TypeScript 6.0.3、Vue Router 5.3.0、Pinia 4.0.3、Tailwind CSS 4.3.3、Python 3.13、uv 0.12.8、FastAPI 0.141.1、Pydantic 2.13.5、SQLAlchemy 2.0.52、Alembic 1.19.1、MySQL 8.0.45、redis-py 8.1.0、pytest 9.1.1、Vitest 4.1.11、Playwright 1.62.1。本地 Redis Server 3.2.100 仅使用 RESP2 兼容模式，正式环境必须升级到 Redis 7.2+。

**Spec:** `docs/superpowers/specs/2026-09-01-ai-video-translation-platform-design.md`

## Global Constraints

- 系统只供公司内部使用；没有注册入口、套餐、订单、支付和第三方登录。
- 登录账号由管理员创建，首次登录必须修改临时密码。
- 角色仅有 `OPERATOR=1` 和 `ADMIN=9`；最后一个启用管理员不能被停用或降级。
- 浏览器认证只使用 `HttpOnly`、`SameSite=Lax` Cookie；生产必须设置 `Secure`，禁止把会话令牌写入 `localStorage`。
- 服务端会话空闲 8 小时失效，绝对有效期 24 小时；登出、停用和重置密码后撤销全部会话。
- 每个会话保存账号 `authVersion`；受保护请求同时校验账号启用状态与版本，使密码重置或停用即使遇到 Redis 清理失败也能立即失效。
- 所有写请求除登录外都校验 `X-CSRF-Token`；所有受保护资源都校验登录、角色和资源归属。
- 密码使用 Argon2id；登录名统一 `strip + casefold`，错误响应不泄露账号是否存在。
- MySQL 使用 InnoDB、`utf8mb4_0900_ai_ci`、`DATETIME(3)` UTC、逻辑外键和显式索引，不建立物理外键。
- 本地开发不使用 Docker；连接 `127.0.0.1:3306` 的 MySQL 8.0.45 和 `127.0.0.1:6379` 的 Redis 3.2.100。
- 本地 Redis 固定使用 RESP2；正式环境 Redis 必须为 7.2 或更高版本，且上线前必须通过真实集成、持久化、认证和故障恢复验证。
- API 使用 `/api/v1`、camelCase JSON 和统一错误对象；数据库错误与堆栈不得返回浏览器。
- 前端主色为橙色，禁止紫色 AI 模板风和无意义渐变；满足 WCAG 2.1 AA。
- 所有实现遵循 TDD：先观察目标测试失败，再写最小实现；不得删测试换取通过。

## Scope Split

总规格包含多个可独立验收的子系统，本计划只覆盖第一个纵向切片。完成后按顺序创建并执行以下独立计划：

1. 视频项目、分片上传、工作台记录与状态机。
2. 豆包 ASR、豆包文本翻译、MiniMax TTS 与 FFmpeg Worker。
3. 供应商版本、API 切换、费用账本、日志中心与管理看板。
4. 生产部署、安全加固、监控告警、备份恢复与灰度上线。

## File Map

```text
/
  .editorconfig                 # 跨语言编辑规则
  .gitattributes                # 统一仓库行尾
  .gitignore                    # Python、Node、IDE 与密钥忽略
  .env.example                  # 无秘密的本地配置模板
  scripts/check_repository.ps1 # 静态仓库和依赖锁检查
  scripts/check_local_services.ps1 # 原生 MySQL、Redis TCP 连通性检查
  README.md                     # 启动、验证与首个管理员流程

backend/
  pyproject.toml                # Python 包与质量工具配置
  uv.lock                       # Python 直接、传递与构建依赖锁文件
  alembic.ini
  migrations/
    env.py
    versions/0001_accounts_and_audit.py
  app/
    __init__.py
    main.py                     # FastAPI 应用工厂
    cli.py                      # 受控首个管理员命令
    api/v1/router.py
    core/
      config.py                 # 环境配置及生产安全校验
      database.py               # 异步 SQLAlchemy 生命周期
      errors.py                 # 领域错误与统一响应
      logging.py                # requestId 与结构化日志
      redis.py                  # Redis 生命周期
      security.py               # Argon2id、临时密码、登录名归一化
    modules/
      account/
        model.py
        repository.py
        schemas.py
        service.py
        routes.py
      auth/
        schemas.py
        sessions.py
        service.py
        dependencies.py
        routes.py
      audit/
        model.py
        repository.py
  tests/
    conftest.py
    unit/
    integration/

frontend/
  package.json
  package-lock.json
  vite.config.ts
  tsconfig.json
  eslint.config.js
  index.html
  src/
    main.ts
    App.vue
    styles/main.css
    api/client.ts
    api/contracts.ts
    router/index.ts
    stores/auth.ts
    components/ui/
      AppButton.vue
      AppField.vue
      AppCard.vue
      StatusMessage.vue
    layouts/
      AuthLayout.vue
      WorkbenchLayout.vue
      AdminLayout.vue
    modules/
      auth/pages/LoginPage.vue
      auth/pages/ChangePasswordPage.vue
      workbench/pages/WorkbenchEntryPage.vue
      admin/pages/AdminDashboardPage.vue
      admin/pages/AccountListPage.vue
  tests/
  e2e/
```

---

### Task 1: Repository Toolchain and Local Dependencies

**Files:**
- Create: `.editorconfig`
- Create: `.gitattributes`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `scripts/check_repository.ps1`
- Create: `scripts/check_local_services.ps1`
- Create: `backend/pyproject.toml`
- Create: `backend/uv.lock`
- Create: `frontend/package.json`

**Interfaces:**
- Consumes: 原生 MySQL 8.0.45、原生 Redis 3.2.100、Python 3.13、Node.js 24。
- Produces: MySQL on `127.0.0.1:3306`, Redis on `127.0.0.1:6379`, reproducible Python and npm dependency manifests, independent repository and local-service checks.

- [ ] **Step 1: Write the repository contract check**

Create `scripts/check_repository.ps1` with explicit checks:

```powershell
$ErrorActionPreference = 'Stop'
py -3.13 -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('backend/pyproject.toml').read_text('utf-8'))"
if ($LASTEXITCODE -ne 0) { throw "Python manifest check failed with exit code $LASTEXITCODE" }
py -3.13 -m uv lock --project backend --check
if ($LASTEXITCODE -ne 0) { throw "Python lock check failed with exit code $LASTEXITCODE" }
node -e "const p=require('./frontend/package.json'); if(!p.scripts?.build) process.exit(1)"
if ($LASTEXITCODE -ne 0) { throw "Node manifest check failed with exit code $LASTEXITCODE" }
```

Create `scripts/check_local_services.ps1` with parameterized TCP probes so failure behavior is testable without stopping local services:

```powershell
param(
    [string]$MySqlHostName = '127.0.0.1',
    [int]$MySqlPort = 3306,
    [string]$RedisHostName = '127.0.0.1',
    [int]$RedisPort = 6379,
    [int]$TimeoutMilliseconds = 1500
)

$ErrorActionPreference = 'Stop'

function Assert-TcpEndpoint {
    param([string]$Name, [string]$HostName, [int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connected = $client.ConnectAsync($HostName, $Port).Wait($TimeoutMilliseconds)
        if (-not $connected -or -not $client.Connected) {
            throw "$Name is unavailable at ${HostName}:${Port}"
        }
    }
    finally {
        $client.Dispose()
    }
}

Assert-TcpEndpoint -Name 'MySQL' -HostName $MySqlHostName -Port $MySqlPort
Assert-TcpEndpoint -Name 'Redis' -HostName $RedisHostName -Port $RedisPort
```

- [ ] **Step 2: Run the check and verify it fails**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_repository.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_local_services.ps1 -MySqlPort 1 -RedisPort 1
```

Expected: the repository check FAILs because package manifests do not exist; the local-service check FAILs because the controlled ports are unavailable.

- [ ] **Step 3: Create deterministic manifests and infrastructure**

Pin backend runtime dependencies to:

```toml
dependencies = [
  "fastapi==0.141.1",
  "uvicorn==0.52.4",
  "pydantic==2.13.5",
  "pydantic-settings==2.11.0",
  "sqlalchemy==2.0.52",
  "alembic==1.19.1",
  "asyncmy==0.2.14",
  "redis==8.1.0",
  "argon2-cffi==25.1.0",
  "python-ulid==4.0.1",
]
```

Pin backend development dependencies to `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `httpx==0.28.1`, `ruff==0.16.5` and `mypy==2.3.1`.

Pin the PEP 517 build requirement to `setuptools==84.0.0`. Generate `backend/uv.lock` with `uv==0.12.8`; the lockfile must remain current under `uv lock --check`, and environment installation must use `uv sync --extra dev --locked`.

Pin frontend runtime dependencies to `vue@3.5.42`, `vue-router@5.3.0`, `pinia@4.0.3`, `reka-ui@2.10.4` and `@lucide/vue@1.38.0`. Pin development dependencies to `vite@8.2.2`, `typescript@6.0.3`, `@vitejs/plugin-vue@6.0.8`, `tailwindcss@4.3.3`, `@tailwindcss/vite@4.3.3`, `vitest@4.1.11`, `@vue/test-utils@2.5.0`, `jsdom@30.0.1`, `vue-tsc@3.3.11`, `eslint@10.9.1`, `eslint-plugin-vue@10.10.0`, `typescript-eslint@8.69.0`, `prettier@3.9.6`, `@playwright/test@1.62.1` and `@axe-core/playwright@4.13.0`. TypeScript 6.0.3 is the newest stable release satisfying typescript-eslint 8.69.0's `>=4.8.4 <6.1.0` peer range; do not bypass peer checks with `--legacy-peer-deps`. `lucide-vue-next@1.0.0` is deprecated by its publisher in favor of the scoped `@lucide/vue` package and must not be installed.

`.env.example` contains only local non-production values and documents `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `REDIS_PROTOCOL=2`, `SESSION_COOKIE_SECURE`, `SESSION_HASH_KEY` and `ALLOWED_ORIGINS`. It must not contain any production secret. `REDIS_PROTOCOL=2` is a local compatibility setting only; production validation rejects it.

- [ ] **Step 4: Install and validate**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_local_services.ps1
py -3.13 -m pip install uv==0.12.8
py -3.13 -m uv sync --project backend --python 3.13 --extra dev --locked
Set-Location frontend
npm install
Set-Location ..
powershell -ExecutionPolicy Bypass -File scripts/check_repository.ps1
```

Expected: native MySQL and Redis TCP probes pass, the Python 3.13 environment is synchronized exactly from `uv.lock`, `package-lock.json` is created, and the repository check exits 0.

- [ ] **Step 5: Commit**

```bash
git add .editorconfig .gitattributes .gitignore .env.example scripts backend/pyproject.toml backend/uv.lock frontend/package.json frontend/package-lock.json
git commit -m "chore: establish project toolchain"
```

### Task 2: FastAPI Core, Configuration, Errors, and Health

**Files:**
- Modify: `.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/v1/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/v1/router.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/core/redis.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_config.py`
- Create: `backend/tests/integration/test_health.py`

**Interfaces:**
- Consumes: environment variables defined in `.env.example`.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`, `DatabaseManager.ping()`, `RedisManager.ping()`, `GET /api/v1/health/live` and `GET /api/v1/health/ready`, unified `AppError` responses.

- [ ] **Step 1: Write failing configuration and health tests**

```python
def valid_production_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        "redis_url": "redis://127.0.0.1:6379/0",
        "redis_protocol": 3,
        "session_cookie_name": "__Host-ai_translation_session",
        "session_cookie_secure": True,
        "session_hash_key": "a-test-key-that-is-at-least-32-bytes-long",
        "allowed_origins": ["https://translation.example.test"],
    }
    values.update(overrides)
    return values

def test_production_rejects_insecure_cookie():
    with pytest.raises(ValueError, match="secure cookie"):
        Settings(**valid_production_values(session_cookie_secure=False))

def test_production_rejects_local_redis_protocol():
    with pytest.raises(ValueError, match="RESP3"):
        Settings(**valid_production_values(redis_protocol=2))

def test_local_accepts_resp2_for_legacy_redis():
    settings = Settings(
        app_env="local",
        database_url="mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        redis_url="redis://127.0.0.1:6379/0",
        redis_protocol=2,
        session_hash_key="local-test-session-key",
    )
    assert settings.redis_protocol == 2

async def test_liveness_returns_request_id(client):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-Id"]

async def test_readiness_reports_dependency_failure(client, database_manager):
    database_manager.ping.side_effect = RuntimeError("database unavailable")
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert "database unavailable" not in response.text
```

- [ ] **Step 2: Run tests and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_config.py backend/tests/integration/test_health.py -v`
Expected: FAIL because `Settings` and `create_app` are undefined.

- [ ] **Step 3: Implement the application core**

Define:

```python
class Settings(BaseSettings):
    app_env: Literal["local", "test", "production"] = "local"
    app_name: str = "LinguaSphere API"
    api_prefix: str = "/api/v1"
    database_url: str
    redis_url: str
    redis_protocol: Literal[2, 3] = 3
    session_cookie_name: str = "ai_translation_session"
    session_cookie_secure: bool = False
    session_hash_key: SecretStr
    allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production":
            if not self.session_cookie_secure:
                raise ValueError("production requires a secure cookie")
            if self.session_cookie_name != "__Host-ai_translation_session":
                raise ValueError("production requires the __Host- cookie name")
            if not self.allowed_origins or "*" in self.allowed_origins:
                raise ValueError("production requires explicit origins")
            if len(self.session_hash_key.get_secret_value().encode()) < 32:
                raise ValueError("session hash key must contain at least 32 bytes")
            if self.redis_protocol != 3:
                raise ValueError("production requires RESP3 and Redis 7.2+")
        return self
```

The validator rejects production when cookies are insecure, the cookie name is not `__Host-ai_translation_session`, origins are empty, an origin is `*`, the session hash key has fewer than 32 bytes, or Redis protocol is not 3. Local HTTP uses the unprefixed `ai_translation_session` cookie because browsers require every `__Host-` cookie to be Secure. `create_app` installs request ID middleware, CORS with explicit origins, unified handlers for `AppError` and validation errors, and the v1 router. Implement minimal database and Redis connection managers with lifecycle close methods and injectable `ping` methods; `RedisManager` passes `protocol=settings.redis_protocol` to redis-py so the local instance uses RESP2. Later tasks extend these same files. Readiness returns 503 when either injected manager ping fails; liveness does not depend on external services.

`Settings` uses `SettingsConfigDict(env_file=".env", extra="ignore")`. Change `ALLOWED_ORIGINS` in `.env.example` to the one-line JSON array `["http://127.0.0.1:5173","http://localhost:5173"]` so pydantic-settings parses it as `list[str]`. Package `__init__.py` files must remain empty. `backend/tests/conftest.py` supplies valid test settings, app/client fixtures, and injected database/Redis managers without contacting real services. Tests assert the exact unified error envelope from the specification and never assert on mock existence or framework internals.

- [ ] **Step 4: Run tests and quality checks**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_config.py backend/tests/integration/test_health.py -v
backend/.venv/Scripts/python.exe -m ruff check backend
Push-Location backend
.venv/Scripts/python.exe -m mypy app
Pop-Location
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 5: Commit**

```bash
git add .env.example backend/app backend/tests
git commit -m "feat: add FastAPI application core"
```

### Task 3: MySQL Account and Audit Schema

**Files:**
- Modify: `backend/app/core/database.py`
- Create: `backend/app/modules/account/model.py`
- Create: `backend/app/modules/audit/model.py`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_accounts_and_audit.py`
- Create: `backend/tests/integration/test_account_migration.py`

**Interfaces:**
- Consumes: `DatabaseManager` and its engine lifecycle from Task 2.
- Produces: `Base`, `get_session() -> AsyncIterator[AsyncSession]`, `UserAccount` and append-only `AuditLog` models.
- Database constants: `Role.OPERATOR=1`, `Role.ADMIN=9`, `AccountStatus.ACTIVE=1`, `AccountStatus.DISABLED=2`.

- [ ] **Step 1: Write the migration contract test**

```python
async def test_account_schema_has_required_constraints(db_connection):
    indexes = await read_indexes(db_connection, "user_account")
    assert "uk_user_account_login_name" in indexes
    assert "uk_user_account_public_id" in indexes
    assert "idx_user_account_status_created_at" in indexes
    foreign_keys = await read_foreign_keys(db_connection, "user_account")
    assert foreign_keys == []
```

Also assert both tables use InnoDB, `utf8mb4_0900_ai_ci`, `DATETIME(3)` columns and comments.

- [ ] **Step 2: Run the migration test and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_account_migration.py -v`
Expected: FAIL because the migration and tables do not exist.

- [ ] **Step 3: Implement the first migration**

Create `user_account` with:

```text
id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY
public_id CHAR(26) NOT NULL
login_name VARCHAR(64) NOT NULL
display_name VARCHAR(64) NOT NULL
role TINYINT UNSIGNED NOT NULL
status TINYINT UNSIGNED NOT NULL
password_hash VARCHAR(255) NOT NULL
must_change_password BOOLEAN NOT NULL DEFAULT TRUE
password_changed_at DATETIME(3) NULL
last_login_at DATETIME(3) NULL
created_by BIGINT UNSIGNED NULL
auth_version INT UNSIGNED NOT NULL DEFAULT 1
version INT UNSIGNED NOT NULL DEFAULT 1
created_at DATETIME(3) NOT NULL
updated_at DATETIME(3) NOT NULL
```

Create `audit_log` with actor ID, action, resource type/public ID, request ID, IPv4/IPv6 `VARBINARY(16)`, before/after JSON and `created_at DATETIME(3)`. Use logical relation indexes but no physical foreign keys. Add database permissions/documentation so the application has no update or delete code path for audit rows.

- [ ] **Step 4: Apply migration and verify**

Run:

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_account_migration.py -v
```

Expected: migration succeeds from an empty database and the contract test PASSes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/database.py backend/app/modules/account backend/app/modules/audit backend/migrations backend/alembic.ini backend/tests/integration/test_account_migration.py
git commit -m "feat: add account and audit schema"
```

### Task 4: Password Security and Account Repository

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/app/modules/account/repository.py`
- Create: `backend/app/modules/account/schemas.py`
- Create: `backend/tests/unit/test_security.py`
- Create: `backend/tests/integration/test_account_repository.py`

**Interfaces:**
- Produces: `normalize_login_name(value: str) -> str`, `hash_password(value: str) -> str`, `verify_password(value: str, encoded: str) -> bool`, `generate_temporary_password() -> str`.
- Produces repository methods `get_by_login_name`, `get_by_public_id`, `create`, `list_page`, `save` and `count_active_admins_for_update`.

- [ ] **Step 1: Write failing security tests**

```python
def test_login_name_is_trimmed_and_casefolded():
    assert normalize_login_name("  Alice.OP  ") == "alice.op"

def test_argon2id_hash_is_not_plaintext():
    encoded = hash_password("Correct-Horse-9!")
    assert encoded.startswith("$argon2id$")
    assert verify_password("Correct-Horse-9!", encoded)
    assert not verify_password("wrong-password", encoded)

def test_temporary_password_has_required_classes():
    value = generate_temporary_password()
    assert len(value) >= 20
    assert any(ch.islower() for ch in value)
    assert any(ch.isupper() for ch in value)
    assert any(ch.isdigit() for ch in value)
```

Repository tests prove normalized login uniqueness, explicit-column pagination and compare-and-swap update through `version`.

- [ ] **Step 2: Run tests and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_security.py backend/tests/integration/test_account_repository.py -v`
Expected: FAIL because the security and repository functions do not exist.

- [ ] **Step 3: Implement security primitives and repository**

Use `argon2.PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)`. Generate passwords with `secrets.choice` from letters, digits and a conservative symbol set; enforce 20 characters and shuffle with `secrets.SystemRandom`.

Repository queries must enumerate selected columns and order cursor pages by `id DESC`. `count_active_admins_for_update` must execute `SELECT id FROM user_account WHERE role = 9 AND status = 1 FOR UPDATE` inside the caller transaction so two concurrent role changes cannot remove the final active administrator.

- [ ] **Step 4: Run tests**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_security.py backend/tests/integration/test_account_repository.py -v
backend/.venv/Scripts/python.exe -m ruff check backend
Push-Location backend
.venv/Scripts/python.exe -m mypy app
Pop-Location
```

Expected: tests PASS; quality checks exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/security.py backend/app/modules/account backend/tests
git commit -m "feat: add secure account persistence"
```

### Task 5: Redis Session Store and Login Rate Limiting

**Files:**
- Modify: `backend/app/core/redis.py`
- Create: `backend/app/modules/auth/sessions.py`
- Create: `backend/app/modules/auth/service.py`
- Create: `backend/app/modules/auth/schemas.py`
- Create: `backend/tests/unit/test_sessions.py`
- Create: `backend/tests/integration/test_auth_service.py`

**Interfaces:**
- Consumes: `RedisManager` and its client lifecycle from Task 2.
- Produces `SessionData(account_id: int, auth_version: int, csrf_token: str, created_at: datetime, absolute_expires_at: datetime)`.
- Produces `SessionStore.create`, `get_and_touch`, `revoke` and `revoke_account`.
- Produces `AuthService.login(login_name, password, ip_address) -> LoginResult`, `change_password` and `logout`.

- [ ] **Step 1: Write failing session tests**

```python
async def test_session_touch_never_exceeds_absolute_expiry(clock, session_store):
    token, session = await session_store.create(account_id=17)
    clock.advance(hours=23, minutes=30)
    loaded = await session_store.get_and_touch(token)
    assert loaded is not None
    assert await session_store.ttl(token) <= 30 * 60

async def test_fifth_failed_login_blocks_for_fifteen_minutes(auth_service):
    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            await auth_service.login("operator", "wrong", "127.0.0.1")
    with pytest.raises(LoginTemporarilyLocked):
        await auth_service.login("operator", "correct", "127.0.0.1")
```

Also test that Redis keys use SHA-256/HMAC digests instead of raw session tokens or raw login names.

- [ ] **Step 2: Run tests and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_sessions.py backend/tests/integration/test_auth_service.py -v`
Expected: FAIL because the session store and auth service do not exist.

- [ ] **Step 3: Implement opaque server-side sessions**

Generate a 32-byte token with `secrets.token_urlsafe(32)`. Store only a keyed HMAC digest in `session:{digest}` and index active session digests under `account-sessions:{accountId}`. Store the CSRF token only in the Redis session JSON and authenticated API response; never put it in the HttpOnly Cookie.

On login:

1. Normalize login name.
2. Increment `login-limit:{sha256(normalizedLogin)}` with a 15-minute TTL.
3. Fetch account and always run one Argon2 verification, using a fixed dummy hash for missing accounts.
4. Return the same `INVALID_CREDENTIALS` response for missing account, bad password and disabled account.
5. Create the session with the account's current `auth_version`, update last login, clear the rate limit and write an audit event after success.

- [ ] **Step 4: Run tests and Redis integration check**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_sessions.py backend/tests/integration/test_auth_service.py -v
powershell -ExecutionPolicy Bypass -File scripts/check_local_services.ps1
```

Expected: all tests PASS and Redis returns `PONG`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/redis.py backend/app/modules/auth backend/tests
git commit -m "feat: add server-side authentication sessions"
```

### Task 6: Auth HTTP API, CSRF, and Bootstrap Administrator

**Files:**
- Create: `backend/app/modules/auth/dependencies.py`
- Create: `backend/app/modules/auth/routes.py`
- Create: `backend/app/cli.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_auth_api.py`
- Create: `backend/tests/integration/test_create_admin_cli.py`

**Interfaces:**
- Produces endpoints `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` and `POST /auth/password`.
- Produces dependencies `require_account`, `require_admin` and `require_csrf`.
- Produces command `python -m app.cli create-admin` with interactive login name, display name and hidden password prompts.

- [ ] **Step 1: Write failing HTTP and CLI tests**

```python
async def test_login_sets_http_only_cookie_and_returns_csrf(client, active_operator):
    response = await client.post("/api/v1/auth/login", json={
        "loginName": active_operator.login_name,
        "password": "Correct-Horse-9!"
    })
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.json()["csrfToken"]
    assert response.json()["account"]["mustChangePassword"] is True

async def test_password_change_rejects_missing_csrf(authenticated_client):
    response = await authenticated_client.post("/api/v1/auth/password", json={
        "currentPassword": "Correct-Horse-9!",
        "newPassword": "New-Correct-Horse-10!"
    })
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"
```

CLI tests invoke the command runner twice and prove the first invocation creates an admin while a duplicate login fails without printing either password.

- [ ] **Step 2: Run tests and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_auth_api.py backend/tests/integration/test_create_admin_cli.py -v`
Expected: FAIL with missing routes and CLI command.

- [ ] **Step 3: Implement routes, dependencies, and CLI**

Set the session cookie with `HttpOnly`, `SameSite=Lax`, `Path=/`, configured `Secure` and no `Domain`. Add `Cache-Control: no-store` to every auth response. `GET /auth/me` returns current account plus the current session's CSRF token. `require_account` loads the account, rejects disabled status or mismatched `auth_version`, and lazily deletes an invalid Redis session. Mutation dependencies compare `X-CSRF-Token` using `secrets.compare_digest`.

When `must_change_password` is true, all protected business endpoints except `/auth/me`, `/auth/password` and `/auth/logout` return:

```json
{
  "error": {
    "code": "PASSWORD_CHANGE_REQUIRED",
    "message": "请先修改临时密码",
    "requestId": "generated-request-id",
    "details": {}
  }
}
```

The CLI uses `getpass.getpass`, rejects weak passwords, opens a short transaction, and writes `BOOTSTRAP_ADMIN_CREATED` to the audit table with a null actor.

- [ ] **Step 4: Verify auth behavior**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_auth_api.py backend/tests/integration/test_create_admin_cli.py -v
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```

Expected: all auth and full backend tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: expose secure authentication API"
```

### Task 7: Administrator Account Lifecycle API

**Files:**
- Create: `backend/app/modules/account/service.py`
- Create: `backend/app/modules/account/routes.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/tests/integration/test_admin_accounts_api.py`

**Interfaces:**
- Produces `GET /admin/accounts`, `POST /admin/accounts`, `PATCH /admin/accounts/:accountId`, `POST /admin/accounts/:accountId/reset-password` and `POST /admin/accounts/:accountId/sessions/revoke`.
- Create/reset responses return `temporaryPassword` exactly once and set `Cache-Control: no-store`.

- [ ] **Step 1: Write failing account lifecycle tests**

```python
async def test_operator_cannot_list_accounts(operator_client):
    response = await operator_client.get("/api/v1/admin/accounts")
    assert response.status_code == 403

async def test_last_active_admin_cannot_be_disabled(admin_client, sole_admin):
    response = await admin_client.patch(
        f"/api/v1/admin/accounts/{sole_admin.public_id}",
        headers={"X-CSRF-Token": admin_client.csrf_token},
        json={"status": 2, "version": sole_admin.version},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"

async def test_reset_password_revokes_all_sessions(admin_client, operator):
    response = await reset_password(admin_client, operator.public_id)
    assert response.status_code == 200
    assert len(response.json()["temporaryPassword"]) >= 20
    assert await active_session_count(operator.id) == 0
```

Also test duplicate login, cursor pagination, stale `version` conflict, self-disable protection, audit before/after values and disabled-account login rejection.

- [ ] **Step 2: Run tests and verify failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_admin_accounts_api.py -v`
Expected: FAIL because the admin account routes do not exist.

- [ ] **Step 3: Implement account lifecycle services**

Use one short transaction for each mutation:

1. Lock the target account.
2. Validate optimistic `version`.
3. When disabling or demoting an admin, lock/count active admins and reject the final one.
4. Update explicit fields and increment `version`; password reset, disable and role-sensitive security changes also increment `auth_version`.
5. Append an audit row with masked before/after JSON.
6. Commit.
7. Revoke sessions after commit. If Redis cleanup fails, emit a high-severity structured log; the committed `auth_version` or disabled status still makes old sessions fail on their next request.

Creation and reset generate the temporary password server-side, store only its Argon2id hash and return the plaintext once. Never include password fields in audit JSON or logs.

- [ ] **Step 4: Run account and full backend tests**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_admin_accounts_api.py -v
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe -m ruff check backend
Push-Location backend
.venv/Scripts/python.exe -m mypy app
Pop-Location
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/account backend/app/api/v1/router.py backend/tests
git commit -m "feat: add administrator account management"
```

### Task 8: Vue Foundation, Design Tokens, and Route Protection

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/eslint.config.js`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/styles/main.css`
- Create: `frontend/src/api/contracts.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/tests/router.test.ts`

**Interfaces:**
- Produces `apiRequest<T>(path, init) -> Promise<T>` and `useAuthStore()`.
- Auth store methods: `bootstrap()`, `login(credentials)`, `changePassword(payload)` and `logout()`.
- Route meta fields: `requiresAuth`, `requiresAdmin` and `allowsTemporaryPassword`.
- Produces temporary semantic route-shell components inside `router/index.ts` so every registered route builds before Task 9 supplies the final pages.

- [ ] **Step 1: Write failing route-guard tests**

```typescript
it('redirects anonymous users to login with a safe return path', async () => {
  auth.account = null
  await router.push('/workbench/new')
  expect(router.currentRoute.value.fullPath).toBe('/login?redirect=/workbench/new')
})

it('forces temporary-password accounts to change password', async () => {
  auth.account = operator({ mustChangePassword: true })
  await router.push('/workbench/new')
  expect(router.currentRoute.value.path).toBe('/change-password')
})

it('blocks operators from administrator routes', async () => {
  auth.account = operator({ mustChangePassword: false })
  await router.push('/admin/accounts')
  expect(router.currentRoute.value.name).toBe('forbidden')
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run frontend/tests/router.test.ts`
Expected: FAIL because the app, auth store and router do not exist.

- [ ] **Step 3: Implement the SPA foundation**

`apiRequest` uses same-origin `/api/v1`, `credentials: 'include'`, JSON content type and the in-memory CSRF token for non-GET requests. It maps the unified API error into:

```typescript
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    requestId: string
    details: Record<string, unknown>
  }
}
```

On 401 it clears account state and redirects to login without creating a loop. Do not persist the account, CSRF token or session token in browser storage. Until Task 9 is complete, each route uses a small local `RouteShell` component with a semantic heading; this keeps Task 8 independently buildable without pretending that the final UI already exists.

Define CSS variables for orange primary, neutral surfaces, blue processing, emerald success, amber warning and red error. Use visible focus rings, minimum 44px interactive height, 4.5:1 text contrast, standard Tailwind spacing and no arbitrary pixel utilities.

- [ ] **Step 4: Run frontend checks**

Run:

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run lint
npm --prefix frontend run build
```

Expected: route tests PASS and all quality commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: establish Vue application shell"
```

### Task 9: Login, Forced Password Change, and Protected Layouts

**Files:**
- Create: `frontend/src/components/ui/AppButton.vue`
- Create: `frontend/src/components/ui/AppField.vue`
- Create: `frontend/src/components/ui/AppCard.vue`
- Create: `frontend/src/components/ui/StatusMessage.vue`
- Create: `frontend/src/layouts/AuthLayout.vue`
- Create: `frontend/src/layouts/WorkbenchLayout.vue`
- Create: `frontend/src/layouts/AdminLayout.vue`
- Create: `frontend/src/modules/auth/pages/LoginPage.vue`
- Create: `frontend/src/modules/auth/pages/ChangePasswordPage.vue`
- Create: `frontend/src/modules/workbench/pages/WorkbenchEntryPage.vue`
- Create: `frontend/src/modules/admin/pages/AdminDashboardPage.vue`
- Create: `frontend/src/modules/auth/pages/ForbiddenPage.vue`
- Modify: `frontend/src/router/index.ts`
- Create: `frontend/tests/LoginPage.test.ts`
- Create: `frontend/tests/ChangePasswordPage.test.ts`

**Interfaces:**
- Consumes auth store and route meta from Task 8.
- Produces accessible `/login`, `/change-password`, `/workbench/new` and `/admin/dashboard` pages.

- [ ] **Step 1: Write failing component tests**

```typescript
it('renders the internal login page without registration links', () => {
  const wrapper = mountLogin()
  expect(wrapper.get('h1').text()).toContain('寰语')
  expect(wrapper.text()).toContain('账号由管理员统一创建')
  expect(wrapper.find('a[href*="register"]').exists()).toBe(false)
  expect(wrapper.get('input[name="loginName"]').attributes('autocomplete')).toBe('username')
  expect(wrapper.get('input[name="password"]').attributes('autocomplete')).toBe('current-password')
})

it('prevents duplicate login submission', async () => {
  const deferred = createDeferred()
  auth.login.mockReturnValue(deferred.promise)
  await submitValidLogin()
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
})

it('announces invalid credentials without account enumeration', async () => {
  auth.login.mockRejectedValue(apiError('INVALID_CREDENTIALS', '用户名或密码错误'))
  await submitValidLogin()
  expect(wrapper.get('[aria-live="polite"]').text()).toBe('用户名或密码错误')
})
```

Password tests require current password, a 12+ character new password, confirmation equality, disabled repeat submission and redirect after success.

- [ ] **Step 2: Run tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run frontend/tests/LoginPage.test.ts frontend/tests/ChangePasswordPage.test.ts`
Expected: FAIL because components and pages do not exist.

- [ ] **Step 3: Implement the visual and interaction design**

Login page requirements:

- neutral light background with one centered card no wider than `max-w-md`;
- orange primary button, product name and “公司内部系统” badge;
- labeled username/password fields, keyboard-operable show-password button and visible focus;
- no registration, package or marketing copy;
- `aria-live="polite"` generic error region;
- submit disabled while loading;
- redirect administrators to `/admin/dashboard` and operators to `/workbench/new`, unless a validated same-origin redirect query is present;
- redirect temporary-password users only to `/change-password`.

Layouts provide skip links, responsive navigation, user menu and logout. Operator navigation never renders admin links. Replace every temporary `RouteShell` from Task 8 with the corresponding lazy-loaded page from this task, including the named `forbidden` route. The phase-one workbench entry page explains that the account is ready and presents the agreed eight target languages as read-only chips; it does not imitate a functioning upload form before the upload phase exists.

- [ ] **Step 4: Verify components, accessibility, and build**

Run:

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run lint
npm --prefix frontend run build
```

Expected: all component tests PASS and production build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat: add login and protected application layouts"
```

### Task 10: Administrator Account Management Page

**Files:**
- Create: `frontend/src/modules/admin/api/accounts.ts`
- Create: `frontend/src/modules/admin/pages/AccountListPage.vue`
- Create: `frontend/src/modules/admin/components/AccountDialog.vue`
- Create: `frontend/src/modules/admin/components/TemporaryPasswordDialog.vue`
- Create: `frontend/tests/AccountListPage.test.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/AdminLayout.vue`

**Interfaces:**
- Consumes administrator account API from Task 7 and `apiRequest` from Task 8.
- Produces typed methods `listAccounts(cursor, filters)`, `createAccount(input)`, `updateAccount(id, input)`, `resetPassword(id)` and `revokeSessions(id)`.

- [ ] **Step 1: Write failing account-page tests**

```typescript
it('lists accounts with text status in addition to color', async () => {
  mockAccounts([activeOperator()])
  const wrapper = await mountAccountList()
  expect(wrapper.text()).toContain('启用')
  expect(wrapper.text()).toContain('运营人员')
})

it('shows a generated temporary password exactly once', async () => {
  mockCreateAccount({ temporaryPassword: 'Generated-Password-9381' })
  await createValidOperator()
  expect(wrapper.get('[role="dialog"]').text()).toContain('Generated-Password-9381')
  await wrapper.get('[data-action="close-password"]').trigger('click')
  expect(wrapper.text()).not.toContain('Generated-Password-9381')
})

it('renders last-admin conflicts as an actionable message', async () => {
  mockUpdateFailure('LAST_ADMIN_REQUIRED')
  await disableAccount()
  expect(wrapper.get('[role="alert"]').text()).toContain('必须保留至少一个启用的管理员')
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run frontend/tests/AccountListPage.test.ts`
Expected: FAIL because the account management components do not exist.

- [ ] **Step 3: Implement account management**

Implement cursor pagination, login/status/role filters, create/edit dialog, reset-password action, revoke-session action and enable/disable controls. Use a confirmation dialog for disabling an account or changing an administrator role. The temporary password dialog:

- adds `Cache-Control` handling through the API;
- displays the plaintext only from the immediate response;
- provides an explicit copy button;
- clears the value from component state when closed;
- never writes it to URL, logs, Pinia persistence or browser storage.

Use optimistic `version` from the row. On `ACCOUNT_VERSION_CONFLICT`, reload the row and tell the administrator that another person changed it.

- [ ] **Step 4: Run frontend validation**

Run:

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run lint
npm --prefix frontend run build
```

Expected: all tests and quality checks exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/admin frontend/src/router frontend/src/layouts/AdminLayout.vue frontend/tests
git commit -m "feat: add internal account administration"
```

### Task 11: End-to-End Authentication Verification

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/auth.setup.ts`
- Create: `frontend/e2e/auth.spec.ts`
- Create: `backend/tests/security/test_auth_security.py`
- Modify: `README.md`

**Interfaces:**
- Consumes the running Vue, FastAPI, MySQL and Redis services.
- Produces repeatable browser and backend security gates for the phase-one acceptance criteria.

- [ ] **Step 1: Write failing E2E and security scenarios**

```typescript
test('operator changes temporary password and enters workbench', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(process.env.E2E_OPERATOR_LOGIN!)
  await page.getByLabel('密码').fill(process.env.E2E_OPERATOR_TEMP_PASSWORD!)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/change-password/)
  await changePassword(page, process.env.E2E_OPERATOR_TEMP_PASSWORD!, 'New-Secure-Password-2026!')
  await expect(page).toHaveURL(/workbench\/new/)
  await expect(page.getByText('账号已就绪')).toBeVisible()
})

test('operator cannot open administrator account page', async ({ page }) => {
  await loginAsOperator(page)
  await page.goto('/admin/accounts')
  await expect(page.getByRole('heading', { name: '无权限访问' })).toBeVisible()
})
```

Backend security tests cover session fixation, missing/incorrect CSRF, expired session, disabled account, password-reset session revocation, generic login error, five-attempt rate limit and last-admin concurrency.

- [ ] **Step 2: Run targeted tests and verify at least one failure**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/security/test_auth_security.py -v
npm --prefix frontend run test:e2e -- auth.spec.ts
```

Expected: FAIL until fixtures, seed command and complete server orchestration are wired.

- [ ] **Step 3: Complete test orchestration and operator documentation**

Add a test-only seed command guarded by `APP_ENV=test`; it must refuse to run in local or production environments. Configure Playwright `webServer` entries for FastAPI and Vite, use a dedicated `ai_translation_test` database and Redis database index, and reset only that named test database between runs.

Document exact commands in `README.md`:

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts/check_local_services.ps1
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe -m app.cli create-admin
backend/.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --app-dir backend --reload
npm --prefix frontend run dev
```

Also document that real API keys are not required for phase one and must never be written to `.env.example`.

- [ ] **Step 4: Run the complete phase-one gate**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe -m ruff check backend
Push-Location backend
.venv/Scripts/python.exe -m mypy app
Pop-Location
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run test:e2e
git diff --check
```

Expected: every command exits 0. Manually verify at 320, 768, 1024 and 1440 px that login, forced password change and account management remain usable with visible keyboard focus.

- [ ] **Step 5: Commit**

```bash
git add README.md backend/tests/security frontend/playwright.config.ts frontend/e2e
git commit -m "test: verify authentication vertical slice"
```

## Phase-One Definition of Done

- A configured development workstation can follow `README.md` to verify native MySQL、Redis and start FastAPI and Vue without Docker.
- The controlled CLI creates the first administrator without exposing the password in command history or logs.
- Administrator and operator accounts can log in through the dedicated login page.
- Temporary-password accounts cannot enter protected product pages until password change succeeds.
- Operators cannot access administrator APIs or routes.
- Administrators can create, edit, enable, disable, reset and revoke accounts without deleting records.
- The final enabled administrator cannot be disabled or demoted, including under concurrent requests.
- Login errors are generic, rate limited and auditable.
- Session Cookie, expiry, revocation and CSRF behavior match the approved specification.
- Unit, integration, security, E2E, lint, type-check and build gates all pass.
- No production secret, raw password, session token or database error appears in source, logs or browser storage.
