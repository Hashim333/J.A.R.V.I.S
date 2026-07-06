"""
voice/vad.py

Voice Activity Detection (VAD) using the webrtcvad library.
"""
from __future__ import annotations

import collections
from typing import Callable

import webrtcvad


class VAD:
    """
    Voice Activity Detection (VAD) that processes audio chunks and triggers
    callbacks for speech start and end.
    """

    def __init__(
        self,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_ended: Callable[[], None] | None = None,
        aggressiveness: int = 1,
        frame_duration_ms: int = 30,
        padding_duration_ms: int = 300,
        sample_rate: int = 16000,
    ) -> None:
        self._on_speech_started = on_speech_started
        self._on_speech_ended = on_speech_ended
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._padding_duration_ms = padding_duration_ms

        # Initialize VAD
        self._vad = webrtcvad.Vad()
        self._vad.set_mode(aggressiveness)

        # Calculate frame size and padding frames
        self._frame_size = int(
            self._sample_rate * (self._frame_duration_ms / 1000.0)
        )
        num_padding_frames = int(self._padding_duration_ms / self._frame_duration_ms)

        # Ring buffer to hold audio frames
        self._ring_buffer = collections.deque(
            maxlen=num_padding_frames
        )
        self._triggered = False

    def process_audio(self, audio_chunk: bytes) -> None:
        """
        Process a chunk of audio data and detect speech.
        """
        if len(audio_chunk) != self._frame_size * 2:  # 16-bit samples
            # This can happen if the audio stream is not perfectly aligned
            # with the frame size. We will ignore this chunk.
            # A more robust implementation might buffer and frame the audio.
            return

        is_speech = self._vad.is_speech(audio_chunk, self._sample_rate)
        # print("DEBUG:", is_speech)
        if not self._triggered:
            self._ring_buffer.append((audio_chunk, is_speech))
            num_voiced = len([f for f, s in self._ring_buffer if s])
            if num_voiced > 0.9 * self._ring_buffer.maxlen:
                self._triggered = True
                if self._on_speech_started:
                    self._on_speech_started()
                self._ring_buffer.clear()
        else:
            self._ring_buffer.append((audio_chunk, is_speech))
            num_unvoiced = len([f for f, s in self._ring_buffer if not s])
            if num_unvoiced > 0.9 * self._ring_buffer.maxlen:
                self._triggered = False
                if self._on_speech_ended:
                    self._on_speech_ended()
                self._ring_buffer.clear()

