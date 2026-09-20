"""Small process-local LRU with per-key single-flight for demand summaries."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from threading import Condition, RLock
from typing import Any


class SummaryCache:
    def __init__(self, max_size: int = 256):
        if max_size < 1:
            raise ValueError("summary cache size must be positive")
        self.max_size = max_size
        self._values: OrderedDict[Hashable, Any] = OrderedDict()
        self._running: set[Hashable] = set()
        self._condition = Condition(RLock())
        self._metrics = {"hit": 0, "miss": 0, "eviction": 0, "wait": 0}

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        with self._condition:
            if key in self._values:
                self._metrics["hit"] += 1
                self._values.move_to_end(key)
                return self._values[key]
            while key in self._running:
                self._metrics["wait"] += 1
                self._condition.wait()
                if key in self._values:
                    self._metrics["hit"] += 1
                    self._values.move_to_end(key)
                    return self._values[key]
            self._metrics["miss"] += 1
            self._running.add(key)
        try:
            value = compute()
        except BaseException:
            with self._condition:
                self._running.remove(key)
                self._condition.notify_all()
            raise
        with self._condition:
            self._values[key] = value
            self._values.move_to_end(key)
            if len(self._values) > self.max_size:
                self._values.popitem(last=False)
                self._metrics["eviction"] += 1
            self._running.remove(key)
            self._condition.notify_all()
        return value

    def metrics(self) -> dict[str, int]:
        with self._condition:
            return {**self._metrics, "size": len(self._values)}

    def clear(self) -> None:
        with self._condition:
            self._values.clear()
