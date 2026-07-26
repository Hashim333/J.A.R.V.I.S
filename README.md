# JARVIS Desktop AI Assistant

## Quick Start

1. **Copy the environment template:**
   ```
   cp .env.example .env
   ```
2. **Edit `.env`** to set your API keys and preferences.
3. **Run JARVIS:**
   ```
   python run.py
   ```

## Configuration

JARVIS loads all settings from environment variables. The `.env` file is automatically loaded at startup — no manual exporting needed.

### Required Variables

| Variable | Required When | Notes |
|---|---|---|
| `OLLAMA_BASE_URL` | Always | Must start with `http://` or `https://` |
| `OLLAMA_MODEL` | Always | Must be a model pulled into your local Ollama |
| `OLLAMA_TIMEOUT` | Always | Must be a positive integer |
| `ELEVENLABS_API_KEY` | `VOICE_PROVIDER=elevenlabs` | See below for setup |
| `VOICE_ID` | `VOICE_PROVIDER=elevenlabs` | See below for setup |

### Optional Variables

All variables in `.env.example` have sensible defaults. You only need to configure what you want to change.

### Voice Setup

#### Option 1: ElevenLabs (cloud, high quality)

1. **Get an API key:**
   - Sign up at https://elevenlabs.io
   - Go to **Profile → API Keys**
   - Create a new key
2. **Find your Voice ID:**
   - Open https://elevenlabs.io/voice-lab
   - Select a voice
   - Copy the ID from the browser URL (e.g., `A2n0deBXrNcraJ2I9mUk`)
3. **Configure `.env`:**
   ```
   VOICE_ENABLED=true
   VOICE_PROVIDER=elevenlabs
   VOICE_ID=<your-voice-id>
   ELEVENLABS_API_KEY=<your-api-key>
   VOICE_MODEL=eleven_multilingual_v2
   ```

#### Option 2: System (Windows TTS, offline, free)

No API key needed:
```
VOICE_ENABLED=true
VOICE_PROVIDER=system
```

### Ollama Setup

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull qwen2.5:3b`
3. Ensure Ollama is running: `ollama serve`

### Configuration Validation

On startup, JARVIS validates the configuration and prints a summary:

```
Configuration Loaded
--------------------------------------------------

  Voice Provider:   Elevenlabs
  Voice Enabled:    Yes
  Voice ID:         A2n0deBXrNcraJ2I9mUk
  Model:            eleven_multilingual_v2
  API Key:          sk****45
  Ollama URL:       http://localhost:11434
  Ollama Model:     qwen2.5:3b
  Ollama Timeout:   30s
  Debug:            No
```

Validation warnings (e.g., missing API key, invalid URL) are printed to stderr. The application automatically falls back to safe defaults where possible.

### Security

- **Never commit `.env`** — it is listed in `.gitignore`
- API keys are masked in the startup summary (e.g., `sk****45`)
- Only `.env.example` is committed to version control
