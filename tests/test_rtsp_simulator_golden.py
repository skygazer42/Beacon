import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "golden" / "rtsp_simulator_probe.json"


class RtspSimulatorGoldenTest(unittest.TestCase):
    def test_rtsp_simulator_probe_matches_golden(self):
        from tools.rtsp_simulator import RtspSimulator

        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        with RtspSimulator() as sim:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height",
                    "-of",
                    "json",
                    sim.stream_url,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probe.returncode, 0, msg=probe.stderr or probe.stdout)
            payload = json.loads(probe.stdout or "{}")
            stream = ((payload.get("streams") or [{}])[0]) if isinstance(payload, dict) else {}
            current = {
                "codec_name": stream.get("codec_name"),
                "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0),
            }
            self.assertEqual(current, golden)

            decode = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    sim.stream_url,
                    "-frames:v",
                    "2",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decode.returncode, 0, msg=decode.stderr or decode.stdout)


if __name__ == "__main__":
    unittest.main()
