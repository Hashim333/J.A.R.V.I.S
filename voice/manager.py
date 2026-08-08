"""
voice/manager.py

Voice provider coordinator with speech queue, provider fallback,
and comprehensive logging.

Manages:
  - Provider selection (ElevenLabs / System)
  - Provider fallback on failure
  - Speech queue (FIFO with priority bump)
  - Cancel / clear queue
  - Retry logic
  - Configuration validation
"""

from __future__ import annotations

import datetime
import logging
import queue
import threading
import time
import traceback
from typing import Any, Callable

from config.settings import settings
from voice.elevenlabs_provider import ElevenLabsProvider
from voice.provider import VoiceProvider, VoiceProviderError
from voice.system_provider import SystemProvider

logger = logging.getLogger(__name__)


class VoiceManager:
    """Provider coordinator with speech queue and fallback.

    Usage::

        manager = VoiceManager()
        manager.speak("Hello")
        manager.speak("How are you?")   # queued, plays after "Hello"
        manager.cancel_all()            # stop + clear queue
        manager.speak("Urgent", priority=True)  # bumps ahead of queue
    """

    def __init__(self, config: Any = settings) -> None:
        self._settings = config
        self._diagnostics: list[str] = []
        self._queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._queue_lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None
        self._worker_start_lock = threading.Lock()
        self._stop_worker = threading.Event()
        self._current_text: str | None = None

        # Speech-activity lifecycle: every enqueued utterance is counted as
        # "pending" from enqueue until its playback (or failure) fully
        # completes.  This lets callers distinguish "currently generating"
        # from "idle" — the missing signal that caused the loop to return to
        # Idle before audio started playing.
        self._activity_lock = threading.Lock()
        self._pending_utterances = 0
        self._speech_finished_event = threading.Event()
        self._speech_finished_event.set()
        self.on_speech_finished: Callable[[], None] | None = None

        # Load the configured provider
        try:
            self._provider = self._load_provider()
            logger.info(
                "VoiceManager: initialized with %s",
                type(self._provider).__name__,
            )
        except Exception as exc:
            self._diagnostics.append(
                f"Voice provider initialization failed; using system voice. ({exc})"
            )
            logger.error("VoiceManager: init failed, using fallback: %s", exc)
            self._provider = self._system_provider()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str, priority: bool = False) -> bool:
        """Enqueue *text* for speech.

        If *priority* is True, the text is inserted at the front of the
        queue and current speech is interrupted.

        Returns True when the text was enqueued.
        """
        if not isinstance(text, str) or not text.strip():
            return False

        if priority:
            self.stop()
            with self._queue_lock:
                # Insert at front — drain existing items, re-queue after
                existing = []
                while not self._queue.empty():
                    try:
                        existing.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                self._queue.put((text.strip(), True))
                for item in existing:
                    self._queue.put(item)
            logger.info("VoiceManager: priority enqueue: '%s'", text[:60])
        else:
            self._queue.put((text.strip(), False))
            logger.info("VoiceManager: enqueued: '%s'", text[:60])

        with self._activity_lock:
            self._pending_utterances += 1
            self._speech_finished_event.clear()
        self._ensure_worker()
        return True

    def stop(self, reason: str = "voice_manager.stop", caller: str = "unknown") -> None:
        """Stop current speech immediately."""
        self._current_text = None
        self._log_stop_request(reason=reason, caller=caller)
        try:
            self._provider.stop()
        except Exception as exc:
            logger.debug("VoiceManager: provider.stop() failed: %s", exc)
        logger.info("VoiceManager: stopped current speech reason=%s caller=%s", reason, caller)

    def cancel_all(self) -> None:
        """Stop current speech and clear the entire queue."""
        self.stop(reason="voice_manager.cancel_all", caller="voice_manager.cancel_all")
        drained = 0
        with self._queue_lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    drained += 1
                except queue.Empty:
                    break
        if drained:
            logger.debug("VoiceManager: cancel_all drained %d queued utterance(s)", drained)
            self._decrement_pending(drained)
        logger.info("VoiceManager: queue cleared")

    def shutdown(self) -> None:
        """Stop playback, clear the queue, and stop the worker thread."""
        self.cancel_all()
        self._stop_worker.set()
        with self._worker_start_lock:
            thread = self._worker_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning("VoiceManager: worker thread did not join within 2s")
        with self._worker_start_lock:
            self._worker_thread = None
        # Any utterance still in flight when the worker was joined is gone —
        # reset the activity bookkeeping so is_busy() is never left True.
        with self._activity_lock:
            self._pending_utterances = 0
            self._speech_finished_event.set()
        self.on_speech_finished = None
        logger.info("VoiceManager: shut down")

    def pause(self) -> None:
        """Pause speech playback (if supported by provider)."""
        try:
            self._provider.pause()
        except Exception:
            pass
        logger.info("VoiceManager: paused")

    def resume(self) -> None:
        """Resume paused speech playback."""
        try:
            self._provider.resume()
        except Exception:
            pass
        logger.info("VoiceManager: resumed")

    @property
    def is_playing(self) -> bool:
        """True when audio is currently playing."""
        return self._provider.is_playing

    @property
    def is_busy(self) -> bool:
        """True while speech is queued, being generated, or playing.

        This is the correct "speech in progress" signal for the conversation
        loop: the plain queue/playing checks go False while an utterance is
        still being generated (dequeued, HTTP in flight), which previously
        let the loop return to Idle before audio started.
        """
        with self._activity_lock:
            pending = self._pending_utterances
        return pending > 0 or self._queue.qsize() > 0 or self._provider.is_playing

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def _decrement_pending(self, n: int = 1) -> None:
        """Mark *n* utterances as finished; fire on_speech_finished at zero."""
        callback = None
        with self._activity_lock:
            self._pending_utterances = max(0, self._pending_utterances - n)
            if self._pending_utterances == 0:
                self._speech_finished_event.set()
                callback = self.on_speech_finished
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                logger.error("VoiceManager: on_speech_finished callback failed: %s", exc)

    def get_speech_progress(self) -> float:
        """Return a rough playback progress estimate for the current utterance."""
        return 1.0

    def _log_stop_request(self, reason: str, caller: str) -> None:
        frame = traceback.extract_stack(limit=7)[-2]
        callsite = f"{frame.filename}:{frame.lineno} {frame.name}"
        logger.info(
            "STOP_REQUEST caller=%s thread=%s reason=%s timestamp=%s stack=%s",
            caller,
            threading.current_thread().name,
            reason,
            datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "".join(traceback.format_stack(limit=8)).rstrip(),
        )
        logger.debug("VoiceManager: stop request originated from %s (%s)", callsite, caller)

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Configuration and runtime diagnostics."""
        return tuple(self._diagnostics)

    @property
    def provider(self) -> VoiceProvider:
        """The currently active voice provider."""
        return self._provider

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def _load_provider(self) -> VoiceProvider:
        """Load the configured voice provider."""
        provider_name = self._provider_name()
        logger.info("VoiceManager: configured provider=%r", provider_name)

        if provider_name == "system":
            return self._system_provider()

        if provider_name == "elevenlabs":
            api_key = self._elevenlabs_api_key()
            voice_id = self._voice_id()

            if not api_key:
                msg = "ELEVENLABS_API_KEY is missing; using system voice."
                self._diagnostics.append(msg)
                logger.warning("VoiceManager: %s", msg)
                return self._system_provider()

            if not voice_id:
                msg = "VOICE_ID is missing; using system voice."
                self._diagnostics.append(msg)
                logger.warning("VoiceManager: %s", msg)
                return self._system_provider()

            try:
                provider = ElevenLabsProvider(
                    api_key=api_key,
                    voice_id=voice_id,
                    model=self._voice_model(),
                    stability=self._voice_stability(),
                    similarity_boost=self._voice_similarity(),
                    style=self._voice_style(),
                    speaker_boost=self._voice_speaker_boost(),
                )
                logger.info(
                    "VoiceManager: ElevenLabs provider created "
                    "(voice=%s, model=%s)", voice_id, self._voice_model(),
                )
                return provider
            except Exception as exc:
                msg = f"ElevenLabs provider failed to initialize; using system voice. ({exc})"
                self._diagnostics.append(msg)
                logger.error("VoiceManager: %s", exc)
                return self._system_provider()

        msg = f"Unsupported VOICE_PROVIDER {provider_name!r}; using system voice."
        self._diagnostics.append(msg)
        logger.warning("VoiceManager: %s", msg)
        return self._system_provider()

    def _fallback_to_system(self, reason: str = "") -> None:
        """Switch to the system provider (fallback)."""
        if isinstance(self._provider, SystemProvider):
            return  # already using fallback
        msg = f"Switching to system voice provider"
        if reason:
            msg += f": {reason}"
        self._diagnostics.append(msg)
        logger.warning("VoiceManager: %s", msg)
        self._provider = self._system_provider()

    # ------------------------------------------------------------------
    # Speech worker
    # ------------------------------------------------------------------

    def _ensure_worker(self) -> None:
        with self._worker_start_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._stop_worker.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop, daemon=True
            )
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Background thread: drain the speech queue."""
        logger.info("VoiceManager: worker started")
        while not self._stop_worker.is_set():
            try:
                text, priority = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._stop_worker.is_set():
                break

            self._current_text = text
            start = time.monotonic()
            success = False

            try:
                success = self._provider.speak(text)
            except Exception as exc:
                logger.error("VoiceManager: provider.speak() raised: %s", exc)

            # Providers may return before the audio actually finishes
            # (async playback via a background process / VoicePlayer). Wait
            # for real completion before pulling the next queue item — the
            # worker must never start a new utterance while the previous
            # one is still playing, otherwise sentences get cut off.
            if success:
                self._wait_for_playback_end(text)

            elapsed = (time.monotonic() - start) * 1000
            self._current_text = None

            if success:
                logger.info(
                    "VoiceManager: OK (%d chars, %.0f ms): '%s'",
                    len(text), elapsed, text[:60],
                )
            else:
                logger.warning(
                    "VoiceManager: FAILED (%d chars, %.0f ms): '%s'",
                    len(text), elapsed, text[:60],
                )
                # Fallback for ElevenLabs failures
                if not isinstance(self._provider, SystemProvider):
                    self._fallback_to_system(
                        f"speak() returned False for '{text[:40]}'"
                    )

            self._decrement_pending()

        logger.info("VoiceManager: worker stopped")

    def _wait_for_playback_end(self, text: str) -> None:
        """Block until the provider's audio has actually finished playing.

        Async providers (PowerShell subprocess, VoicePlayer) only report
        ``is_playing`` True once playback has begun, so give them a short
        startup window before concluding the utterance already finished
        (i.e. a synchronous provider).
        """
        time.sleep(0.15)
        startup_deadline = time.monotonic() + 1.5
        playing = self._provider.is_playing
        while not playing and time.monotonic() < startup_deadline:
            if self._stop_worker.is_set():
                return
            time.sleep(0.05)
            playing = self._provider.is_playing

        if not playing:
            return

        deadline = time.monotonic() + 120.0
        while self._provider.is_playing:
            if self._stop_worker.is_set():
                break
            if time.monotonic() >= deadline:
                logger.warning(
                    "VoiceManager: playback did not finish within 120s — moving on"
                )
                break
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _provider_name(self) -> str:
        return str(
            getattr(self._settings, "voice_provider", "system")
        ).strip().casefold()

    def _system_provider(self) -> SystemProvider:
        return SystemProvider(voice_id=self._voice_id())

    def _voice_id(self) -> str:
        return str(getattr(self._settings, "voice_id", "") or "").strip()

    def _voice_model(self) -> str:
        return str(
            getattr(self._settings, "voice_model", "eleven_multilingual_v2")
            or "eleven_multilingual_v2"
        ).strip()

    def _elevenlabs_api_key(self) -> str:
        return str(
            getattr(self._settings, "elevenlabs_api_key", "") or ""
        ).strip()

    def _voice_stability(self) -> float | None:
        val = getattr(self._settings, "voice_stability", None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None

    def _voice_similarity(self) -> float | None:
        val = getattr(self._settings, "voice_similarity", None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None

    def _voice_style(self) -> float | None:
        val = getattr(self._settings, "voice_style", None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None

    def _voice_speaker_boost(self) -> bool | None:
        val = getattr(self._settings, "voice_speaker_boost", None)
        if val is not None:
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.casefold() in ("true", "1", "yes")
        return None
