"""
테스트 실행 스크립트

사용법:
    python test/run_tests.py              # 모든 테스트 실행
    python test/run_tests.py --fast       # 빠른 테스트만 (단위 테스트)
    python test/run_tests.py --cov        # 커버리지 포함
    python test/run_tests.py --file test_pathfinding_service.py  # 특정 파일만
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_tests(args):
    """테스트 실행"""
    # 프로젝트 루트 디렉토리
    project_root = Path(__file__).parent.parent

    # pytest 명령어 구성
    cmd = ["pytest", "test/"]

    if args.verbose:
        cmd.append("-v")

    if args.fast:
        # 빠른 테스트만 (integration, slow 제외)
        cmd.extend(["-m", "not slow and not integration"])
        print("🏃 빠른 테스트만 실행합니다...")

    if args.cov:
        # 커버리지 측정
        cmd.extend(["--cov=app", "--cov-report=html", "--cov-report=term-missing"])
        print("📊 커버리지를 측정합니다...")

    if args.file:
        # 특정 파일만
        cmd[-1] = f"test/{args.file}"
        print(f"📁 {args.file} 파일만 테스트합니다...")

    if args.parallel:
        # 병렬 실행
        cmd.extend(["-n", str(args.parallel)])
        print(f"⚡ {args.parallel}개 프로세스로 병렬 실행합니다...")

    if args.keyword:
        # 키워드 필터링
        cmd.extend(["-k", args.keyword])
        print(f"🔍 '{args.keyword}' 키워드로 필터링합니다...")

    # 테스트 실행
    print(f"\n실행 명령어: {' '.join(cmd)}\n")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=project_root)

    # 결과 출력
    print("=" * 70)
    if result.returncode == 0:
        print("\n✅ 모든 테스트를 통과했습니다!")
        if args.cov:
            print("\n📊 커버리지 리포트: htmlcov/index.html")
    else:
        print("\n❌ 일부 테스트가 실패했습니다.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Transit-Routing 테스트 실행")

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="상세한 출력"
    )

    parser.add_argument(
        "--fast",
        action="store_true",
        help="빠른 테스트만 실행 (단위 테스트)"
    )

    parser.add_argument(
        "--cov",
        action="store_true",
        help="코드 커버리지 측정"
    )

    parser.add_argument(
        "--file",
        type=str,
        help="특정 테스트 파일만 실행 (예: test_pathfinding_service.py)"
    )

    parser.add_argument(
        "-n", "--parallel",
        type=int,
        help="병렬 실행 프로세스 수 (pytest-xdist 필요)"
    )

    parser.add_argument(
        "-k", "--keyword",
        type=str,
        help="키워드로 테스트 필터링"
    )

    args = parser.parse_args()

    print("🧪 Transit-Routing 테스트 실행")
    print("=" * 70)

    run_tests(args)


if __name__ == "__main__":
    main()
