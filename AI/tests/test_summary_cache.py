from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

from worker.summary_cache import SummaryCache


def test_summary_cache_is_bounded_lru():
    cache = SummaryCache(max_size=2)
    assert cache.get_or_compute("a", lambda: 1) == 1
    assert cache.get_or_compute("b", lambda: 2) == 2
    assert cache.get_or_compute("a", lambda: 9) == 1
    assert cache.get_or_compute("c", lambda: 3) == 3
    assert cache.get_or_compute("b", lambda: 4) == 4
    assert cache.metrics() == {
        "hit": 1,
        "miss": 4,
        "eviction": 2,
        "wait": 0,
        "size": 2,
    }


def test_summary_cache_single_flights_same_key():
    cache = SummaryCache()
    barrier = Barrier(2)
    calls = 0
    lock = Lock()

    def compute():
        nonlocal calls
        with lock:
            calls += 1
        barrier.wait()
        return "value"

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cache.get_or_compute, "same", compute) for _ in range(4)]
        # Only the elected computation reaches the barrier; release it from the test.
        barrier.wait()
        assert [future.result(timeout=2) for future in futures] == ["value"] * 4
    assert calls == 1
    assert cache.metrics()["wait"] == 3
