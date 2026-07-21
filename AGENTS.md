# Beacon repository guidance

This file applies to the entire repository.

## Project layout

- `Admin/`: Django backend and React management UI.
- `Analyzer/`: C++ video-analysis engine.
- `MediaServer/source/`: vendored ZLMediaKit-derived media server.
- `sdk/`: Python, JavaScript, and Go client SDKs.
- `deploy/`: Docker Compose and Helm deployment resources.
- `docs/`: MkDocs documentation.

## Required verification

Run the checks that match the files you changed:

- Admin: `cd Admin && python manage.py test app.tests -v 1`
- Admin launchers: `cd Admin && python -m unittest test_runtime_paths test_video_analyzer_launcher_paths`
- Frontend: `cd Admin/frontend && npm test && npm run build`
- Analyzer core: `bash tools/run_analyzer_unit_tests.sh`
- Documentation: `python tools/docs_strict_check.py`
- Python SDK: `python -m unittest discover -s sdk/python/tests -p 'test_*.py'`
- JavaScript SDK: `npm --prefix sdk/javascript test`
- Go SDK: `cd sdk/go && go test ./...`

The supported Admin runtime is Python 3.10–3.12. Frontend source changes must
include the matching generated output under `Admin/static/app-shell/`.

## Repository constraints

- Do not commit credentials, customer data, recordings, face images, model
  weights, local databases, logs, or build output.
- Preserve existing user changes in a dirty worktree.
- Keep changes focused and add tests for behavior changes.
- Preserve all upstream license and attribution files under
  `MediaServer/source/`; read `MediaServer/UPSTREAM.md` and
  `THIRD_PARTY_NOTICES.md` before changing vendored code.
- Use environment variables for production secrets and keep example values as
  obvious non-working placeholders.
