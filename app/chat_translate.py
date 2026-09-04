"""JSON-lines helper for launcher-authored chat translation."""

import json
import os
import sys


_RESPONSE_PREFIX = "DQCX_OUTGOING_TRANSLATION::"


def _parse_request(raw_line: str) -> dict:
    """Accept JSON lines from launchers that may emit a UTF-8 BOM."""

    return json.loads(raw_line.lstrip("\ufeff"))


def _respond(request_id: str, source: str, translation: str = "", error: str = "") -> None:
    payload = json.dumps(
        {
            "Id": request_id,
            "Source": source,
            "Translation": translation,
            "Error": error,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    print(f"{_RESPONSE_PREFIX}{payload}", flush=True)


def main() -> None:
    # Provider classes read UserConfig themselves. Process-local overrides let
    # all supported providers target Japanese without modifying user_settings.
    os.environ["DQXCLARITY_TARGET_LANGUAGE_OVERRIDE"] = "ja"
    os.environ["DQXCLARITY_SOURCE_LANGUAGE_OVERRIDE"] = "auto"

    from common.config import UserConfig
    from common.translate import Translator

    config = UserConfig()
    translator = None if config.translate_service in ("", "none") else Translator()

    for raw_line in sys.stdin:
        request_id = ""
        source = ""
        try:
            request = _parse_request(raw_line)
            request_id = str(request.get("Id", ""))
            source = str(request.get("Text", "")).strip()
            if not request_id or not source:
                raise ValueError("A non-empty message is required.")
            if translator is None:
                raise RuntimeError("No translation provider is selected.")
            translated = translator.translate_outgoing_chat(source)
            if not translated:
                raise RuntimeError("The translation provider returned no translation.")
            _respond(request_id, source, translated)
        except Exception as exc:  # noqa: BLE001 - every request needs a response
            _respond(request_id, source, error=str(exc))


if __name__ == "__main__":
    main()
