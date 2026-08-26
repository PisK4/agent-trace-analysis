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


if __name__ == "__main__":
    unittest.main()
