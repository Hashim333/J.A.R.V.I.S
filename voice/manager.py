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
from voice.piper_provider import PiperProvider
from voice.provider import VoiceProvider, VoiceProviderError
from voice.system_provider import SystemProvider

logger = logging.getLogger(__name__)

# PART 9: cap how long the worker waits for a single utterance's playback to
# finish.  Normal TTS responses finish in seconds; a provider that reports
# "playing" but never stops must not wedge the speech worker (which would
# stall queued acks like "Yes?" and block the conversation loop's waits).
_PLAYBACK_MAX_WAIT_SECONDS = 30.0


class VoiceManager:
    """Provider coordinator with speech queue and fallback.

    Usage::

        manager = VoiceManager()
        manager.speak("Hello")
        manager.speak("How are you?")   # queued, plays after "Hello"
        manager.cancel_all()            # stop + clear queue
        manager.speak("Urgent", priority=True)  # bumps ahead of queue
    """

    def __init__(self, config: Any = settings, bridge=None) -> None:
        self._settings = config
        self._diagnostics: list[str] = []
        self._queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._queue_lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None
        self._worker_start_lock = threading.Lock()
        self._stop_worker = threading.Event()
        self._current_text: str | None = None
        # Set when stop()/cancel_all() interrupts the in-flight utterance.
        # An interrupted utterance still counts as delivered (the user cut
        # real audio short) — it must never trigger fallback/retry loops.
        self._interrupted = False

        # Generation counter for generation-safe cancellation.
        # Each speak() increments this. cancel_all() captures the generation
        # at the time of call and only acts if no new speak() has occurred.
        self._generation = 0
        self._generation_lock = threading.Lock()

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
        # Provider-agnostic TTS lifecycle hooks, fired by the speech worker
        # around EVERY utterance (including fallback deliveries) in a
        # try/finally so the "finished" hook always runs: run.py uses
        # these for the mic-mute echo guard on providers that cannot feed
        # a PCM echo reference (e.g. the system SAPI voice).  Unlike the
        # player callbacks they fire regardless of which provider (or
        # fallback) actually delivered the audio, so a runtime provider
        # swap can never leave the microphone muted — or unguarded.
        self.on_utterance_started: Callable[[], None] | None = None
        self.on_utterance_finished: Callable[[], None] | None = None

        self._bridge = bridge

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

        with self._generation_lock:
            self._generation += 1
            current_gen = self._generation
        with self._activity_lock:
            self._pending_utterances += 1
            self._speech_finished_event.clear()
        self._ensure_worker()
        return True

    def stop(self, reason: str = "voice_manager.stop", caller: str = "unknown") -> None:
        """Stop current speech immediately.

        Interruption is a normal event (barge-in, cancellation, shutdown), so
        this never publishes an error state.  The previous version emitted
        ``ERROR / "Interrupted"`` here, which flipped the UI to a failure for
        a user who merely spoke over JARVIS.  Conversation state is owned by
        ``services.conversation_owner``; this manager only stops audio.
        """
        self._current_text = None
        self._interrupted = True
        self._log_stop_request(reason=reason, caller=caller)
        try:
            self._provider.stop()
        except Exception as exc:
            logger.debug("VoiceManager: provider.stop() failed: %s", exc)
        logger.info("VoiceManager: stopped current speech reason=%s caller=%s", reason, caller)

    def cancel_all(self, expected_generation: int | None = None) -> None:
        """Stop current speech and clear the entire queue.

        Pass *expected_generation* (a value read from :attr:`generation` when
        the caller enqueued its speech) to make the cancellation conditional:
        it is skipped when newer speech has been enqueued since, so an old
        task's cleanup can never kill newer audio.  Without it the
        cancellation is unconditional.

        The previous version read the generation and compared it against
        itself under the same lock, so that guard could never fire — the
        documented protection did not exist.
        """
        if expected_generation is not None:
            with self._generation_lock:
                current_generation = self._generation
            if current_generation != expected_generation:
                logger.debug(
                    "VoiceManager: cancel_all skipped — newer speech enqueued "
                    "(gen=%d vs expected=%d)",
                    current_generation, expected_generation,
                )
                return

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
        self.on_utterance_started = None
        self.on_utterance_finished = None
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
            # Timezone-aware: datetime.utcnow() is deprecated in 3.12+.
            datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "".join(traceback.format_stack(limit=8)).rstrip(),
        )
        logger.debug("VoiceManager: stop request originated from %s (%s)", callsite, caller)

    @property
    def generation(self) -> int:
        """Monotonic counter, bumped by every :meth:`speak`.

        Read it before enqueuing speech and pass the value to
        :meth:`cancel_all` to cancel only that utterance.
        """
        with self._generation_lock:
            return self._generation

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
                    speed=self._voice_speed(),
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
        try:
            self._provider = self._system_provider()
            logger.info("VoiceManager: System provider initialized successfully")
        except Exception as exc:
            logger.error("VoiceManager: Failed to initialize system provider: %s", exc)
            # As a last resort, create a minimal no-op provider
            from voice.provider import VoiceProvider
            class SilentProvider(VoiceProvider):
                def speak(self, text: str) -> bool:
                    logger.warning("VoiceManager: SilentProvider - no audio output available: %s", text[:40])
                    return True
                def stop(self) -> None:
                    pass
                @property
                def is_playing(self) -> bool:
                    return False
            self._provider = SilentProvider()

    def _fallback_to_piper(self, reason: str = "") -> None:
        """Switch to the local Piper provider (optimal offline fallback).

        When the Piper voice model file is missing, Piper's own ``speak()``
        will fail anyway — skip straight to the system voice (last resort)
        so the failed utterance never silently disappears.
        """
        if isinstance(self._provider, PiperProvider):
            return  # already using piper
        piper = self._piper_provider()
        if not piper.model_available:
            msg = f"Piper voice model missing ({piper.model_path}) — skipping to system voice"
            if reason:
                msg += f": {reason}"
            self._diagnostics.append(msg)
            logger.warning("VoiceManager: %s", msg)
            self._fallback_to_system(
                f"Piper voice model missing ({piper.model_path})"
            )
            return
        msg = f"Switching to Piper (local) voice provider"
        if reason:
            msg += f": {reason}"
        self._diagnostics.append(msg)
        logger.warning("VoiceManager: %s", msg)
        self._provider = piper

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
            self._interrupted = False
            start = time.monotonic()
            # Emit SPEAKING state
            if self._bridge is not None:
                try:
                    self._bridge.emit_speaking("Speaking...")
                except Exception as exc:
                    logger.debug("Bridge state emit failed: %s", exc)
            started_hook = self.on_utterance_started
            if started_hook is not None:
                try:
                    started_hook()
                except Exception as exc:
                    logger.error("VoiceManager: on_utterance_started hook failed: %s", exc)
            try:
                success = self._speak_with_fallback(text)
            finally:
                # Emit DONE state after speaking
                if self._bridge is not None:
                    try:
                        self._bridge.emit_done("Done speaking")
                    except Exception as exc:
                        logger.debug("Bridge state emit failed: %s", exc)
                finished_hook = self.on_utterance_finished
                if finished_hook is not None:
                    try:
                        finished_hook()
                    except Exception as exc:
                        logger.error("VoiceManager: on_utterance_finished hook failed: %s", exc)

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
            self._decrement_pending()

        logger.info("VoiceManager: worker stopped")

    def _playback_consumed(self) -> bool:
        """True when the current provider actually emitted audio.

        FIX 1: providers backed by VoicePlayer measure real bytes written;
        a 0-byte "success" (e.g. a stream that died before the first chunk)
        is a failure, never OK.  Providers without byte accounting (system
        voice) keep the legacy verdict.  An interrupted utterance always
        counts as delivered — the user cut real audio short.
        """
        if self._interrupted:
            return True
        player = getattr(self._provider, "player", None)
        consumed = getattr(player, "last_play_bytes", None) if player is not None else None
        if isinstance(consumed, bool):
            # Defensive: never treat a mock/flag as a byte count.
            return True
        if isinstance(consumed, int):
            if consumed > 0:
                return True
            logger.warning(
                "VoiceManager: provider reported success but 0 bytes reached "
                "the device (error=%r)",
                getattr(player, "last_play_error", None),
            )
            return False
        return True

    def _speak_with_fallback(self, text: str) -> bool:
        """Deliver one utterance, retrying it after provider fallback."""
        try:
            if self._provider.speak(text):
                self._wait_for_playback_end(text)
                if self._playback_consumed():
                    return True
                logger.warning(
                    "VoiceManager: no audio consumed for '%s' — failing over",
                    text[:40],
                )
        except Exception as exc:
            logger.error("VoiceManager: provider.speak() raised: %s", exc)

        reason = f"speak() failed for '{text[:40]}'"
        if isinstance(self._provider, ElevenLabsProvider):
            self._fallback_to_piper(reason)
        elif not isinstance(self._provider, SystemProvider):
            self._fallback_to_system(reason)

        try:
            success = self._provider.speak(text)
        except Exception as exc:
            logger.error("VoiceManager: fallback provider.speak() raised: %s", exc)
            return False
        if success:
            self._wait_for_playback_end(text)
            return self._playback_consumed()
        return False

    def _wait_for_playback_end(self, text: str) -> bool:
        """Block until the provider's audio has actually finished playing.

        Async providers (PowerShell subprocess, VoicePlayer) only report
        ``is_playing`` True once playback has begun, so give them a short
        startup window before concluding the utterance already finished
        (i.e. a synchronous provider).

        Returns True when playback was observed at any point (used with
        byte accounting to reach an honest verdict).
        """
        # VOICE-FIX: streaming providers report is_playing almost
        # immediately — keep the startup grace short so the worker does not
        # idle before observing playback.
        time.sleep(0.05)
        observed = bool(self._provider.is_playing)
        startup_deadline = time.monotonic() + 5.0
        playing = observed
        while not playing and time.monotonic() < startup_deadline:
            if self._stop_worker.is_set():
                return observed
            time.sleep(0.05)
            playing = self._provider.is_playing
            observed = observed or bool(playing)

        if not playing:
            return observed

        deadline = time.monotonic() + _PLAYBACK_MAX_WAIT_SECONDS
        while self._provider.is_playing:
            observed = True
            if self._stop_worker.is_set():
                break
            if time.monotonic() >= deadline:
                logger.warning(
                    "VoiceManager: playback did not finish within %.0fs — moving on",
                    _PLAYBACK_MAX_WAIT_SECONDS,
                )
                break
            time.sleep(0.05)
        return observed

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _provider_name(self) -> str:
        return str(
            getattr(self._settings, "voice_provider", "system")
        ).strip().casefold()

    def _system_provider(self) -> SystemProvider:
        return SystemProvider(voice_id="Microsoft Zira Desktop")

    def _piper_provider(self) -> PiperProvider:
        return PiperProvider(
            model_path=self._piper_model_path(),
            voice_name=self._piper_voice_name(),
        )

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

    def _piper_model_path(self) -> str:
        return str(
            getattr(self._settings, "piper_voice_model_path", "") or ""
        ).strip()

    def _piper_voice_name(self) -> str:
        return str(
            getattr(self._settings, "piper_voice_name", "en_US-lessac-medium")
            or "en_US-lessac-medium"
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

    def _voice_speed(self) -> float:
        val = getattr(self._settings, "voice_speed", None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return 1.25
