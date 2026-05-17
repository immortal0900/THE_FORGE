"""scripts/deploy.py 단위 테스트.

대상:
- diff_against (sha256 비교 + missing 분리)
- sync_target (수동 복사 폴백)
- collect_src_files (__pycache__ 제외)
- find_uv_tool_target / find_venv_target (자동 탐색 — 환경 비의존)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# scripts/deploy.py 는 패키지가 아니라 단독 스크립트이므로 spec_from_file_location 로 로드.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY_PATH = _REPO_ROOT / "scripts" / "deploy.py"


@pytest.fixture(scope="module")
def deploy():
    spec = importlib.util.spec_from_file_location("forge_deploy", _DEPLOY_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_deploy"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── collect_src_files ─────────────────────────────────────────────────────


def test_collect_src_files_excludes_pycache(deploy, tmp_path, monkeypatch):
    fake_src = tmp_path / "forge"
    fake_src.mkdir()
    (fake_src / "a.py").write_text("x", encoding="utf-8")
    pycache = fake_src / "__pycache__"
    pycache.mkdir()
    (pycache / "a.cpython-313.pyc").write_text("compiled", encoding="utf-8")
    sub = fake_src / "agents"
    sub.mkdir()
    (sub / "b.py").write_text("y", encoding="utf-8")

    monkeypatch.setattr(deploy, "SRC_FORGE", fake_src)
    files = deploy.collect_src_files()
    names = sorted(f.name for f in files)
    assert "a.py" in names
    assert "b.py" in names
    assert all(".pyc" not in f.name for f in files)
    assert all("__pycache__" not in f.parts for f in files)


# ── diff_against ──────────────────────────────────────────────────────────


def _make_pkg(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_diff_against_detects_mismatch_and_missing(deploy, tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(
        src,
        {
            "same.py": "identical",
            "changed.py": "new",
            "agents/added.py": "brand new",
        },
    )
    _make_pkg(
        dst,
        {
            "same.py": "identical",
            "changed.py": "old",
            # agents/added.py 누락
        },
    )
    monkeypatch.setattr(deploy, "SRC_FORGE", src)

    mismatched, missing = deploy.diff_against(dst)
    assert {p.as_posix() for p in mismatched} == {"changed.py"}
    assert {p.as_posix() for p in missing} == {"agents/added.py"}


def test_diff_against_clean_when_identical(deploy, tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    files = {"a.py": "1", "b.py": "2", "sub/c.py": "3"}
    _make_pkg(src, files)
    _make_pkg(dst, files)
    monkeypatch.setattr(deploy, "SRC_FORGE", src)
    m, n = deploy.diff_against(dst)
    assert m == []
    assert n == []


# ── sync_target ───────────────────────────────────────────────────────────


def test_sync_target_copies_mismatched_and_missing(deploy, tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(
        src,
        {"a.py": "new-a", "agents/b.py": "new-b", "agents/c.py": "new-c"},
    )
    _make_pkg(
        dst,
        {"a.py": "new-a", "agents/b.py": "old-b"},  # c.py 누락
    )
    monkeypatch.setattr(deploy, "SRC_FORGE", src)

    copied = deploy.sync_target(dst)
    assert copied == 2  # b.py mismatch + c.py missing

    # 사후 검증: 완전 동일해야 함
    m, n = deploy.diff_against(dst)
    assert m == [] and n == []
    assert (dst / "agents" / "c.py").read_text(encoding="utf-8") == "new-c"
    assert (dst / "agents" / "b.py").read_text(encoding="utf-8") == "new-b"


def test_sync_target_dry_run_does_not_write(deploy, tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(src, {"a.py": "new"})
    _make_pkg(dst, {"a.py": "old"})
    monkeypatch.setattr(deploy, "SRC_FORGE", src)

    copied = deploy.sync_target(dst, dry_run=True)
    assert copied == 1
    # 실제 파일은 그대로
    assert (dst / "a.py").read_text(encoding="utf-8") == "old"


def test_sync_target_skips_already_identical(deploy, tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(src, {"a.py": "same", "b.py": "same"})
    _make_pkg(dst, {"a.py": "same", "b.py": "same"})
    monkeypatch.setattr(deploy, "SRC_FORGE", src)
    copied = deploy.sync_target(dst)
    assert copied == 0


# ── find_*_target (환경 비의존 smoke) ──────────────────────────────────────


def test_find_uv_tool_target_returns_path_or_none(deploy):
    # 실제 환경에 uv tool이 깔려 있을 수도 없을 수도. 둘 다 정상.
    result = deploy.find_uv_tool_target()
    assert result is None or isinstance(result, Path)


def test_find_venv_target_returns_path_or_none(deploy):
    result = deploy.find_venv_target()
    assert result is None or isinstance(result, Path)


# ── main(--check-only) 모드 회귀 ───────────────────────────────────────────


def test_main_check_only_with_clean_target(deploy, tmp_path, monkeypatch, capsys):
    """check-only는 install/복사 안 함 + 일치 시 exit 0."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    files = {"a.py": "ok"}
    _make_pkg(src, files)
    _make_pkg(dst, files)
    monkeypatch.setattr(deploy, "SRC_FORGE", src)
    monkeypatch.setattr(deploy, "find_uv_tool_target", lambda: dst)
    monkeypatch.setattr(deploy, "find_venv_target", lambda: None)

    rc = deploy.main(["--check-only", "--targets", "tool"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "일치" in out


def test_main_check_only_with_mismatch_returns_1(deploy, tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(src, {"a.py": "new"})
    _make_pkg(dst, {"a.py": "old"})
    monkeypatch.setattr(deploy, "SRC_FORGE", src)
    monkeypatch.setattr(deploy, "find_uv_tool_target", lambda: dst)
    monkeypatch.setattr(deploy, "find_venv_target", lambda: None)

    rc = deploy.main(["--check-only", "--targets", "tool"])
    assert rc == 1
    # check-only는 폴백 안 함 — 실제 파일은 변경 X
    assert (dst / "a.py").read_text(encoding="utf-8") == "old"


def test_main_skip_install_runs_fallback(deploy, tmp_path, monkeypatch, capsys):
    """--skip-install + 불일치 → 폴백 자동 실행 → 일치 회복 → exit 0."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_pkg(src, {"a.py": "new", "sub/b.py": "added"})
    _make_pkg(dst, {"a.py": "old"})
    monkeypatch.setattr(deploy, "SRC_FORGE", src)
    monkeypatch.setattr(deploy, "find_uv_tool_target", lambda: dst)
    monkeypatch.setattr(deploy, "find_venv_target", lambda: None)

    rc = deploy.main(["--skip-install", "--skip-smoke", "--targets", "tool"])
    assert rc == 0
    assert (dst / "a.py").read_text(encoding="utf-8") == "new"
    assert (dst / "sub" / "b.py").read_text(encoding="utf-8") == "added"


def test_main_invalid_target_exits_2(deploy):
    rc = deploy.main(["--check-only", "--targets", "unknown"])
    assert rc == 2
