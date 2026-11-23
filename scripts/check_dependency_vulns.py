"""Release-blocking dependency vulnerability gate (Issue #19).

Runs `pip-audit --format=json` (or evaluates a provided JSON fixture via --input-json),
applies strictly scoped, time-bounded waivers from `docs/SECURITY_WAIVERS.json`,
fails on any expired waiver or unwaived vulnerability, and writes an auditable report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any


def load_waivers(waiver_path: Path, today: date | None = None) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Load waivers and return (active_waivers_by_(pkg, vuln_id), expired_errors)."""
    ref_date = today or date.today()
    data = json.loads(waiver_path.read_text(encoding="utf-8"))
    active: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []

    for item in data.get("waivers", []):
        pkg = str(item.get("package") or "").strip().lower()
        expires_raw = str(item.get("expires_on") or "").strip()
        owner = str(item.get("owner") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        control = str(item.get("compensating_control") or "").strip()
        vuln_ids = [str(v).strip().upper() for v in (item.get("vuln_ids") or []) if str(v).strip()]

        if not pkg or not vuln_ids or not expires_raw or not owner or not rationale or not control:
            errors.append(f"Malformed waiver entry for package='{pkg}': missing required metadata fields.")
            continue
        try:
            exp_date = date.fromisoformat(expires_raw)
        except ValueError:
            errors.append(f"Invalid expires_on date '{expires_raw}' in waiver for package='{pkg}'.")
            continue
        if exp_date < ref_date:
            errors.append(f"Expired waiver for package='{pkg}' vulns={vuln_ids} (expired {expires_raw} < {ref_date.isoformat()}).")
            continue
        for vid in vuln_ids:
            active[(pkg, vid)] = item

    return active, errors


def evaluate_audit_payload(
    audit_payload: dict[str, Any],
    waiver_path: Path,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Evaluate a pip-audit JSON payload against active time-bounded waivers."""
    active_waivers, waiver_errors = load_waivers(waiver_path, today=today)
    unwaived: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for dep in audit_payload.get("dependencies", []):
        pkg_name = str(dep.get("name") or "").strip().lower()
        pkg_ver = str(dep.get("version") or "")
        for vuln in dep.get("vulns") or []:
            vid = str(vuln.get("id") or "").strip().upper()
            aliases = [str(a).strip().upper() for a in (vuln.get("aliases") or [])]
            pair = (pkg_name, vid)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            matched_waiver = active_waivers.get((pkg_name, vid))
            if matched_waiver is None:
                for alias in aliases:
                    if (pkg_name, alias) in active_waivers:
                        matched_waiver = active_waivers[(pkg_name, alias)]
                        break

            entry = {
                "package": pkg_name,
                "version": pkg_ver,
                "id": vid,
                "aliases": aliases,
                "fix_versions": vuln.get("fix_versions") or [],
            }
            if matched_waiver is not None:
                entry["waived_until"] = matched_waiver["expires_on"]
                entry["waiver_owner"] = matched_waiver["owner"]
                waived.append(entry)
            else:
                unwaived.append(entry)

    passed = (len(waiver_errors) == 0) and (len(unwaived) == 0)
    return {
        "passed": passed,
        "waiver_errors": waiver_errors,
        "unwaived_count": len(unwaived),
        "waived_count": len(waived),
        "unwaived": unwaived,
        "waived": waived,
    }


def _run_pip_audit_json() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (proc.stdout or "").strip()
    if not stdout.startswith("{"):
        raise RuntimeError(f"pip-audit did not return valid JSON (exit={proc.returncode}): {proc.stderr[:400]}")
    return json.loads(stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce dependency vulnerability release gate.")
    parser.add_argument(
        "--waivers",
        default=str(Path(__file__).resolve().parents[1] / "docs" / "SECURITY_WAIVERS.json"),
        help="Path to structured JSON waiver policy.",
    )
    parser.add_argument("--input-json", default=None, help="Optional pre-generated pip-audit JSON file.")
    parser.add_argument("--report-path", default=None, help="Optional output path for JSON gate report.")
    args = parser.parse_args(argv)

    if args.input_json:
        audit_payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    else:
        audit_payload = _run_pip_audit_json()

    result = evaluate_audit_payload(audit_payload, Path(args.waivers))
    if args.report_path:
        Path(args.report_path).write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(
        f"Dependency Security Gate: passed={result['passed']} "
        f"unwaived={result['unwaived_count']} waived={result['waived_count']} "
        f"waiver_errors={len(result['waiver_errors'])}"
    )
    for err in result["waiver_errors"]:
        print(f"  [WAIVER ERROR] {err}")
    for item in result["unwaived"]:
        print(
            f"  [UNWAIVED] {item['package']}=={item['version']} {item['id']} "
            f"(aliases={item['aliases']}, fix_versions={item['fix_versions']})"
        )
    for item in result["waived"]:
        print(
            f"  [WAIVED until {item['waived_until']}] {item['package']}=={item['version']} {item['id']}"
        )

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
