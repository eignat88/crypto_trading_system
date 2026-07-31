"""Create an evidence-backed CSV readiness report without starting history load."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import settings  # noqa: E402


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    status: str
    actual: str
    expected: str
    evidence: str
    details: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose whether a full historical load may be started"
    )
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--symbol", default="BTCUSDT", choices=("BTCUSDT", "ETHUSDT"))
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs")
    parser.add_argument("--run-active-checks", action="store_true")
    parser.add_argument("--skip-ci", action="store_true")
    parser.add_argument("--repo", default="eignat88/crypto_trading_system")
    parser.add_argument("--command-timeout-seconds", type=int, default=900)
    return parser.parse_args()


def now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def run_command(
    name: str,
    command: list[str],
    run_dir: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 900,
) -> tuple[int, str, Path]:
    log_path = run_dir / f"{name}.log"
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_seconds,
        )
        exit_code = completed.returncode
        output = completed.stdout or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        partial = exc.stdout or ""
        output = (
            partial if isinstance(partial, str) else partial.decode("utf-8", errors="replace")
        )
        output += f"\nTIMEOUT after {timeout_seconds} seconds. Check PostgreSQL locks.\n"
    log_path.write_text(
        f"COMMAND: {subprocess.list2cmdline(command)}\n"
        f"EXIT_CODE: {exit_code}\n\n{output}",
        encoding="utf-8-sig",
    )
    return exit_code, output, log_path


def command_check(
    category: str,
    name: str,
    expected_marker: str,
    result: tuple[int, str, Path],
) -> Check:
    code, output, path = result
    passed = code == 0 and expected_marker in output
    return Check(
        category,
        name,
        "success" if passed else "failed",
        f"exit_code={code}; marker_found={expected_marker in output}",
        f"exit_code=0; output contains {expected_marker!r}",
        str(path),
    )


def integration_database_is_safe() -> tuple[bool, str]:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        return False, "TEST_DATABASE_URL is not set"
    database_part = url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    return ("test" in database_part), f"database={database_part}"


def run_active_checks(args: argparse.Namespace, run_dir: Path) -> list[Check]:
    checks: list[Check] = []
    migration_command = [sys.executable, "scripts/apply_migrations.py"]

    first = run_command(
        "migration_first",
        migration_command,
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    first_check = command_check(
        "migrations", "migration_first", "migration_status=success", first
    )
    checks.append(first_check)

    if first_check.status == "success":
        second = run_command(
            "migration_second",
            migration_command,
            run_dir,
            timeout_seconds=args.command_timeout_seconds,
        )
        second_check = command_check(
            "migrations", "migration_second", "migration_status=success", second
        )
    else:
        second_check = Check(
            "migrations",
            "migration_second",
            "blocked",
            "not run",
            "first migration run succeeds before the second run",
            str(first[2]),
        )
    checks.append(second_check)

    if first_check.status != "success" or second_check.status != "success":
        checks.append(
            Check(
                "tests",
                "integration_tests",
                "blocked",
                "not run",
                "both migration runs succeed",
                "",
                "Flow stopped after a migration discrepancy.",
            )
        )
        return checks + blocked_raw_to_dds_checks("migration discrepancy")

    safe_test_db, test_db_detail = integration_database_is_safe()
    if not safe_test_db:
        checks.append(
            Check(
                "tests",
                "integration_tests",
                "blocked",
                test_db_detail,
                "TEST_DATABASE_URL must point to an isolated database containing 'test'",
                "",
                "Integration tests were not started to protect the project database.",
            )
        )
        return checks + blocked_raw_to_dds_checks("integration-test safety gate")

    integration = run_command(
        "integration_tests",
        [sys.executable, "-m", "pytest", "-m", "integration", "-q"],
        run_dir,
        os.environ.copy(),
        timeout_seconds=args.command_timeout_seconds,
    )
    code, _, path = integration
    passed = code == 0
    integration_check = Check(
        "tests",
        "integration_tests",
        "success" if passed else "failed",
        f"exit_code={code}; {test_db_detail}",
        "exit_code=0 against an isolated TEST_DATABASE_URL",
        str(path),
    )
    checks.append(integration_check)
    if integration_check.status != "success":
        return checks + blocked_raw_to_dds_checks("integration-test discrepancy")

    load_command = [
        sys.executable,
        "scripts/load_dds.py",
        "--exchange",
        args.exchange,
        "--symbol",
        args.symbol,
        "--interval",
        args.interval,
    ]
    load_first = run_command(
        "raw_to_dds_first",
        load_command,
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    first_load_check = command_check(
        "raw_to_dds", "raw_to_dds_first", "run=", load_first
    )
    checks.append(first_load_check)
    if first_load_check.status != "success":
        checks.append(
            Check(
                "raw_to_dds",
                "raw_to_dds_repeat",
                "blocked",
                "not run",
                "first RAW -> DDS run succeeds before repeat",
                str(load_first[2]),
            )
        )
        return checks

    load_second = run_command(
        "raw_to_dds_repeat",
        load_command,
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    code, output, path = load_second
    match = re.search(
        r"source=(\d+)\s+inserted=(\d+)\s+rejected=(\d+)\s+deferred=(\d+)",
        output,
    )
    explainable = bool(
        code == 0
        and match
        and int(match.group(2)) == 0
        and int(match.group(3)) == 0
        and int(match.group(4)) == 0
    )
    checks.append(
        Check(
            "raw_to_dds",
            "raw_to_dds_repeat",
            "success" if explainable else "failed",
            match.group(0) if match else f"exit_code={code}; counters not found",
            "exit_code=0; inserted=0; rejected=0; deferred=0",
            str(path),
        )
    )
    return checks


def blocked_raw_to_dds_checks(reason: str) -> list[Check]:
    return [
        Check(
            "raw_to_dds",
            name,
            "blocked",
            "not run",
            "migrations and integration tests succeed",
            "",
            f"Flow stopped after: {reason}.",
        )
        for name in ("raw_to_dds_first", "raw_to_dds_repeat")
    ]


def inactive_checks() -> list[Check]:
    checks = [
        Check(
            "migrations",
            name,
            "not_run",
            "active checks disabled",
            "migration_status=success",
            "",
            "Run again with --run-active-checks.",
        )
        for name in ("migration_first", "migration_second")
    ]
    checks.append(
        Check(
            "tests",
            "integration_tests",
            "not_run",
            "active checks disabled",
            "exit_code=0 against isolated TEST_DATABASE_URL",
            "",
            "Run again with --run-active-checks.",
        )
    )
    for name in ("raw_to_dds_first", "raw_to_dds_repeat"):
        checks.append(
            Check(
                "raw_to_dds",
                name,
                "not_run",
                "active checks disabled",
                "successful, explainable run",
                "",
                "Run again with --run-active-checks.",
            )
        )
    return checks


def collect_database_checks(
    args: argparse.Namespace, run_dir: Path
) -> tuple[list[Check], dict[str, Any]]:
    sql_path = PROJECT_ROOT / "sql" / "diagnostic_readiness.sql"
    query = sql_path.read_text(encoding="utf-8-sig")
    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET statement_timeout = '5min'"))
            row = connection.execute(
                text(query),
                {
                    "exchange_name": args.exchange,
                    "symbol": args.symbol,
                    "interval_code": args.interval,
                },
            ).mappings().one()
            data = dict(row)
    finally:
        engine.dispose()

    evidence_path = run_dir / "database_diagnostics.json"
    evidence_path.write_text(
        json.dumps(
            {key: stringify(value) for key, value in data.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8-sig",
    )

    checks = [
        Check(
            "database",
            "raw_check",
            "success" if data["raw_check_success"] else "failed",
            (
                f"raw={data['raw_count']}; duplicates={data['duplicate_key_groups']}; "
                f"gaps={data['gap_count']}; invalid_time={data['invalid_time_count']}; "
                f"invalid_ohlc={data['invalid_ohlc_count']}; "
                f"loading_journal={data['loading_journal_status']}"
            ),
            "RAW rows > 0; no duplicates/gaps/invalid rows; latest journal status=success",
            str(evidence_path),
        ),
        Check(
            "database",
            "raw_to_dds_journals",
            "success" if data["raw_to_dds_repeat_explainable"] else "failed",
            (
                f"previous_run={data['previous_etl_run_id']}:{data['previous_etl_status']}; "
                f"latest_run={data['latest_etl_run_id']}:{data['latest_etl_status']}; "
                f"latest source={data['latest_source_count']} "
                f"inserted={data['latest_inserted_count']} "
                f"rejected={data['latest_rejected_count']} deferred={data['latest_deferred_count']}"
            ),
            "two successful runs; repeat inserted=0, rejected=0, deferred=0",
            str(evidence_path),
        ),
        Check(
            "database",
            "checkpoint",
            "success" if data["checkpoint_last_loaded_at"] else "failed",
            (
                f"last_loaded_at={stringify(data['checkpoint_last_loaded_at'])}; "
                f"last_run_at={stringify(data['checkpoint_last_run_at'])}"
            ),
            "checkpoint exists and has timestamps",
            str(evidence_path),
        ),
        Check(
            "database",
            "data_quality_events",
            "success" if data["data_quality_event_count"] == 0 else "failed",
            (
                f"count={data['data_quality_event_count']}; "
                f"latest={stringify(data['latest_data_quality_event_at'])}"
            ),
            "count=0",
            str(evidence_path),
        ),
        Check(
            "database",
            "final_database_check",
            "success" if data["database_final_check_success"] else "failed",
            (
                f"dds_count={data['dds_count']}; running_etl={data['running_etl_count']}; "
                f"status={stringify(data['database_final_check_success'])}"
            ),
            "status=success",
            str(evidence_path),
        ),
    ]
    return checks, data


def collect_ci_checks(args: argparse.Namespace, run_dir: Path) -> list[Check]:
    names = ("Ruff", "Unit tests", "PostgreSQL 17 integration")
    if args.skip_ci:
        checks = [
            Check("ci", name, "not_run", "CI check skipped", "conclusion=success", "")
            for name in names
        ]
        return checks + blocked_ci_context_checks("CI check skipped")
    if shutil.which("gh") is None:
        checks = [
            Check("ci", name, "blocked", "gh CLI not found", "conclusion=success", "")
            for name in names
        ]
        return checks + blocked_ci_context_checks("gh CLI not found")

    list_result = run_command(
        "ci_run_list",
        [
            "gh", "run", "list", "--repo", args.repo, "--workflow", "ci.yml",
            "--branch", "main", "--limit", "20",
            "--json", "databaseId,status,conclusion,headSha,createdAt",
        ],
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    if list_result[0] != 0:
        checks = [
            Check(
                "ci", name, "blocked", "cannot read GitHub Actions",
                "conclusion=success", str(list_result[2]),
            )
            for name in names
        ]
        return checks + blocked_ci_context_checks("cannot read GitHub Actions")
    try:
        runs = json.loads(list_result[1])
        latest = next(run for run in runs if run.get("status") == "completed")
    except (json.JSONDecodeError, StopIteration, TypeError):
        checks = [
            Check(
                "ci", name, "blocked", "no completed CI run found",
                "conclusion=success", str(list_result[2]),
            )
            for name in names
        ]
        return checks + blocked_ci_context_checks("no completed CI run found")

    view_result = run_command(
        "ci_run_view",
        [
            "gh", "run", "view", str(latest["databaseId"]),
            "--repo", args.repo, "--json", "jobs,url,conclusion,status,headSha",
        ],
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    if view_result[0] != 0:
        checks = [
            Check(
                "ci", name, "blocked", "cannot read CI jobs",
                "conclusion=success", str(view_result[2]),
            )
            for name in names
        ]
        return checks + blocked_ci_context_checks("cannot read CI jobs")
    payload = json.loads(view_result[1])
    jobs = {job.get("name"): job for job in payload.get("jobs", [])}
    checks = []
    local_sha_result = run_command(
        "git_head",
        ["git", "rev-parse", "HEAD"],
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    local_sha = local_sha_result[1].strip() if local_sha_result[0] == 0 else ""
    ci_sha = payload.get("headSha", "")
    checks.append(
        Check(
            "ci",
            "ci_commit_matches_local",
            "success" if local_sha and local_sha == ci_sha else "failed",
            f"local_sha={local_sha}; ci_sha={ci_sha}",
            "latest completed CI belongs to the current local commit",
            str(local_sha_result[2]),
        )
    )
    worktree_result = run_command(
        "git_tracked_status",
        ["git", "status", "--porcelain", "--untracked-files=no"],
        run_dir,
        timeout_seconds=args.command_timeout_seconds,
    )
    tracked_changes = worktree_result[1].strip()
    worktree_clean = worktree_result[0] == 0 and not tracked_changes
    checks.append(
        Check(
            "ci",
            "tracked_worktree_clean",
            "success" if worktree_clean else "failed",
            "clean" if worktree_clean else tracked_changes or "git status failed",
            "no uncommitted changes in tracked files",
            str(worktree_result[2]),
            "Untracked diagnostics and logs are intentionally ignored.",
        )
    )
    for name in names:
        job = jobs.get(name, {})
        conclusion = job.get("conclusion", "missing")
        checks.append(
            Check(
                "ci",
                name,
                "success" if conclusion == "success" else "failed",
                f"conclusion={conclusion}; sha={payload.get('headSha', '')}; "
                f"url={payload.get('url', '')}",
                "conclusion=success",
                str(view_result[2]),
            )
        )
    return checks


def blocked_ci_context_checks(reason: str) -> list[Check]:
    return [
        Check(
            "ci",
            name,
            "blocked",
            reason,
            expected,
            "",
        )
        for name, expected in (
            ("ci_commit_matches_local", "latest completed CI belongs to current HEAD"),
            ("tracked_worktree_clean", "no uncommitted changes in tracked files"),
        )
    ]


def write_csv(checks: list[Check], run_dir: Path) -> Path:
    required_names = {
        "migration_first", "migration_second", "integration_tests", "raw_check",
        "raw_to_dds_first", "raw_to_dds_repeat", "raw_to_dds_journals",
        "checkpoint", "data_quality_events", "final_database_check",
        "Ruff", "Unit tests", "PostgreSQL 17 integration",
        "ci_commit_matches_local",
        "tracked_worktree_clean",
    }
    required = [check for check in checks if check.name in required_names]
    overall_success = len(required) == len(required_names) and all(
        check.status == "success" for check in required
    )
    decision = Check(
        "decision",
        "full_history_load",
        "success" if overall_success else "blocked",
        (
            "full historical load is allowed"
            if overall_success
            else "STOP: full historical load is prohibited"
        ),
        "all mandatory checks have status=success",
        str(run_dir),
        "Do not restart the three-year load. Inspect failed checks and database journals.",
    )
    final_checks = checks + [decision]
    output_path = run_dir / "readiness_summary.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            (
                "checked_at_utc", "category", "check_name", "status",
                "actual", "expected", "evidence_file", "details",
            )
        )
        checked_at = datetime.now(UTC).isoformat()
        for check in final_checks:
            writer.writerow(
                (
                    checked_at, check.category, check.name, check.status,
                    check.actual, check.expected, check.evidence, check.details,
                )
            )
    return output_path


def main() -> int:
    args = parse_args()
    run_name = (
        f"readiness_{args.exchange}_{args.symbol}_{args.interval}_{now_stamp()}"
    )
    run_dir = args.log_dir.resolve() / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    checks = run_active_checks(args, run_dir) if args.run_active_checks else inactive_checks()
    try:
        database_checks, _ = collect_database_checks(args, run_dir)
        checks.extend(database_checks)
    except Exception as exc:  # diagnostic must still produce a summary
        error_path = run_dir / "database_diagnostics_error.log"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8-sig")
        checks.append(
            Check(
                "database", "final_database_check", "failed", str(exc),
                "status=success", str(error_path),
            )
        )
    checks.extend(collect_ci_checks(args, run_dir))
    csv_path = write_csv(checks, run_dir)
    with csv_path.open(encoding="utf-8-sig") as handle:
        decision = next(
            row
            for row in csv.DictReader(handle, delimiter=";")
            if row["check_name"] == "full_history_load"
        )
    print(f"summary_csv={csv_path}")
    print(f"logs_dir={run_dir}")
    print(f"status={decision['status']}")
    return 0 if decision["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
