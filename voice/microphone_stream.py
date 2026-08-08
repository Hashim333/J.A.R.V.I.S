"""
voice/microphone_stream.py

A non-blocking, continuous microphone stream.

The microphone is opened ONCE in start() and kept open until
shutdown().  Between those two calls, the capture thread runs
continuously.  Consumers (callbacks) can be swapped at any time
via set_consumer() without closing or reopening the mic.

Methods:
  start()        — open mic, start capture thread (idempotent)
  stop()         — pause the consumer (mic stays open, thread runs)
  shutdown()     — close mic, stop thread, release resources (final)
  set_consumer() — atomically swap the audio chunk callback
  capture_utterance() — VAD-based one-shot command capture
"""
import audioop
import collections
import logging
import threading
import time
from typing import Any, Callable

import speech_recognition as sr

from monitoring.pipeline_trace import stage_entry, stage_exit
from voice.audio_lock import audio_lock

logger = logging.getLogger(__name__)


class MicrophoneStream:
    """A non-blocking, continuous microphone stream."""

    def __init__(
        self,
        microphone_factory: Callable[..., Any] | None = None,
        chunk_size: int = 1024,
        sample_rate: int = 16000,
        on_audio_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        self._microphone_factory = microphone_factory or sr.Microphone
        self._chunk_size = chunk_size
        self._sample_rate = sample_rate
        self._consumer: Callable[[bytes], None] | None = on_audio_chunk
        self._stream = None
        self._thread = None
        self._microphone = None
        self._source_sample_rate = sample_rate
        self._sample_width = 2
        self._channels = 1
        self._resample_state = None
        self._is_running = False
        self._started = False
        self._lock = threading.Lock()
        self._processor = None
        self._on_audio_level: Callable[[float], None] | None = None
        self._muted: bool = False

    def _probe_default_input_format(self) -> None:
        """Log the PyAudio default input format before opening the stream."""
        try:
            pyaudio_module = sr.Microphone.get_pyaudio()
            audio = pyaudio_module.PyAudio()
            try:
                info = audio.get_default_input_device_info()
                device_index = int(info.get("index"))
                default_rate = int(info.get("defaultSampleRate"))
                sample_width = audio.get_sample_size(pyaudio_module.paInt16)
                try:
                    supports_requested = audio.is_format_supported(
                        self._sample_rate,
                        input_device=device_index,
                        input_channels=1,
                        input_format=pyaudio_module.paInt16,
                    )
                except Exception as exc:
                    supports_requested = f"no ({exc})"

                logger.info(
                    "PyAudio default input: device=%r, index=%s, "
                    "defaultSampleRate=%d Hz, maxInputChannels=%s, "
                    "paInt16_sample_width=%d bytes, requested_mono_16bit_%dHz=%s",
                    info.get("name"),
                    info.get("index"),
                    default_rate,
                    info.get("maxInputChannels"),
                    sample_width,
                    self._sample_rate,
                    supports_requested,
                )
            finally:
                audio.terminate()
        except Exception as exc:
            logger.warning("Could not probe PyAudio default input format: %s", exc)

    def _notify_audio_format(self) -> None:
        """Tell the downstream detector exactly what format chunks will use."""
        callback_owner = getattr(self._consumer, "__self__", None)
        set_audio_format = getattr(callback_owner, "set_audio_format", None)
        if callable(set_audio_format):
            set_audio_format(
                sample_rate=self._sample_rate,
                sample_width=self._sample_width,
                channels=self._channels,
            )

    def _normalize_chunk(self, audio_chunk: bytes) -> bytes:
        """Convert microphone PCM to the pipeline PCM format if needed."""
        if self._source_sample_rate == self._sample_rate:
            return audio_chunk

        converted, self._resample_state = audioop.ratecv(
            audio_chunk,
            self._sample_width,
            self._channels,
            self._source_sample_rate,
            self._sample_rate,
            self._resample_state,
        )
        return converted

    def set_consumer(self, consumer: Callable[[bytes], None] | None) -> None:
        """
        Atomically swap the audio chunk consumer.

        The capture thread will call *consumer* for every audio chunk
        (after format normalisation and optional processing).  Pass
        *None* to pause processing (chunks are silently discarded).
        """
        self._consumer = consumer
        logger.debug(
            "MicrophoneStream consumer -> %s",
            getattr(consumer, "__name__", type(consumer).__name__)
            if consumer is not None
            else "None",
        )

    def set_processor(self, processor: Any) -> None:
        """Attach a MicrophoneProcessor for AGC / noise gate / normalisation.

        The processor's start() is called automatically when the stream
        starts, and shutdown() when the stream shuts down.
        """
        self._processor = processor

    def set_on_audio_level(self, callback: Callable[[float], None] | None) -> None:
        """Register a callback for periodic audio level reports (0.0-1.0)."""
        self._on_audio_level = callback

    def mute(self) -> None:
        """Mute mic processing. Audio chunks are discarded until unmute()."""
        self._muted = True
        logger.debug("MicrophoneStream: muted")

    def unmute(self) -> None:
        """Restore mic processing."""
        self._muted = False
        logger.debug("MicrophoneStream: unmuted")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the microphone and start the capture thread (one-time)."""
        with self._lock:
            if self._started:
                logger.debug("start() called but already started")
                return
            self._started = True

            if not audio_lock.acquire("microphone_stream", timeout=5.0):
                raise RuntimeError(
                    "Could not start microphone stream: another component "
                    f"({audio_lock.owner}) is using the microphone"
                )

            try:
                self._probe_default_input_format()
                self._microphone = self._microphone_factory(
                    sample_rate=self._sample_rate, chunk_size=self._chunk_size
                )
                self._microphone.__enter__()
                self._stream = self._microphone.stream
                if self._stream is None:
                    raise RuntimeError(
                        "Microphone stream is None after __enter__; "
                        "audio device may not be available"
                    )

                sr_value = getattr(self._microphone, "SAMPLE_RATE", self._sample_rate)
                sw_value = getattr(self._microphone, "SAMPLE_WIDTH", 2)
                chunk_value = getattr(self._microphone, "CHUNK", self._chunk_size)
                self._source_sample_rate = int(sr_value)
                self._sample_width = int(sw_value)
                self._channels = 1
                self._resample_state = None

                source_bytes_per_sec = (
                    self._source_sample_rate * self._sample_width * self._channels
                )
                output_bytes_per_sec = (
                    self._sample_rate * self._sample_width * self._channels
                )
                logger.info(
                    "SpeechRecognition Microphone opened: sample_rate=%d Hz, "
                    "channels=%d, sample_width=%d bytes, chunk_size=%d frames, "
                    "expected_chunk_duration=%.1f ms, expected_chunk_bytes=%d, "
                    "bytes_per_second=%d",
                    self._source_sample_rate,
                    self._channels,
                    self._sample_width,
                    chunk_value,
                    chunk_value / self._source_sample_rate * 1000,
                    chunk_value * self._sample_width * self._channels,
                    source_bytes_per_sec,
                )
                logger.info(
                    "MicrophoneStream output format: sample_rate=%d Hz, channels=%d, "
                    "sample_width=%d bytes, bytes_per_second=%d",
                    self._sample_rate,
                    self._channels,
                    self._sample_width,
                    output_bytes_per_sec,
                )
                if self._source_sample_rate != self._sample_rate:
                    logger.warning(
                        "Microphone source rate %d Hz != pipeline rate %d Hz; "
                        "MicrophoneStream will resample before VAD and Vosk",
                        self._source_sample_rate,
                        self._sample_rate,
                    )
                self._notify_audio_format()

                self._is_running = True
                self._thread = threading.Thread(target=self._capture_loop)
                self._thread.daemon = True
                self._thread.start()
                if self._processor is not None:
                    self._processor.start()
                logger.info(
                    "Microphone stream started (sample_rate=%d, chunk_size=%d)",
                    self._sample_rate,
                    self._chunk_size,
                )
            except Exception:
                audio_lock.release("microphone_stream")
                self._started = False
                raise

    def stop(self) -> None:
        """
        Pause audio processing.

        The microphone stays open and the capture thread keeps running;
        audio chunks are silently discarded until a consumer is set again.
        """
        self.set_consumer(None)
        logger.info("Microphone stream paused (consumer set to None)")

    def shutdown(self) -> None:
        """Fully stop the microphone stream.  Idempotent — safe to call multiple times."""
        logger.info("Microphone stream shutting down")
        with self._lock:
            if not self._is_running:
                logger.debug("shutdown() called but not running")
                return
            self._is_running = False

        if self._stream:
            try:
                self._stream.stop_stream()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass

        if self._processor is not None:
            try:
                self._processor.shutdown()
            except Exception:
                pass

        if self._microphone:
            try:
                self._microphone.__exit__(None, None, None)
            except Exception:
                pass

        try:
            audio_lock.release("microphone_stream")
        except Exception:
            pass

        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Capture thread did not exit within 5s timeout.")
            self._thread = None

        with self._lock:
            self._stream = None
            self._microphone = None
        logger.info("Microphone stream fully shut down")

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        logger.info("Capture loop started")

        count = 0
        source_byte_count = 0
        output_byte_count = 0
        last_log_time = time.monotonic()
        last_read_elapsed_ms = 0.0
        level_report_count = 0

        while self._is_running:
            try:
                read_started = time.monotonic()
                source_chunk = self._stream.read(self._chunk_size)
                last_read_elapsed_ms = (time.monotonic() - read_started) * 1000
                audio_chunk = self._normalize_chunk(source_chunk)

                if self._processor is not None:
                    try:
                        audio_chunk = self._processor.process_chunk(audio_chunk)
                    except Exception as exc:
                        logger.error("Processor failed: %s", exc, exc_info=True)

                count += 1
                source_byte_count += len(source_chunk)
                output_byte_count += len(audio_chunk)

                level_report_count += 1
                if level_report_count >= 5 and self._on_audio_level is not None:
                    level_report_count = 0
                    try:
                        level = (
                            self._processor.audio_level
                            if self._processor is not None
                            else 0.0
                        )
                        self._on_audio_level(level)
                    except Exception:
                        pass

                now = time.monotonic()
                elapsed = now - last_log_time
                if elapsed >= 2.0:
                    source_bytes_per_sec = source_byte_count / elapsed
                    output_bytes_per_sec = output_byte_count / elapsed
                    expected_source_duration_ms = (
                        source_byte_count
                        / (self._source_sample_rate * self._sample_width * self._channels)
                        * 1000
                    )
                    expected_output_duration_ms = (
                        output_byte_count
                        / (self._sample_rate * self._sample_width * self._channels)
                        * 1000
                    )
                    estimated_source_rate = round(
                        source_bytes_per_sec / (self._sample_width * self._channels)
                    )
                    logger.debug(
                        "Microphone throughput: source=%d bytes "
                        "(%.0f bytes/s, expected_duration=%.0f ms), "
                        "output=%d bytes (%.0f bytes/s, expected_duration=%.0f ms), "
                        "actual_window=%.0f ms, last_read=%.1f ms, "
                        "estimated_source_rate=%d Hz, declared_source_rate=%d Hz, "
                        "pipeline_rate=%d Hz",
                        source_byte_count,
                        source_bytes_per_sec,
                        expected_source_duration_ms,
                        output_byte_count,
                        output_bytes_per_sec,
                        expected_output_duration_ms,
                        elapsed * 1000,
                        last_read_elapsed_ms,
                        estimated_source_rate,
                        self._source_sample_rate,
                        self._sample_rate,
                    )

                    source_byte_count = 0
                    output_byte_count = 0
                    last_log_time = now

                if count % 100 == 0:
                    logger.debug("Read %d chunks", count)

                consumer = self._consumer
                if consumer is not None and not self._muted:
                    try:
                        consumer(audio_chunk)
                    except Exception as exc:
                        logger.error("Audio consumer failed: %s", exc, exc_info=True)

            except IOError:
                logger.debug("Buffer overflow")

            except OSError:
                logger.warning("Microphone device error — recovery attempt")
                time.sleep(0.5)
                try:
                    self._stream.stop_stream()
                    self._stream.start_stream()
                except Exception:
                    logger.error("Microphone stream restart failed — shutting down capture")
                    self._is_running = False

            except Exception as exc:
                logger.error("Unexpected stream error: %s — continuing", exc, exc_info=True)

        logger.info("Capture loop exited")

    # ------------------------------------------------------------------
    # One-shot utterance capture (for follow-up commands)
    # ------------------------------------------------------------------

    def capture_utterance(self, timeout: float = 10.0) -> sr.AudioData | None:
        """
        Capture a single utterance using VAD-based end-of-speech detection.

        Blocks the calling thread until speech ends or *timeout* seconds
        elapse.  The captured audio (including any silence before speech)
        is returned as an ``sr.AudioData`` instance suitable for
        transcription.

        This method temporarily installs a consumer that buffers audio
        and detects speech boundaries via WebRTC VAD.  The previous
        consumer is restored before returning.

        Returns:
            ``sr.AudioData`` with the captured utterance, or *None* if
            no audio was captured within the timeout.
        """
        from voice.vad import VAD

        start = stage_entry("capture_utterance", input_=timeout)

        buffer = bytearray()
        done = threading.Event()

        vad = VAD(
            on_speech_started=None,
            on_speech_ended=lambda: done.set(),
            sample_rate=self._sample_rate,
        )

        def _consumer(chunk: bytes) -> None:
            buffer.extend(chunk)
            vad.process_audio(chunk)

        with self._lock:
            old_consumer = self._consumer
            self._consumer = _consumer
            # Echo-prevention may have muted the mic right before capture.
            # Force it open for the duration of this capture.
            was_muted = self._muted
            self._muted = False

        captured = done.wait(timeout=timeout)

        with self._lock:
            # Only restore if our consumer is still active (not swapped by another caller)
            if self._consumer is _consumer:
                self._consumer = old_consumer
            self._muted = was_muted  # restore the pre-capture mute state

        if captured and buffer:
            logger.info(
                "capture_utterance: %d bytes captured via VAD end-of-speech",
                len(buffer),
            )
            stage_exit("capture_utterance", start, status="OK", output="vad_end")
            return sr.AudioData(
                bytes(buffer), self._sample_rate, self._sample_width
            )

        if buffer:
            logger.info(
                "capture_utterance: %d bytes captured (timeout, no VAD end)",
                len(buffer),
            )
            stage_exit("capture_utterance", start, status="OK", output="timeout_with_audio")
            return sr.AudioData(
                bytes(buffer), self._sample_rate, self._sample_width
            )

        logger.info("capture_utterance: no audio captured (timeout)")
        stage_exit("capture_utterance", start, status="TIMEOUT", output="no_audio")
        return None
