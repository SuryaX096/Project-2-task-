"""CI Validator: validates YAML test declarations before pull requests or merges."""
from __future__ import annotations
import sys
import argparse
from pathlib import Path
from dq_framework.discovery import TestDiscovery


def validate_configs(config_dir: str) -> int:
    """Validate all YAML test configurations in directory.
    Returns 0 if all valid, 1 if any syntax or schema violations exist.
    """
    print(f"[CI CHECK] Validating data quality test declarations in: {config_dir}")
    declarations, errors = TestDiscovery.discover_tests(config_dir)

    if errors:
        print("\n[FAIL] CI VALIDATION FAILED! The following declaration errors were detected:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\n[PASS] CI VALIDATION PASSED!")
    print(f"  - Successfully parsed and validated {len(declarations)} test declarations across configuration files.")
    
    # Display table breakdown
    table_counts = {}
    for d in declarations:
        table_counts[d.table] = table_counts.get(d.table, 0) + 1
    
    print("  - Table coverage:")
    for tbl, count in sorted(table_counts.items()):
        print(f"      * {tbl}: {count} checks")

    return 0


def main():
    parser = argparse.ArgumentParser(description="CI Data Quality Declaration Validator")
    parser.add_argument(
        "--config-dir",
        "-c",
        default="config/rules",
        help="Path to folder containing test declaration YAML files"
    )
    args = parser.parse_args()
    sys.exit(validate_configs(args.config_dir))


if __name__ == "__main__":
    main()
