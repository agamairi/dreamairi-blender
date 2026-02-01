import unittest

from dreamairi_blender.security.sanitizer import redact


class SanitizerTests(unittest.TestCase):
    def test_redact_secret(self) -> None:
        text = "API key: secret123"
        cleaned = redact(text, ["secret123"])
        self.assertEqual(cleaned, "API key: ***")


if __name__ == "__main__":
    unittest.main()
