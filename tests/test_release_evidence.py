import io
import json
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools import release_evidence


class ReleaseEvidenceTest(unittest.TestCase):
    VERSION = "v1.2.3"
    COMMIT = "0123456789abcdef0123456789abcdef01234567"

    @staticmethod
    def _write_project_files(root: Path, version: str = VERSION) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "PROJECT_VERSION").write_text(f"{version}\n", encoding="utf-8")
        (root / "LICENSE").write_text("test license\n", encoding="utf-8")
        (root / "THIRD_PARTY_NOTICES.md").write_text("test notices\n", encoding="utf-8")
        (root / "SECURITY.md").write_text("test security policy\n", encoding="utf-8")

    @staticmethod
    def _write_source_archive(path: Path, version: str = VERSION, *, symlink: bool = False) -> None:
        prefix = f"Beacon-{version}"
        with tarfile.open(path, mode="w:gz") as archive:
            for relative_path, payload in (
                ("PROJECT_VERSION", f"{version}\n".encode()),
                ("LICENSE", b"test license\n"),
                ("THIRD_PARTY_NOTICES.md", b"test notices\n"),
                ("SECURITY.md", b"test security policy\n"),
                ("README.md", b"Beacon\n"),
            ):
                member = tarfile.TarInfo(f"{prefix}/{relative_path}")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            if symlink:
                member = tarfile.TarInfo(f"{prefix}/unsafe-link")
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                archive.addfile(member)

    def _create_evidence_inputs(self, base: Path, *, empty_sbom: bool = False) -> tuple[Path, Path]:
        project_root = base / "project"
        evidence_dir = base / "evidence"
        self._write_project_files(project_root)
        evidence_dir.mkdir()
        self._write_source_archive(evidence_dir / f"Beacon-{self.VERSION}-source.tar.gz")
        (evidence_dir / f"Beacon-{self.VERSION}.spdx.json").write_text(
            json.dumps(
                {
                    "spdxVersion": "SPDX-2.3",
                    "SPDXID": "SPDXRef-DOCUMENT",
                    "name": "Beacon",
                    "dataLicense": "CC0-1.0",
                    "documentNamespace": "https://example.invalid/beacon/test",
                    "creationInfo": {"creators": ["Tool: syft-1.42.3"]},
                    "packages": [] if empty_sbom else [{"name": "Beacon"}],
                }
            ),
            encoding="utf-8",
        )
        bundle = {
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {},
            "dsseEnvelope": {},
        }
        for name in ("provenance.sigstore.json", "sbom.sigstore.json"):
            (evidence_dir / name).write_text(json.dumps(bundle), encoding="utf-8")
        for name, predicate_type in (
            ("provenance-verification.json", "https://slsa.dev/provenance/v1"),
            ("sbom-verification.json", "https://spdx.dev/Document"),
        ):
            (evidence_dir / name).write_text(
                json.dumps(
                    [
                        {
                            "attestation": bundle,
                            "verificationResult": {
                                "statement": {"predicateType": predicate_type}
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
        return project_root, evidence_dir

    def _artifacts(self) -> dict[str, str]:
        return {
            "source": f"Beacon-{self.VERSION}-source.tar.gz",
            "sbom": f"Beacon-{self.VERSION}.spdx.json",
            "provenance-attestation": "provenance.sigstore.json",
            "sbom-attestation": "sbom.sigstore.json",
            "provenance-verification": "provenance-verification.json",
            "sbom-verification": "sbom-verification.json",
        }

    @staticmethod
    def _create_history_repo(root: Path, tags: tuple[str, ...]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "release-history@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Release History Test"],
            cwd=root,
            check=True,
        )
        (root / "README.md").write_text("release history fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "release history fixture"],
            cwd=root,
            check=True,
        )
        for tag in tags:
            subprocess.run(["git", "tag", tag], cwd=root, check=True)

    @staticmethod
    def _published_release(tag: str, release_id: int = 1) -> dict[str, object]:
        return {
            "id": release_id,
            "tag_name": tag,
            "draft": False,
            "prerelease": "-" in tag,
            "published_at": "2026-01-01T00:00:00Z",
        }

    def _assemble(self, project_root: Path, evidence_dir: Path):
        return release_evidence.assemble_evidence(
            project_root=project_root,
            directory=evidence_dir,
            tag=self.VERSION,
            commit=self.COMMIT,
            repository="example/Beacon",
            workflow_run_url="https://github.com/example/Beacon/actions/runs/123/attempts/1",
            artifacts=self._artifacts(),
        )

    def test_assemble_and_verify_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(Path(temporary_dir))

            assembled = self._assemble(project_root, evidence_dir)
            verified = release_evidence.verify_evidence(directory=evidence_dir)

            self.assertEqual(assembled["status"], "assembled")
            self.assertEqual(verified["status"], "ok")
            self.assertEqual(verified["artifact_count"], 6)
            manifest = json.loads((evidence_dir / release_evidence.MANIFEST_NAME).read_text())
            self.assertEqual(manifest["commit"], self.COMMIT)
            self.assertEqual(manifest["source_ref"], f"refs/tags/{self.VERSION}")
            self.assertIn("gh attestation verify", manifest["verification"]["github_cli"])

    def test_verify_rejects_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(Path(temporary_dir))
            self._assemble(project_root, evidence_dir)
            with (evidence_dir / self._artifacts()["source"]).open("ab") as artifact:
                artifact.write(b"tampered")

            with self.assertRaisesRegex(release_evidence.EvidenceError, "hash or size mismatch"):
                release_evidence.verify_evidence(directory=evidence_dir)

    def test_verify_rejects_unmanifested_file(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(Path(temporary_dir))
            self._assemble(project_root, evidence_dir)
            (evidence_dir / "unmanifested.txt").write_text("unexpected", encoding="utf-8")

            with self.assertRaisesRegex(release_evidence.EvidenceError, "unmanifested"):
                release_evidence.verify_evidence(directory=evidence_dir)

    def test_assemble_rejects_empty_sbom(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(
                Path(temporary_dir), empty_sbom=True
            )

            with self.assertRaisesRegex(release_evidence.EvidenceError, "at least one package"):
                self._assemble(project_root, evidence_dir)

    def test_assemble_rejects_source_archive_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(Path(temporary_dir))
            source = evidence_dir / self._artifacts()["source"]
            source.unlink()
            self._write_source_archive(source, symlink=True)

            with self.assertRaisesRegex(release_evidence.EvidenceError, "non-file member"):
                self._assemble(project_root, evidence_dir)

    def test_assemble_refuses_to_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root, evidence_dir = self._create_evidence_inputs(Path(temporary_dir))
            self._assemble(project_root, evidence_dir)

            with self.assertRaisesRegex(release_evidence.EvidenceError, "already exists"):
                self._assemble(project_root, evidence_dir)

    def test_validate_release_ref_requires_matching_clean_tag(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir) / "repo"
            self._write_project_files(project_root)
            subprocess.run(["git", "init", "--quiet"], cwd=project_root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "release-test@example.invalid"],
                cwd=project_root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Release Test"], cwd=project_root, check=True
            )
            subprocess.run(["git", "add", "."], cwd=project_root, check=True)
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "release fixture"],
                cwd=project_root,
                check=True,
            )
            subprocess.run(["git", "tag", self.VERSION], cwd=project_root, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            report = release_evidence.validate_release_ref(
                project_root=project_root,
                tag=self.VERSION,
                expected_commit=commit,
            )
            self.assertEqual(report["commit"], commit)

            (project_root / "untracked-build-input.txt").write_text(
                "must not enter a release build\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(release_evidence.EvidenceError, "untracked"):
                release_evidence.validate_release_ref(
                    project_root=project_root,
                    tag=self.VERSION,
                    expected_commit=commit,
                )
            (project_root / "untracked-build-input.txt").unlink()

            (project_root / "LICENSE").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(release_evidence.EvidenceError, "dirty"):
                release_evidence.validate_release_ref(
                    project_root=project_root,
                    tag=self.VERSION,
                    expected_commit=commit,
                )

    def test_validate_release_history_accepts_monotonic_semver(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir) / "repo"
            self._create_history_repo(
                project_root,
                ("v1.0.0", "v1.1.0-rc.1", "v1.1.0"),
            )
            releases = [
                self._published_release("v1.0.0", 1),
                self._published_release("v1.1.0-rc.1", 2),
                self._published_release("v1.1.0", 3),
            ]

            report = release_evidence.validate_release_history(
                project_root=project_root,
                tag="v1.1.0",
                releases=releases,
                latest_release=releases[-1],
            )

            self.assertEqual(report["published_release_count"], 3)
            self.assertEqual(report["highest_published_tag"], "v1.1.0")

    def test_validate_release_history_rejects_version_rollback(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir) / "repo"
            self._create_history_repo(project_root, ("v1.2.0",))

            with self.assertRaisesRegex(
                release_evidence.EvidenceError,
                "does not advance published release",
            ):
                release_evidence.validate_release_history(
                    project_root=project_root,
                    tag="v1.1.0",
                    releases=[self._published_release("v1.2.0")],
                )

    def test_validate_release_history_rejects_invalid_latest_release(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir) / "repo"
            self._create_history_repo(project_root, ("v1.0.0",))

            with self.assertRaisesRegex(
                release_evidence.EvidenceError,
                "unsupported tag: 'v4.747'",
            ):
                release_evidence.validate_release_history(
                    project_root=project_root,
                    tag="v1.1.0",
                    releases=[self._published_release("v1.0.0")],
                    latest_release=self._published_release("v4.747", 2),
                )

    def test_validate_release_history_requires_matching_git_tag(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir) / "repo"
            self._create_history_repo(project_root, ())

            with self.assertRaisesRegex(
                release_evidence.EvidenceError,
                "has no matching fetched Git tag",
            ):
                release_evidence.validate_release_history(
                    project_root=project_root,
                    tag="v1.1.0",
                    releases=[self._published_release("v1.0.0")],
                )

    def test_semver_comparison_handles_prerelease_and_build_metadata(self):
        self.assertGreater(release_evidence._compare_semver("v1.0.0", "v1.0.0-rc.1"), 0)
        self.assertGreater(
            release_evidence._compare_semver("v1.0.0-beta.11", "v1.0.0-beta.2"),
            0,
        )
        self.assertLess(
            release_evidence._compare_semver("v1.0.0-alpha", "v1.0.0-alpha.1"),
            0,
        )
        self.assertEqual(
            release_evidence._compare_semver("v1.0.0+build.1", "v1.0.0+build.2"),
            0,
        )
        with self.assertRaisesRegex(release_evidence.EvidenceError, "supported SemVer"):
            release_evidence._compare_semver("v1.0.0-01", "v1.0.0")


class ReleaseWorkflowAssetNamingTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_source_and_container_attestation_assets_cannot_collide(self):
        source_workflow = (
            self.ROOT / ".github/workflows/release-evidence.yml"
        ).read_text(encoding="utf-8")
        container_workflow = (
            self.ROOT / ".github/workflows/release-container.yml"
        ).read_text(encoding="utf-8")

        source_names = {
            "provenance.sigstore.json",
            "sbom.sigstore.json",
            "provenance-verification.json",
            "sbom-verification.json",
        }
        container_names = {f"container-{name}" for name in source_names}

        for name in source_names:
            self.assertRegex(
                source_workflow,
                rf"(?<![A-Za-z0-9-]){re.escape(name)}",
            )
            self.assertNotRegex(
                container_workflow,
                rf"(?<![A-Za-z0-9-]){re.escape(name)}",
            )
        for name in container_names:
            self.assertIn(name, container_workflow)

        self.assertTrue(source_names.isdisjoint(container_names))

    def test_release_workflows_validate_paged_and_latest_history(self):
        for workflow_name in ("release-evidence.yml", "release-container.yml"):
            workflow = (self.ROOT / ".github" / "workflows" / workflow_name).read_text(
                encoding="utf-8"
            )

            self.assertIn("tools/release_evidence.py validate-history", workflow)
            self.assertIn("/releases?per_page=100", workflow)
            self.assertIn("/releases/latest", workflow)
            self.assertIn("GH_TOKEN: ${{ github.token }}", workflow)


if __name__ == "__main__":
    unittest.main()
