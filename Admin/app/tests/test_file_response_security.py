import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from app.views import FileServiceView
from app.views.FileServiceView import _build_local_file_response


class FileResponseSecurityTests(SimpleTestCase):
    def test_active_content_is_downloaded_as_opaque_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'payload.html')
            with open(path, 'wb') as handle:
                handle.write(b'<script>alert(1)</script>')

            response = _build_local_file_response(path)
            try:
                self.assertEqual(response['Content-Type'], 'application/octet-stream')
                self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertIn('sandbox', response['Content-Security-Policy'])
            finally:
                response.close()

    def test_media_remains_inline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'recording.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'media')

            response = _build_local_file_response(path)
            try:
                self.assertEqual(response['Content-Type'], 'video/mp4')
                self.assertTrue(response['Content-Disposition'].startswith('inline;'))
            finally:
                response.close()

    def test_symlink_targets_outside_file_service_root_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside_file = os.path.join(outside_dir, "secret.txt")
            with open(outside_file, "wb") as handle:
                handle.write(b"secret")
            link_path = os.path.join(temp_dir, "link.txt")
            os.symlink(outside_file, link_path)

            with mock.patch.object(FileServiceView.g_config, "fileServiceEnabled", True), mock.patch.object(
                FileServiceView.g_config,
                "fileServiceRootDir",
                temp_dir,
            ):
                with self.assertRaisesRegex(ValueError, "escapes"):
                    FileServiceView._resolve_abs_path("link.txt")

            response = _build_local_file_response(link_path)
            self.assertEqual(response.status_code, 404)
