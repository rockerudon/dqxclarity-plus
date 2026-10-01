import re
import time

import requests
from common.config import UserConfig
from common.language import is_suspicious_translation, provider_target_code
from common.measure import measure_duration
from loguru import logger as log


# Google answers on the JSON endpoint it built for its own clients, without a
# key.  The public client ids are throttled independently, so an anonymous
# request rotates to the next id instead of hitting the "sorry" captcha wall
# that the mobile HTML page puts in front of a flagged address.
class GoogleTranslateFree:
    json_url = "https://translate.googleapis.com/translate_a/single"
    # Ordered by how little traffic each id carries outside Google's own apps:
    # the browser widget id ("gtx") is what every scraper burns first, while the
    # Chrome dictionary client still has room on a throttled address.  Four ids
    # is deliberate - every dead end is a ~600 ms round trip on the game thread.
    _json_clients = ("dict-chrome-ex", "at", "x", "gtx")
    _batch_marker = "ZXQSEGMENT{index:04d}QXZ"
    _cooldown_schedule = (5.0, 15.0, 30.0)
    # Nothing about this phrase matters; it only has to survive translation.
    _probe = "こんにちは"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.108 Mobile Safari/537.36"  # noqa: E501
    }

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(GoogleTranslateFree.headers)
        config = UserConfig()
        self.target = provider_target_code("googlefree", config.target_language)
        self.source = config.source_language
        self._last_request_at = 0.0
        self._blocked_until = 0.0
        self._consecutive_throttles = 0
        self._client_index = 0
        self._translation_cache: dict[str, str] = {}

    def __wait_for_request_slot(self, minimum_interval: float = 0.1) -> None:
        """Avoid bursts that make the anonymous endpoint throttle itself."""

        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        self._last_request_at = time.monotonic()

    def __get(self, params: dict[str, str], timeout: float = 10.0):
        self.__wait_for_request_slot()
        return self.session.get(self.json_url, params=params, timeout=timeout)

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

    @staticmethod
    def __is_server_error(exc: requests.RequestException) -> bool:
        response = getattr(exc, "response", None)
        return response is not None and 500 <= response.status_code < 600

    @staticmethod
    def __parse_json_response(data: object) -> str:
        try:
            segments = data[0]  # type: ignore[index]
            return "".join(segment[0] for segment in segments if segment and segment[0])
        except (IndexError, KeyError, TypeError):
            return ""

    def __fetch_batch(self, request_text: str, expected: int, timeout: float = 10.0) -> tuple[list[str], bool]:
        """Fetch one batch, rotating over client ids until Google answers.

        Returns the batch alongside whether any id answered with rate
        limiting, so the caller decides whether that deserves a cooldown.
        Google answers HTTP 5xx per route, so those rotate, but every id sits
        behind the same host: a transport failure will not heal by trying the
        next one.
        """

        saw_throttle = False
        for offset in range(len(self._json_clients)):
            index = (self._client_index + offset) % len(self._json_clients)
            client = self._json_clients[index]
            try:
                params = {"client": client, "sl": self.source, "tl": self.target, "dt": "t", "q": request_text}
                response = self.__get(params, timeout)
                response.raise_for_status()
                candidate = self.__parse_json_response(response.json())
            except requests.RequestException as exc:
                if self.__is_throttled_error(exc):
                    saw_throttle = True
                    log.debug(f"Google Translate Free client {client!r} is rate limited.")
                    continue
                if self.__is_server_error(exc):
                    log.warning(f"Google Translate Free client {client!r} returned a server error.")
                    continue
                log.warning(f"Google Translate Free request failed with client {client!r}: {exc}")
                return [], saw_throttle
            except ValueError as exc:
                log.warning(f"Google Translate Free client {client!r} returned unreadable JSON: {exc}")
                continue

            if not candidate or is_suspicious_translation(candidate):
                log.debug(f"Google Translate Free client {client!r} returned an unusable batch.")
                continue
            items = self.__split_batch(candidate, expected)
            if not items:
                log.debug("Google Translate Free batch lost one of its segment sentinels.")
                continue

            if index != self._client_index:
                log.info(f"Google Translate Free rotated to client {client!r}.")
                self._client_index = index
            return items, saw_throttle

        return [], saw_throttle

    def __request_batch(self, request_text: str, expected: int) -> list[str]:
        """Fetch game text, cooling down only once every client id refused.

        A blocked id costs one request in this call rather than a round trip
        on every later line.
        """

        translated_items, saw_throttle = self.__fetch_batch(request_text, expected)
        if translated_items:
            return translated_items

        if saw_throttle:
            cooldown = self.__mark_throttled()
            log.warning(
                "Google Translate Free was rate limited on every client id; pausing translation "
                f"requests for {cooldown:.0f} seconds."
            )
        else:
            log.warning("Google Translate Free returned no usable translation batch.")
        return []

    def prewarm(self, timeout: float = 5.0) -> bool:
        """Choose a working client id before gameplay text depends on it.

        Without this, the first line after a block pays the whole rotation.
        Finding every id blocked here deliberately leaves no cooldown behind:
        the game may not reach its first line for another minute.
        """

        translated_items, _ = self.__fetch_batch(self._probe, 1, timeout)
        return bool(translated_items)

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
            remaining_cooldown = self._blocked_until - time.monotonic()
            if remaining_cooldown > 0:
                log.debug(
                    "Google Translate Free is cooling down after a rate-limit response "
                    f"({remaining_cooldown:.1f} seconds remaining)."
                )
                return [self._translation_cache.get(phrase, "") for phrase in text]
            if self._blocked_until > 0:
                log.info("Google Free cooldown ended; returning to Google for new translations.")
                self._blocked_until = 0.0

            translated_items = self.__request_batch(self.__join_batch(missing), len(missing))
            if len(translated_items) == len(missing):
                self._translation_cache.update(zip(missing, translated_items, strict=True))
            if translated_items:
                self._consecutive_throttles = 0

        return [self._translation_cache.get(phrase, "") for phrase in text]
