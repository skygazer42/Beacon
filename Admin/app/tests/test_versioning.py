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

    def test_frozen_bundle_version_file_is_used_outside_repository(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            versioning,
            "_latest_git_tag",
            return_value="",
        ):
            bundle_root = Path(tmp) / "_internal"
            module_file = bundle_root / "framework" / "versioning.py"
            module_file.parent.mkdir(parents=True)
            (bundle_root / "PROJECT_VERSION").write_text("v7.6.5\n", encoding="utf-8")

            with mock.patch.object(versioning, "__file__", str(module_file)):
                self.assertEqual(
                    versioning.get_project_version(Path(tmp) / "distribution"),
                    "v7.6.5",
                )
