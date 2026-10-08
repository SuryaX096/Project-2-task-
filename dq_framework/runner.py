"""Test Runner CLI: executes quality checks across tables and demonstrates pipeline halting."""
from __future__ import annotations
import sys
import argparse
import json
from pathlib import Path
from dq_framework.database import SQLiteAdapter, DuckDBAdapter
from dq_framework.discovery import TestDiscovery
from dq_framework.engine import ExecutionEngine
from dq_framework.multi_tenancy import MultiTenancyGuardSuite
from dq_framework.reporter import Reporter
from dq_framework.fixtures import seed_synthetic_data


def run_checks(
    config_dir: str = "config/rules",
    db_engine: str = "sqlite",
    inject_corruptions: bool = True,
    include_auto_guards: bool = True,
    stop_on_error: bool = False,
    output_json: str | None = None
) -> int:
    """Run data quality test suite."""
    print(f"[RUNNER] Initializing database engine: {db_engine.upper()}")
    if db_engine.lower() == "duckdb":
        adapter = DuckDBAdapter(":memory:")
    else:
        adapter = SQLiteAdapter(":memory:")

    print(f"[RUNNER] Seeding synthetic 10-table normalized dataset (corruptions={inject_corruptions})...")
    seed_result = seed_synthetic_data(adapter, inject_corruptions=inject_corruptions)
    print(f"[RUNNER] Created {len(seed_result['tables'])} tables: {', '.join(seed_result['tables'])}")

    print(f"[RUNNER] Loading test declarations from {config_dir}...")
    declarations, parse_errors = TestDiscovery.discover_tests(config_dir)
    if parse_errors:
        print("[ERROR] Found syntax/schema errors in test declarations:")
        for err in parse_errors:
            print(f"  - {err}")
        return 1

    if include_auto_guards:
        print("[RUNNER] Generating auto-injected Multi-Tenancy Guards...")
        # Auto-generate guards for tables and known cross-table relations
        table_configs = {
            "organisations": {"primary_key": "organisation_id"},
            "users": {"primary_key": "user_id"},
            "products": {"primary_key": "product_id"},
            "customers": {"primary_key": "customer_id"},
            "orders": {"primary_key": "order_id"},
            "order_items": {"primary_key": "item_id"},
            "payments": {"primary_key": "payment_id"},
            "invoices": {"primary_key": "invoice_id"},
            "audit_logs": {"primary_key": "log_id"},
            "shipments": {"primary_key": "shipment_id"},
        }
        relationships = [
            {"child_table": "invoices", "parent_table": "orders", "join_key": "order_id"},
            {"child_table": "order_items", "parent_table": "orders", "join_key": "order_id"},
            {"child_table": "shipments", "parent_table": "orders", "join_key": "order_id"},
        ]
        reconciliations = [
            {"source_table": "orders", "target_table": "staging_orders", "max_allowed_diff": 0}
        ]
        auto_guards = MultiTenancyGuardSuite.generate_suite_for_dataset(
            table_configs=table_configs,
            relationships=relationships,
            reconciliations=reconciliations
        )
        print(f"[RUNNER] Added {len(auto_guards)} auto-injected multi-tenancy & deduplication checks.")
        # Prepend auto guards
        declarations = auto_guards + declarations

    print(f"[RUNNER] Executing {len(declarations)} total data quality tests...")
    engine = ExecutionEngine(adapter)
    summary = engine.execute_suite(declarations, stop_on_first_error=stop_on_error)

    # Print terminal report
    report_text = Reporter.format_terminal_report(summary)
    print("\n" + report_text)

    if output_json:
        json_report = Reporter.to_json_report(summary)
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(json_report, f, indent=2)
        print(f"[RUNNER] Exported JSON report to {output_json}")

    adapter.close()
    return 1 if summary.pipeline_halted else 0


def main():
    parser = argparse.ArgumentParser(description="Data Quality Test Runner")
    parser.add_argument("--config-dir", "-c", default="config/rules")
    parser.add_argument("--engine", "-e", choices=["sqlite", "duckdb"], default="sqlite")
    parser.add_argument("--clean", action="store_true", help="Run against clean data without corruptions")
    parser.add_argument("--no-auto-guards", action="store_true", help="Disable auto-generated multi-tenancy guards")
    parser.add_argument("--stop-on-error", action="store_true", help="Halt execution upon first blocking error")
    parser.add_argument("--json-out", default=None, help="Save structured report to JSON file")
    
    args = parser.parse_args()
    exit_code = run_checks(
        config_dir=args.config_dir,
        db_engine=args.engine,
        inject_corruptions=not args.clean,
        include_auto_guards=not args.no_auto_guards,
        stop_on_error=args.stop_on_error,
        output_json=args.json_out
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
