import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy" / "observability" / "tracing" / "compose.yml"
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"
SAFE_BINDING = "${BEACON_BIND_ADDRESS:-127.0.0.1}"
EXPECTED_PORTS = (3000, 3200, 4317, 4318, 9411, 13133, 16686)
IMAGE_PATTERN = re.compile(r"^\s*image:\s*\S+@sha256:[0-9a-f]{64}\s*$", re.MULTILINE)


class ObservabilityComposeSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = COMPOSE_PATH.read_text(encoding="utf-8")

    def test_every_published_port_defaults_to_loopback(self):
        for port in EXPECTED_PORTS:
            self.assertIn(f'"{SAFE_BINDING}:{port}:{port}"', self.compose)

        self.assertNotRegex(
            self.compose,
            re.compile(r'^\s*-\s*"(?:0\.0\.0\.0:)?[0-9]+:[0-9]+"', re.MULTILINE),
        )

    def test_all_images_are_pinned_by_digest(self):
        image_lines = re.findall(r"^\s*image:\s*\S+\s*$", self.compose, re.MULTILINE)
        pinned_lines = IMAGE_PATTERN.findall(self.compose)

        self.assertEqual(len(image_lines), 4)
        self.assertEqual(pinned_lines, image_lines)

    def test_grafana_password_is_required(self):
        self.assertIn(
            'GF_SECURITY_ADMIN_PASSWORD: "${GF_SECURITY_ADMIN_PASSWORD:?set GF_SECURITY_ADMIN_PASSWORD}"',
            self.compose,
        )

    def test_tracing_images_receive_dependabot_updates(self):
        dependabot = DEPENDABOT_PATH.read_text(encoding="utf-8")

        self.assertIn("directory: /deploy/observability/tracing", dependabot)
        self.assertIn("tracing-images:", dependabot)


if __name__ == "__main__":
    unittest.main()
