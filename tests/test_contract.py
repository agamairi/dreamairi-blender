import unittest

from dreamairi_blender.llm.contract import ContractError, parse_and_validate


class ContractTests(unittest.TestCase):
    def test_parse_valid_payload(self) -> None:
        payload = {
            "version": "1.0",
            "summary": "Test",
            "style": {"poly_budget": 500, "notes": "ok"},
            "ops": [
                {"op": "ADD_CUBE", "name": "Cube"},
            ],
        }
        text = str(payload).replace("'", '"')
        plan = parse_and_validate(text)
        self.assertEqual(plan.summary, "Test")
        self.assertEqual(plan.style.poly_budget, 500)
        self.assertEqual(plan.ops[0].op, "ADD_CUBE")

    def test_reject_extra_keys(self) -> None:
        payload = {
            "version": "1.0",
            "summary": "Test",
            "style": {"poly_budget": 500, "notes": "ok"},
            "ops": [],
            "extra": "nope",
        }
        text = str(payload).replace("'", '"')
        with self.assertRaises(ContractError):
            parse_and_validate(text)

    def test_extract_from_text(self) -> None:
        text = "Here is JSON: {\"version\": \"1.0\", \"summary\": \"Ok\", " \
            "\"style\": {\"poly_budget\": 100, \"notes\": \"\"}, " \
            "\"ops\": []} trailing"
        plan = parse_and_validate(text)
        self.assertEqual(plan.summary, "Ok")


if __name__ == "__main__":
    unittest.main()
