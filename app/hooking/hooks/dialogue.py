import re
from common.db_ops import (
    read_dialogue_translation_variant,
    search_bad_strings,
    sql_read,
    write_dialogue_translation,
)
from common.language import (
    contains_choice_markup,
    looks_like_choice_list,
    prepare_game_text,
)
from common.translate import Translator, is_text_japanese, should_translate_text
from loguru import logger as log


_translator = None
_GAME_TAG_RE = re.compile(r"<[^>]+>")
_SELECT_BLOCK_RE = re.compile(
    r"<select(?!_end\b)[^>]*>(.*?)<select_end>",
    re.IGNORECASE | re.DOTALL,
)


def _prepare_output(text: str) -> str:
    """Apply the target-language display policy to complete dialogue text."""

    # Dialogue replacements are passed through a repointed string argument;
    # truncating them to the source byte length produced fake ``...`` text and
    # detached selectors.
    # ``prepare_game_text`` transliterates output for non-Japanese targets.
    # That policy belongs to successful target-language translations, not to
    # a Japanese fallback.  Applying it after a provider failure turned valid
    # Japanese into unreadable romaji (for example ``koushite DaoXing...``).
    # Japanese is natively supported by the game, so preserve it verbatim.
    if is_text_japanese(text):
        return text
    return prepare_game_text(text, _translator.language)


def _init_locals():
    """Initialize locals if not already loaded."""
    global _translator

    if not _translator:
        _translator = Translator()


def _read_dialogue(text: str, language_code: str) -> str | None:
    """Read an exact dialogue first and a conservative formatting variant second."""

    exact = sql_read(text=text, table="dialog", language_code=language_code)
    return exact or read_dialogue_translation_variant(text, language_code=language_code)


def _choice_controls(text: str) -> tuple[str, ...]:
    """Return parser-control tags while ignoring presentation tags."""

    controls = []
    for tag in _GAME_TAG_RE.findall(text):
        name_match = re.match(r"<\s*/?\s*([^\s/>]+)", tag)
        if not name_match:
            continue
        name = name_match.group(1).lower()
        if name.startswith(("select", "yesno", "case")) or name == "close":
            controls.append(tag)
    return tuple(controls)


def _choice_options(text: str) -> tuple[tuple[str, ...], ...]:
    """Return each explicit select block as its ordered non-empty lines."""

    return tuple(
        tuple(line.strip() for line in payload.splitlines() if line.strip())
        for payload in _SELECT_BLOCK_RE.findall(text)
    )


def _safe_choice_translation(source: str, candidate: str | None) -> bool:
    """Require identical controls and the same number of explicit options."""

    if not candidate or _choice_controls(source) != _choice_controls(candidate):
        return False
    source_blocks = _choice_options(source)
    candidate_blocks = _choice_options(candidate)
    return len(source_blocks) == len(candidate_blocks) and all(
        len(source_block) == len(candidate_block)
        for source_block, candidate_block in zip(source_blocks, candidate_blocks, strict=True)
    )


def _choice_cache_is_complete(source: str, candidate: str | None) -> bool:
    """Reject old prose-only cache rows so their English options can be upgraded."""

    if not _safe_choice_translation(source, candidate):
        return False
    source_options = _choice_options(source)
    return not source_options or source_options != _choice_options(candidate or "")


def _choice_dialogue_replacement(original_text: str, npc_name: str, target_language: str) -> str:
    """Translate prose and options while preserving the choice parser structure."""

    english_source = _read_dialogue(original_text, "en")
    if not english_source and not is_text_japanese(original_text):
        # With the English pack active the hook may already receive its final
        # English string, which naturally has no Japanese-keyed DB row.
        english_source = original_text
    translation_source = english_source or original_text
    if not english_source:
        # The English pack is preferred, but it is not complete.  A choice
        # block can still be translated safely from Japanese as long as the
        # API result preserves every parser control and option count.
        log.debug("[dialogue] choice has no English pack entry; translating source block directly")

    if target_language == "en" and english_source:
        return _prepare_output(english_source)

    target_cached = _read_dialogue(original_text, target_language)
    if _choice_cache_is_complete(translation_source, target_cached):
        log.debug(f"[dialogue] validated choice cache hit ({target_language})")
        return _prepare_output(target_cached)
    if target_cached:
        log.debug("Ignoring incomplete or structurally invalid choice cache entry.")

    if not should_translate_text(translation_source):
        return _prepare_output(english_source or original_text)

    translated = _translator.translate(
        text=translation_source,
        wrap_width=46,
        translate_choices=True,
    )
    if not translated:
        return _prepare_output(english_source or original_text)

    if not _safe_choice_translation(translation_source, translated):
        log.warning("Choice translation changed controls or option count; using English pack block.")
        return _prepare_output(english_source or original_text)

    try:
        write_dialogue_translation(
            original_text,
            translated,
            npc_name,
            language_code=target_language,
        )
    except Exception as exc:  # noqa: BLE001 - cache failure must not hide live text
        log.warning(f"Unable to cache choice dialogue translation: {exc}")
    return _prepare_output(translated)


def _tagless_choice_replacement(original_text: str, npc_name: str, target_language: str) -> str:
    """Translate a short unmarked option list through a temporary select wrapper."""

    english_source = _read_dialogue(original_text, "en")
    if not english_source and not is_text_japanese(original_text):
        english_source = original_text
    if not english_source or target_language == "en":
        return _prepare_output(english_source or original_text)

    source_lines = tuple(line.strip() for line in english_source.splitlines() if line.strip())
    target_cached = _read_dialogue(original_text, target_language)
    cached_lines = tuple(line.strip() for line in (target_cached or "").splitlines() if line.strip())
    if target_cached and len(cached_lines) == len(source_lines) and cached_lines != source_lines:
        return _prepare_output(target_cached)

    wrapped = f"<select>\n{english_source}\n<select_end>"
    translated = _translator.translate(
        text=wrapped,
        wrap_width=46,
        add_brs=False,
        translate_choices=True,
    )
    if not translated or not _safe_choice_translation(wrapped, translated):
        return _prepare_output(english_source)
    blocks = _choice_options(translated)
    if len(blocks) != 1 or len(blocks[0]) != len(source_lines):
        return _prepare_output(english_source)
    translated_list = "\n".join(blocks[0])
    try:
        write_dialogue_translation(
            original_text,
            translated_list,
            npc_name,
            language_code=target_language,
        )
    except Exception as exc:  # noqa: BLE001 - cache failure must not hide live text
        log.warning(f"Unable to cache tagless choice translation: {exc}")
    return _prepare_output(translated_list)


def dialogue_replacement(original_text: str, npc_name: str = "No_NPC") -> str:
    """Replace dialogue text using the translation logic from the parent Dialog
    class.

    :param original_text: Source text exposed by the active language pack.
    :param npc_name: Name of the NPC.
    """
    _init_locals()
    log.debug(f"[dialogue] source={original_text[:240]!r}")

    target_language = _translator.language.code
    if looks_like_choice_list(original_text):
        return _tagless_choice_replacement(original_text, npc_name, target_language)

    choice_dialogue = contains_choice_markup(original_text)

    # Selection controls are parser state. Translate their visible payload but
    # require the controls and option count to survive unchanged.
    if choice_dialogue:
        return _choice_dialogue_replacement(original_text, npc_name, target_language)

    # Dynamic cache entries are strictly isolated by target language.
    target_cached = _read_dialogue(original_text, target_language)
    if target_cached and target_cached != original_text:
        log.debug(f"[dialogue] target cache hit ({target_language})")
        return _prepare_output(target_cached)

    # The hand-authored English pack is the preferred API source and the safe
    # fallback. It is never treated as if it were already translated to the
    # selected target language.
    english_source = target_cached if target_language == "en" else _read_dialogue(original_text, "en")
    if not english_source:
        english_source = search_bad_strings(original_text, language_code="en")
    translation_source = english_source or original_text

    if target_language == "en" and english_source:
        return _prepare_output(english_source)

    if not should_translate_text(translation_source):
        fallback = english_source or original_text
        log.debug("[dialogue] API layer skipped; using pack/source fallback")
        return _prepare_output(fallback)

    # translate the text
    translated_text = _translator.translate(
        text=translation_source,
        wrap_width=46,
        translate_choices=True,
    )

    # translate() returns a falsy value if translation was skipped (e.g. majority
    # English text) or failed. Don't cache those cases to the database.
    if translated_text:
        # Persist the full Unicode version under the original game source;
        # ASCII/byte policies belong only at the final game boundary.
        try:
            write_dialogue_translation(
                original_text,
                translated_text,
                npc_name,
                language_code=target_language,
            )
        except Exception as exc:  # noqa: BLE001 - a cache failure must not hide live text
            log.warning(f"Unable to cache dialogue translation: {exc}")
        return _prepare_output(translated_text)

    # A real English pack entry is safer than Japanese when the API fails. If
    # none exists, retain the original rather than inventing menu structure.
    fallback = english_source or original_text
    log.debug("[dialogue] provider returned no translation; using pack/source fallback")
    return _prepare_output(fallback)


def on_message(message, data, script):
    """Message handler for dialogue hook.

    Args:
        message: Message dict from Frida script
        data: Binary data (if any) from Frida script
        script: Frida script instance for posting responses
    """
    if message["type"] == "send":
        payload = message["payload"]
        msg_type = payload.get("type", "unknown")

        if msg_type == "get_replacement":
            original_text = payload.get("text", "")
            npc_name = payload.get("npc_name", "Unknown")

            try:
                replacement = dialogue_replacement(original_text, npc_name)

            except Exception as e:
                log.exception(f"Replacement failed: {e}")

                # use original text as fallback
                replacement = original_text

            # send the replacement back to frida
            script.post({"type": "replacement", "text": replacement})

        elif msg_type == "info":
            log.debug(f"{payload['payload']}")
        elif msg_type == "error":
            log.error(f"{payload['payload']}")
        else:
            log.debug(f"{payload}")

    elif message["type"] == "error":
        log.error(f"[JS ERROR] {message.get('stack', message)}")
