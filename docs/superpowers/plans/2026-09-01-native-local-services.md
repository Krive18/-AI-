# 原生本地依赖切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除项目的 Docker 运行依赖，改用本机 MySQL 8.0.45 和 Redis 3.2.100，同时把 Redis 7.2+ 固定为正式上线门槛。

**Architecture:** 静态仓库检查与机器服务检查分离。仓库检查只验证 Python/npm 清单与锁文件；本地服务脚本通过 TCP 探测原生 MySQL 和 Redis。应用本地配置显式使用 RESP2 连接旧 Redis，正式环境由主计划的配置校验和后续上线计划禁止使用该兼容模式。

**Tech Stack:** PowerShell 5.1+、Python 3.13、MySQL 8.0.45、Redis Server 3.2.100（本地 RESP2）、redis-py 8.1.0；无 Docker 依赖。

**Spec:** `docs/superpowers/specs/2026-09-01-native-local-services-design.md`

## Global Constraints

- 不调用 Docker，不保留 `compose.yaml` 作为项目启动入口。
- MySQL 本地地址为 `127.0.0.1:3306`；Redis 本地地址为 `127.0.0.1:6379`。
- 本地 `.env.example` 使用 `REDIS_PROTOCOL=2`；真实秘密只能写入被 Git 忽略的 `.env`。
- Redis 3.2.100 只用于本地开发；正式环境必须升级到 Redis 7.2+。
- 静态仓库检查不得依赖本机服务状态；本地服务检查必须在端口不可用时返回非零退出码。
- 不决定腾讯云服务器操作系统和部署拓扑。

---

### Task 1: Replace Docker With Native Local Service Checks

**Files:**
- Delete: `compose.yaml`
- Modify: `.env.example`
- Modify: `scripts/check_repository.ps1`
- Create: `scripts/check_local_services.ps1`
- Create: `scripts/tests/check_local_services.tests.ps1`

**Interfaces:**
- Consumes: native MySQL on `127.0.0.1:3306`, native Redis on `127.0.0.1:6379`, Python 3.13, Node.js 24.
- Produces: `scripts/check_repository.ps1` for static repository validation and `scripts/check_local_services.ps1` for parameterized TCP readiness checks.

- [ ] **Step 1: Write the failing local-service behavior test**

Create `scripts/tests/check_local_services.tests.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\check_local_services.ps1'

& powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath -MySqlPort 1 -RedisPort 1 -TimeoutMilliseconds 100 2>$null
if ($LASTEXITCODE -eq 0) {
    throw 'Unavailable service ports must fail the local-service check.'
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Available native services must pass; exit code $LASTEXITCODE."
}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/check_local_services.tests.ps1`

Expected: FAIL because `scripts/check_local_services.ps1` does not exist.

- [ ] **Step 3: Implement native service configuration**

Delete `compose.yaml`.

Remove the Docker Compose invocation and its exit-code branch from `scripts/check_repository.ps1`; keep the Python manifest, uv lock and Node build-script checks unchanged.

Add this local-only setting to `.env.example` immediately after `REDIS_URL`:

```dotenv
# Redis 3.2 local compatibility only. Production must use RESP3 with Redis 7.2+.
REDIS_PROTOCOL=2
```

Create `scripts/check_local_services.ps1`:

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

- [ ] **Step 4: Verify GREEN and repository integrity**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/check_local_services.tests.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_local_services.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_repository.ps1
backend/.venv/Scripts/python.exe -c "from redis import Redis; assert Redis(host='127.0.0.1', port=6379, protocol=2).ping()"
git diff --check
```

Expected: the controlled unavailable ports fail inside the behavior test, the real 3306/6379 checks pass, the repository check exits 0 without Docker, RESP2 `PING` succeeds, and Git reports no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add .env.example scripts/check_repository.ps1 scripts/check_local_services.ps1 scripts/tests/check_local_services.tests.ps1 compose.yaml
git commit -m "chore: use native local services"
```

## Definition of Done

- `compose.yaml` no longer exists.
- No executable repository or service check calls Docker.
- Native MySQL and Redis checks pass on the current workstation.
- The local Redis compatibility mode is explicit and cannot be mistaken for the production baseline.
- The task behavior test, repository check, RESP2 client probe and `git diff --check` all pass.
