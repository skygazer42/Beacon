import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from framework import versioning


class ProjectVersionTest(SimpleTestCase):
    def test_file_version_is_canonical(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            versioning,
            "_latest_git_tag",
            return_value="v9.9.9",
        ):
            root = Path(tmp)
            (root / "PROJECT_VERSION").write_text("v9.8.7\n", encoding="utf-8")
            self.assertEqual(versioning.get_project_version(root), "v9.8.7")
