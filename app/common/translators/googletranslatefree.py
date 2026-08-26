import html
import re
import requests
import time
from common.config import UserConfig
from common.language import is_suspicious_translation, provider_target_code
from common.measure import measure_duration
from loguru import logger as log


# uses the free Google Translate mobile web interface to send translations.
# parses the html response to extract the translated text.
class GoogleTranslateFree:
    url = "https://translate.google.com/m"
    json_url = "https://translate.googleapis.com/translate_a/single"
    _batch_marker = "ZXQSEGMENT{index:04d}QXZ"
    _cooldown_schedule = (5.0, 15.0, 30.0, 60.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.108 Mobile Safari/537.36"  # noqa: E501
    }

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(GoogleTranslateFree.headers)
        config = UserConfig()
        self.target = provider_target_code("googlefree", config.target_language)
        self.source = config.source_language
        # ``is True`` also keeps loose/mocked config objects opt-out by default.
        self._yandex_fallback_enabled = config.googlefree_yandex_fallback is True
        self._yandex_fallback = None
        self._last_request_at = 0.0
        self._blocked_until = 0.0
        self._consecutive_throttles = 0
        self._translation_cache: dict[str, str] = {}

    def __wait_for_request_slot(self, minimum_interval: float = 0.75) -> None:
        """Avoid bursts that make the anonymous endpoint throttle itself."""

        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        self._last_request_at = time.monotonic()

    def __get(self, url: str, params: dict[str, str]):
        self.__wait_for_request_slot()
        return self.session.get(url, params=params, timeout=10)

    @classmethod
    def __join_batch(cls, phrases: list[str]) -> str:
        """Join provider items with stable sentinels for one HTTP request."""

        output = phrases[0]
        for index, phrase in enumerate(phrases[1:], start=1):
            output += f"\n{cls._batch_marker.format(index=index)}\n{phrase}"
        return output

    @classmethod
    def __split_batch(cls, translated: str, expected: int) -> list[str]:
        """Split a batched response only when every sentinel survived."""

        if expected == 1:
            return [translated.strip()] if translated.strip() else []
        marker = r"\s*ZXQSEGMENT\d{4}QXZ\s*"
        parts = [part.strip() for part in re.split(marker, translated, flags=re.IGNORECASE)]
        if len(parts) != expected or any(not part for part in parts):
            return []
        return parts

    def __mark_throttled(self) -> float:
        """Apply bounded exponential backoff for consecutive HTTP 429 responses."""

        schedule_index = min(self._consecutive_throttles, len(self._cooldown_schedule) - 1)
        cooldown = self._cooldown_schedule[schedule_index]
        self._consecutive_throttles += 1
        self._blocked_until = time.monotonic() + cooldown
        return cooldown

    @staticmethod
    def __is_throttled_error(exc: requests.RequestException) -> bool:
        response = getattr(exc, "response", None)
        return response is not None and response.status_code == 429

    def __parse_response(self, response: str) -> str:
        """Parses the HTML response to extract the translated text."""
        match = re.search(r'<div class="result-container">(.*?)</div>', response, re.DOTALL)
        if not match:
            return ""

        text = match.group(1).strip()
        return html.unescape(text)

    @staticmethod
    def __parse_json_response(data: object) -> str:
        try:
            segments = data[0]  # type: ignore[index]
            return "".join(segment[0] for segment in segments if segment and segment[0])
        except (IndexError, KeyError, TypeError):
            return ""

    def __translate_with_yandex(self, phrases: list[str], reason: str) -> list[str]:
        """Translate through Yandex only during an established Google cooldown."""

        if not self._yandex_fallback_enabled:
            return []

        if self._yandex_fallback is None:
            # Lazy import/initialization keeps Yandex completely unused unless
            # the user explicitly enabled it and Google actually returned 429.
            from common.translators.yandex import YandexTranslate

            self._yandex_fallback = YandexTranslate()

        log.info(f"Using temporary Yandex fallback while Google Free is {reason}.")
        results = self._yandex_fallback.translate(phrases)
        if len(results) != len(phrases):
            log.warning("Temporary Yandex fallback returned an incomplete translation batch.")
            return []
        if any(not result or is_suspicious_translation(result) for result in results):
            log.warning("Temporary Yandex fallback returned an invalid translation batch.")
            return []
        return results

    @measure_duration
    def translate(self, text: list[str]) -> list[str]:
        """Translate phrases with one batched request and a short-lived cache.

        Dialogue choices previously generated up to three requests *per line*.
        A six-item selector therefore caused an immediate anonymous-endpoint
        throttle.  Batch only the missing phrases and cache successful results.
        """

        if not text:
            return []

        missing = list(dict.fromkeys(phrase for phrase in text if phrase not in self._translation_cache))
        if missing:
            request_text = self.__join_batch(missing)
            translated_items: list[str] = []
            google_succeeded = False
            remaining_cooldown = self._blocked_until - time.monotonic()
            if remaining_cooldown > 0:
                log.debug(
                    "Google Translate Free is cooling down after a rate-limit response "
                    f"({remaining_cooldown:.1f} seconds remaining)."
                )
                translated_items = self.__translate_with_yandex(missing, "cooling down")
                if len(translated_items) == len(missing):
                    self._translation_cache.update(zip(missing, translated_items, strict=True))
                return [self._translation_cache.get(phrase, "") for phrase in text]
            if self._blocked_until > 0:
                log.info("Google Free cooldown ended; returning to Google for new translations.")
                self._blocked_until = 0.0

            mobile_params = {"hl": self.target, "sl": self.source, "tl": self.target, "q": request_text}
            google_throttled = False
            try:
                response = self.__get(self.url, mobile_params)
                response.raise_for_status()
                candidate = self.__parse_response(response.text)
                if candidate and not is_suspicious_translation(candidate):
                    translated_items = self.__split_batch(candidate, len(missing))
                    google_succeeded = bool(translated_items)
                if not translated_items:
                    log.debug("Google mobile response did not contain a valid translation batch.")
            except requests.RequestException as exc:
                if self.__is_throttled_error(exc):
                    cooldown = self.__mark_throttled()
                    log.warning(
                        "Google Translate Free was rate limited; pausing translation requests "
                        f"for {cooldown:.0f} seconds."
                    )
                    google_throttled = True
                log.debug(f"Google mobile request failed: {exc}")
            except (TypeError, ValueError) as exc:
                log.debug(f"Google mobile response could not be parsed: {exc}")

            if not translated_items and not google_throttled:
                try:
                    response = self.__get(
                        self.json_url,
                        {"client": "gtx", "sl": self.source, "tl": self.target, "dt": "t", "q": request_text},
                    )
                    response.raise_for_status()
                    candidate = self.__parse_json_response(response.json())
                    if candidate and not is_suspicious_translation(candidate):
                        translated_items = self.__split_batch(candidate, len(missing))
                        google_succeeded = bool(translated_items)
                    if not translated_items:
                        log.warning("Google Translate Free returned an invalid translation batch.")
                except requests.RequestException as exc:
                    if self.__is_throttled_error(exc):
                        cooldown = self.__mark_throttled()
                        log.warning(
                            "Google Translate Free was rate limited; pausing translation requests "
                            f"for {cooldown:.0f} seconds."
                        )
                        google_throttled = True
                    else:
                        log.warning(f"Google Translate Free JSON request failed: {exc}")
                except (TypeError, ValueError) as exc:
                    log.warning(f"Google Translate Free JSON response could not be parsed: {exc}")

            if not translated_items and google_throttled:
                translated_items = self.__translate_with_yandex(missing, "rate limited")

            if len(translated_items) == len(missing):
                self._translation_cache.update(zip(missing, translated_items, strict=True))
            if google_succeeded:
                self._consecutive_throttles = 0

        return [self._translation_cache.get(phrase, "") for phrase in text]
