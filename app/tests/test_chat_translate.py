import unittest

from chat_translate import _parse_request


class ChatTranslateTests(unittest.TestCase):
    def test_request_accepts_utf8_bom(self) -> None:
        request = _parse_request('\ufeff{"Id":"1","Text":"Test"}')

        self.assertEqual(request, {"Id": "1", "Text": "Test"})


if __name__ == "__main__":
    unittest.main()
