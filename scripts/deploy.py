"""THE FORGE 배포 스크립트.

uv tool install이 directory source cache hit으로 silent skip되는 함정과,
프로젝트 .venv의 옛 빌드가 새 코드와 어긋나는 함정을 한 번에 막는다.

진단된 silent skip 원인:
- uv는 `the-forge` 같은 file://... directory source 의존성을 version 키로 캐싱.
- pyproject.toml의 version이 그대로면 src/ 코드가 바뀌어도 캐시 hit → 옛 빌드 wheel
  재사용 → site-packages에 옛 코드가 박힌 채 "Installed 1 package" 만 표시.
- `--force`는 site-packages를 비울 뿐 build cache는 무효화하지 않음.

본 스크립트의 책임:
1. `uv tool install --force --refresh-package the-forge .` 로 캐시 강제 무효화.
2. site-packages (uv tool 글로벌 + 프로젝트 .venv 둘 다)에 src/forge 와의 sha256
   일치를 검증. 어긋난 파일은 수동 복사로 폴백 (memory 폴백 절차 자동화).
3. 검증 후 forge --help smoke test로 CLI 동작 확인.

사용:
  python scripts/deploy.py                # 전체 배포 (install + verify + fallback + smoke)
  python scripts/deploy.py --check-only   # 해시 검증만 (install 안 함)
  python scripts/deploy.py --targets tool # uv tool 글로벌만 (venv 건너뜀)
  python scripts/deploy.py --targets venv # 프로젝트 .venv 만
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 기본 cp949에서 유니코드 체크마크 인코딩 실패 방지.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_FORGE = PROJECT_ROOT / "src" / "forge"
TOOL_NAME = "the-forge"
PACKAGE_NAME = "forge"

# uv tool 글로벌 설치 경로 (Windows + POSIX 자동 탐색)
UV_TOOL_PATHS = [
    Path.home() / "AppData" / "Roaming" / "uv" / "tools" / TOOL_NAME / "Lib" / "site-packages" / PACKAGE_NAME,
    Path.home() / ".local" / "share" / "uv" / "tools" / TOOL_NAME / "lib" / "site-packages" / PACKAGE_NAME,
]


def find_uv_tool_target() -> Path | None:
    """uv tool 글로벌 설치된 forge 패키지 디렉토리. 없으면 None.

    Windows/POSIX 둘 다 시도하고, glob으로 Python 버전 폴더(lib/python3.x)도 탐색.
    """
    for p in UV_TOOL_PATHS:
        if p.exists():
            return p
    # POSIX는 python 버전 폴더가 중간에 끼는 경우가 있음
    posix_root = Path.home() / ".local" / "share" / "uv" / "tools" / TOOL_NAME
    if posix_root.exists():
        matches = list(posix_root.glob("lib/python*/site-packages/" + PACKAGE_NAME))
        if matches:
            return matches[0]
    return None


def find_venv_target() -> Path | None:
    """프로젝트 .venv의 forge 패키지 디렉토리. 없으면 None."""
    candidates = [
        PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / PACKAGE_NAME,
    ]
    posix_root = PROJECT_ROOT / ".venv" / "lib"
    if posix_root.exists():
        candidates.extend(posix_root.glob("python*/site-packages/" + PACKAGE_NAME))
    for p in candidates:
        if p.exists():
            return p
    return None


def collect_src_files() -> list[Path]:
    """src/forge 안의 모든 .py + 비-python 데이터 파일 (scaffold 제외)."""
    files: list[Path] = []
    for p in SRC_FORGE.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.is_file():
            files.append(p)
    return files


def diff_against(target: Path) -> tuple[list[Path], list[Path]]:
    """src/forge ↔ target 간 mismatch 목록.

    반환: (mismatched_rel_paths, missing_rel_paths)
    """
    mismatched: list[Path] = []
    missing: list[Path] = []
    for src_path in collect_src_files():
        rel = src_path.relative_to(SRC_FORGE)
        dst = target / rel
        if not dst.exists():
            missing.append(rel)
            continue
        s = hashlib.sha256(src_path.read_bytes()).hexdigest()
        i = hashlib.sha256(dst.read_bytes()).hexdigest()
        if s != i:
            mismatched.append(rel)
    return mismatched, missing


def sync_target(target: Path, *, dry_run: bool = False) -> int:
    """src/forge → target 수동 복사 (memory 폴백 절차 자동화).

    반환: 복사된 파일 개수. dry_run=True면 복사 안 하고 카운트만.
    """
    copied = 0
    for src_path in collect_src_files():
        rel = src_path.relative_to(SRC_FORGE)
        dst = target / rel
        # 이미 동일하면 skip
        if dst.exists():
            s = hashlib.sha256(src_path.read_bytes()).hexdigest()
            i = hashlib.sha256(dst.read_bytes()).hexdigest()
            if s == i:
                continue
        if dry_run:
            copied += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)
        copied += 1
    return copied


def run_uv_install() -> bool:
    """uv tool install + 캐시 무효화. 성공 True.

    --refresh-package the-forge 가 핵심 — 이게 없으면 directory source cache hit으로
    옛 빌드 wheel이 재설치돼서 src 변경분이 안 반영됨.
    """
    cmd = [
        "uv", "tool", "install",
        "--force",
        "--refresh-package", TOOL_NAME,
        str(PROJECT_ROOT),
    ]
    print(f"[deploy] $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True)
    return proc.returncode == 0


def run_pip_install_editable_venv() -> bool:
    """프로젝트 .venv에 editable install. .venv가 없으면 skip(False)."""
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        # POSIX
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print("[deploy] .venv 없음 — pip install -e 건너뜀")
        return False
    # pip 가용성 사전 확인 (uv venv는 기본적으로 pip를 안 깔아둠).
    probe = subprocess.run(
        [str(venv_python), "-c", "import pip"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print("[deploy] .venv에 pip 없음 — 수동 복사 폴백으로 처리됩니다")
        return False
    cmd = [str(venv_python), "-m", "pip", "install", "-e", ".", "--quiet"]
    print(f"[deploy] $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True)
    return proc.returncode == 0


def smoke_forge_cli() -> bool:
    """forge --help 한 줄 호출로 CLI 동작 확인."""
    # uv tool이 깐 forge.exe (Windows) 또는 forge (POSIX)
    candidates = [
        Path.home() / ".local" / "bin" / "forge.exe",
        Path.home() / ".local" / "bin" / "forge",
    ]
    forge = next((c for c in candidates if c.exists()), None)
    if forge is None:
        print("[deploy] forge 실행 파일을 찾지 못함 (uv tool install 직후라야 정상 노출)")
        return False
    proc = subprocess.run(
        [str(forge), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "FORGE" in out.upper()
    print(f"[deploy] smoke '{forge.name} --help' → {'OK' if ok else 'FAIL'}")
    if not ok:
        print(out[:500])
    return ok


def verify_target(label: str, target: Path | None) -> bool:
    """타겟 한 곳 검증 + 자동 폴백 + 재검증.

    반환: 최종 검증 성공 True. target이 None이면 (해당 환경 없음) True 반환(skip).
    """
    if target is None:
        print(f"[deploy] {label}: 환경 없음 → skip")
        return True

    mismatched, missing = diff_against(target)
    total = len(mismatched) + len(missing)
    if total == 0:
        print(f"[deploy] {label}: ✓ 일치 ({len(collect_src_files())} 파일)")
        return True

    print(f"[deploy] {label}: ✗ mismatched={len(mismatched)} missing={len(missing)}")
    for rel in mismatched[:5]:
        print(f"  - MISMATCH {rel}")
    for rel in missing[:5]:
        print(f"  - MISSING  {rel}")
    if total > 10:
        print(f"  ... 외 {total - 10} 건")

    print(f"[deploy] {label}: 수동 복사 폴백 실행")
    copied = sync_target(target)
    print(f"[deploy] {label}: {copied} 파일 복사 완료, 재검증")

    mismatched2, missing2 = diff_against(target)
    if mismatched2 or missing2:
        print(f"[deploy] {label}: ✗ 폴백 후에도 mismatched={len(mismatched2)} missing={len(missing2)}")
        return False
    print(f"[deploy] {label}: ✓ 폴백 후 일치")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="install/복사 안 하고 sha256 검증만 (CI/사전 점검용)",
    )
    parser.add_argument(
        "--targets",
        default="tool,venv",
        help="배포 대상 (쉼표 구분): tool=uv tool 글로벌, venv=프로젝트 .venv. 기본 둘 다",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="uv tool install 실행 건너뛰고 sha256 검증 + 수동 복사 폴백만",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="forge --help smoke test 건너뜀",
    )
    args = parser.parse_args(argv)

    targets = {t.strip() for t in args.targets.split(",") if t.strip()}
    invalid = targets - {"tool", "venv"}
    if invalid:
        print(f"[deploy] 알 수 없는 target: {invalid}", file=sys.stderr)
        return 2

    print(f"[deploy] PROJECT_ROOT = {PROJECT_ROOT}")
    print(f"[deploy] targets = {sorted(targets)}")

    if args.check_only:
        print("[deploy] --check-only 모드 (install 건너뜀, 폴백 안 함)")
        all_ok = True
        if "tool" in targets:
            t = find_uv_tool_target()
            print(f"[deploy] uv tool target: {t}")
            if t is None:
                print("[deploy] (uv tool 설치 안 됨)")
            else:
                m, n = diff_against(t)
                if m or n:
                    print(f"[deploy] uv tool: ✗ mismatched={len(m)} missing={len(n)}")
                    all_ok = False
                else:
                    print("[deploy] uv tool: ✓ 일치")
        if "venv" in targets:
            v = find_venv_target()
            print(f"[deploy] .venv target: {v}")
            if v is None:
                print("[deploy] (.venv 설치 안 됨)")
            else:
                m, n = diff_against(v)
                if m or n:
                    print(f"[deploy] .venv: ✗ mismatched={len(m)} missing={len(n)}")
                    all_ok = False
                else:
                    print("[deploy] .venv: ✓ 일치")
        return 0 if all_ok else 1

    # 1. install 단계
    if not args.skip_install:
        if "tool" in targets:
            print("[deploy] === uv tool install 단계 ===")
            if not run_uv_install():
                print("[deploy] uv tool install 실패 — 폴백으로 진행")
        if "venv" in targets:
            print("[deploy] === venv pip install -e 단계 ===")
            run_pip_install_editable_venv()  # 실패해도 폴백으로 계속
    else:
        print("[deploy] --skip-install (install 건너뜀)")

    # 2. 검증 + 폴백 단계
    all_ok = True
    if "tool" in targets:
        ok = verify_target("uv tool", find_uv_tool_target())
        all_ok = all_ok and ok
    if "venv" in targets:
        ok = verify_target(".venv", find_venv_target())
        all_ok = all_ok and ok

    if not all_ok:
        print("[deploy] ✗ 일부 타겟이 폴백 후에도 불일치 — 수동 점검 필요")
        return 1

    # 3. smoke test
    if not args.skip_smoke and "tool" in targets:
        print("[deploy] === smoke test ===")
        if not smoke_forge_cli():
            print("[deploy] ✗ smoke test 실패")
            return 1

    print("[deploy] ✓ 배포 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
