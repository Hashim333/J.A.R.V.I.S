# JARVIS Architecture

JARVIS is a Windows desktop assistant with a Qt Widgets shell, microphone-driven conversation loop, reasoning pipeline, and registered OS/browser automation.

## Runtime

`run.py` initializes configuration, logging, the microphone and duplex voice path, planner/registry/executor, `Brain`, and the conversation services. `ConversationOwner.run()` owns conversation state on a worker thread; the Qt event loop remains on the main thread. `--backend-only` starts without a window. A normal persistent launch owns the named process mutex; duplicate launches ask the existing window to show itself and exit.

`JarvisApp` creates the placeholder window, `Bridge`, tray, and `WindowManager`. The tray can show, hide, quit, and configure per-user login launch. Login launch uses the active Python environment's `pythonw.exe` and starts hidden when a tray is available.

## Backend and Voice

Commands flow through `ConversationOwner` to `Brain.process()`, the parser/planner and `Executor`. The executor validates each plan step and dispatches it through the action registry. `TaskManager` cancellation is cooperative at executor step boundaries.

`MicrophoneStream` captures audio and feeds one `DuplexVoiceSession` consumer. The session handles echo cancellation, noise reduction, VAD, and Faster-Whisper transcription. Wake-word detection uses Porcupine when configured and local Vosk otherwise. `VoiceManager` queues TTS and selects the configured provider with fallbacks.

## UI Contract

`Bridge` is the only backend-to-UI state channel. Its `coreStateChanged`, `subtitleChanged`, and `currentTaskChanged` signals publish the assistant's state. Backend calls made off the Qt thread are marshalled through queued Qt signals. Window visibility and quit requests also go through `Bridge`.

`WindowManager` owns show/hide operations for the current window. UI polling and presentation must not be performed by backend automation handlers.

## Lifecycle

`run.py` owns a named Windows mutex for a persistent instance; `.jarvis_backend.pid` is informational only. The local IPC endpoint forwards second-launch show requests. The tray's login-launch option writes the current interpreter path under the user's Windows Run key.

On quit, the app signals the conversation owner, stops the microphone and registered services, joins the backend worker, and releases the mutex and diagnostic PID file. Logs rotate at five megabytes with five backups.
