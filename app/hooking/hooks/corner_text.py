"""Translate hook-visible event text rendered outside dialogue boxes."""

from common.config import UserConfig
from common.db_ops import generate_m00_dict, sql_read, sql_write
from common.language import prepare_game_text
from common.lib import get_project_root, setup_logger
from common.translate import Translator, is_text_japanese, should_translate_text
from loguru import logger as log


_data = None
_custom_text_logger = None
_translator = None
_language = None


def _init_data():
    """Initialize the corner text database if not already loaded."""
    global _data, _custom_text_logger, _translator, _language

    if _data is not None:
        return _data

    _data = generate_m00_dict("'custom_corner_text'")
    _custom_text_logger = setup_logger("text_logger", get_project_root("logs/corner_text.log"))
    _translator = Translator()
    _language = UserConfig().active_language

    return _data


def corner_text_replacement(original_text: str) -> str:
    """Translate event prose while retaining the English pack as fallback.

    :param original_text: The original text to replace.
    :return: Replacement text, or original if no replacement found.
    """
    data = _init_data()

    # The complete pack is hand-authored in English.  When the game exposes
    # Japanese, prefer that entry as the API source; when the pack has already
    # replaced the buffer, ``original_text`` itself is the English source.
    pack_text = data.get(original_text)
    translation_source = pack_text or original_text

    if cached := sql_read(text=translation_source, table="corner_text"):
        return cached

    if should_translate_text(translation_source):
        translated = _translator.translate(
            translation_source,
            wrap_width=46,
            add_brs=False,
        )
        if translated:
            try:
                sql_write(
                    source_text=translation_source,
                    translated_text=translated,
                    table="corner_text",
                )
            except Exception as exc:  # noqa: BLE001 - cache failure must not hide live text
                log.warning(f"Unable to cache corner/event translation: {exc}")
            return translated

    if not pack_text and is_text_japanese(original_text):
        _custom_text_logger.info(f"--\n>>corner_text ::\n{original_text}")

    return translation_source


def on_message(message, data, script):
    """Message handler for corner_text hook.

    :param message: Message dict from Frida script
    :param data: Binary data (if any) from Frida script
    :param script: Frida script instance for posting responses
    """
    if message["type"] == "send":
        payload = message["payload"]
        msg_type = payload.get("type", "unknown")

        if msg_type == "get_replacement":
            original_text = payload.get("text", "")

            try:
                replacement = corner_text_replacement(original_text)
                if replacement != original_text and not is_text_japanese(replacement):
                    replacement = prepare_game_text(replacement, _language)

            except Exception as e:
                log.exception(f"Replacement failed: {e}")

                # use original text as fallback
                replacement = original_text

            # send the replacement back to frida
            log.debug(
                f"[corner_text] source={original_text[:160]!r}, "
                f"replacement={replacement[:160]!r}, changed={replacement != original_text}"
            )
            script.post({"type": "replacement", "text": replacement})

        elif msg_type == "info":
            log.debug(f"{payload['payload']}")
        elif msg_type == "error":
            log.error(f"{payload['payload']}")
        else:
            log.debug(f"{payload}")

    elif message["type"] == "error":
        log.error(f"[JS ERROR] {message.get('stack', message)}")
