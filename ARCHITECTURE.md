# JARVIS Architecture

JARVIS is a Windows desktop AI assistant with a PySide6/QML interface, a voice-first conversation loop, a local LLM planning pipeline, and automation handlers for apps, browser actions, keyboard, mouse, files, and accessibility tasks. The frontend is intentionally thin: it renders state, receives events through the bridge, and requests window-mode changes. The backend remains the source of behavior.

## Architecture Overview

The application has four main layers:

1. **Desktop shell**
   - `ui.app.JarvisApp` creates `QApplication`, `QQmlApplicationEngine`, the system tray, `Bridge`, and `WindowManager`.
   - `ui/qml/main.qml` renders the full dashboard, floating orb, edge dock, status panels, and animated AI core.
   - QML never talks directly to Brain, Planner, Executor, voice services, or automation modules.

2. **Runtime orchestration**
   - `run.py` is the primary entry point.
   - It constructs parser, planner, registry, executor, brain, voice services, conversation manager, microphone stream, and UI app.
   - It starts the backend loop on a daemon thread while Qt owns the main thread.

3. **Command intelligence**
   - `Brain.process(text)` coordinates `Parser -> Planner -> Executor`.
   - `Parser` converts natural language into a parsed command.
   - `Planner` turns parsed intent into an `ExecutionPlan`.
   - `Executor` validates and dispatches each plan step to a registered handler.

4. **Device, voice, and automation services**
   - Services keep the microphone, wake word, conversation state, and voice pipeline alive.
   - Automation handlers perform OS, app, browser, mouse, keyboard, file, and security actions.

## Folder Structure

```text
JARVIS/
  run.py                    Primary desktop runtime entry point
  main.py                   Reserved placeholder
  config/                   Environment-driven settings and aliases
  brain/                    Parser, planner, LLM, prompt, intent resolution
  executor/                 Execution dispatcher and handler registry
  models/                   Shared parsed command, plan, and response models
  services/                 Wake word, listener, conversation, service manager
  voice/                    Microphone stream, STT, TTS, VAD, voice providers
  automation/               App, browser, keyboard, mouse, window, file actions
  browser/                  Browser support modules
  memory/                   Short, long, file, preference, and vision memory
  response/                 Console and voice response formatting
  safety/                   Policy, validation, and audit logging
  accessibility/            Screen reading and visual accessibility helpers
  background/               Optional background monitors
  vision/                   OCR, screenshot, detector, UI understanding
  ui/
    app.py                  Qt app composition and tray setup
    bridge.py               Python-to-QML state and event boundary
    window_manager.py       Fullscreen, orb, dock, tray behavior
    config.py               UI performance and visual config
    qml/main.qml            Main dashboard composition
    qml/components/         Reusable QML visual components
    themes/                 Theme definitions
  dev_tests/                Focused tests for backend modules
```

## Startup Flow

1. `python run.py` loads configuration from `config.settings`.
2. If command-line arguments are present, JARVIS runs a single command through `Parser`, `Planner`, `Executor`, and exits.
3. In desktop mode, `run.py` constructs backend dependencies:
   - `Parser`
   - `Planner`
   - `Registry`
   - `ResponseManager`
   - `MicrophoneStream`
   - `ListenerService`
   - `WakeWordService`
   - `VoiceManager`
   - `VoiceEngine`
   - `VoiceConversationPipeline`
   - `ConversationManager`
4. Automation handlers are registered for app, browser, mouse, and keyboard actions.
5. The microphone stream starts.
6. `JarvisApp` creates Qt, the tray icon, `Bridge`, `WindowManager`, and loads QML.
7. The backend loop starts on a daemon thread.
8. The Qt event loop runs on the main thread.

## Voice Pipeline

The voice path is designed around one shared microphone stream.

1. `MicrophoneStream` captures audio continuously.
2. In `STANDBY`, `WakeWordService` monitors for the wake phrase.
3. When the wake word fires, `wake_word_detected` is set.
4. The backend loop updates the UI:
   - `bridge.wakeActive = True`
   - `bridge.set_core_state("listening")`
   - `bridge.show_subtitle("Listening...")`
5. `VoiceConversationPipeline.wait_for_command(...)` clears the wake event, plays confirmation, captures an utterance, and sends it to `ListenerService`.
6. On transcription success, the text enters the brain pipeline.
7. `ResponseManager` formats the result for display and voice.
8. `VoiceEngine` speaks responses through the selected provider.
9. `ConversationManager` moves between `STANDBY` and `ACTIVE_CONVERSATION`.

The voice pipeline does not import Brain, Planner, Executor, or automation modules. That separation keeps audio capture independent from command execution.

## UI Architecture

The UI is built from QML and driven by `Bridge` signals.

`ui/qml/main.qml` contains:

- Fullscreen dashboard frame
- Left navigation and system overview
- Animated central AI core
- State-aware waveform and conversation card
- Right quick status panel
- AI core state cards for idle, listening, thinking, and speaking
- Bottom always-accessible previews
- Integration preview cards
- Voice activity visualization
- Floating orb and edge dock windows

Reusable visual components live in `ui/qml/components/`:

- `AiCore.qml`
- `OrbitRing.qml`
- `ParticleField.qml`
- `VoiceWaveform.qml`
- `FloatingOrb.qml`
- `EdgeDock.qml`
- Supporting status, subtitle, sidebar, and indicator components

The QML layer only receives state and requests window modes. It does not own backend lifecycle.

## Window Manager

`ui.window_manager.WindowManager` owns window mode transitions:

- `fullscreen`
- `floating_orb`
- `edge_dock`
- `system_tray`

Startup mode is `fullscreen`, so the dashboard opens first. The floating orb appears only when:

- the user minimizes or requests it,
- the tray action requests it,
- the window manager detects a confirmed fullscreen foreground app.

The manager polls foreground windows after startup. It avoids switching modes for the JARVIS fullscreen window itself. Opening normal applications such as Notepad should not close the dashboard because the automatic switch only triggers for fullscreen foreground windows.

## Bridge

`ui.bridge.Bridge` is the single Python object exposed to QML as `bridge`.

It emits:

- Core state: `idle`, `listening`, `thinking`, `speaking`, `error`, `offline`
- Window mode
- Subtitles
- Wake indicator state
- Microphone and assistant energy
- Internet, microphone, speaker, CPU, RAM, GPU, battery, provider, model, and task status
- Sidebar state

QML calls bridge slots such as:

- `set_window_mode(mode)`
- `set_core_state(state)`
- `show_subtitle(text)`
- `set_sidebar_section(section)`

`JarvisApp` wires bridge window-mode requests back into `WindowManager`, and wires `WindowManager.modeChanged` back into the bridge. This keeps QML requests, tray requests, and automatic fullscreen detection on one path.

## Event System

JARVIS uses three event styles:

1. **Qt signals**
   - Bridge-to-QML updates.
   - WindowManager-to-Bridge mode updates.

2. **Threading primitives**
   - `threading.Event` for wake word detection.
   - `queue.Queue` for debug text commands from stdin.

3. **Service callbacks and polling**
   - `ServiceManager` initializes, starts, and shuts down services.
   - `WindowManager` polls foreground windows.
   - QML timers animate visual state at the UI layer.

The backend thread communicates with QML only through thread-safe Qt signal emission on the bridge.

## Conversation Flow

Text command flow:

```text
stdin/debug input
  -> command_queue
  -> backend loop
  -> bridge.set_core_state("thinking")
  -> Brain.process(text)
  -> Parser.parse(text)
  -> Planner.create_plan(parsed)
  -> Executor.execute(plan)
  -> ResponseManager formats result
  -> bridge.show_subtitle(...)
  -> VoiceEngine.speak(...)
  -> bridge.set_core_state("idle")
```

Voice command flow:

```text
WakeWordService
  -> wake_word_detected event
  -> VoiceConversationPipeline
  -> ListenerService transcription
  -> Brain.process(text)
  -> Executor dispatch
  -> ResponseManager
  -> VoiceEngine
  -> ConversationManager active/standby transitions
```

Clarification and confirmation are handled in the backend loop. If Brain or Executor returns a response with `needs_clarification`, the loop asks for confirmation by text or voice, then re-runs the command with `confirmed=True` when appropriate.

## Browser Automation

Browser automation is registered in `run.py` through `BrowserHandler`.

Supported browser-oriented actions include:

- open website
- search
- navigate or browser search where planned

The executor validates URLs before dispatch. Known website aliases may be expanded before validation. Browser actions are separated from UI rendering; the QML dashboard only displays the result through bridge subtitles and state changes.

Browser context awareness belongs in the automation and browser modules, not the QML layer. Future browser extensions or sidebars should communicate through a small bridge/API layer rather than importing UI components directly.

## Automation Dispatch

`Executor` receives an `ExecutionPlan` and runs each `Step`.

Before a handler is called, `Executor` applies:

- safe-mode checks,
- parameter sanitization,
- URL validation,
- file path validation,
- dangerous-action confirmation,
- app existence checks,
- audit logging.

Handlers are registered by action name. Current desktop startup registers:

- `open_app`
- `close_app`
- `open_website`
- `search`
- `move_mouse`
- `left_click`
- `right_click`
- `double_click`
- `scroll`
- `type_text`
- `hotkey`

The automation adapter layer lives in `automation/handlers.py`.

## LLM and Planning

The LLM layer is in `brain/llm.py` and configuration is read through `config.settings`. The default setup targets local Ollama models, with the model name shown in the UI via `bridge.set_model(settings.model)`.

The planner is responsible for turning parsed intent into executable steps. The executor should not invent intent; it should validate and run the plan it receives.

## Memory

Memory modules are present but loosely coupled:

- `short_memory.py`
- `long_memory.py`
- `file_memory.py`
- `preferences.py`
- `vision_memory.py`
- `database.py`

Memory should be integrated through Brain, Planner, or dedicated services. UI components should display memory-derived state only through Bridge properties or future explicit signals.

## Extension Points

Add new capabilities by extending the narrowest layer possible:

- New natural language behavior: update Parser and Planner.
- New executable action: add a handler and register it in `run.py`.
- New safety rule: update `safety.policy` or validators.
- New UI indicator: add a Bridge signal/property and bind QML to it.
- New voice provider: implement the provider interface in `voice/`.
- New background monitor: add a service and register it with `ServiceManager`.
- New browser integration: extend browser automation and expose status through Bridge.

Keep dependencies directional:

```text
UI -> Bridge only
Bridge -> no automation imports
Brain -> Parser/Planner/Executor
Executor -> Registry/Handlers/Safety
Voice pipeline -> voice/listener/microphone services only
```

## Future Agents Module

The UI includes an Agents navigation item marked as future work. The expected architecture is:

```text
Agents UI
  -> Bridge agent signals
  -> AgentService
  -> AgentRegistry
  -> Tool/skill adapters
  -> Planner or Executor integration
```

Agents should not bypass SafetyPolicy or AuditLog. Any agent action that affects the OS, files, browser, or apps should still produce an execution plan or a validated executor step. Agent state should be observable through bridge events, not direct QML imports.

## Runtime Guarantees

The intended guarantees are:

- Main dashboard opens first.
- Floating orb is secondary and appears only by request or fullscreen-app behavior.
- Backend services continue while QML animates.
- QML renders backend state but does not block backend threads.
- Normal application launches do not close JARVIS.
- Safety validation remains between planned actions and OS automation.
- Architecture boundaries keep the frontend replaceable without rewriting Brain, Parser, Planner, Executor, voice, or automation.

