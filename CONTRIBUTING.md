# Contributing to Beacon

Thank you for contributing. Keep changes focused, include tests for behavior
changes, and do not commit credentials, customer data, recordings, face
images, model weights, or generated build directories.

## Development prerequisites

- Python 3.10, 3.11, or 3.12
- Node.js 20.19+ (or 22.12+)
- a C++17 compiler, CMake 3.16+, pkg-config, and OpenCV 4 development files

## Admin backend

```bash
cd Admin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-linux.txt
python manage.py migrate --noinput
python manage.py test
python -m unittest test_video_analyzer_launcher_paths
```

Use `requirements-windows.txt` instead on Windows. Optional integrations are
listed in `requirements-optional.txt`.

## React frontend

```bash
cd Admin/frontend
npm ci
npm test
npm run build
npm audit --audit-level=high
```

The production app shell under `Admin/static/app-shell/` is tracked. Commit
the corresponding build output when frontend source changes.

## Analyzer core tests

On Debian or Ubuntu, install `clang` or `g++`, `pkg-config`, and
`libopencv-dev`, then run:

```bash
bash tools/run_analyzer_unit_tests.sh
```

The full Analyzer build also needs ONNX Runtime and, depending on the chosen
backend, OpenVINO or CUDA/TensorRT. See `Analyzer/README.md`.

## SDKs and documentation

```bash
(cd sdk/python && python -m unittest discover -s tests)
(cd sdk/javascript && npm ci && npm test && npm pack --dry-run)
(cd sdk/go && go test ./...)

python -m pip install -r docs/requirements.txt
python tools/docs_strict_check.py
```

## Pull requests

1. Explain the user-visible change and its operational impact.
2. List the exact verification commands you ran.
3. Add or update tests and documentation when contracts change.
4. Keep secrets and private runtime data out of commits and screenshots.
5. Preserve all notices for code under `MediaServer/source/` and other
   third-party directories.

Use a short conventional commit subject such as `fix(stream): handle relay
timeout`. By submitting a contribution, you agree that it may be distributed
under the license that applies to the files you changed.
