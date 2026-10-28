import unittest
from organizer.classification_timing import estimate, RunTiming, time_range


class ClassificationTimingTests(unittest.TestCase):
    def test_cache_and_rules_do_not_include_ai_time(self):
        self.assertEqual(estimate('ollama', 0, 20), estimate('rules', 20, 20))
        self.assertLess(estimate('ollama', 0, 20)[1], estimate('ollama', 1, 20)[0])

    def test_estimate_scales_with_unique_work_and_uses_measurements(self):
        self.assertGreater(estimate('ollama', 20, 20)[1], estimate('ollama', 1, 20)[1])
        low, high = estimate('ollama', 10, 20, [2, 2, 2])
        self.assertLessEqual(low, 20)
        self.assertGreaterEqual(high, 20)

    def test_remaining_adapts_to_completed_batches(self):
        run = RunTiming(20, 200, 600, 100)
        run.observe(10, 120)
        self.assertEqual(run.completed, 10)
        self.assertAlmostEqual(run.low, 13)
        self.assertAlmostEqual(run.high, 32)
        self.assertIn('10/20 AI files checked', run.text(125))
        self.assertIn('Elapsed:', run.text(125))

    def test_overrun_is_explicit_and_completion_does_not_fake_zero(self):
        run = RunTiming(1, 10, 30, 100)
        self.assertIn('Taking longer than estimated', run.text(140))
        run.observe(1, 145)
        self.assertIn('Finalizing results', run.text(146))

    def test_large_durations_are_readable(self):
        self.assertIn('h', time_range(3600, 7200))
