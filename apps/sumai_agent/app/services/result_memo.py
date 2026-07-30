from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")
Factory = Callable[[], Awaitable[tuple[T, bool]]]


@dataclass
class _InFlightEntry(Generic[T]):
    worker: asyncio.Task[tuple[T, bool]]
    waiters: int = 0


class AsyncResultMemo(Generic[T]):
    """Bounded, process-local semantic result memo with in-flight coalescing."""

    def __init__(
        self,
        *,
        max_items: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be greater than zero")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        self._max_items = max_items
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._values: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._in_flight: dict[str, _InFlightEntry[T]] = {}
        self._lock = asyncio.Lock()

    async def get_or_compute(self, key: str, factory: Factory[T]) -> tuple[T, bool]:
        async with self._lock:
            self._purge_expired()
            cached = self._values.get(key)
            if cached is not None:
                self._values.move_to_end(key)
                return deepcopy(cached[1]), True
            entry = self._in_flight.get(key)
            if entry is None:
                worker = asyncio.create_task(
                    self._run_worker(key, factory)
                )
                worker.add_done_callback(self._observe_task_failure)
                entry = _InFlightEntry(worker=worker)
                self._in_flight[key] = entry
            entry.waiters += 1

        try:
            # One disconnected request must not cancel work still shared by
            # another waiter.
            value, _cacheable = await asyncio.shield(entry.worker)
            return deepcopy(value), False
        finally:
            await self._release_waiter(key, entry)

    def _purge_expired(self) -> None:
        now = self._clock()
        for key, (expires_at, _value) in list(self._values.items()):
            if expires_at <= now:
                del self._values[key]

    @staticmethod
    def _observe_task_failure(task: asyncio.Task[object]) -> None:
        """Consume detached task failures without changing exceptions seen by waiters."""
        if not task.cancelled():
            task.exception()

    async def _run_worker(
        self,
        key: str,
        factory: Factory[T],
    ) -> tuple[T, bool]:
        try:
            return await self._compute(key, factory)
        finally:
            async with self._lock:
                entry = self._in_flight.get(key)
                if (
                    entry is not None
                    and entry.worker is asyncio.current_task()
                ):
                    del self._in_flight[key]

    async def _release_waiter(
        self,
        key: str,
        entry: _InFlightEntry[T],
    ) -> None:
        cancel_worker = False
        async with self._lock:
            if entry.waiters <= 0:
                raise RuntimeError("result_memo_waiter_underflow")
            entry.waiters -= 1
            if entry.waiters == 0 and not entry.worker.done():
                if self._in_flight.get(key) is entry:
                    del self._in_flight[key]
                entry.worker.cancel()
                cancel_worker = True
        if cancel_worker:
            await asyncio.gather(entry.worker, return_exceptions=True)

    async def _compute(self, key: str, factory: Factory[T]) -> tuple[T, bool]:
        value, cacheable = await factory()
        if cacheable:
            async with self._lock:
                self._purge_expired()
                self._values[key] = (self._clock() + self._ttl_seconds, deepcopy(value))
                self._values.move_to_end(key)
                while len(self._values) > self._max_items:
                    self._values.popitem(last=False)
        return deepcopy(value), cacheable
