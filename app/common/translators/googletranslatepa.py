import time

import requests
from common.config import UserConfig
from common.language import is_suspicious_translation, provider_target_code
from common.measure import measure_duration
from loguru import logger as log


# Google's keyless translate_a/single endpoint, one request per phrase so a
# dialogue line never waits on a batch the player has already passed.
class GoogleTranslatePa:
    _URL = "https://translate.googleapis.com/translate_a/single"
    # Same order as GoogleTranslateFree's ids: the browser widget id ("gtx") is the
    # one every scraper burns first, while the Chrome dictionary client still has
    # room on a throttled address.  Four ids because every dead end costs a ~600 ms
    # round trip on the game thread.
    _clients = ("dict-chrome-ex", "at", "x", "gtx")
    _cooldown_schedule = (5.0, 15.0, 30.0)
    # Nothing about this phrase matters; it only has to survive translation.
    _probe = "こんにちは"

    def __init__(self, api_key: str = "") -> None:
        self.session = requests.Session()
        config = UserConfig()
        self.target = provider_target_code("googletranslatepa", config.target_language)
        self.source = config.source_language
        self._last_request_at = 0.0
        self._blocked_until = 0.0
        self._consecutive_throttles = 0
        self._client_index = 0

    def __wait_for_request_slot(self, minimum_interval: float = 0.1) -> None:
        """Avoid bursts that make the anonymous endpoint throttle itself."""

        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        self._last_request_at = time.monotonic()

    def __mark_throttled(self) -> float:
        """Apply bounded exponential backoff for consecutive HTTP 429 responses."""

        schedule_index = min(self._consecutive_throttles, len(self._cooldown_schedule) - 1)
        cooldown = self._cooldown_schedule[schedule_index]
        self._consecutive_throttles += 1
        self._blocked_until = time.monotonic() + cooldown
        return cooldown

    @staticmethod
    def __status_code(exc: requests.RequestException) -> int:
        response = getattr(exc, "response", None)
        return 0 if response is None else response.status_code

    def __fetch_phrase(self, phrase: str, timeout: float = 10.0) -> tuple[str, bool]:
        """Fetch one phrase, rotating over client ids until Google answers.

        Returns the translation alongside whether any id answered with rate
        limiting, so the caller decides whether that deserves a cooldown.
        Google answers HTTP 5xx per route, so those rotate, but every id sits
        behind the same host: a transport failure will not heal by trying the
        next one.
        """

        saw_throttle = False
        for offset in range(len(self._clients)):
            index = (self._client_index + offset) % len(self._clients)
            client = self._clients[index]
            try:
                self.__wait_for_request_slot()
                response = self.session.get(
                    self._URL,
                    params={"client": client, "sl": self.source, "tl": self.target, "dt": "t", "q": phrase},
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                translated = "".join(segment[0] for segment in data[0] if segment[0])
            except requests.RequestException as exc:
                status = self.__status_code(exc)
                if status == 429:
                    saw_throttle = True
                    log.debug(f"Google Translate PA client {client!r} is rate limited.")
                    continue
                if 500 <= status < 600:
                    log.warning(f"Google Translate PA client {client!r} returned a server error.")
                    continue
                log.error(f"Error during request: {exc}")
                return "", saw_throttle
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                log.warning(f"Google Translate PA client {client!r} returned an unreadable response: {exc}")
                continue

            if is_suspicious_translation(translated):
                log.warning(f"Google Translate PA client {client!r} returned an invalid response.")
                continue

            if index != self._client_index:
                log.info(f"Google Translate PA rotated to client {client!r}.")
                self._client_index = index
            return translated, saw_throttle

        return "", saw_throttle

    def prewarm(self, timeout: float = 5.0) -> bool:
        """Choose a working client id before gameplay text depends on it.

        Without this, the first line after a block pays the whole rotation.
        Finding every id blocked here deliberately leaves no cooldown behind:
        the game may not reach its first line for another minute.
        """

        translated, _ = self.__fetch_phrase(self._probe, timeout)
        return bool(translated)

    @measure_duration
    def translate(self, text: list[str]) -> list[str]:
        """Translate each phrase on its own request.

        A phrase fails the batch only after every client id refused it, and the
        batch then stays empty on purpose: Translator's length guard keeps the
        source text rather than caching a line with a hole in it.
        """

        results: list[str] = []
        for phrase in text:
            remaining_cooldown = self._blocked_until - time.monotonic()
            if remaining_cooldown > 0:
                log.debug(
                    "Google Translate PA is cooling down after a rate-limit response "
                    f"({remaining_cooldown:.1f} seconds remaining)."
                )
                return []
            if self._blocked_until > 0:
                log.info("Google Translate PA cooldown ended; returning to Google for new translations.")
                self._blocked_until = 0.0

            translated, saw_throttle = self.__fetch_phrase(phrase)
            if not translated:
                if saw_throttle:
                    cooldown = self.__mark_throttled()
                    log.warning(
                        "Google Translate PA was rate limited on every client id; pausing translation "
                        f"requests for {cooldown:.0f} seconds."
                    )
                else:
                    log.warning("Google Translate PA returned no usable translation.")
                return []

            self._consecutive_throttles = 0
            results.append(translated)

        return results
