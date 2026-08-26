import unittest

from ata.projection_cache import ProjectionCache


class ProjectionCacheTest(unittest.TestCase):
    def test_same_rev_hits_cache(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(1)
            return {"llm_ms": 5}
        self.assertEqual(cache.get_or_compute("s1", 3, compute), {"llm_ms": 5})
        self.assertEqual(cache.get_or_compute("s1", 3, compute), {"llm_ms": 5})
        self.assertEqual(len(calls), 1)

    def test_rev_bump_recomputes(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(len(calls))
            return {"n": len(calls)}
        cache.get_or_compute("s1", 3, compute)
        self.assertEqual(cache.get_or_compute("s1", 4, compute)["n"], 2)

    def test_sessions_are_isolated(self):
        cache = ProjectionCache()
        cache.get_or_compute("s1", 3, lambda: {"who": "s1"})
        got = cache.get_or_compute("s2", 3, lambda: {"who": "s2"})
        self.assertEqual(got, {"who": "s2"})

    def test_stale_rev_writeback_does_not_clobber_newer_slot(self):
        # 慢的旧 rev 计算晚到时，不得回退已就位的新 rev 结果
        cache = ProjectionCache()
        calls = []
        started = threading.Event()
        release = threading.Event()
        def blocking_old():
            started.wait(5)
            release.wait(5)
            calls.append("old")
            return {"gen": "old"}
        def fresh():
            return {"gen": "fresh"}
        t = threading.Thread(target=lambda: cache.get_or_compute("s", 5, blocking_old), daemon=True)
        t.start()
        started.set()
        self.assertEqual(cache.get_or_compute("s", 6, fresh), {"gen": "fresh"})
        release.set()
        t.join(5)
        self.assertEqual(calls, ["old"])  # 旧计算确实执行过
        self.assertEqual(
            cache.get_or_compute("s", 6, lambda: (_ for _ in ()).throw(AssertionError("must hit"))),
            {"gen": "fresh"})  # 新槽未被回退

    def test_slots_capped_fifo(self):
        cache = ProjectionCache()
        cache.MAX_SLOTS = 3
        for i in range(5):
            cache.get_or_compute(f"s{i}", 1, lambda i=i: {"i": i})
        self.assertEqual(len(cache._slots), 3)
        # 最老的 s0/s1 被 FIFO 淘汰；重算原样可得（rev 门控保证无正确性影响）
        self.assertEqual(cache.get_or_compute("s0", 1, lambda: {"i": "recomputed"}), {"i": "recomputed"})


import threading

if __name__ == "__main__":
    unittest.main()
