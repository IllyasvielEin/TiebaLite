"""Check envelope field assumptions against every declared protobuf service schema.

This source-level check supplements JVM decoder tests; it is not runtime proof.
"""
from pathlib import Path
import re
import unittest

MAIN = Path(__file__).resolve().parents[2] / "main"
JAVA = MAIN / "java/com/huanchengfly/tieba/post"


class ProtobufResponseContracts(unittest.TestCase):
    def test_every_service_schema_matches_interceptor_error_field(self):
        interface = (JAVA / "api/retrofit/interfaces/OfficialProtobufTiebaApi.kt").read_text()
        methods = re.findall(
            r'@POST\("([^"?]+)(?:\?[^\"]*)?"\)\s*fun\s+\w+\(.*?\):\s*Flow<(\w+)>',
            interface, re.S,
        )
        self.assertEqual(interface.count("@POST("), len(methods))
        schemas = {}
        for path in (MAIN / "protos").rglob("*.proto"):
            for name, body in re.findall(r"message\s+(\w+)\s*\{([^}]+)\}", path.read_text(), re.S):
                match = re.search(r"\bError\s+error\s*=\s*(\d+)\s*;", body)
                if match:
                    schemas[name] = int(match[1])
        interceptor = (JAVA / "api/retrofit/interceptors/ProtoFailureResponseInterceptor.kt").read_text()
        overrides = dict(re.findall(r'"([^"]+)"\s*->\s*(\w+)\.ADAPTER\.decode\(peek\)\.error', interceptor))
        expected_overrides = {}
        for path, response in methods:
            self.assertIn(response, schemas, f"Missing error field: {response}")
            if schemas[response] != 1:
                self.assertEqual(2, schemas[response], f"Review new error field in {response}")
                expected_overrides[path] = response
        self.assertEqual(expected_overrides, overrides)
        self.assertEqual(4, len(overrides))
        self.assertIn("else -> ProtoCommonResponse.ADAPTER.decode(peek).error", interceptor)


if __name__ == "__main__":
    unittest.main()
