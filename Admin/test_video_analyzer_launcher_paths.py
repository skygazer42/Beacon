import configparser
import importlib
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock
from unittest import mock


class TestVideoAnalyzerLauncherPaths(unittest.TestCase):
    def setUp(self):
        admin_dir = os.path.dirname(os.path.abspath(__file__))
        if admin_dir not in sys.path:
            sys.path.insert(0, admin_dir)
        for name in ("VideoAnalyzer", "runtime_paths"):
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in ("VideoAnalyzer", "runtime_paths"):
            sys.modules.pop(name, None)

    def _import_video_analyzer(self):
        va = importlib.import_module("VideoAnalyzer")
        va.logger = logging.getLogger("VideoAnalyzer.test")
        return va

    def test_build_admin_args_prefers_packaged_python_runtime(self):
        va = self._import_video_analyzer()
        with tempfile.TemporaryDirectory() as tmp:
            manage_py = os.path.join(tmp, "manage.py")
            with open(manage_py, "w", encoding="utf-8") as f:
                f.write("")
            scripts_dir = os.path.join(tmp, "venv", "Scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            python_exe = os.path.join(scripts_dir, "python.exe")
            with open(python_exe, "w", encoding="utf-8") as f:
                f.write("")
            venv_cfg = os.path.join(tmp, "venv", "pyvenv.cfg")
            with open(venv_cfg, "w", encoding="ascii") as f:
                f.write("home = C:\\ProgramData\\anaconda3\n")
            runtime_dir = os.path.join(tmp, "python-runtime")
            os.makedirs(runtime_dir, exist_ok=True)
            runtime_exe = os.path.join(runtime_dir, "python.exe")
            with open(runtime_exe, "w", encoding="utf-8") as f:
                f.write("")
            runtime_pth = os.path.join(runtime_dir, "python311._pth")
            with open(runtime_pth, "w", encoding="ascii") as f:
                f.write("python311.zip\n")

            with (
                mock.patch.object(va, "BASE_DIR", tmp),
                mock.patch.object(va.platform, "system", return_value="Windows"),
            ):
                args = va._build_admin_args(9991)

            with open(venv_cfg, "r", encoding="ascii") as f:
                cfg = f.read()
            with open(runtime_pth, "r", encoding="ascii") as f:
                pth = f.read()

        self.assertIn("home = %s" % runtime_dir, cfg)
        self.assertIn("executable = %s" % runtime_exe, cfg)
        self.assertIn("..\\venv\\Lib\\site-packages", pth)
        self.assertIn("import site", pth)
        self.assertEqual(args[0], python_exe)
        self.assertEqual(args[1:], [manage_py, "runserver", "0.0.0.0:9991", "--noreload"])

    def test_lock_file_frozen_uses_exe_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = os.path.join(tmp, "app")
            os.makedirs(exe_dir, exist_ok=True)
            exe_path = os.path.join(exe_dir, "VideoAnalyzer.exe")
            with open(exe_path, "w", encoding="utf-8") as f:
                f.write("")

            old_executable = sys.executable
            old_frozen = getattr(sys, "frozen", None)
            try:
                sys.executable = exe_path
                setattr(sys, "frozen", True)

                va = self._import_video_analyzer()
                expected_prefix = os.path.normpath(os.path.join(exe_dir, "log"))
                self.assertTrue(
                    os.path.normpath(str(va.LOCK_FILE)).startswith(expected_prefix),
                    msg=f"LOCK_FILE={va.LOCK_FILE} expected_prefix={expected_prefix}",
                )
            finally:
                sys.executable = old_executable
                if old_frozen is None:
                    if hasattr(sys, "frozen"):
                        delattr(sys, "frozen")
                else:
                    setattr(sys, "frozen", old_frozen)

    def test_ensure_single_instance_reclaims_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            va = self._import_video_analyzer()
            lock_path = os.path.join(tmp, "startup.lock")
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write("999999,0\n")

            old_pid_exists = va._pid_exists
            try:
                va._pid_exists = lambda pid: False
                self.assertTrue(va.ensure_single_instance(lock_path))
                self.assertEqual(va._read_pid_from_lock(lock_path), os.getpid())
            finally:
                va._pid_exists = old_pid_exists

    def test_ensure_single_instance_rejects_live_pid_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            va = self._import_video_analyzer()
            lock_path = os.path.join(tmp, "startup.lock")
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write("12345,0\n")

            old_pid_exists = va._pid_exists
            try:
                va._pid_exists = lambda pid: True
                self.assertFalse(va.ensure_single_instance(lock_path))
                self.assertEqual(va._read_pid_from_lock(lock_path), 12345)
            finally:
                va._pid_exists = old_pid_exists

    def test_app_start_skips_restart_when_backoff_active(self):
        va = self._import_video_analyzer()
        app = va.App("Analyzer", ["analyzer"])
        app.get_info = lambda: {"process": "Analyzer", "state": False, "pid": None}
        setattr(app, "_App__last_start_ts", 100)
        setattr(app, "_App__restart_failures", 1)

        calls = {"port": 0, "kill": 0, "start": 0}
        old_time = va.time.time
        old_check_port_free = va._check_port_free
        try:
            va.time.time = lambda: 150

            def _check_port_free(_port):
                calls["port"] += 1
                return True, "free"

            va._check_port_free = _check_port_free
            setattr(app, "_App__kill_process", lambda: calls.__setitem__("kill", calls["kill"] + 1) or True)
            setattr(app, "_App__start_process", lambda: calls.__setitem__("start", calls["start"] + 1) or True)

            self.assertFalse(app.start())
            self.assertEqual(calls["port"], 0)
            self.assertEqual(calls["kill"], 0)
            self.assertEqual(calls["start"], 0)
        finally:
            va.time.time = old_time
            va._check_port_free = old_check_port_free

    def test_app_start_skips_when_required_port_is_occupied(self):
        va = self._import_video_analyzer()
        app = va.App("Analyzer", ["analyzer"], ports=[19093])
        app.get_info = lambda: {"process": "Analyzer", "state": False, "pid": None}

        calls = {"kill": 0, "start": 0}
        old_check_port_free = va._check_port_free
        try:
            va._check_port_free = lambda port: (False, "busy:%d" % port)
            setattr(app, "_App__kill_process", lambda: calls.__setitem__("kill", calls["kill"] + 1) or True)
            setattr(app, "_App__start_process", lambda: calls.__setitem__("start", calls["start"] + 1) or True)

            self.assertFalse(app.start(force=True))
            self.assertEqual(calls["kill"], 0)
            self.assertEqual(calls["start"], 0)
        finally:
            va._check_port_free = old_check_port_free

    def test_app_start_force_bypasses_backoff_and_resets_failures(self):
        va = self._import_video_analyzer()
        app = va.App("Analyzer", ["analyzer"], ports=[19094])
        app.get_info = lambda: {"process": "Analyzer", "state": False, "pid": None}
        setattr(app, "_App__last_start_ts", 100)
        setattr(app, "_App__restart_failures", 3)

        calls = {"kill": 0, "start": 0}
        old_time = va.time.time
        old_check_port_free = va._check_port_free
        try:
            va.time.time = lambda: 101
            va._check_port_free = lambda _port: (True, "free")
            setattr(app, "_App__kill_process", lambda: calls.__setitem__("kill", calls["kill"] + 1) or True)
            setattr(app, "_App__start_process", lambda: calls.__setitem__("start", calls["start"] + 1) or True)

            self.assertTrue(app.start(force=True))
            self.assertEqual(calls["kill"], 1)
            self.assertEqual(calls["start"], 1)
            self.assertEqual(getattr(app, "_App__restart_failures"), 0)
        finally:
            va.time.time = old_time
            va._check_port_free = old_check_port_free

    def test_record_log_restarts_stopped_process_after_grace_period(self):
        class _StopLoop(RuntimeError):
            pass

        class _FakeApp:
            def __init__(self):
                self.starts = 0
                setattr(self, "_App__last_start_ts", 100)

            def get_info(self):
                return {"process": "Analyzer", "state": False, "pid": None}

            def start(self):
                self.starts += 1
                return True

        va = self._import_video_analyzer()
        runner = va.VideoAnalyzer({})
        fake_app = _FakeApp()
        setattr(runner, "_VideoAnalyzer__apps", [fake_app])

        old_time = va.time.time
        old_sleep = va.time.sleep
        try:
            va.time.time = lambda: 161
            sleep_calls = {"count": 0}

            def _sleep(_seconds):
                sleep_calls["count"] += 1
                if sleep_calls["count"] > 1:
                    raise _StopLoop()

            va.time.sleep = _sleep

            with self.assertRaises(_StopLoop):
                runner._VideoAnalyzer__record_log()

            self.assertEqual(fake_app.starts, 1)
        finally:
            va.time.time = old_time
            va.time.sleep = old_sleep

    def test_app_get_info_uses_running_process_started_time(self):
        class _FakeProc:
            pid = 123

            def poll(self):
                return None

        class _FakePsProcess:
            def status(self):
                return "running"

            def create_time(self):
                return 1700000000

        def _process(pid):
            self.assertEqual(pid, 123)
            return _FakePsProcess()

        class _FakePsutil:
            pass

        _FakePsutil.Process = staticmethod(_process)

        va = self._import_video_analyzer()
        old_psutil = va.psutil
        try:
            va.psutil = _FakePsutil()
            app = va.App("Analyzer", ["analyzer"])
            setattr(app, "_App__proc", _FakeProc())

            info = app.get_info()

            self.assertTrue(info["state"])
            self.assertEqual(info["status"], "running")
            self.assertEqual(
                info["started"],
                va.time.strftime("%Y-%m-%d %H:%M:%S", va.time.localtime(1700000000)),
            )
        finally:
            va.psutil = old_psutil

    def test_app_get_info_uses_tracked_pid_started_time(self):
        class _FakePsProcess:
            def status(self):
                return "sleeping"

            def create_time(self):
                return 1700000060

        def _process(pid):
            self.assertEqual(pid, 456)
            return _FakePsProcess()

        class _FakePsutil:
            pass

        _FakePsutil.Process = staticmethod(_process)

        va = self._import_video_analyzer()
        old_psutil = va.psutil
        old_pid_exists = va._pid_exists
        try:
            va.psutil = _FakePsutil()
            va._pid_exists = lambda pid: pid == 456
            app = va.App("Analyzer", ["analyzer"])
            setattr(app, "_App__pid", 456)

            info = app.get_info()

            self.assertTrue(info["state"])
            self.assertEqual(info["status"], "sleeping")
            self.assertEqual(
                info["started"],
                va.time.strftime("%Y-%m-%d %H:%M:%S", va.time.localtime(1700000060)),
            )
        finally:
            va.psutil = old_psutil
            va._pid_exists = old_pid_exists

    def test_build_usb_camera_bridge_args_disabled_by_default(self):
        va = self._import_video_analyzer()

        self.assertEqual(va._build_usb_camera_bridge_args({}), [])

    def test_build_usb_camera_bridge_args_uses_defaults_and_loopback_publish_url(self):
        va = self._import_video_analyzer()

        args = va._build_usb_camera_bridge_args(
            {
                "usbCameraEnabled": True,
                "host": "0.0.0.0",
                "mediaRtmpPort": 9995,
            }
        )

        self.assertEqual(
            args,
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-f",
                "v4l2",
                "-input_format",
                "mjpeg",
                "-video_size",
                "1280x720",
                "-framerate",
                "25",
                "-i",
                "/dev/video0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "50",
                "-f",
                "flv",
                "rtmp://127.0.0.1:9995/live/usbcam",
            ],
        )

    def test_build_usb_camera_bridge_args_prefers_env_overrides(self):
        va = self._import_video_analyzer()

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_USB_CAMERA_ENABLED": "1",
                "BEACON_USB_CAMERA_FFMPEG_BIN": "/usr/local/bin/ffmpeg",
                "BEACON_USB_CAMERA_INPUT_DRIVER": "v4l2",
                "BEACON_USB_CAMERA_INPUT_FORMAT": "yuyv422",
                "BEACON_USB_CAMERA_VIDEO_SIZE": "640x480",
                "BEACON_USB_CAMERA_FRAMERATE": "15",
                "BEACON_USB_CAMERA_DEVICE": "/dev/video9",
                "BEACON_USB_CAMERA_PUBLISH_URL": "rtmp://127.0.0.1:9995/live/front-door",
            },
            clear=False,
        ):
            args = va._build_usb_camera_bridge_args({"usbCameraEnabled": False})

        self.assertEqual(args[0], "/usr/local/bin/ffmpeg")
        self.assertIn("yuyv422", args)
        self.assertIn("640x480", args)
        self.assertIn("/dev/video9", args)
        self.assertEqual(args[-1], "rtmp://127.0.0.1:9995/live/front-door")

    def test_video_analyzer_run_starts_usb_camera_bridge_when_enabled(self):
        va = self._import_video_analyzer()
        created = []
        events = []

        class _FakeApp:
            def __init__(self, process_name, process_start_args, ports=None, env=None):
                self.process_name = process_name
                created.append(
                    {
                        "process_name": process_name,
                        "args": list(process_start_args),
                        "ports": list(ports or []),
                        "env": env,
                    }
                )

            def start(self, force=False):
                events.append("start:%s" % self.process_name)
                return True

            def get_info(self):
                return {"process": "fake", "state": True, "pid": 1}

        class _FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                return None

            def join(self):
                return None

        old_app = va.App
        old_thread = va.threading.Thread
        old_media = va._build_media_server_args
        old_admin = va._build_admin_args
        old_analyzer = va._build_analyzer_args
        old_wait = getattr(va, "_wait_for_usb_camera_publish_target", None)

        def _fake_wait(config_data, publish_url):
            events.append("wait:%s" % publish_url)
            return True

        try:
            va.App = _FakeApp
            va.threading.Thread = _FakeThread
            va._build_media_server_args = lambda config_data=None: ["media-server"]
            va._build_admin_args = lambda port: ["manage", "runserver", "0.0.0.0:%s" % port, "--noreload"]
            va._build_analyzer_args = lambda: ["analyzer", "-f", "/tmp/config.json"]
            va._wait_for_usb_camera_publish_target = _fake_wait

            runner = va.VideoAnalyzer(
                {
                    "adminPort": 9991,
                    "analyzerPort": 9993,
                    "mediaHttpPort": 9992,
                    "mediaRtspPort": 9994,
                    "mediaRtmpPort": 9995,
                    "usbCameraEnabled": True,
                }
            )
            runner.run()
        finally:
            va.App = old_app
            va.threading.Thread = old_thread
            va._build_media_server_args = old_media
            va._build_admin_args = old_admin
            va._build_analyzer_args = old_analyzer
            if old_wait is None:
                delattr(va, "_wait_for_usb_camera_publish_target")
            else:
                va._wait_for_usb_camera_publish_target = old_wait

        self.assertEqual(
            [item["process_name"] for item in created],
            ["MediaServer", "manage", "Analyzer", "UsbCameraBridge"],
        )
        self.assertEqual(created[-1]["args"][-1], "rtmp://127.0.0.1:9995/live/usbcam")
        self.assertEqual(
            events,
            [
                "start:MediaServer",
                "start:manage",
                "start:Analyzer",
                "wait:rtmp://127.0.0.1:9995/live/usbcam",
                "start:UsbCameraBridge",
            ],
        )

    def test_video_analyzer_run_starts_media_admin_and_analyzer_apps(self):
        created = []
        threads = []

        class _FakeApp:
            def __init__(self, name, args, ports=None, env=None):
                self.name = name
                self.args = args
                self.ports = ports
                self.env = env
                self.started = 0
                created.append(self)

            def start(self):
                self.started += 1
                return True

        class _FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                self.target = target
                self.args = args
                self.daemon = daemon
                self.started = False
                self.joined = False
                threads.append(self)

            def start(self):
                self.started = True

            def join(self):
                self.joined = True

        va = self._import_video_analyzer()
        old_app = va.App
        old_thread = va.threading.Thread
        old_media_args = va._build_media_server_args
        old_admin_args = va._build_admin_args
        old_analyzer_args = va._build_analyzer_args
        try:
            va.App = _FakeApp
            va.threading.Thread = _FakeThread
            va._build_media_server_args = lambda config_data=None: ["media"]
            va._build_admin_args = lambda port: ["admin", str(port)]
            va._build_analyzer_args = lambda: ["analyzer"]

            runner = va.VideoAnalyzer(
                {
                    "adminPort": 9991,
                    "mediaHttpPort": 9992,
                    "mediaRtspPort": 9993,
                    "mediaRtmpPort": 9994,
                    "analyzerPort": 9995,
                }
            )
            runner.run()

            self.assertEqual([app.name for app in created], ["MediaServer", "manage", "Analyzer"])
            self.assertEqual(created[0].ports, [9992, 9993, 9994])
            self.assertEqual(created[1].ports, [9991])
            self.assertEqual(created[2].ports, [9995])
            self.assertIsInstance(created[2].env, dict)
            self.assertTrue(all(app.started == 1 for app in created))
            self.assertEqual(len(threads), 2)
            self.assertTrue(all(thread.started for thread in threads))
            self.assertTrue(threads[1].joined)
        finally:
            va.App = old_app
            va.threading.Thread = old_thread
            va._build_media_server_args = old_media_args
            va._build_admin_args = old_admin_args
            va._build_analyzer_args = old_analyzer_args

    def test_build_analyzer_args_ignores_source_directory_without_binary(self):
        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_system = va.platform.system
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.makedirs(os.path.join(tmp, "Analyzer", "Analyzer", "Core"), exist_ok=True)
                va.ROOT_DIR = tmp
                va.platform.system = lambda: "Linux"

                self.assertEqual(va._build_analyzer_args(), [])
        finally:
            va.ROOT_DIR = old_root_dir
            va.platform.system = old_system

    def test_build_media_server_args_requires_existing_binary(self):
        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_system = va.platform.system
        old_machine = va.platform.machine
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.makedirs(os.path.join(tmp, "MediaServer", "bin", "bin.x86.gcc9.4"), exist_ok=True)
                va.ROOT_DIR = tmp
                va.platform.system = lambda: "Linux"
                va.platform.machine = lambda: "x86_64"

                self.assertEqual(va._build_media_server_args(), [])
        finally:
            va.ROOT_DIR = old_root_dir
            va.platform.system = old_system
            va.platform.machine = old_machine

    def test_build_media_server_args_generates_runtime_config_with_config_json_ports(self):
        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_system = va.platform.system
        old_machine = va.platform.machine
        try:
            with tempfile.TemporaryDirectory() as tmp:
                release_dir = os.path.join(tmp, "MediaServer", "source", "release", "linux", "Release")
                bin_dir = os.path.join(tmp, "MediaServer", "bin", "bin.x86.gcc9.4")
                os.makedirs(release_dir, exist_ok=True)
                os.makedirs(bin_dir, exist_ok=True)

                media_bin_target = os.path.join(release_dir, "MediaServer")
                with open(media_bin_target, "w", encoding="utf-8") as f:
                    f.write("")

                config_target = os.path.join(release_dir, "config.ini")
                with open(config_target, "w", encoding="utf-8") as f:
                    f.write(
                        "[api]\n"
                        "secret=template-secret\n"
                        "\n"
                        "[http]\n"
                        "port=80\n"
                        "sslport=443\n"
                        "\n"
                        "[rtmp]\n"
                        "port=1935\n"
                        "\n"
                        "[rtsp]\n"
                        "port=554\n"
                    )

                os.symlink(
                    os.path.relpath(media_bin_target, bin_dir),
                    os.path.join(bin_dir, "MediaServer"),
                )
                os.symlink(
                    os.path.relpath(config_target, bin_dir),
                    os.path.join(bin_dir, va.MEDIA_SERVER_CONFIG_INI),
                )

                va.ROOT_DIR = tmp
                va.platform.system = lambda: "Linux"
                va.platform.machine = lambda: "x86_64"

                with mock.patch.dict(os.environ, {"BEACON_MEDIA_SECRET": "env-secret"}):
                    args = va._build_media_server_args(
                        {
                            "mediaSecret": "config-secret",
                            "mediaHttpPort": 9992,
                            "mediaRtspPort": 9994,
                            "mediaRtmpPort": 9995,
                        }
                    )

                runtime_config = os.path.join(release_dir, "config.runtime.ini")
                self.assertEqual(args, [os.path.join(bin_dir, "MediaServer"), "-c", runtime_config])

                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str
                parser.read(runtime_config, encoding="utf-8")

                self.assertEqual(parser.get("api", "secret"), "env-secret")
                self.assertEqual(parser.getint("http", "port"), 9992)
                self.assertEqual(parser.getint("http", "sslport"), 0)
                self.assertEqual(parser.getint("rtsp", "port"), 9994)
                self.assertEqual(parser.getint("rtmp", "port"), 9995)
        finally:
            va.ROOT_DIR = old_root_dir
            va.platform.system = old_system
            va.platform.machine = old_machine

    def test_build_analyzer_env_includes_runtime_libs_dir(self):
        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_system = va.platform.system
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_libs = os.path.join(tmp, "runtime-libs")
                os.makedirs(runtime_libs, exist_ok=True)

                va.ROOT_DIR = tmp
                va.platform.system = lambda: "Linux"

                env = va._build_analyzer_env({"LD_LIBRARY_PATH": "/already/here"})

                self.assertEqual(env["LD_LIBRARY_PATH"].split(os.pathsep)[0], runtime_libs)
                self.assertIn("/already/here", env["LD_LIBRARY_PATH"])
        finally:
            va.ROOT_DIR = old_root_dir
            va.platform.system = old_system

    def test_build_analyzer_env_prefers_project_localdeps(self):
        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_system = va.platform.system
        try:
            with tempfile.TemporaryDirectory() as tmp:
                project_deps = os.path.join(tmp, "third_party", "localdeps")
                legacy_deps = os.path.join(tmp, ".beads", "localdeps")
                ort = os.path.join(project_deps, "src", "onnxruntime-linux-x64-1.17.3")
                ov_runtime = os.path.join(
                    project_deps,
                    "src",
                    "l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64",
                    "runtime",
                )
                sysroot = os.path.join(project_deps, "sysroot")

                for path in (
                    os.path.join(sysroot, "usr", "include"),
                    os.path.join(sysroot, "usr", "include", "jsoncpp"),
                    os.path.join(sysroot, "usr", "include", "x86_64-linux-gnu"),
                    os.path.join(sysroot, "usr", "lib", "x86_64-linux-gnu"),
                    os.path.join(ort, "include"),
                    os.path.join(ort, "lib"),
                    os.path.join(ov_runtime, "include"),
                    os.path.join(ov_runtime, "lib", "intel64"),
                    os.path.join(ov_runtime, "3rdparty", "tbb", "include"),
                    os.path.join(ov_runtime, "3rdparty", "tbb", "lib"),
                    os.path.join(legacy_deps, "sysroot"),
                ):
                    os.makedirs(path, exist_ok=True)

                va.ROOT_DIR = tmp
                va.platform.system = lambda: "Linux"

                env = va._build_analyzer_env({"LD_LIBRARY_PATH": "/already/here"})

                self.assertEqual(env["BEACON_LOCALDEPS_DIR"], project_deps)
                self.assertIn(os.path.join(ort, "include"), env["CPATH"])
                self.assertIn(os.path.join(ov_runtime, "lib", "intel64"), env["LD_LIBRARY_PATH"])
                self.assertIn("/already/here", env["LD_LIBRARY_PATH"])
                self.assertNotIn(legacy_deps, env["BEACON_LOCALDEPS_DIR"])
        finally:
            va.ROOT_DIR = old_root_dir
            va.platform.system = old_system

    def test_run_passes_runtime_libs_env_to_media_server_and_analyzer(self):
        created_apps = []

        class _FakeApp:
            def __init__(self, name, args, ports=None, env=None):
                self.name = name
                self.args = args
                self.ports = ports
                self.env = env
                created_apps.append(self)

            def start(self):
                return True

            def get_info(self):
                return {"process": self.name, "state": True, "pid": 1}

        class _FakeThread:
            def __init__(self, target=None, args=None, daemon=None):
                self._target = target
                self._args = args or ()

            def start(self):
                return None

            def join(self):
                return None

        va = self._import_video_analyzer()
        old_root_dir = va.ROOT_DIR
        old_app = va.App
        old_thread = va.threading.Thread
        old_build_media_server_args = va._build_media_server_args
        old_build_admin_args = va._build_admin_args
        old_build_analyzer_args = va._build_analyzer_args
        old_build_usb_camera_bridge_args = va._build_usb_camera_bridge_args
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_libs = os.path.join(tmp, "runtime-libs")
                os.makedirs(runtime_libs, exist_ok=True)

                va.ROOT_DIR = tmp
                va.App = _FakeApp
                va.threading.Thread = _FakeThread
                va._build_media_server_args = lambda config_data=None: ["media"]
                va._build_admin_args = lambda _port: ["manage"]
                va._build_analyzer_args = lambda: ["analyzer"]
                va._build_usb_camera_bridge_args = lambda _config: []

                with mock.patch.object(va.secrets, "token_urlsafe", return_value="generated-media-secret"):
                    runner = va.VideoAnalyzer({"adminPort": 9991, "analyzerPort": 9993})
                    runner.run()

                media_app = next(app for app in created_apps if app.name == "MediaServer")
                admin_app = next(app for app in created_apps if app.name == "manage")
                analyzer_app = next(app for app in created_apps if app.name == "Analyzer")

                self.assertEqual(media_app.env["LD_LIBRARY_PATH"].split(os.pathsep)[0], runtime_libs)
                self.assertEqual(analyzer_app.env["LD_LIBRARY_PATH"].split(os.pathsep)[0], runtime_libs)
                self.assertEqual(media_app.env["BEACON_MEDIA_SECRET"], "generated-media-secret")
                self.assertEqual(admin_app.env["BEACON_MEDIA_SECRET"], "generated-media-secret")
                self.assertEqual(analyzer_app.env["BEACON_MEDIA_SECRET"], "generated-media-secret")
        finally:
            va.ROOT_DIR = old_root_dir
            va.App = old_app
            va.threading.Thread = old_thread
            va._build_media_server_args = old_build_media_server_args
            va._build_admin_args = old_build_admin_args
            va._build_analyzer_args = old_build_analyzer_args
            va._build_usb_camera_bridge_args = old_build_usb_camera_bridge_args

    def test_app_start_process_passes_custom_env_to_popen(self):
        class _FakeProc:
            pid = 321

        calls = {}

        def _fake_popen(args, shell, cwd, creationflags, env):
            calls["args"] = args
            calls["shell"] = shell
            calls["cwd"] = cwd
            calls["creationflags"] = creationflags
            calls["env"] = env
            return _FakeProc()

        va = self._import_video_analyzer()
        old_popen = va.subprocess.Popen
        try:
            va.subprocess.Popen = _fake_popen
            app = va.App("Analyzer", ["analyzer"], env={"BEACON_LOCALDEPS_DIR": "/tmp/localdeps"})

            self.assertTrue(app._App__start_process())
            self.assertEqual(calls["args"], ["analyzer"])
            self.assertEqual(calls["cwd"], va.ROOT_DIR)
            self.assertEqual(calls["env"]["BEACON_LOCALDEPS_DIR"], "/tmp/localdeps")
        finally:
            va.subprocess.Popen = old_popen

    def test_get_logger_adds_file_and_console_handlers(self):
        va = self._import_video_analyzer()
        root_logger = logging.getLogger()
        original_handlers = tuple(root_logger.handlers)
        original_level = root_logger.level
        for handler in tuple(root_logger.handlers):
            root_logger.removeHandler(handler)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                log_dir = os.path.join(tmp, "logs")
                logger = va.get_logger(log_dir=log_dir, is_show_console=True)
                self.assertIs(logger, root_logger)
                self.assertTrue(
                    any(str(getattr(handler, "baseFilename", "")).startswith(log_dir) for handler in logger.handlers)
                )
                self.assertTrue(any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers))
        finally:
            for handler in tuple(root_logger.handlers):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
            root_logger.setLevel(original_level)
            for handler in original_handlers:
                root_logger.addHandler(handler)


if __name__ == "__main__":
    unittest.main()
