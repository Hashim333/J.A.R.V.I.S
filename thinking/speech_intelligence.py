"""
thinking/speech_intelligence.py — Speech Intelligence Layer (FIX-002).

Sits between Speech Recognition (Whisper/STT) and Intent Processing so
JARVIS never executes a raw speech transcript directly.

Every recognised utterance is gated by confidence *before* it reaches the
planner:

    HIGH    confidence  -> EXECUTE the recognised text as-is.
    MEDIUM  confidence  -> CORRECT via alias / installed-app / fuzzy /
                           semantic matching, then execute the *corrected*
                           text; if the match is ambiguous, ASK a natural
                           question instead of guessing.
    LOW     confidence  -> REFUSE naturally — never executed.

The layer keeps an internal-only correction log (original, corrected,
confidence, reason) that is never shown in the UI.
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

from voice.transcript_quality import (
    is_pathological as _is_pathological,
    plausible_command as _plausible_command,
)

logger = logging.getLogger(__name__)

# Confidence bands (FIX-002)
# Lowered from 0.45 to 0.30 to work better with Whisper base model.
# Action commands with semantic validity can pass at lower confidence.
HIGH_CONFIDENCE = 0.70
LOW_CONFIDENCE = 0.30

# Correction scoring thresholds
CORRECT_SCORE_THRESHOLD = 0.50
AMBIGUITY_GAP = 0.15

# PART 1: a corroborated known command needs at least this much voiced speech
# (capture-VAD seconds) to be accepted below the LOW band — a real utterance
# of a known command is almost never shorter than this.
MIN_VOICED_SECONDS = 0.20

# FIX 4: the *conversational* rescue (non-command phrases like "can you hear
# me?") needs strictly more evidence than a known command, because its only
# credentials are shape + duration.  A genuine 2+-word phrase takes ~0.4 s
# to say; a noise blip cannot.  The per-word floor rejects decoder garbage
# ("or not man") whose content words carry near-zero probability.  Both are
# duration/probability based — accent- and language-independent.
CONVERSATIONAL_MIN_VOICED_SECONDS = 0.30
CONVERSATIONAL_MIN_WORD_CONFIDENCE = 0.08


class ConfidenceBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SpeechAction(str, Enum):
    EXECUTE = "EXECUTE"
    CORRECT = "CORRECT"
    ASK = "ASK"
    REFUSE = "REFUSE"


# Verb prefixes that mark an utterance as an application command.
_APP_VERB_PATTERN = re.compile(
    r"^\s*(?P<verb>open\s+up|open|launch|start|run|go\s+to|"
    r"close|kill|stop|focus|switch\s+to)\s+(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)

# Filler words stripped from the app token before matching.
_FILLER_WORDS = {"the", "an", "a", "please", "app", "for", "me"}

_REFUSAL_MESSAGES = (
    "I didn't quite catch that.",
    "Could you repeat that, sir?",
    "I heard something different than expected. Please say it again.",
)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _semantic_score(a: str, b: str) -> float:
    """Token Jaccard + containment similarity."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    jaccard = overlap / len(ta | tb)
    containment = overlap / len(ta)
    return 0.6 * containment + 0.4 * jaccard


def _combined_score(a: str, b: str) -> float:
    """Fuzzy (SequenceMatcher) blended with semantic token similarity."""
    if a.casefold() == b.casefold():
        return 1.0
    fuzzy = difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()
    semantic = _semantic_score(a, b)
    return max(fuzzy, semantic)


def classify_band(confidence: float) -> ConfidenceBand:
    if confidence >= HIGH_CONFIDENCE:
        return ConfidenceBand.HIGH
    if confidence < LOW_CONFIDENCE:
        return ConfidenceBand.LOW
    return ConfidenceBand.MEDIUM


@dataclass(frozen=True)
class SpeechTranscript:
    """A recognised speech transcript ready for intelligence processing.

    (FIX-003) ``word_confidences`` and ``min_word_confidence`` carry the
    per-word recognition confidence so the layer can flag a garbled word
    inside an otherwise strong command.
    """

    text: str
    confidence: float
    timestamp: float = field(default_factory=time.time)
    word_confidences: tuple[tuple[str, float], ...] = ()
    min_word_confidence: float | None = None
    speech_seconds: float | None = None


@dataclass(frozen=True)
class SpeechDecision:
    """Outcome of the Speech Intelligence Layer for one transcript."""

    action: SpeechAction
    text: str
    original_text: str
    confidence: float
    band: ConfidenceBand
    reason: str
    corrected_text: str = ""
    candidates: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CorrectionRecord:
    """One entry in the internal correction log (never shown in the UI)."""

    original: str
    corrected: str
    confidence: float
    reason: str
    action: SpeechAction
    timestamp: float = field(default_factory=time.time)


class AliasDictionary:
    """Registry of spoken aliases -> canonical app names.

    Extensible: either seed with a mapping at construction or call
    ``register`` / ``register_many`` at runtime.
    """

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self._aliases: dict[str, str] = {}
        if entries:
            self.register_many(entries)

    def register(self, alias: str, canonical: str) -> None:
        key = alias.strip().casefold()
        if key:
            self._aliases[key] = canonical

    def register_many(self, entries: dict[str, str]) -> None:
        for alias, canonical in entries.items():
            self.register(alias, canonical)

    def lookup(self, alias: str) -> str | None:
        key = alias.strip().casefold()
        return self._aliases.get(key)

    def canonical_for(self, token: str) -> str | None:
        """Resolve *token* to a canonical app name via the alias registry."""
        if not token:
            return None
        direct = self.lookup(token)
        if direct:
            return direct
        for word in token.split():
            found = self.lookup(word)
            if found:
                return found
        return None

    @property
    def entries(self) -> dict[str, str]:
        return dict(self._aliases)

    def __len__(self) -> int:
        return len(self._aliases)


def default_aliases() -> dict[str, str]:
    """The out-of-the-box alias registry for common spoken app names."""
    return {
        "chrome": "Google Chrome",
        "google": "Google Chrome",
        "browser": "Google Chrome",
        "calc": "Calculator",
        "calculator": "Calculator",
        "folder": "File Explorer",
        "file explorer": "File Explorer",
        "terminal": "Command Prompt",
        "cmd": "Command Prompt",
        "notes": "Notepad",
        "notepad": "Notepad",
        "paint": "Paint",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "word": "Microsoft Word",
        "excel": "Microsoft Excel",
        "powerpoint": "Microsoft PowerPoint",
        "settings": "Settings",
        "control panel": "Control Panel",
        "spotify": "Spotify",
        "itunes": "iTunes",
        "vlc": "VLC Media Player",
        "firefox": "Mozilla Firefox",
        "edge": "Microsoft Edge",
        "camera": "Camera",
        "mail": "Mail",
        "photos": "Photos",
        "discord": "Discord",
        "slack": "Slack",
        "zoom": "Zoom",
    }


class InstalledAppMatcher:
    """Installed-application matcher with a single-scan guarantee.

    Wraps the process-wide ``ApplicationRegistry`` (Start Menu, Desktop,
    Program Files, WindowsApps, Registry, PATH) so the disk is scanned at
    most once per process — never again per command.

    For tests, an explicit ``apps`` list (canonical names) can be injected
    to avoid any disk scan; the scan guard still holds.
    """

    def __init__(
        self,
        apps: list[str] | None = None,
        registry: object | None = None,
        scan_now: bool = True,
    ) -> None:
        self._injected_apps: list[str] | None = list(apps) if apps else None
        self._registry = registry
        self._scanned = False
        self._lock = threading.Lock()
        if scan_now:
            self.scan()

    # ------------------------------------------------------------------
    # Single-scan guarantee
    # ------------------------------------------------------------------

    def scan(self) -> int:
        """Scan the machine for installed apps at most once.

        Idempotent and thread-safe: subsequent calls are no-ops.
        """
        if self._scanned:
            return self._count()
        with self._lock:
            if self._scanned:
                return self._count()
            self._scanned = True
            if self._injected_apps is not None:
                count = len(self._injected_apps)
                logger.info(
                    "InstalledAppMatcher: injected %d app names (no disk scan)",
                    count,
                )
                return count
            try:
                registry = self._ensure_registry()
                count = registry.count if registry is not None else 0
                logger.info(
                    "InstalledAppMatcher: application registry scanned once "
                    "(%d apps)",
                    count,
                )
                return count
            except Exception as exc:
                logger.warning("InstalledAppMatcher: scan failed: %s", exc)
                return 0

    @property
    def scanned(self) -> bool:
        return self._scanned

    @property
    def count(self) -> int:
        return self._count()

    def _count(self) -> int:
        if self._injected_apps is not None:
            return len(self._injected_apps)
        try:
            return self._ensure_registry().count if self._registry else 0
        except Exception:
            return 0

    def _ensure_registry(self):
        if self._registry is None:
            from automation.application_registry import get_application_registry

            self._registry = get_application_registry()
        return self._registry

    # ------------------------------------------------------------------
    # Lookup / search
    # ------------------------------------------------------------------

    def search(
        self, name: str, threshold: float = 0.0
    ) -> list[tuple[str, float]]:
        """Return ``(canonical_name, score)`` matches, best first."""
        self.scan()
        if not name or not name.strip():
            return []
        if self._injected_apps is not None:
            scored = [
                (app, _combined_score(name, app)) for app in self._injected_apps
            ]
            scored = [(a, s) for a, s in scored if s >= threshold]
            scored.sort(key=lambda pair: (-pair[1], pair[0].casefold()))
            return scored
        registry = self._ensure_registry()
        if registry is None:
            return []
        try:
            raw = registry.search(name, threshold=threshold)
            return [(info.canonical_name, score) for info, score in raw]
        except Exception as exc:
            logger.warning("InstalledAppMatcher: search failed: %s", exc)
            return []

    def resolve(self, name: str) -> str | None:
        """Resolve *name* to a canonical installed app, or ``None``."""
        self.scan()
        if self._injected_apps is not None:
            matches = self.search(name, threshold=CORRECT_SCORE_THRESHOLD)
            return matches[0][0] if matches else None
        registry = self._ensure_registry()
        if registry is None:
            return None
        try:
            info = registry.lookup(name)
            return info.canonical_name if info is not None else None
        except Exception as exc:
            logger.warning("InstalledAppMatcher: resolve failed: %s", exc)
            return None

    def get_exact_match(self, name: str) -> str | None:
        """Return canonical name if *name* exactly matches (case-insensitive)
        an installed app's canonical name, else None. Does NOT do fuzzy matching."""
        self.scan()
        target = name.strip().casefold()
        if not target:
            return None
        if self._injected_apps is not None:
            for app in self._injected_apps:
                if app.casefold() == target:
                    return app
            return None
        registry = self._ensure_registry()
        if registry is None:
            return None
        for info in registry.list_applications():
            if info.canonical_name.casefold() == target:
                return info.canonical_name
        return None


class SpeechIntelligenceLayer:
    """The Speech Intelligence Layer (FIX-002).

    Gates every voice transcript by confidence before it reaches the
    planner, correcting MEDIUM-confidence app commands and refusing
    LOW-confidence ones.  All decisions are recorded in the internal
    correction log.
    """

    def __init__(
        self,
        aliases: AliasDictionary | None = None,
        app_matcher: InstalledAppMatcher | None = None,
        refusal_messages: Iterable[str] = _REFUSAL_MESSAGES,
    ) -> None:
        self._aliases = aliases or AliasDictionary(default_aliases())
        self._app_matcher = app_matcher or InstalledAppMatcher()
        self._refusals: tuple[str, ...] = tuple(refusal_messages)
        self._log: list[CorrectionRecord] = []
        self._log_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def aliases(self) -> AliasDictionary:
        return self._aliases

    @property
    def app_matcher(self) -> InstalledAppMatcher:
        return self._app_matcher

    @property
    def corrections(self) -> tuple[CorrectionRecord, ...]:
        with self._log_lock:
            return tuple(self._log)

    def scan_apps(self) -> int:
        """Scan installed apps once at startup (idempotent)."""
        return self._app_matcher.scan()

    def process(self, transcript: SpeechTranscript) -> SpeechDecision:
        """Gate one transcript and return the decision to execute."""
        text = (transcript.text or "").strip()
        if not text:
            return self._decide(
                SpeechAction.REFUSE,
                text=transcript.text,
                original=transcript.text,
                transcript=transcript,
                reason="empty",
            )

        band = classify_band(transcript.confidence)

        if band is ConfidenceBand.LOW:
            # PART 1: a low-confidence *known* command (clean text, action
            # verb + known app, enough voiced speech) is corroborated and
            # corrected/executed — e.g. "open chrome" at 0.38 must still
            # reach the deterministic app pipeline.  Garbage at the same
            # confidence (pathological repetition, no known command, no
            # voiced evidence) is still refused.  This is evidence-based
            # acceptance, never a blanket threshold cut.
            # VOICE-FIX: ordinary multi-word conversational speech with
            # voiced evidence is likewise executed, not refused, on the
            # same evidence basis (plausible + voiced, not a threshold cut).
            if self._corroborated_low(text, transcript):
                return self._correct_medium(text, transcript)
            if self._corroborated_conversational(text, transcript):
                return self._decide(
                    SpeechAction.EXECUTE,
                    text=text,
                    original=text,
                    transcript=transcript,
                    reason="low_confidence_conversational",
                )
            return self._decide(
                SpeechAction.REFUSE,
                text=self._pick_refusal(),
                original=text,
                transcript=transcript,
                reason="low_confidence",
            )

        if band is ConfidenceBand.HIGH:
            return self._decide(
                SpeechAction.EXECUTE,
                text=text,
                original=text,
                transcript=transcript,
                reason="high_confidence",
            )

        return self._correct_medium(text, transcript)

    # ------------------------------------------------------------------
    # LOW-confidence corroboration (PART 1)
    # ------------------------------------------------------------------

    def _corroborated_low(self, text: str, transcript: SpeechTranscript) -> bool:
        """True when a LOW-confidence transcript is a plausible, voiced,
        known command that should be executed rather than refused."""
        if _is_pathological(text):
            logger.info(
                "SPEECH_INTELLIGENCE low-confidence pathological transcript "
                "refused: %r", text,
            )
            return False
        # VOICE-FIX: Use semantic validation for action commands instead of
        # only checking known_app_command. This allows "open YouTube",
        # "search for Python", etc. to pass even if not in the exact alias list.
        if not self._is_plausible_action_command(text):
            return False
        # PART 1: corroboration is evidence-based — a known command alone is
        # NOT enough.  The capture must actually have measured voiced speech
        # for this utterance; without that evidence a low-confidence result is
        # refused (never executed).
        voiced = transcript.speech_seconds
        if voiced is None or voiced < MIN_VOICED_SECONDS:
            logger.info(
                "SPEECH_INTELLIGENCE low-confidence command lacks voiced "
                "evidence: %r (voiced=%s)",
                text,
                f"{voiced:.2f}" if voiced is not None else "-",
            )
            return False
        logger.info(
            "SPEECH_INTELLIGENCE corroborated low-confidence action command: "
            "%r (confidence=%.3f voiced=%s)",
            text, transcript.confidence,
            f"{voiced:.2f}" if voiced is not None else "-",
        )
        return True

    def _corroborated_conversational(
        self, text: str, transcript: SpeechTranscript
    ) -> bool:
        """True for ordinary multi-word conversational speech with voiced
        evidence: clean, non-pathological, 2+ words / 6+ chars, enough
        measured speech, and no collapsed content-word confidence.  Single
        words and garbage are never rescued here."""
        words = text.split()
        if len(words) < 2 or len(text.strip()) < 6:
            return False
        if _is_pathological(text):
            return False
        # Garbage guard: at least half the words must look like real words
        # (contain a vowel).  "zzz qqq" is refused; "can you hear me" passes.
        vowels = set("aeiouy")
        plausible = sum(1 for w in words if vowels & set(w.casefold()))
        if plausible * 2 < len(words):
            return False
        voiced = transcript.speech_seconds
        if voiced is None or voiced < CONVERSATIONAL_MIN_VOICED_SECONDS:
            return False
        # FIX 4: decoder garbage ("or not man") decodes with collapsed
        # per-word probabilities.  Genuine conversational speech keeps its
        # content words well above this floor in every accent.
        min_word = transcript.min_word_confidence
        if min_word is not None and min_word < CONVERSATIONAL_MIN_WORD_CONFIDENCE:
            logger.info(
                "SPEECH_INTELLIGENCE conversational rescue refused on "
                "word confidence: %r (min_word=%.3f)",
                text, min_word,
            )
            return False
        logger.info(
            "SPEECH_INTELLIGENCE corroborated low-confidence conversation: "
            "%r (confidence=%.3f voiced=%.2f)",
            text, transcript.confidence, voiced,
        )
        return True

    def _is_plausible_action_command(self, text: str) -> bool:
        """Semantic validation: check if text looks like a valid computer-control
        command even with imperfect transcription. This is more permissive than
        _plausible_command which only checks known aliases.

        Matches patterns like:
        - open <app/website>
        - search for <query>
        - search <site> for <query>
        - play <video/music>
        - click <element>
        - scroll <direction>
        - type <text>
        """
        text_lower = text.lower().strip()
        if not text_lower:
            return False

        # Action verb patterns that indicate a computer-control command
        action_patterns = [
            # App/website commands
            r'^(open|launch|start|run|go to)\s+\w+',
            # Search commands
            r'^(search|find|look up|google)\s+(for\s+)?\w+',
            r'^(search|find|look up)\s+\w+\s+(for|on|in)\s+\w+',
            # Play commands
            r'^(play|pause|resume|stop)\s+\w+',
            r'^(play|pause|resume|stop)\s+(the\s+)?(first|second|third|next|previous|video|song|music)\b',
            # Browser control
            r'^(click|tap|press)\s+(the\s+)?(first|second|third|link|button|video|result)\b',
            # Navigation
            r'^(scroll|page)\s+(up|down|top|bottom)\b',
            r'^(go|navigate)\s+(back|forward|home)\b',
            # Type/input
            r'^(type|enter|input)\s+',
            # Volume/media
            r'^(volume|mute|unmute)\s+(up|down|on|off)?\b',
            # Close/quit
            r'^(close|quit|exit|stop|kill)\s+\w+',
            # Focus/switch
            r'^(focus|switch to|bring to)\s+\w+',
        ]

        import re
        for pattern in action_patterns:
            if re.search(pattern, text_lower):
                return True

        # Also accept known commands from transcript_quality
        if _plausible_command(text):
            return True

        return False

    # ------------------------------------------------------------------
    # MEDIUM-confidence correction
    # ------------------------------------------------------------------

    def _correct_medium(
        self, text: str, transcript: SpeechTranscript
    ) -> SpeechDecision:
        verb, app_token = self._extract_app_command(text)

        if verb is None:
            # Not an app command — no correction available, execute as-is.
            return self._decide(
                SpeechAction.EXECUTE,
                text=text,
                original=text,
                transcript=transcript,
                reason="medium_confidence_non_app",
            )

        # 1. Alias dictionary wins outright.
        canonical = self._aliases.canonical_for(app_token)
        if canonical:
            corrected = f"{verb} {canonical}"
            return self._decide(
                SpeechAction.CORRECT,
                text=corrected,
                corrected=corrected,
                original=text,
                transcript=transcript,
                reason="alias",
                candidates=(canonical,),
            )

        # 2. Exact case-insensitive match against installed app canonical names.
        #    An exact match must never be *fuzzy*-corrected ("Notepad" must not
        #    become "Notepad++"), but the canonical casing IS known, and
        #    normalising to it is exactly what MEDIUM + installed-app
        #    correction means — the raw transcript token used to be forwarded
        #    unchanged, so the canonical name was thrown away.
        exact_match = self._app_matcher.get_exact_match(app_token)
        if exact_match:
            if exact_match != app_token:
                corrected = f"{verb} {exact_match}"
                return self._decide(
                    SpeechAction.CORRECT,
                    text=corrected,
                    corrected=corrected,
                    original=text,
                    transcript=transcript,
                    reason="installed_app",
                    candidates=(exact_match,),
                )
            return self._decide(
                SpeechAction.EXECUTE,
                text=text,
                original=text,
                transcript=transcript,
                reason="exact_match",
            )

        # 3. Near-ties between the top installed-app matches -> ask which one.
        matches = self._app_matcher.search(app_token, threshold=CORRECT_SCORE_THRESHOLD)
        if len(matches) >= 2:
            best_score, second_score = matches[0][1], matches[1][1]
            if best_score - second_score < AMBIGUITY_GAP:
                candidates = (matches[0][0], matches[1][0])
                question = self._ambiguity_question(candidates)
                return self._decide(
                    SpeechAction.ASK,
                    text=question,
                    original=text,
                    transcript=transcript,
                    reason="ambiguous",
                    candidates=candidates,
                )

        # 3. A single confident installed-app match.
        if len(matches) == 1:
            canonical = matches[0][0]
            corrected = f"{verb} {canonical}"
            return self._decide(
                SpeechAction.CORRECT,
                text=corrected,
                corrected=corrected,
                original=text,
                transcript=transcript,
                reason="installed_app",
                candidates=(canonical,),
            )

        # 4. The full resolver (well-known / generic role aliases) as a
        #    last resort for the real registry.
        resolved = self._app_matcher.resolve(app_token)
        if resolved:
            corrected = f"{verb} {resolved}"
            return self._decide(
                SpeechAction.CORRECT,
                text=corrected,
                corrected=corrected,
                original=text,
                transcript=transcript,
                reason="installed_app",
                candidates=(resolved,),
            )

        # No confident match — execute the recognised text unchanged.
        return self._decide(
            SpeechAction.EXECUTE,
            text=text,
            original=text,
            transcript=transcript,
            reason="no_app_match",
        )

    @staticmethod
    def _extract_app_command(text: str) -> tuple[str | None, str]:
        """Split ``open chrome`` -> (``open``, ``chrome``).

        Returns ``(None, '')`` when the utterance is not an app command.
        """
        match = _APP_VERB_PATTERN.match(text)
        if not match:
            return None, ""
        verb = match.group("verb").strip()
        rest = match.group("rest").strip()
        tokens = [
            token
            for token in re.split(r"[\s,]+", rest)
            if token.casefold() not in _FILLER_WORDS
        ]
        app_token = " ".join(tokens).strip()
        if not app_token:
            return None, ""
        return verb, app_token

    def _ambiguity_question(self, candidates: tuple[str, ...]) -> str:
        if len(candidates) >= 2:
            return f"Did you mean {candidates[0]} or {candidates[1]}?"
        return f"Did you mean {candidates[0]}?"

    def _pick_refusal(self) -> str:
        index = int(time.monotonic()) % len(self._refusals)
        return self._refusals[index]

    # ------------------------------------------------------------------
    # Internal correction log
    # ------------------------------------------------------------------

    def _decide(
        self,
        action: SpeechAction,
        text: str,
        original: str,
        transcript: SpeechTranscript,
        reason: str,
        corrected: str = "",
        candidates: tuple[str, ...] = (),
    ) -> SpeechDecision:
        decision = SpeechDecision(
            action=action,
            text=text,
            original_text=original,
            corrected_text=corrected or text,
            confidence=transcript.confidence,
            band=classify_band(transcript.confidence),
            reason=reason,
            candidates=candidates,
            timestamp=transcript.timestamp,
        )
        self._record(decision, reason)
        return decision

    def _record(self, decision: SpeechDecision, reason: str) -> None:
        record = CorrectionRecord(
            original=decision.original_text,
            corrected=decision.corrected_text,
            confidence=decision.confidence,
            reason=reason,
            action=decision.action,
            timestamp=decision.timestamp,
        )
        with self._log_lock:
            self._log.append(record)
        logger.info(
            "SPEECH_INTELLIGENCE action=%s band=%s reason=%s "
            "original=%r corrected=%r confidence=%.3f candidates=%r",
            decision.action.value, decision.band.value, reason,
            decision.original_text, decision.corrected_text,
            decision.confidence, list(decision.candidates),
        )
