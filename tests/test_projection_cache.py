import unittest

from ata.projection_cache import ProjectionCache


class ProjectionCacheTest(unittest.TestCase):
    def test_same_rev_hits_cache(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(1)
            return {"llm_ms": 5}
        self.assertEqual(cache.get_or_compute("s1", 3, "timing", compute), {"llm_ms": 5})
        self.assertEqual(cache.get_or_compute("s1", 3, "timing", compute), {"llm_ms": 5})
        self.assertEqual(len(calls), 1)

    def test_rev_bump_recomputes(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(len(calls))
            return {"n": len(calls)}
        cache.get_or_compute("s1", 3, "timing", compute)
        self.assertEqual(cache.get_or_compute("s1", 4, "timing", compute)["n"], 2)

    def test_kinds_are_independent_slots(self):
        cache = ProjectionCache()
        cache.get_or_compute("s1", 3, "timing", lambda: {"k": "timing"})
        got = cache.get_or_compute("s1", 3, "usage", lambda: {"k": "usage"})
        self.assertEqual(got, {"k": "usage"})

    def test_sessions_are_isolated(self):
        cache = ProjectionCache()
        cache.get_or_compute("s1", 3, "timing", lambda: {"who": "s1"})
        got = cache.get_or_compute("s2", 3, "timing", lambda: {"who": "s2"})
        self.assertEqual(got, {"who": "s2"})

    def test_stale_rev_writeback_does_not_clobber_newer_slot(self):
        # 慢的旧 rev 计算晚到时，不得回退已就位的新 rev 结果
        cache = ProjectionCache()
        calls = []
        def slow_old():
            calls.append("old")
            return {"gen": "old"}
        def fresh():
            return {"gen": "fresh"}
        promise = []
        import threading
        # 先占住旧 rev 的 compute（模拟在途），让新 rev 先落位
        started = threading.Event()
        release = threading.Event()
        def blocking_old():
            started.set()
            release.wait(5)
            return slow_old()
        import threading as _t
        t = _t.Thread(target=lambda: cache.get_or_compute("s", 5, "k", blocking_old), daemon=True)
        t.start()
        self.assertTrue(started.wait(5))
        self.assertEqual(cache.get_or_compute("s", 6, "k", fresh), {"gen": "fresh"})
        release.set()
        t.join(5)
        self.assertEqual(calls, ["old"])  # 旧计算确实执行过
        self.assertEqual(cache.get_or_compute("s", 6, "k", lambda: (_ for _ in ()).throw(AssertionError("must hit"))),
                         {"gen": "fresh"})  # 新槽未被回退

    def test_slots_capped_fifo(self):
        cache = ProjectionCache()
        cache.MAX_SLOTS = 3
        for i in range(5):
            cache.get_or_compute(f"s{i}", 1, "k", lambda i=i: {"i": i})
        self.assertEqual(len(cache._slots), 3)
        # 最老的 s0/s1 被 FIFO 淘汰；重算原样可得（rev 门控保证无正确性影响）
        self.assertEqual(cache.get_or_compute("s0", 1, "k", lambda: {"i": "recomputed"}), {"i": "recomputed"})


if __name__ == "__main__":
    unittest.main()
