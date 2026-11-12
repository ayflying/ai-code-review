"""验证并发上限、实际重叠及稳定汇总，不访问网络。"""

import threading
import time
import unittest

from batch_parallel import review_prepared


class ParallelTests(unittest.TestCase):
    def test_three_requests_overlap_and_keep_order(self):
        barrier = threading.Barrier(3, timeout=5)
        lock = threading.Lock()
        active = peak = 0

        def request(diff, context, loaded):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            with lock:
                active -= 1
            return {"summary": diff}, [], "OPENAI"

        items = [(i, str(i), "", {}, []) for i in range(1, 7)]
        results = list(review_prepared(items, 3, time.monotonic() + 30, request))
        self.assertEqual(peak, 3)
        self.assertEqual([result[0][0] for result in results], list(range(1, 7)))
        self.assertTrue(all(result[1] is not None for result in results))

    def test_expired_budget_never_calls_model(self):
        def request(*args):
            self.fail("预算耗尽不应调用模型")
        results = list(review_prepared([(1, "", "", {}, [])], 3, 0, request))
        self.assertIsNone(results[0][1])
        self.assertIn("未调用模型", results[0][2][0])
