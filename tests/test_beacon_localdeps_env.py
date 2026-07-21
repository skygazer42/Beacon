import os
import subprocess
from pathlib import Path


def test_localdeps_env_prefers_gpu_onnxruntime(tmp_path):
    localdeps = tmp_path / "third_party" / "localdeps"
    (localdeps / "sysroot").mkdir(parents=True)
    cpu_dir = localdeps / "src" / "onnxruntime-linux-x64-1.17.3"
    gpu_dir = localdeps / "src" / "onnxruntime-linux-x64-gpu-1.18.1"
    cpu_dir.mkdir(parents=True)
    gpu_dir.mkdir(parents=True)

    env = os.environ.copy()
    env["BEACON_ROOT_DIR"] = str(tmp_path)
    for key in (
        "BEACON_LOCALDEPS_DIR",
        "BEACON_SYSROOT_DIR",
        "BEACON_ONNXRUNTIME_DIR",
        "NO_PROXY",
        "no_proxy",
    ):
        env.pop(key, None)

    script = Path(__file__).resolve().parents[1] / "tools" / "beacon_localdeps_env.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'eval "$("$1" --print)"; printf "%s\\n%s\\n%s\\n" '
            '"$BEACON_ONNXRUNTIME_DIR" "$NO_PROXY" "$no_proxy"',
            "bash",
            str(script),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    values = result.stdout.splitlines()
    assert values == [str(gpu_dir), "127.0.0.1,localhost,::1", "127.0.0.1,localhost,::1"]
