#!/usr/bin/env python3
"""
tools/tts_probe.py

ElevenLabs TTS probe tool — tests the same voice/model/settings as the app,
both streaming and non-streaming, and prints:
- bytes received
- audio seconds (from bytes / sample rate)
- characters per second of audio
- time to first byte (TTFB)
- total time

Run 3 times to get averages. Never prints the API key.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings


@dataclass
class ProbeResult:
    """Single probe run result."""
    streaming: bool
    text_chars: int
    bytes_received: int
    audio_seconds: float
    chars_per_audio_sec: float
    ttfb_ms: float
    total_ms: float
    status: str
    error: str | None = None


# Test sentences from the log evidence
TEST_SENTENCES = [
    "Done.",  # 5 chars - very short
    "Opened Notepad.",  # 16 chars - medium
    "I have opened Notepad for you. Is there anything else I can help with?",  # 64 chars - longer
]

# App's default settings
VOICE_ID = settings.voice_id
MODEL = settings.voice_model
OUTPUT_FORMAT = "pcm_22050"  # Same as elevenlabs_provider default
STABILITY = settings.voice_stability
SIMILARITY_BOOST = settings.voice_similarity
STYLE = settings.voice_style
SPEAKER_BOOST = settings.voice_speaker_boost
SPEED = settings.voice_speed

# PCM format mapping (from elevenlabs_provider)
PCM_FORMATS = {
    "pcm_8000": (8000, 1),
    "pcm_16000": (16000, 1),
    "pcm_22050": (22050, 1),
    "pcm_44100": (44100, 1),
}

SAMPLE_RATE, CHANNELS = PCM_FORMATS.get(OUTPUT_FORMAT, (22050, 1))
SAMPLE_WIDTH = 2  # 16-bit
BYTES_PER_SEC = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
REQUEST_TIMEOUT = 30


def build_request(text: str, streaming: bool) -> urllib.request.Request:
    """Build HTTP request matching the app's elevenlabs_provider."""
    body_fields = {
        "text": text,
        "model_id": MODEL,
    }

    voice_settings = {}
    if STABILITY is not None:
        voice_settings["stability"] = STABILITY
    if SIMILARITY_BOOST is not None:
        voice_settings["similarity_boost"] = SIMILARITY_BOOST
    if STYLE is not None:
        voice_settings["style"] = STYLE
    if SPEAKER_BOOST is not None:
        voice_settings["use_speaker_boost"] = SPEAKER_BOOST
    voice_settings["speed"] = max(0.7, min(1.2, SPEED))
    if voice_settings:
        body_fields["voice_settings"] = voice_settings

    body = json.dumps(body_fields).encode("utf-8")

    if streaming:
        url = f"{ELEVENLABS_URL}/{VOICE_ID}/stream"
    else:
        url = f"{ELEVENLABS_URL}/{VOICE_ID}"

    accept = (
        f"audio/pcm;rate={SAMPLE_RATE}"
        if OUTPUT_FORMAT in PCM_FORMATS
        else "audio/mpeg"
    )

    return urllib.request.Request(
        f"{url}?output_format={OUTPUT_FORMAT}",
        data=body,
        headers={
            "Accept": accept,
            "Content-Type": "application/json",
            "xi-api-key": settings.elevenlabs_api_key or "",
        },
        method="POST",
    )


def run_probe(text: str, streaming: bool) -> ProbeResult:
    """Run a single probe request."""
    request = build_request(text, streaming)
    start = time.monotonic()
    ttfb = None
    bytes_received = 0
    status = "ok"
    error = None

    try:
        response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)
        content_type = response.headers.get("Content-Type", "")

        is_pcm = OUTPUT_FORMAT in PCM_FORMATS or any(
            fmt in content_type for fmt in (
                "audio/pcm", "audio/L16", "audio/l16",
                "audio/raw", "audio/x-raw",
            )
        )

        if streaming and is_pcm:
            # Streaming: read chunk by chunk
            chunk_size = 4096
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                if ttfb is None:
                    ttfb = time.monotonic() - start
                bytes_received += len(chunk)
        else:
            # Non-streaming: read all at once
            audio_data = response.read()
            if audio_data:
                ttfb = time.monotonic() - start
                bytes_received = len(audio_data)

        response.close()

    except urllib.error.HTTPError as exc:
        elapsed = (time.monotonic() - start) * 1000
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<unreadable>"
        status = f"HTTP {exc.code}"
        error = f"HTTP {exc.code}: {body[:200]}"
        ttfb = elapsed / 1000.0 if ttfb is None else ttfb
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        status = "ERROR"
        error = f"{type(exc).__name__}: {exc}"
        ttfb = elapsed / 1000.0 if ttfb is None else ttfb

    total_ms = (time.monotonic() - start) * 1000
    ttfb_ms = ttfb * 1000 if ttfb is not None else total_ms
    audio_seconds = bytes_received / BYTES_PER_SEC if BYTES_PER_SEC else 0.0
    chars_per_audio_sec = len(text) / audio_seconds if audio_seconds > 0 else 0.0

    return ProbeResult(
        streaming=streaming,
        text_chars=len(text),
        bytes_received=bytes_received,
        audio_seconds=audio_seconds,
        chars_per_audio_sec=chars_per_audio_sec,
        ttfb_ms=ttfb_ms,
        total_ms=total_ms,
        status=status,
        error=error,
    )


def print_result(result: ProbeResult, run_num: int, text: str) -> None:
    """Print a formatted probe result."""
    mode = "streaming" if result.streaming else "non-streaming"
    print(f"  Run {run_num} ({mode}): {result.status}")
    print(f"    Text: \"{text[:60]}{'...' if len(text) > 60 else ''}\" ({result.text_chars} chars)")
    print(f"    Bytes received: {result.bytes_received:,}")
    print(f"    Audio duration: {result.audio_seconds:.3f} s")
    print(f"    Chars/audio-sec: {result.chars_per_audio_sec:.1f}")
    print(f"    TTFB: {result.ttfb_ms:.0f} ms")
    print(f"    Total time: {result.total_ms:.0f} ms")
    if result.error:
        print(f"    Error: {result.error}")


def main() -> int:
    if not settings.elevenlabs_api_key:
        print("ERROR: ELEVENLABS_API_KEY not configured in settings/.env")
        return 1
    if not settings.voice_id:
        print("ERROR: VOICE_ID not configured in settings/.env")
        return 1

    print("=" * 70)
    print("ElevenLabs TTS Probe")
    print("=" * 70)
    print(f"Voice ID: {VOICE_ID}")
    print(f"Model: {MODEL}")
    print(f"Output format: {OUTPUT_FORMAT} ({SAMPLE_RATE} Hz, {CHANNELS} ch, {SAMPLE_WIDTH*8}-bit)")
    print(f"Settings: stability={STABILITY}, similarity={SIMILARITY_BOOST}, "
         f"style={STYLE}, speaker_boost={SPEAKER_BOOST}, speed={SPEED}")
    print(f"Test sentences: {len(TEST_SENTENCES)}")
    print(f"Runs per sentence: 3")
    print(f"Modes: streaming + non-streaming")
    print(f"Total probes: {len(TEST_SENTENCES) * 3 * 2}")
    print()

    all_results: list[ProbeResult] = []

    for sentence in TEST_SENTENCES:
        print(f"--- Testing: \"{sentence}\" ---")
        for streaming in (True, False):
            for run in range(1, 4):
                result = run_probe(sentence, streaming)
                all_results.append(result)
                print_result(result, run, sentence)
                time.sleep(0.5)  # Be nice to the API
            print()

    # Summary
    print("=" * 70)
    print("SUMMARY (averages over 3 runs)")
    print("=" * 70)
    for sentence in TEST_SENTENCES:
        print(f"\nSentence: \"{sentence}\" ({len(sentence)} chars)")
        for streaming in (True, False):
            runs = [r for r in all_results if r.text_chars == len(sentence) and r.streaming == streaming]
            ok_runs = [r for r in runs if r.status == "ok"]
            if not ok_runs:
                print(f"  {'Streaming' if streaming else 'Non-streaming'}: ALL FAILED")
                continue
            avg_bytes = sum(r.bytes_received for r in ok_runs) / len(ok_runs)
            avg_audio = sum(r.audio_seconds for r in ok_runs) / len(ok_runs)
            avg_cps = sum(r.chars_per_audio_sec for r in ok_runs) / len(ok_runs)
            avg_ttfb = sum(r.ttfb_ms for r in ok_runs) / len(ok_runs)
            avg_total = sum(r.total_ms for r in ok_runs) / len(ok_runs)
            mode = "streaming" if streaming else "non-streaming"
            print(f"  {mode}: bytes={avg_bytes:.0f} audio={avg_audio:.3f}s "
                  f"cps={avg_cps:.1f} ttfb={avg_ttfb:.0f}ms total={avg_total:.0f}ms "
                  f"({len(ok_runs)}/3 ok)")

    # Compare with app's VoicePlayer expectations
    print("\n" + "=" * 70)
    print("COMPARISON WITH APP PLAYBACK")
    print("=" * 70)
    print("App log showed:")
    print("  - 58-char sentence: bytes=53248 (1.2s audio at 22050Hz)")
    print("  - 92-char sentence: \"played 0.7 sec\" (truncated!)")
    print()
    print("Expected at 22050 Hz mono 16-bit:")
    print(f"  1 second = {BYTES_PER_SEC:,} bytes")
    print(f"  58 chars at ~15 chars/s = ~3.9s audio = ~{int(3.9 * BYTES_PER_SEC):,} bytes")
    print(f"  92 chars at ~15 chars/s = ~6.1s audio = ~{int(6.1 * BYTES_PER_SEC):,} bytes")
    print()
    print("If probe bytes match expected but app plays less,")
    print("the cut-off is in OUR read/playback code (VoicePlayer).")
    print("If probe bytes are also truncated, the cut-off is from API/network.")

    return 0


if __name__ == "__main__":
    sys.exit(main())