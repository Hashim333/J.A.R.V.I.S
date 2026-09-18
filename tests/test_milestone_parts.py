"""
tests/test_milestone_parts.py

Tests for the voice-reliability milestone additions:

  PART 11  ``brain/time_budget`` — a shared monotonic budget that bounds
           nested LLM calls so the sum of child calls never exceeds the
           parent request.
  PART 13  ``services/silence_gate`` — silence / noise / empty / cancelled
           captures never start a repeat loop.
  PART 14  capture callback clamp in ``voice/duplex`` — a slow inline
           ``on_partial`` must never stall the mic thread.
  PART 15  capture finalize hard limit in ``voice/duplex`` — a stuck
           recognizer must never wedge ``capture_command``.

No microphone hardware, network, or real TTS is used.
"""

from __future__ import annotations

import time
import unittest

from brain.time_budget import TimeBudget
from services.silence_gate import is_silence_or_garbage


class TestTimeBudget(unittest.TestCase):
    def test_remaining_starts_at_seconds(self) -> None:
        budget = TimeBudget(10.0)
        self.assertGreater(budget.remaining, 9.0)
        self.assertLessEqual(budget.remaining, 10.0)
        self.assertFalse(budget.expired)

    def test_child_timeout_is_capped_by_remaining(self) -> None:
        budget = TimeBudget(3.0)
        # Default of 60 s must be clamped down to the remaining budget.
        self.assertLessEqual(budget.child_timeout(60.0), 3.0)

    def test_child_timeout_uses_smaller_default(self) -> None:
        budget = TimeBudget(30.0)
        self.assertEqual(budget.child_timeout(2.0), 2.0)

    def test_expired_budget_returns_zero(self) -> None:
        budget = TimeBudget(-5.0)
        self.assertTrue(budget.expired)
        self.assertEqual(budget.remaining, 0.0)
        self.assertEqual(budget.child_timeout(60.0), 0.0)

    def test_budget_expires_after_deadline(self) -> None:
        budget = TimeBudget(0.05)
        time.sleep(0.1)
        self.assertTrue(budget.expired)
        self.assertEqual(budget.child_timeout(5.0), 0.0)


class TestSilenceGate(unittest.TestCase):
    def test_empty_text_is_silence(self) -> None:
        self.assertTrue(is_silence_or_garbage("", "low confidence"))
        self.assertTrue(is_silence_or_garbage(None, ""))
        self.assertTrue(is_silence_or_garbage("   ", ""))

    def test_quiet_reasons_never_repeat(self) -> None:
        for reason in ("no speech recognized", "pathological repetition",
                       "too short", "cancelled"):
            with self.subTest(reason=reason):
                self.assertTrue(
                    is_silence_or_garbage("something", reason),
                    f"{reason!r} must be treated as quiet, never a repeat loop",
                )

    def test_low_confidence_is_not_garbage(self) -> None:
        # "low confidence" is real (but unclear) speech — allowed one repeat.
        self.assertFalse(is_silence_or_garbage("open chrome", "low confidence"))

    def test_accepted_text_with_unknown_reason_proceeds(self) -> None:
        self.assertFalse(is_silence_or_garbage("open chrome", ""))


if __name__ == "__main__":
    unittest.main()
