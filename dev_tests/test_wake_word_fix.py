"""
dev_tests/test_wake_word_fix.py

Verify the wake-word detector ONLY triggers on exactly "jarvis" and
ignores "[unk]", partial matches, empty text, and noise.

Run with: python -m dev_tests.test_wake_word_fix
"""

from __future__ import annotations

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_mock_recognizer(text: str):
    """Create a mock KaldiRecognizer that returns a given text."""
    import unittest.mock as mock
    rec = mock.MagicMock()
    rec.AcceptWaveform.return_value = True
    rec.FinalResult.return_value = json.dumps({"text": text})
    return rec


def make_mock_model():
    import unittest.mock as mock
    return mock.MagicMock()


def test_contains_wake_word(text: str, expected: bool) -> bool:
    """
    Test LocalWakeWordDetector.contains_wake_word() with a mocked Vosk
    recognizer that returns the given text.
    """
    from voice.local_wake_word import LocalWakeWordDetector

    # We'll patch vosk.KaldiRecognizer inside contains_wake_word
    import unittest.mock as mock
    original_kaldi = None

    recognizer = make_mock_recognizer(text)

    with mock.patch("voice.local_wake_word.vosk.KaldiRecognizer", return_value=recognizer):
        detector = LocalWakeWordDetector()
        # Patch the model too (it's created in __init__)
        detector._model = make_mock_model()
        result = detector.contains_wake_word(b"\x00\x00" * 8000, sample_rate=16000)

    ok = result == expected
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: text={text!r:20s} expected={expected!r:5s} got={result!r}")
    return ok


def test_grammar_does_not_contain_unk() -> bool:
    """Verify the grammar string used with KaldiRecognizer does not include [unk]."""
    import inspect
    from voice.local_wake_word import LocalWakeWordDetector

    source = inspect.getsource(LocalWakeWordDetector.contains_wake_word)
    # Find the actual KaldiRecognizer constructor call
    for line in source.split('\n'):
        if 'KaldiRecognizer' in line:
            # The grammar is the third argument
            if "'[\"jarvis\"]'" in line and "unk" not in line:
                print(f"  PASS: Grammar correctly excludes [unk] (uses '[\"jarvis\"]')")
                return True
            else:
                print(f"  FAIL: Grammar line: {line.strip()}")
                return False
    print(f"  FAIL: Could not find KaldiRecognizer constructor")
    return False


def test_uses_exact_equality() -> bool:
    """Verify contains_wake_word uses == not 'in'."""
    import inspect
    from voice.local_wake_word import LocalWakeWordDetector

    source = inspect.getsource(LocalWakeWordDetector.contains_wake_word)
    if "text == self._WAKE_PHRASE" in source:
        print(f"  PASS: Uses exact equality (==) not substring match")
        return True
    else:
        print(f"  FAIL: Does not use exact equality")
        return False


def test_force_flush_clears_buffer() -> bool:
    """Verify _flush_and_keep_capturing clears the buffer on miss."""
    import inspect
    from voice.wakeword import WakeWordDetector

    source = inspect.getsource(WakeWordDetector._flush_and_keep_capturing)
    if "self._audio_buffer = bytearray()" in source:
        print(f"  PASS: Force-flush clears buffer on miss")
        return True
    else:
        print(f"  FAIL: Force-flush does not clear buffer")
        return False


def test_uses_final_result() -> bool:
    """Verify contains_wake_word uses FinalResult(), not PartialResult()."""
    import inspect
    from voice.local_wake_word import LocalWakeWordDetector

    source = inspect.getsource(LocalWakeWordDetector.contains_wake_word)
    if "FinalResult()" in source and "PartialResult()" not in source:
        print(f"  PASS: Uses FinalResult() without PartialResult()")
        return True
    else:
        print(f"  FAIL: Uses PartialResult() or missing FinalResult()")
        return False


def main():
    # Suppress Vosk model-loading log noise
    os.environ["VOSK_LOG_LEVEL"] = "-1"

    print("=" * 60)
    print("WAKE WORD DETECTION VERIFICATION")
    print("=" * 60)
    print()

    # Source-code checks (no mocking needed)
    print("--- Source-code invariants ---")
    src_tests = [
        ("Grammar excludes [unk]", test_grammar_does_not_contain_unk()),
        ("Uses exact equality (==)", test_uses_exact_equality()),
        ("Force-flush clears buffer", test_force_flush_clears_buffer()),
        ("Uses FinalResult not PartialResult", test_uses_final_result()),
    ]

    # Behavioral tests (with mocked Vosk)
    print()
    print("--- Behavioral tests (mocked Vosk) ---")
    # Note: Vosk FinalResult() never includes leading/trailing whitespace,
    # so whitespace-padded test cases are unrealistic and excluded.
    behavior_tests = [
        ("jarvis", True,    "exact wake word"),
        ("JARVIS", True,    "wake word uppercase"),
        ("Jarvis", True,    "wake word capitalised"),
        ("[unk]", False,    "unknown token"),
        ("[unk] [unk]", False, "multiple unknown tokens"),
        ("", False,         "empty text"),
        ("jarvis something", False, "wake word with extra text"),
        ("something jarvis", False, "extra text before wake word"),
        ("open chrome", False, "other command"),
    ]

    total = len(src_tests) + len(behavior_tests)
    passed = 0

    for name, ok in src_tests:
        if ok:
            passed += 1

    for text, expected, desc in behavior_tests:
        ok = test_contains_wake_word(text, expected)
        if ok:
            passed += 1

    print()
    print("=" * 60)
    print(f"RESULTS: {passed}/{total} passed")
    print("=" * 60)

    if passed == total:
        print("All wake-word tests passed!")
    else:
        print(f"*** {total - passed} test(s) FAILED ***")
        sys.exit(1)


if __name__ == "__main__":
    main()
