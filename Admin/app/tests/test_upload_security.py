import base64
import os
import tempfile
from pathlib import Path
from unittest import TestCase

from app.utils.UploadSecurity import (
    atomic_write_bytes,
    decode_base64_limited,
    validate_media_header,
)


class UploadSecurityTest(TestCase):
    def test_strict_bounded_base64_decode(self):
        payload = base64.b64encode(b"\xff\xd8\xffimage").decode("ascii")
        self.assertEqual(
            decode_base64_limited(f"data:image/jpeg;base64,{payload}", max_bytes=32),
            b"\xff\xd8\xffimage",
        )
        with self.assertRaises(ValueError):
            decode_base64_limited("%%%", max_bytes=32)
        with self.assertRaises(ValueError):
            decode_base64_limited(base64.b64encode(b"too-large").decode("ascii"), max_bytes=4)

    def test_media_headers_must_match_extension(self):
        validate_media_header(b"\xff\xd8\xffimage", "jpg")
        validate_media_header(b"\x00\x00\x00\x18ftypmp42", "mp4")
        with self.assertRaises(ValueError):
            validate_media_header(b"<svg onload=alert(1)>", "png")

    def test_atomic_write_is_private_and_removes_invalid_partial_file(self):
        with tempfile.TemporaryDirectory() as root:
            valid_target = Path(root) / "alarm" / "valid.jpg"
            atomic_write_bytes(
                str(valid_target),
                b"\xff\xd8\xffimage",
                allowed_root=root,
                max_bytes=32,
                media_extension="jpg",
            )
            self.assertEqual(valid_target.read_bytes(), b"\xff\xd8\xffimage")
            if os.name != "nt":
                self.assertEqual(valid_target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(valid_target.parent.stat().st_mode & 0o777, 0o700)

            invalid_target = Path(root) / "alarm" / "invalid.png"
            with self.assertRaises(ValueError):
                atomic_write_bytes(
                    str(invalid_target),
                    b"<html>active</html>",
                    allowed_root=root,
                    max_bytes=64,
                    media_extension="png",
                )
            self.assertFalse(invalid_target.exists())
            self.assertEqual(list(invalid_target.parent.glob(".*.part")), [])

    def test_symlinked_parent_cannot_escape_upload_root(self):
        if os.name == "nt":
            self.skipTest("symlink behavior is platform-specific")
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, Path(root) / "escape")
            with self.assertRaises(ValueError):
                atomic_write_bytes(
                    str(Path(root) / "escape" / "new-parent" / "image.jpg"),
                    b"\xff\xd8\xffimage",
                    allowed_root=root,
                    max_bytes=32,
                    media_extension="jpg",
                )
            self.assertFalse((Path(outside) / "new-parent").exists())

    def test_symlinked_target_is_rejected_even_when_it_stays_inside_root(self):
        if os.name == "nt":
            self.skipTest("symlink behavior is platform-specific")
        with tempfile.TemporaryDirectory() as root:
            real_target = Path(root) / "real.jpg"
            real_target.write_bytes(b"original")
            linked_target = Path(root) / "linked.jpg"
            os.symlink(real_target, linked_target)

            with self.assertRaises(ValueError):
                atomic_write_bytes(
                    str(linked_target),
                    b"\xff\xd8\xffreplacement",
                    allowed_root=root,
                    max_bytes=64,
                    media_extension="jpg",
                )

            self.assertEqual(real_target.read_bytes(), b"original")
