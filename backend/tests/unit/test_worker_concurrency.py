import asyncio
from typing import Any

from app.workers.pipeline import TranslationWorker, WorkerRun


class _FakeRedis:
    """In-memory stand-in for the WorkLease SET NX and release/renew scripts."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        key, token = str(args[0]), str(args[1])
        if self._values.get(key) != token:
            return 0
        if len(args) == 2:  # release script: delete; renew keeps the key
            self._values.pop(key, None)
        return 1


class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.completed: list[int] = []

    async def run(self, task_id: int, *, fail: bool = False) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.05)
            if fail:
                raise RuntimeError(f"task {task_id} failed")
            self.completed.append(task_id)
        finally:
            self.active -= 1


class _StubbedWorker(TranslationWorker):
    def __init__(
        self,
        redis: _FakeRedis,
        task_ids: list[int],
        probe: _ConcurrencyProbe,
        failing: set[int] | None = None,
        *,
        max_concurrency: int,
    ) -> None:
        super().__init__(
            None,  # type: ignore[arg-type]
            redis,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            lease_seconds=60,
            max_concurrency=max_concurrency,
        )
        self._task_ids = task_ids
        self._probe = probe
        self._failing = failing or set()

    async def _pending_projects(self) -> list[int]:
        return []

    async def _pending_tasks(self) -> list[int]:
        return list(self._task_ids)

    async def _run_task(self, task_id: int) -> None:
        await self._probe.run(task_id, fail=task_id in self._failing)


async def test_run_once_processes_all_tasks_with_bounded_concurrency() -> None:
    probe = _ConcurrencyProbe()
    worker = _StubbedWorker(_FakeRedis(), [1, 2, 3], probe, max_concurrency=2)

    result = await worker.run_once()

    assert result == WorkerRun(projects=0, tasks=3)
    assert sorted(probe.completed) == [1, 2, 3]
    assert probe.max_active == 2


async def test_run_once_failure_does_not_block_other_tasks() -> None:
    probe = _ConcurrencyProbe()
    worker = _StubbedWorker(
        _FakeRedis(), [1, 2, 3], probe, failing={2}, max_concurrency=2
    )

    result = await worker.run_once()

    assert result == WorkerRun(projects=0, tasks=2)
    assert sorted(probe.completed) == [1, 3]


async def test_run_once_max_concurrency_one_runs_serially() -> None:
    probe = _ConcurrencyProbe()
    worker = _StubbedWorker(_FakeRedis(), [1, 2, 3], probe, max_concurrency=1)

    result = await worker.run_once()

    assert result == WorkerRun(projects=0, tasks=3)
    assert probe.max_active == 1
    assert probe.completed == [1, 2, 3]
