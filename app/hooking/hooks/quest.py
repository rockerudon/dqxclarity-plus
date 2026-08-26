from common.db_ops import generate_m00_dict, sql_read, sql_write
from common.language import prepare_game_text
from common.translate import Translator, clean_up_and_return_items, is_text_japanese, should_translate_text
from common.translation_domains import PROSE_LAYOUTS, fit_prose_layout
from loguru import logger as log


_quests = None
_translator = None


def _init_translator():
    """Initialize the translator if not already loaded."""
    global _translator

    if _translator is not None:
        return _translator

    _translator = Translator()
    return _translator


def _query_quest(text: str) -> str:
    """Query quest data from pre-generated dict."""
    global _quests
    if _quests is None:
        _quests = generate_m00_dict(files="'quests'")

    return _quests.get(text, None)


def _translate_quest_desc(text: str) -> str | None:
    """Translate quest description using DB cache or translator."""
    _init_translator()
    layout = PROSE_LAYOUTS["quests"]

    if (db_quest_text := sql_read(text=text, table="quests")) and db_quest_text != text:
        fitted = fit_prose_layout(db_quest_text, layout)
        return prepare_game_text(fitted, _translator.language)

    # translate() returns a falsy value if translation was skipped (e.g. majority
    # English text) or failed. Don't cache those cases to the database.
    if translation := _translator.translate(
        text,
        wrap_width=layout.wrap_width,
        max_lines=layout.max_lines,
        add_brs=False,
    ):
        translation = fit_prose_layout(translation, layout)
        sql_write(source_text=text, translated_text=translation, table="quests")
        return prepare_game_text(translation, _translator.language)

    return None


def process_quest_data(data: dict) -> dict:
    """Process quest data received from Frida and return replacements.

    :param data: Dict containing quest strings from Frida:
        - subquestName: Subquest name
        - questName: Quest name
        - questDesc: Quest description
        - questRewards: Quest rewards text
        - questRepeatRewards: Repeat quest rewards text
    :returns: Dict with replacement strings (only includes fields that need updating)
    """
    # extract original strings
    subquest_name = data.get("subquestName", "")
    quest_name = data.get("questName", "")
    quest_desc = data.get("questDesc", "")
    quest_rewards = data.get("questRewards", "")
    quest_repeat_rewards = data.get("questRepeatRewards", "")

    # Names and rewards are canonical pack content. The overlay adds only the
    # hook-visible prose description when the source is already localized.
    is_ja = is_text_japanese(quest_desc)
    translate_description = should_translate_text(quest_desc)

    replacements = {}

    if is_ja:
        _init_translator()
        if subquest_name:  # noqa: SIM102
            if replacement := _query_quest(subquest_name):
                replacements["subquestName"] = prepare_game_text(replacement, _translator.language)

        if quest_name:  # noqa: SIM102
            if replacement := _query_quest(quest_name):
                replacements["questName"] = prepare_game_text(replacement, _translator.language)

        if quest_desc:  # noqa: SIM102
            if replacement := _translate_quest_desc(quest_desc):
                replacements["questDesc"] = replacement

        if quest_rewards:  # noqa: SIM102
            if replacement := clean_up_and_return_items(quest_rewards):
                replacements["questRewards"] = prepare_game_text(replacement, _translator.language)

        if quest_repeat_rewards:  # noqa: SIM102
            if replacement := clean_up_and_return_items(quest_repeat_rewards):
                # Capacity after the final field is not established; apply the
                # language policy but do not claim an unsafe byte limit.
                replacements["questRepeatRewards"] = prepare_game_text(replacement, _translator.language)

    elif translate_description and quest_desc:
        if replacement := _translate_quest_desc(quest_desc):
            replacements["questDesc"] = replacement

    return replacements


def on_message(message, data, script):
    """Message handler for accept_quest hook.

    :param message: Message dict from Frida script
    :param data: Binary data (if any) from Frida script
    :param script: Frida script instance for posting responses
    """
    if message["type"] == "send":
        payload = message["payload"]
        msg_type = payload.get("type", "unknown")

        if msg_type == "quest_data":
            quest_data = payload.get("data", {})

            try:
                replacements = process_quest_data(quest_data)

                quest_name_preview = quest_data.get("questName", "Unknown")[:50]
                if replacements:
                    log.debug(f"Processed: {quest_name_preview} ({len(replacements)} fields translated)")
                else:
                    log.debug(f"No translation needed: {quest_name_preview}")

            except Exception as e:
                log.exception(f"Processing failed: {e}")
                replacements = {}

            # send replacements back to Frida
            quest_description = quest_data.get("questDesc", "No description?")
            log.debug(f"\n{quest_description}")
            script.post({"type": "quest_replacements", "data": replacements})

        elif msg_type == "info":
            log.debug(f"{payload['payload']}")
        elif msg_type == "error":
            log.error(f"{payload['payload']}")
        else:
            log.debug(f"{payload}")

    elif message["type"] == "error":
        log.error(f"[JS ERROR] {message.get('stack', message)}")
