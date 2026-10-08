"""CLI Reporter and formatting tools for execution results."""
from __future__ import annotations
import json
from typing import Dict, Any
from .models import SuiteExecutionSummary, Severity


class Reporter:
    """Formats and prints test results strictly respecting PII privacy (count-only)."""

    @staticmethod
    def format_terminal_report(summary: SuiteExecutionSummary) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append("  DATA QUALITY & MULTI-TENANCY ENGINE - EXECUTION REPORT")
        lines.append("=" * 80)
        lines.append(f"Total Tests Run   : {summary.total_tests}")
        lines.append(f"Passed Tests      : {summary.passed_tests}")
        lines.append(f"Failed Tests      : {summary.failed_tests}")
        lines.append(f"  - ERROR/CRITICAL: {summary.error_tests} (Pipeline Halting)")
        lines.append(f"  - WARNING       : {summary.warning_tests} (Non-blocking Alert)")
        lines.append(f"Total Execution   : {summary.total_duration_ms:.2f} ms")
        lines.append(f"Pipeline Status   : {'[HALTED / BLOCKED]' if summary.pipeline_halted else '[PASSED]'}")
        lines.append("-" * 80)
        lines.append(f"{'STATUS':<8} | {'SEVERITY':<8} | {'TABLE':<16} | {'VIOLATIONS':<10} | {'TIME(ms)':<8} | {'RULE NAME'}")
        lines.append("-" * 80)

        for r in summary.results:
            status_tag = "PASS" if r.passed else "FAIL"
            tbl = r.table[:16]
            rule = r.rule_name[:30]
            lines.append(
                f"{status_tag:<8} | {r.severity.value:<8} | {tbl:<16} | {r.failed_count:<10} | {r.execution_time_ms:<8.2f} | {rule}"
            )
            if not r.passed:
                if r.error_message:
                    lines.append(f"         [!] Error: {r.error_message}")
                else:
                    lines.append(f"         [!] Violated: {r.failed_count} records (Threshold: {r.threshold}) | Query: {r.query_executed}")

        lines.append("=" * 80)
        if summary.pipeline_halted:
            lines.append("[HALTED] PIPELINE HALTED: One or more ERROR or CRITICAL data quality checks failed.")
            lines.append("         Downstream dashboard ingestion and production replication have been aborted.")
        else:
            lines.append("[SUCCESS] QUALITY GATES PASSED: All critical assertions succeeded.")
        lines.append("=" * 80)
        return "\n".join(lines)

    @staticmethod
    def to_json_report(summary: SuiteExecutionSummary) -> Dict[str, Any]:
        """Produce structured JSON report for observability pipelines."""
        return {
            "summary": {
                "total_tests": summary.total_tests,
                "passed_tests": summary.passed_tests,
                "failed_tests": summary.failed_tests,
                "error_tests": summary.error_tests,
                "warning_tests": summary.warning_tests,
                "pipeline_halted": summary.pipeline_halted,
                "total_duration_ms": summary.total_duration_ms
            },
            "results": [
                {
                    "rule_name": r.rule_name,
                    "table": r.table,
                    "rule_type": r.rule_type.value,
                    "severity": r.severity.value,
                    "passed": r.passed,
                    "failed_count": r.failed_count,
                    "total_evaluated_count": r.total_evaluated_count,
                    "threshold": r.threshold,
                    "execution_time_ms": r.execution_time_ms,
                    "query_executed": r.query_executed,
                    "error_message": r.error_message,
                    "details": r.details
                }
                for r in summary.results
            ]
        }
