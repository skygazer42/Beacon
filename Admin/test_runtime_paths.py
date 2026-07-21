import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock


class TestRuntimePaths(unittest.TestCase):
    def setUp(self):
        admin_dir = os.path.dirname(os.path.abspath(__file__))
        if admin_dir not in sys.path:
            sys.path.insert(0, admin_dir)

    def tearDown(self):
        sys.modules.pop("runtime_paths", None)

    def test_frozen_root_dir_uses_executable_dir(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = os.path.join(tmp, "bin")
            os.makedirs(exe_dir, exist_ok=True)
            exe_path = os.path.join(exe_dir, "VideoAnalyzer.exe")
            with open(exe_path, "w", encoding="utf-8") as f:
                f.write("")

            old_executable = sys.executable
            old_frozen = getattr(sys, "frozen", None)
            try:
                sys.executable = exe_path
                setattr(sys, "frozen", True)

                rp = importlib.import_module("runtime_paths")
                root = rp.resolve_root_dir()
                self.assertEqual(root, exe_dir)
            finally:
                sys.executable = old_executable
                if old_frozen is None:
                    if hasattr(sys, "frozen"):
                        delattr(sys, "frozen")
                else:
                    setattr(sys, "frozen", old_frozen)

    def test_frozen_root_dir_supports_launcher_inside_admin_dir(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            admin_dir = os.path.join(tmp, "Admin")
            os.makedirs(admin_dir, exist_ok=True)
            with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            exe_path = os.path.join(admin_dir, "VideoAnalyzer.exe")
            with open(exe_path, "w", encoding="utf-8") as f:
                f.write("")

            old_executable = sys.executable
            old_frozen = getattr(sys, "frozen", None)
            try:
                sys.executable = exe_path
                setattr(sys, "frozen", True)

                rp = importlib.import_module("runtime_paths")
                self.assertEqual(rp.resolve_root_dir(), tmp)
                self.assertEqual(rp.resolve_admin_dir(tmp), admin_dir)
            finally:
                sys.executable = old_executable
                if old_frozen is None:
                    if hasattr(sys, "frozen"):
                        delattr(sys, "frozen")
                else:
                    setattr(sys, "frozen", old_frozen)

    def test_frozen_admin_dir_defaults_to_root_admin_directory(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            admin_dir = os.path.join(tmp, "Admin")
            os.makedirs(admin_dir, exist_ok=True)
            exe_path = os.path.join(tmp, "VideoAnalyzer.exe")
            with open(exe_path, "w", encoding="utf-8") as f:
                f.write("")

            old_executable = sys.executable
            old_frozen = getattr(sys, "frozen", None)
            try:
                sys.executable = exe_path
                setattr(sys, "frozen", True)

                rp = importlib.import_module("runtime_paths")
                self.assertEqual(rp.resolve_root_dir(), tmp)
                self.assertEqual(rp.resolve_admin_dir(tmp), admin_dir)
            finally:
                sys.executable = old_executable
                if old_frozen is None:
                    if hasattr(sys, "frozen"):
                        delattr(sys, "frozen")
                else:
                    setattr(sys, "frozen", old_frozen)

    def test_env_override_root_dir(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"BEACON_ROOT_DIR": tmp}, clear=False):
                rp = importlib.import_module("runtime_paths")
                root = rp.resolve_root_dir()
                self.assertEqual(root, tmp)

    def test_resolve_localdeps_dir_prefers_project_directory(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "third_party", "localdeps", "sysroot"), exist_ok=True)
            os.makedirs(os.path.join(tmp, ".beads", "localdeps", "sysroot"), exist_ok=True)

            with mock.patch.dict(os.environ, {"BEACON_ROOT_DIR": tmp}, clear=False):
                rp = importlib.import_module("runtime_paths")
                deps_dir = rp.resolve_localdeps_dir()
                self.assertEqual(deps_dir, os.path.join(tmp, "third_party", "localdeps"))

    def test_resolve_localdeps_dir_supports_explicit_override(self):
        sys.modules.pop("runtime_paths", None)

        with tempfile.TemporaryDirectory() as tmp:
            override_dir = os.path.join(tmp, "custom", "deps")
            os.makedirs(os.path.join(override_dir, "sysroot"), exist_ok=True)

            with mock.patch.dict(
                os.environ,
                {
                    "BEACON_ROOT_DIR": tmp,
                    "BEACON_LOCALDEPS_DIR": override_dir,
                },
                clear=False,
            ):
                rp = importlib.import_module("runtime_paths")
                deps_dir = rp.resolve_localdeps_dir()
                self.assertEqual(deps_dir, override_dir)


if __name__ == "__main__":
    unittest.main()
