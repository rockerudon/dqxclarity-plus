"""Language identity and game-output policies shared by the runtime.

Language codes are stored in canonical BCP 47 form.  Persisted translations keep
their full Unicode text; output policies are applied only immediately before text
is sent to the game hooks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_LANGUAGE = "en"
SOURCE_LANGUAGE = "ja"
# DQX's injected-text renderer is reliable for printable ASCII and its native
# Japanese glyphs. "*" means romanize every non-Japanese target at the final
# game boundary while preserving full Unicode in the translation database.
DEFAULT_ASCII_OUTPUT_LANGUAGES = ("*",)

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_GAME_TAG_RE = re.compile(r"(<[^>]+>)")
_CHOICE_MARKUP_RE = re.compile(r"<(?:select(?:_end|_[^>]*|\b)|yesno(?:\b|_)|case(?:_|\s|>))", re.IGNORECASE)
_CHOICE_CANCEL_TERMS = frozenset(
    {
        "...",
        "…",
        "やめる",
        "キャンセル",
        "いいえ",
        "もどる",
        "戻る",
        "cancel",
        "quit",
        "no",
        "back",
        "exit",
        "cancelar",
        "sair",
        "voltar",
        "annuler",
        "quitter",
        "zurück",
        "abbrechen",
        "назад",
        "отмена",
        "취소",
        "뒤로",
        "取消",
        "返回",
    }
)
_SUSPICIOUS_TRANSLATION_RE = re.compile(
    r"(?:<\s*/?\s*(?:html|head|body|style|script)\b|body\s*[>{]|"
    r"\b(?:display|overflow|position|visibility)\s*:\s*|"
    r"\b(?:result-container|translate_a|goog-te)\b)",
    re.IGNORECASE,
)
_DISPLAY_NAMES = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt-BR": "Brazilian Portuguese",
    "pt-PT": "European Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
}

# Providers do not all accept the same spelling for regional/script variants.
# Keep the full BCP 47 code in configuration and cache keys; collapse or rewrite
# it only at the API boundary where a provider requires a different target.
_GOOGLE_TARGETS = {
    "pt-BR": "pt",
    "pt-PT": "pt",
    "zh-Hans": "zh-CN",
    "zh-Hant": "zh-TW",
}
_BASIC_TARGETS = {
    "pt-BR": "pt",
    "pt-PT": "pt",
    "zh-Hans": "zh",
    "zh-Hant": "zh",
}
_PROVIDER_TARGET_OVERRIDES = {
    "chatgpt": {},
    "deepl": {
        "en": "EN-US",
        "pt-BR": "PT-BR",
        "pt-PT": "PT-PT",
        "zh-Hans": "ZH-HANS",
        "zh-Hant": "ZH-HANT",
    },
    "google": _GOOGLE_TARGETS,
    "googlefree": _GOOGLE_TARGETS,
    "googletranslatepa": _GOOGLE_TARGETS,
    "libretranslate": _BASIC_TARGETS,
    "ollama": {},
    "yandex": _BASIC_TARGETS,
}


def normalize_language_code(code: str | None, *, default: str | None = None) -> str:
    """Validate and canonicalize a BCP 47 language code.

    Language subtags are lowercase, four-letter script subtags are title case,
    and region subtags are uppercase. Underscores are accepted as user-input
    separators but are never persisted.
    """

    raw = (code or "").strip().replace("_", "-")
    if not raw or not _LANGUAGE_RE.fullmatch(raw):
        if default is not None:
            return normalize_language_code(default)
        raise ValueError(f"Invalid language code: {code!r}")

    parts = raw.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            canonical.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())
        else:
            canonical.append(part.lower())
    return "-".join(canonical)


def language_display_name(code: str, configured_name: str | None = None) -> str:
    """Return the provider-facing English display name for a language."""

    canonical = normalize_language_code(code)
    return _DISPLAY_NAMES.get(canonical) or (configured_name or "").strip() or canonical


def provider_target_code(provider: str, code: str) -> str:
    """Return a provider target without changing the persisted language identity."""

    canonical = normalize_language_code(code)
    return _PROVIDER_TARGET_OVERRIDES.get((provider or "").strip().lower(), {}).get(canonical, canonical)


def parse_language_codes(value: str | None) -> tuple[str, ...]:
    """Parse a pipe/comma-separated language list, discarding invalid entries."""

    result: list[str] = []
    for item in re.split(r"[|,]", value or ""):
        if not item.strip():
            continue
        try:
            code = normalize_language_code(item)
        except ValueError:
            continue
        if code not in result:
            result.append(code)
    return tuple(result)


def _uses_ascii_output(language_code: str, policy: str | None) -> bool:
    tokens = {item.strip() for item in re.split(r"[|,]", policy or "") if item.strip()}
    if "*" in tokens:
        return language_code != SOURCE_LANGUAGE
    return language_code in parse_language_codes(policy)


@dataclass(frozen=True)
class LanguageContext:
    code: str
    display_name: str
    ascii_output: bool = False

    @classmethod
    def create(
        cls,
        code: str | None,
        display_name: str | None = None,
        ascii_output_languages: str | None = None,
    ) -> LanguageContext:
        canonical = normalize_language_code(code, default=DEFAULT_LANGUAGE)
        output_policy = (
            "|".join(DEFAULT_ASCII_OUTPUT_LANGUAGES) if ascii_output_languages is None else ascii_output_languages
        )
        return cls(
            code=canonical,
            display_name=language_display_name(canonical, display_name),
            ascii_output=_uses_ascii_output(canonical, output_policy),
        )

    def fallback_codes(self, *, include_english: bool = True, include_source: bool = True) -> tuple[str, ...]:
        codes = [self.code]
        if include_english and DEFAULT_LANGUAGE not in codes:
            codes.append(DEFAULT_LANGUAGE)
        if include_source and SOURCE_LANGUAGE not in codes:
            codes.append(SOURCE_LANGUAGE)
        return tuple(codes)


def contains_choice_markup(text: str) -> bool:
    """Return whether text contains DQX's selectable-dialogue controls."""

    return bool(_CHOICE_MARKUP_RE.search(text or ""))


def looks_like_choice_list(text: str) -> bool:
    """Recognize a short, unmarked option list without changing its text."""

    if not text or _GAME_TAG_RE.search(text):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 2 <= len(lines) <= 8 or any(len(line) > 48 for line in lines):
        return False
    if any(re.search(r"[.!?。！？:：]", line) for line in lines[:-1]):
        return False
    return lines[-1].casefold() in _CHOICE_CANCEL_TERMS


def utf8_length(text: str) -> int:
    return len(text.encode("utf-8"))


def transliterate_game_ascii(text: str) -> str:
    """Romanize visible text into DQX-safe ASCII without modifying game tags.

    AnyAscii covers Latin diacritics plus non-Latin scripts such as Arabic,
    Cyrillic, Greek, Han, and Hangul. It emits printable ASCII and removes an
    unknown character instead of allowing an unsupported glyph into the game.
    """

    from anyascii import anyascii

    pieces = _GAME_TAG_RE.split(text)
    for index in range(0, len(pieces), 2):
        pieces[index] = anyascii(pieces[index])
    return "".join(pieces)


def truncate_utf8(text: str, max_bytes: int, *, suffix: str = "...") -> str:
    """Truncate at UTF-8 boundaries while never cutting through a game tag."""

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if utf8_length(text) <= max_bytes:
        return text
    if max_bytes == 0:
        return ""

    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) > max_bytes:
        return suffix_bytes[:max_bytes].decode("utf-8", "ignore")

    budget = max_bytes - len(suffix_bytes)
    output: list[str] = []
    used = 0
    for piece in _GAME_TAG_RE.split(text):
        if not piece:
            continue
        if piece.startswith("<") and piece.endswith(">"):
            size = utf8_length(piece)
            if used + size > budget:
                break
            output.append(piece)
            used += size
            continue
        for char in piece:
            size = utf8_length(char)
            if used + size > budget:
                return "".join(output) + suffix
            output.append(char)
            used += size
    return "".join(output) + suffix


def prepare_game_text(
    text: str,
    language: LanguageContext,
    *,
    max_bytes: int | None = None,
) -> str:
    """Apply the active language's display policy at the game boundary."""

    if language.ascii_output:
        output = transliterate_game_ascii(text)
    else:
        output = text
    return truncate_utf8(output, max_bytes) if max_bytes is not None else output


def is_suspicious_translation(text: str) -> bool:
    """Detect HTML/CSS or provider-page fragments leaking as game text."""

    if not isinstance(text, str) or not text.strip():
        return True
    if len(text) > 20_000:
        return True
    return bool(_SUSPICIOUS_TRANSLATION_RE.search(text))
