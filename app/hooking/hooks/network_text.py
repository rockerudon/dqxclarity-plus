"""Hooks network text template string replacements."""

import json
import queue
import re
import threading
import time
from dataclasses import dataclass
from uuid import uuid4
from common.config import UserConfig
from common.db_ops import generate_m00_dict, sql_read, sql_write
from common.language import prepare_game_text
from common.lib import get_project_root, setup_logger
from common.translate import Translator, is_text_japanese, should_translate_text, transliterate_player_name
from common.translation_domains import PROSE_LAYOUTS, fit_prose_layout
from loguru import logger as log


# Module-level cache and logger
_m00_text = None
_custom_text_logger = None
_language = None
_chat_translator = None

_CHAT_EVENT_PREFIX = "DQCX_CHAT_TRANSLATION::"
_CHAT_QUEUE_LIMIT = 8
_CHAT_SEEN_TTL_SECONDS = 120.0
_CHAT_MIN_REQUEST_INTERVAL_SECONDS = 1.0
_CHAT_OCCURRENCE_LIMIT = 4096

_chat_queue = queue.Queue(maxsize=_CHAT_QUEUE_LIMIT)
_chat_lock = threading.Lock()
_chat_pending = set()
_chat_seen = {}
_chat_results = {}
_chat_events = {}
_chat_occurrences = {}
_chat_last_occurrence = {}
_chat_worker_started = False


@dataclass
class _ChatRow:
    id: str
    sender: str
    category: str
    recipient: str = ""
    published: tuple | None = None

_translate_categories = {
    "<%sM_pc>",
    "<%sM_npc>",
    "<%sL_SENDER_NAME>",
    "<%sB_TARGET_RPL>",
    "<%sM_00>",
    "<%sM_kaisetubun>",
    "<%sM_text01>",
    "<%sC_QUEST>",
    "<%sC_PC>",
    "<%sM_OWNER>",
    "<%sM_hiryu>",
    "<%sL_HIRYU>",
    "<%sL_HIRYU_NAME>",
    "<%sM_name>",
    "<%sM_02>",
    "<%sM_header>",
    "<%sM_item>",
    "<%sL_OWNER>",
    "<%sL_URINUSI>",
    "<%sM_NAME>",
    "<%sL_PLAYER_NAME>",
    "<%sL_QUEST>",
    "<%sC_ITMR_STITLE>",
    "<%sCAS_gambler>",
    "<%sCAS_target>",
    "<%sC_MERCENARY>",
    "<%sC_STR2>",
    "<%sL_MONSTERNAME>",
    "<%sEV_QUEST_NAME>",
}

_prose_categories = {
    "<%sM_kaisetubun>": ("story_so_far", "story_so_far"),
    # Observed in network-delivered story/progress summaries.  This category
    # was previously logged as unknown and therefore stayed in Japanese.
    "<%sM_text01>": ("fixed_dialog_template", "story_so_far"),
}

# Server-delivered banners that no language pack can cover on an event's first
# day.  They are translated live instead of staying Japanese.
_live_label_categories = {"<%sM_header>", "<%sEV_QUEST_NAME>"}

# categories to ignore (known but not translated)
_to_ignore = {
    "<%sM_Hankaku>",
    "<%sM_katagaki2>",
    "<%sW_MAP_NAME>",
    "<%sM_timei>",
    "<%sW_REP_MAX_2ND_R>",
    "<%sW_REP_MAX_2ND_F>",
    "<%sB_TARGET_ID>",
    "<%sM_mp_hp>",
    "<%sB_ITEM>",
    "<%sB_ACTOR_ID>",
    "<%sB_TARGET2_ID>",
    "<%sB_ACTION>",
    "<%sB_TARGET2>",
    "<%sB_renkin1>",
    "<%sB_kakko>",
    "<%sB_renkindiff>",
    "<%sB_plusminus>",
    "<%sM_plusnum>",
    "<%sB_VALUE>",
    "<%sB_VALUE2>",
    "<%sB_VALUE3>",
    "<%sB_VALUE4>",
    "<%sB_VALUE5>",
    "<%sB_VALUE6>",
    "<%sM_caption>",
    "<%sM_tuyosa>",
    "<%sParam1>",
    "<%sParam2>",
    "<%sParam3>",
    "<%sB_RANK>",
    "<%sM_rurastone>",
    "<%sM_sub>",
    "<%sM_dot>",
    "<%sM_TXT_00>",
    "<%sM_skill1>",
    "<%sM_01>",
    "<%sM_rare>",
    "<%sM_fugou>",
    "<%sM_num1>",
    "<%sM_emote>",
    "<%sM_3PLeader1>",
    "<%sM_3PLeader2>",
    "<%sM_3PLeader3>",
    "<%sC_STR1>",
    "<%s_MVER1>",
    "<%s_MVER2>",
    "<%s_MVER3>",
    "<%sW_DELIMITER>",
    "<%sM_slogan>",
    "<%sM_team>",
    "<%sM_monster>",
    "<%sM_chat>",
    "<%sM_CW_stamp>",
    "<%sCAS_monster>",
    "<%sCAS_action>",
    "<%sB_ACTOR>",
    "<%sB_TARGET>",
    "<%sL_GOODS>",
}


def _init_data():
    """Initialize the m00 text database if not already loaded."""
    global _m00_text, _custom_text_logger, _language

    if _m00_text is not None:
        return _m00_text

    _m00_text = generate_m00_dict()
    _language = UserConfig().active_language
    _custom_text_logger = setup_logger("text_logger", get_project_root("logs/custom_text.log"))

    return _m00_text


def _init_chat_translator():
    """Reuse one translator for ephemeral live chat."""

    global _chat_translator
    if _chat_translator is None:
        _chat_translator = Translator()
    return _chat_translator


def _emit_chat_translation(source: str, translation: str, category: str, sender: str = "",
                           *, event_id: str = "", is_update: bool = False,
                           recipient: str = "", status: str = ""):
    """Send one machine-readable event to the launcher without logging chat."""

    payload = json.dumps(
        {
            "Source": source,
            "Translation": translation,
            "Category": category,
            "Sender": sender,
            "Id": event_id,
            "IsUpdate": is_update,
            "Recipient": recipient,
            "Status": status,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    print(f"{_CHAT_EVENT_PREFIX}{payload}", flush=True)


def _translate_chat_text(source: str, category: str) -> str | None:
    """Translate one chat line on the background worker."""

    translator = _init_chat_translator()
    translated = translator.translate(
        source,
        wrap_width=9999,
        max_lines=None,
        add_brs=False,
    )
    if not translated:
        return None
    return translated


def _publish_chat_row(source: str, row: _ChatRow, translation: str, status: str = ""):
    """Called under _chat_lock so an update cannot overtake its initial event."""
    state = (translation, row.recipient, status)
    if row.published == state:
        return
    _emit_chat_translation(source, translation, row.category, row.sender,
                           event_id=row.id, is_update=row.published is not None,
                           recipient=row.recipient, status=status)
    row.published = state


def _flush_chat_occurrences(source: str, translation: str | None, status: str = ""):
    """Update the existing launcher rows, never append on completion."""
    with _chat_lock:
        occurrences = _chat_occurrences.get(source, {})
        for row in occurrences.values():
            if not translation and row.published and row.published[0] != source:
                continue  # A failed retry must not erase an earlier translation.
            _publish_chat_row(source, row, translation or source, status)
        if translation:
            _chat_occurrences.pop(source, None)


def _record_chat_occurrence(source: str, category: str, sender: str, instance: str = "",
                            recipient: str = "", needs_translation: bool = True) -> bool:
    """Reserve display order on first capture, independently of API completion."""

    # Formatter calls are renders, not incoming-message notifications. A time
    # debounce republishes the same row whenever the history is redrawn later.
    # This is a render identity, NOT a server message ID: the game can reuse
    # the buffer. Keep the existing bounded dedupe without claiming that it
    # distinguishes identical messages from one player at the same address.
    key = (instance, sender, source)
    with _chat_lock:
        row = _chat_last_occurrence.pop(key, None)
        is_new = row is None
        if row is None:
            row = _ChatRow(uuid4().hex, sender, category)
        if recipient:
            row.recipient = recipient
        _chat_last_occurrence[key] = row
        while len(_chat_last_occurrence) > _CHAT_OCCURRENCE_LIMIT:
            oldest_key = next(iter(_chat_last_occurrence))
            oldest = _chat_last_occurrence.pop(oldest_key)
            waiting = _chat_occurrences.get(oldest_key[2], {})
            waiting.pop(oldest.id, None)
            if not waiting:
                _chat_occurrences.pop(oldest_key[2], None)
        if is_new:
            log.debug(
                f"[chat-history] new rendered row: instance={instance or 'unknown'}, "
                f"chars={len(source)}, tracked={len(_chat_last_occurrence)}"
            )
        translated = _chat_results.get(source) if needs_translation else source
        if translated:
            _publish_chat_row(source, row, translated)
        else:
            _chat_occurrences.setdefault(source, {})[row.id] = row
            # Do not regress a completed row when the provider cache expires.
            if row.published is None:
                _publish_chat_row(source, row, source, "Waiting for translation")
            elif row.published[1] != row.recipient:
                _publish_chat_row(source, row, row.published[0], row.published[2])
    return is_new


def _chat_worker():
    """Consume chat slowly so bursts cannot overwhelm the provider."""

    last_request_at = 0.0
    while True:
        source, category = _chat_queue.get()
        translated = None
        try:
            delay = _CHAT_MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_at)
            if delay > 0:
                time.sleep(delay)
            last_request_at = time.monotonic()
            translated = _translate_chat_text(source, category)
        except Exception as exc:  # noqa: BLE001 - chat must never affect the game
            log.warning(f"Unable to translate chat message: {exc}")
        finally:
            with _chat_lock:
                _chat_pending.discard(source)
                _chat_seen[source] = time.monotonic()
                _chat_results[source] = translated
                event = _chat_events.pop(source, None)
                if event is not None:
                    event.set()
            _flush_chat_occurrences(source, translated, "" if translated else "Translation unavailable")
            _chat_queue.task_done()


def _ensure_chat_worker():
    global _chat_worker_started

    with _chat_lock:
        if _chat_worker_started:
            return
        _chat_worker_started = True
        threading.Thread(
            target=_chat_worker,
            name="dqxclarity-chat-translator",
            daemon=True,
        ).start()


def _queue_chat_translation(source: str, category: str) -> threading.Event | None:
    """Queue chat without blocking; keep a strict upper bound during spam."""

    source = source.strip()
    if not source or not should_translate_text(source):
        return False

    now = time.monotonic()
    with _chat_lock:
        expired = [text for text, seen_at in _chat_seen.items() if now - seen_at >= _CHAT_SEEN_TTL_SECONDS]
        for text in expired:
            del _chat_seen[text]
            _chat_results.pop(text, None)

        if source in _chat_pending:
            return _chat_events.get(source)
        recently_attempted = source in _chat_seen
        previous_result = _chat_results.get(source)
        if not recently_attempted:
            _chat_pending.add(source)
            event = threading.Event()
            _chat_events[source] = event

    if recently_attempted:
        _flush_chat_occurrences(source, previous_result, "" if previous_result else "Translation unavailable")
        return None

    try:
        _chat_queue.put_nowait((source, category))
    except queue.Full:
        with _chat_lock:
            _chat_pending.discard(source)
            _chat_events.pop(source, None)
        _flush_chat_occurrences(source, None, "Queue full — retry when shown again")
        return None

    _flush_chat_occurrences(source, None, "Waiting for translation")
    _ensure_chat_worker()
    return event


def _split_chat_display(original_text: str, category: str) -> tuple[str, str, str]:
    """Separate a composed speaker prefix from its chat message."""

    # The separator belongs to the template, not to the contents of a message.
    # Stamps use brackets; quotes within their caption must remain body text.
    opening, closing = ('[', ']') if '[<%sM_chat>]' in category else ('"', '"')
    if category != "<%sM_chat>" and "<%sM_chat>" in category and opening in original_text:
        prefix, _, body = original_text.partition(opening)
        # Directed chat is formatted again after appending the recipient.
        # Keep that suffix out of the API/cache key, including its control bytes.
        boundary = body.rfind(closing)
        if boundary >= 0 and re.match(r'^\s*(?:→|->|>)\s*\S', body[boundary + 1:]):
            return f'{prefix}{opening}', body[:boundary], body[boundary:]
        suffix = closing if body.endswith(closing) else ""
        if suffix:
            body = body[:-1]
        return f'{prefix}{opening}', body, suffix
    return "", original_text, ""


def _romanize_chat_prefix(prefix: str) -> str:
    """Replace a supported name within the observed 12-column sender field.

    The live formatter supplies four spaces for a four-kana name, two for
    five kana, and none for six. Its localized form includes the 0x04 marker
    in that field (five spaces + marker + Kanapi). Match that padding rule;
    do not run the prefix through AnyAscii or change unrecognized layouts.
    """

    match = re.fullmatch(r'( *)(\x04?)([\u3041-\u3096\u30a1-\u30fa\u30fc]+)( ["\[])', prefix)
    if not match:
        return prefix
    padding, marker, name, separator = match.groups()
    field_width = len(padding) + len(marker) + 2 * len(name)
    if field_width != 12:
        return prefix
    romanized = transliterate_player_name(name)
    if romanized == name or not romanized.isascii() or not romanized:
        return prefix
    localized = "\x04" + romanized
    if len(localized) > field_width:
        return prefix
    replacement = " " * (field_width - len(localized)) + localized + separator
    # Never spend any message-buffer capacity on a longer sender field.
    if len(replacement.encode("utf-8")) > len(prefix.encode("utf-8")):
        return prefix
    return replacement


def _chat_sender(prefix: str) -> str:
    """Remove DQX formatting controls from a composed chat speaker prefix."""

    sender = prefix.rstrip(' "[')
    sender = re.sub(r"[\x00-\x1f\x7f]", "", sender)
    return transliterate_player_name(sender.strip())


def chat_text_replacement(original_text: str, category: str, instance: str = "") -> str:
    """Translate chat history from a non-blocking shared cache."""

    # The game invokes the composed template once with only the speaker and
    # again after appending the quoted message. Touching the intermediate value
    # creates a bogus name-only entry and corrupts the following composition.
    prefix, body, suffix = _split_chat_display(original_text, category)
    if category != "<%sM_chat>" and "<%sM_chat>" in category and not prefix:
        return original_text

    source = body.strip()
    if not source:
        return original_text

    is_composed = bool(prefix)
    needs_translation = should_translate_text(source)
    if is_composed:
        recipient = re.sub(r'^["\]]\s*(?:→|->|>)\s*', '', suffix) if len(suffix) > 1 else ""
        recipient = _chat_sender(recipient) if recipient else ""
        _record_chat_occurrence(source, category, _chat_sender(prefix), instance, recipient, needs_translation)
        prefix = _romanize_chat_prefix(prefix)
    untranslated_row = f"{prefix}{body}{suffix}"

    if not needs_translation:
        # Stamps and already localized messages still belong in the launcher
        # history; they simply do not need a provider request.
        if is_composed:
            with _chat_lock:
                _chat_results.setdefault(source, source)
            _flush_chat_occurrences(source, source)
        return untranslated_row

    with _chat_lock:
        cached = _chat_results.get(source)
    if cached:
        return f"{prefix}{cached}{suffix}"

    _queue_chat_translation(source, category)

    return untranslated_row


def _format_to_json(text: str) -> str:
    """Format text for logging as JSON."""
    replaced = text.replace("\n", "\\n")
    return f'{{\n  "1": {{\n    "{replaced}": ""\n  }}\n}}'


def chat_speaker_replacement(original_name: str) -> str:
    """Romanize the standalone speaker field, never an already aligned row."""

    # Keep the game's existing whitespace and control bytes outside the name.
    match = re.fullmatch(r"([\s\x00-\x1f\x7f]*)(.*?)([\s\x00-\x1f\x7f]*)", original_name)
    if not match:
        return original_name
    prefix, name, suffix = match.groups()
    if not name or not is_text_japanese(name):
        return original_name
    romanized = transliterate_player_name(name)
    if romanized == name or not romanized.isascii():
        return original_name

    # Match the existing nameplate path: this marker identifies a localized
    # player name and prevents the red-name/GM-avatar interpretation.
    marker = "" if "\x04" in prefix else "\x04"
    replacement = f"{prefix}{marker}{romanized}{suffix}"
    if len(replacement.encode("utf-8")) > len(original_name.encode("utf-8")):
        # Do not truncate a player's identity to fit an inline buffer.
        return original_name
    return replacement


def _translate_ui_label(original_text: str, category: str) -> str:
    """Machine-translate one server-delivered banner.

    Japanese headers are far more compact than any Latin target, and the writer
    can only ever use the source buffer, so the result is cut to that size with
    the project's tag-safe truncation.  Nothing reaches the database: an event
    name that outlived its event would be worse than the Japanese original.
    """

    budget = len(original_text.encode("utf-8"))
    translated = Translator().translate(original_text, wrap_width=9999, add_brs=False)
    if not translated or len(translated.encode("utf-8")) > budget:
        # Either way the player still reads Japanese, so record the string for
        # someone who can write a pack name short enough to fit.
        _custom_text_logger.info(f"--\n>>{category} ::\n{original_text}")
    if not translated:
        return original_text
    return prepare_game_text(translated, _language, max_bytes=budget)


def network_text_replacement(original_text: str, category: str) -> str:
    """Replace network text based on category.

    :param original_text: The original text to replace.
    :param category: The category/variable name.
    :return: Replacement text, or original if no replacement.
    """
    if category == "<%sM_speaker>":
        return chat_speaker_replacement(original_text)

    overlay_prose = category in _prose_categories and should_translate_text(original_text)
    if not is_text_japanese(original_text) and not overlay_prose:
        return original_text

    # this hook hits on login screen, but we don't init data until player is logged in.
    # if we see this string, we ignore it. (categories starting with _MVER)
    if category.startswith("Version <%s_MVER"):
        return original_text

    m00_text = _init_data()

    if category in _to_ignore:
        return original_text

    if original_text.endswith("自分"):
        # "self" text when player/monster uses spell on themselves
        return original_text.replace("自分", m00_text.get("自分", "self"))

    if category not in _translate_categories:
        # log unknown category
        if category and original_text:
            _custom_text_logger.info(f"--\n{category} ::\n{original_text}")
        return original_text

    elif category in {
        "<%sM_pc>",
        "<%sM_npc>",
        "<%sC_PC>",
        "<%sL_SENDER_NAME>",
        "<%sM_OWNER>",
        "<%sM_hiryu>",
        "<%sL_HIRYU>",
        "<%sL_HIRYU_NAME>",
        "<%sM_name>",
        "<%sL_OWNER>",
        "<%sL_URINUSI>",
        "<%sM_NAME>",
        "<%sL_PLAYER_NAME>",
        "<%sCAS_gambler>",
        "<%sCAS_target>",
        "<%sC_MERCENARY>",
        "<%sL_MONSTERNAME>",
    }:
        # NPC or player names
        if m00_text.get(original_text):
            return m00_text[original_text]
        else:
            return transliterate_player_name(original_text)

    elif category in {
        "<%sM_00>",
        "<%sC_QUEST>",
        "<%sM_02>",
        "<%sM_item>",
        "<%sL_QUEST>",
        "<%sC_ITMR_STITLE>",
        "<%sC_STR2>",
    }:
        # generic string
        if replacement := m00_text.get(original_text):
            return replacement
        else:
            # log missing translation
            log_text = _format_to_json(original_text) if category == "<%sM_00>" else original_text
            _custom_text_logger.info(f"--\n>>{category} ::\n{log_text}")
            return original_text

    elif category in _live_label_categories:
        return m00_text.get(original_text) or _translate_ui_label(original_text, category)

    elif category in _prose_categories:
        # Story summaries and network-delivered story/progress prose use the
        # same measured box constraints. Prefer a manual pack entry when one
        # exists, but permit direct Japanese MTL when the pack is incomplete.
        table, layout_name = _prose_categories[category]
        layout = PROSE_LAYOUTS[layout_name]
        translation_source = m00_text.get(original_text) or original_text
        if prose_text := sql_read(text=translation_source, table=table):
            return fit_prose_layout(prose_text, layout)
        elif should_translate_text(translation_source):
            translator = Translator()
            if translated := translator.translate(
                translation_source,
                wrap_width=layout.wrap_width,
                max_lines=layout.max_lines,
                add_brs=False,
            ):
                translated = fit_prose_layout(translated, layout)
                try:
                    sql_write(source_text=translation_source, translated_text=translated, table=table)
                except Exception as exc:  # noqa: BLE001 - cache failures must not hide live text
                    log.warning(f"Unable to cache network prose translation: {exc}")
                return translated
            return translation_source
        else:
            _custom_text_logger.info(f"--\n{category} ::\n{original_text}")
            return translation_source

    return original_text


def on_message(message, data, script):
    """Message handler for network_text hook.

    Args:
        message: Message dict from Frida script
        data: Binary data (if any) from Frida script
        script: Frida script instance for posting responses
    """
    if message["type"] == "send":
        payload = message["payload"]
        msg_type = payload.get("type", "unknown")

        if msg_type == "get_chat_replacement":
            original_text = payload.get("text", "")
            category = payload.get("category", "")
            instance = payload.get("instance", "")
            try:
                replacement = chat_text_replacement(original_text, category, instance)
                if replacement != original_text:
                    # Name-only changes must not turn an untranslated Japanese
                    # body into romanized prose while the API is still pending.
                    _, original_body, _ = _split_chat_display(original_text, category)
                    prefix, body, suffix = _split_chat_display(replacement, category)
                    if body != original_body:
                        _init_data()
                        replacement = f"{prefix}{prepare_game_text(body, _language)}{suffix}"
            except Exception as exc:  # noqa: BLE001 - chat must always fail open
                log.warning(f"Chat replacement failed: {exc}")
                replacement = original_text
            response_type = payload.get("response_type", "chat_replacement")
            script.post({"type": response_type, "text": replacement})

        elif msg_type == "get_replacement":
            # frida is requesting a replacement
            original_text = payload.get("text", "")
            category = payload.get("category", "")

            try:
                replacement = network_text_replacement(original_text, category)
                if replacement != original_text and category != "<%sM_speaker>":
                    _init_data()
                    replacement = prepare_game_text(replacement, _language)

            except Exception as e:
                log.exception(f"Replacement failed: {e}")

                # use original text as fallback
                replacement = original_text

            # send the replacement back to Frida
            if replacement != original_text:
                log.debug(
                    f"[network_text] category={category!r}, source={original_text[:160]!r}, "
                    f"replacement={replacement[:160]!r}"
                )
            log.trace(f"{original_text} => {replacement}")
            response_type = payload.get("response_type", "replacement")
            script.post({"type": response_type, "text": replacement})

        elif msg_type == "info":
            log.debug(f"{payload['payload']}")
        elif msg_type == "error":
            log.error(f"{payload['payload']}")
        else:
            log.debug(f"{payload}")

    elif message["type"] == "error":
        log.error(f"[JS ERROR] {message.get('stack', message)}")
