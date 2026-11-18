from __future__ import annotations

import yaml

from scripts.tests.m1_helpers import REPO_ROOT


def test_build_iso_workflow_yaml_and_structure() -> None:
    wf_path = REPO_ROOT / ".github" / "workflows" / "build-iso.yml"
    assert wf_path.is_file()
    raw = wf_path.read_bytes()
    assert b"\r\n" not in raw, "Workflow YAML must use LF line endings"

    data = yaml.safe_load(raw.decode("utf-8"))
    assert isinstance(data, dict)
    assert "on" in data, "Trigger key must be quoted 'on' so PyYAML parses string 'on', not boolean True"
    triggers = data["on"]
    for trig in ("push", "pull_request", "workflow_dispatch"):
        assert trig in triggers

    jobs = data["jobs"]
    assert "validate" in jobs
    assert "build-iso" in jobs

    validate_steps = jobs["validate"]["steps"]
    setup_py = [s for s in validate_steps if s.get("uses", "").startswith("actions/setup-python@")]
    assert setup_py and setup_py[0]["with"]["python-version"] == "3.12"
    validate_runs = "\n".join(s.get("run", "") for s in validate_steps)
    assert "scripts/check_invariants.py" in validate_runs
    assert "pytest" in validate_runs

    build_job = jobs["build-iso"]
    assert build_job["needs"] == "validate"
    assert build_job["container"]["image"] == "archlinux:latest"
    assert "--privileged" in build_job["container"]["options"]

    build_steps = build_job["steps"]
    build_runs = "\n".join(s.get("run", "") for s in build_steps)
    assert "archiso" in build_runs
    assert "scripts/build-iso.sh" in build_runs
    assert "sha256sum" in build_runs

    upload_steps = [s for s in build_steps if s.get("uses", "").startswith("actions/upload-artifact@v4")]
    assert len(upload_steps) == 1
    upload_path = upload_steps[0]["with"]["path"]
    assert "out/kite-os-folio9480-x86_64_v3.iso" in upload_path
    assert "out/kite-os-folio9480-x86_64_v3.iso.sha256" in upload_path
