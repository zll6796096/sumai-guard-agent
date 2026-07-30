from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from copy import deepcopy
from typing import Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")
Factory = Callable[[], Awaitable[tuple[T, bool]]]


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
        self._in_flight: dict[str, asyncio.Task[tuple[T | None, BaseException | None]]] = {}
        self._lock = asyncio.Lock()

    async def get_or_compute(self, key: str, factory: Factory[T]) -> tuple[T, bool]:
        async with self._lock:
            self._purge_expired()
            cached = self._values.get(key)
            if cached is not None:
                self._values.move_to_end(key)
                return deepcopy(cached[1]), True
            task = self._in_flight.get(key)
            if task is None:
                worker = asyncio.create_task(self._compute(key, factory))
                worker.add_done_callback(self._observe_task_failure)
                task = asyncio.create_task(self._capture_worker(key, worker))
                self._in_flight[key] = task

        # A cancelled request must not cancel the shared provider computation.
        value, error = await asyncio.shield(task)
        if error is not None:
            raise error
        return deepcopy(value), False

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

    async def _capture_worker(
        self, key: str, worker: asyncio.Task[tuple[T, bool]]
    ) -> tuple[T | None, BaseException | None]:
        """Convert worker failure into a successful shield target for detached waiters."""
        try:
            value, _cacheable = await worker
            return value, None
        except asyncio.CancelledError as error:
            return None, error
        except Exception as error:
            return None, error
        finally:
            async with self._lock:
                if self._in_flight.get(key) is asyncio.current_task():
                    del self._in_flight[key]

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
