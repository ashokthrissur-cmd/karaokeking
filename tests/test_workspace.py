"""Per-job workspace and provenance-manifest tests."""

from __future__ import annotations

import json
import shutil
import time

from abikaraoke.workspace import JobWorkspace, cleanup_old_jobs, sha256_file


def _make_source(tmp_path, name="song.wav"):
    source = tmp_path / name
    shutil.copyfile(__file__, source)  # any non-empty file works for hashing
    return source


def test_workspace_is_isolated_per_job(tmp_path):
    source = _make_source(tmp_path)
    first = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    second = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    assert first.root != second.root
    assert first.source_audio.parent == first.root
    assert second.source_audio.parent == second.root


def test_manifest_records_source_hash(tmp_path):
    source = _make_source(tmp_path)
    workspace = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    manifest = json.loads(workspace.manifest_path.read_text())
    assert manifest["schema"] >= 2
    assert manifest["source"]["sha256"] == sha256_file(source)
    assert manifest["source"]["size"] == source.stat().st_size


def test_is_current_source_detects_changed_input(tmp_path):
    source = _make_source(tmp_path)
    workspace = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    assert workspace.is_current_source()
    source.write_bytes(b"different content")
    assert not workspace.is_current_source()


def test_artifacts_and_stages_are_recorded(tmp_path):
    source = _make_source(tmp_path)
    workspace = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    artifact = workspace.path("instrumental.wav")
    artifact.write_bytes(b"audio")
    workspace.artifact("instrumental", artifact, method="center")
    workspace.stage("separate", "done", method="center")
    workspace.warn("test warning")

    manifest = json.loads(workspace.manifest_path.read_text())
    assert manifest["artifacts"]["instrumental"]["sha256"] == sha256_file(artifact)
    assert manifest["artifacts"]["instrumental"]["method"] == "center"
    assert manifest["stages"]["separate"]["status"] == "done"
    assert manifest["warnings"] == ["test warning"]


def test_cleanup_removes_intermediates_but_keeps_output(tmp_path):
    source = _make_source(tmp_path)
    workspace = JobWorkspace.create(source, base_dir=tmp_path / "jobs")
    workspace.source_audio.write_bytes(b"wav")
    workspace.vocals.write_bytes(b"wav")
    workspace.output.write_bytes(b"mp4")
    workspace.cleanup(keep_intermediates=False)
    assert not workspace.source_audio.exists()
    assert not workspace.vocals.exists()
    assert workspace.output.exists()


def test_cleanup_old_jobs_keeps_newest(tmp_path):
    source = _make_source(tmp_path)
    jobs = tmp_path / "jobs"
    for index in range(4):
        JobWorkspace.create(source, base_dir=jobs, job_id=f"job-{index}")
        time.sleep(0.01)
    removed = cleanup_old_jobs(jobs, keep=2)
    assert len(removed) == 2
    remaining = {p.name for p in jobs.iterdir() if p.is_dir()}
    assert remaining == {"job-2", "job-3"}
