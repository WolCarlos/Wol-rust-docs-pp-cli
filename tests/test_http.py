from __future__ import annotations

import unittest

from rust_docs_pp_cli.http import Response


class ResponseTests(unittest.TestCase):
    def test_utf8_and_invalid_charset_fallback(self) -> None:
        self.assertEqual(
            Response("à".encode(), "https://example.test", "text/plain; charset=utf-8").text(), "à"
        )
        self.assertEqual(
            Response(b"ok", "https://example.test", "text/plain; charset=invalid").text(), "ok"
        )


if __name__ == "__main__":
    unittest.main()
