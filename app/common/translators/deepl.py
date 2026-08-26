import deepl
from common.config import UserConfig
from common.language import provider_target_code
from common.measure import measure_duration
from loguru import logger as log


def _deepl_target(code: str) -> str:
    """Return DeepL's spelling without changing the configured language identity."""

    return provider_target_code("deepl", code or "en").upper()


# uses DeepL's official Translate API to send translations.
# requires creating a developer API account to obtain an API key.
class DeepLTranslate:
    def __init__(self, api_key: str) -> None:
        # don't retry on timeout to avoid hanging up the thread longer than we need to.
        deepl.http_client.max_network_retries = 1
        deepl.http_client.min_connection_timeout = 3

        config = UserConfig()
        self.target_lang = _deepl_target(config.target_language)
        self.target_language_name = config.target_language_name
        self.source_lang = None if config.source_language == "auto" else config.source_language.upper()
        self.ascii_output = config.active_language.ascii_output
        self.translator = deepl.DeepLClient(auth_key=api_key, send_platform_info=False)

    @measure_duration
    def translate(self, text: list[str]) -> list[str]:
        try:
            request = dict(
                text=text,
                target_lang=self.target_lang,
                preserve_formatting=True,
                model_type="prefer_quality_optimized",
                custom_instructions=[
                    # Copied from some expert prompt engineers that wrote Echoglossian.
                    # https://github.com/lokinmodar/Echoglossian/blob/API12/Translators/ChatGPTTranslator.cs#L122
                    "You are an expert translator and cultural localization specialist with deep knowledge of video game localization. Preserve the original tone, humor, personality, and emotional nuances of the dialogue, considering the unique style and atmosphere of Dragon Quest X.",  # noqa: E501
                    f"Adapt idioms, cultural references, and wordplay to resonate naturally with native {self.target_language_name} speakers while maintaining the fantasy RPG context. Avoid the overuse of profanity. Don't use the same word over and over.",  # noqa: E501
                    "Maintain consistency in character voices, terminology, and naming conventions specific to Dragon Quest X throughout the translation.",  # noqa: E501
                    "Avoid literal translations that may lose the original intent or impact, especially for game-specific terms or lore elements.",  # noqa: E501
                    f"Ensure the translation flows naturally and reads as if it were originally written in {self.target_language_name}, while staying true to the game's narrative style.",  # noqa: E501
                    "Consider the context and subtext of the dialogue, including any references to the game's lore, world, or ongoing storylines.",  # noqa: E501
                    "If a word, phrase, or name has been translated in a specific way, maintain that translation consistently unless the context demands otherwise, respecting established localization choices for Dragon Quest X.",  # noqa: E501
                    "Pay attention to formal/informal speech patterns and adjust accordingly for the target language and cultural norms, considering the speaker's role and status within the game world.",  # noqa: E501
                    "Be mindful of character limits or text box constraints that may be present in the game, adapting the translation to fit if necessary.",  # noqa: E501
                    "Preserve any game-specific jargon, spell names, or technical terms according to the official localization guidelines for Dragon Quest X.",  # noqa: E501
                    "Preserve every angle-bracket game tag and placeholder exactly as supplied.",
                ],
            )
            if self.source_lang is not None:
                request["source_lang"] = self.source_lang
            response = self.translator.translate_text(**request)

            results = []
            for result in response:
                results.append(result.text)

            return results
        except Exception as e:
            log.error(f"Error during request: {e}")
            return []
