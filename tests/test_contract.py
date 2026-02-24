import unittest

from dreamairi_blender.llm.contract import ContractError, parse_agent_response, parse_and_validate


class ContractTests(unittest.TestCase):
    def test_parse_plan(self) -> None:
        envelope = parse_agent_response('{"type":"PLAN","steps":["a","b"]}')
        self.assertEqual(envelope.response_type, "PLAN")
        self.assertEqual(envelope.plan_steps, ["a", "b"])

    def test_parse_tool_calls(self) -> None:
        envelope = parse_agent_response(
            '{"type":"TOOL_CALL","calls":[{"tool":"create_primitive","args":{"type":"cube"}}]}'
        )
        self.assertEqual(envelope.response_type, "TOOL_CALL")
        self.assertEqual(envelope.tool_calls[0].tool, "create_primitive")
        self.assertEqual(envelope.tool_calls[0].args["type"], "cube")

    def test_parse_final(self) -> None:
        envelope = parse_agent_response('{"type":"FINAL","message":"done"}')
        self.assertEqual(envelope.response_type, "FINAL")
        self.assertEqual(envelope.final_message, "done")

    def test_invalid_type(self) -> None:
        with self.assertRaises(ContractError):
            parse_agent_response('{"type":"UNKNOWN"}')

    def test_legacy_plan_parser_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ContractError):
            parse_and_validate(
                '{"version":"2","summary":"x","style":{"poly_budget":100,"notes":""},"ops":[],"extra":1}'
            )


if __name__ == "__main__":
    unittest.main()

