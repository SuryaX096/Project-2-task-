"""Discovery and parser module for YAML test declarations."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import yaml
from .models import TestDeclaration, RuleType, Severity


class DeclarationParser:
    """Parses and validates YAML test definition files."""

    @staticmethod
    def parse_file(file_path: str | Path) -> Tuple[List[TestDeclaration], List[str]]:
        """Parse a single YAML file into TestDeclaration objects.
        Returns a tuple: (declarations, validation_errors)
        """
        path = Path(file_path)
        if not path.exists():
            return [], [f"File does not exist: {file_path}"]

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
        except Exception as e:
            return [], [f"Malformed YAML in {file_path}: {e}"]

        if not content:
            return [], []

        return DeclarationParser.parse_dict(content, source_file=str(file_path))

    @staticmethod
    def parse_dict(content: Dict[str, Any], source_file: str = "inline") -> Tuple[List[TestDeclaration], List[str]]:
        declarations: List[TestDeclaration] = []
        errors: List[str] = []

        if not isinstance(content, dict):
            return [], [f"Root of YAML file must be a dictionary/mapping ({source_file})"]

        # Support schema format:
        # version: 1
        # tables:
        #   orders:
        #     - name: check_id
        #       rule: null_check
        #       column: id
        # OR list format:
        # tests:
        #   - table: orders
        #     name: check_id
        #     rule: null_check
        #     ...

        if "tables" in content and isinstance(content["tables"], dict):
            for table_name, tests in content["tables"].items():
                if not isinstance(tests, list):
                    errors.append(f"In '{source_file}', table '{table_name}' must map to a list of tests.")
                    continue
                for idx, t in enumerate(tests):
                    decl, errs = DeclarationParser._parse_single_test(t, default_table=table_name, source_file=source_file, idx=idx)
                    if errs:
                        errors.extend(errs)
                    if decl:
                        declarations.append(decl)

        elif "tests" in content and isinstance(content["tests"], list):
            for idx, t in enumerate(content["tests"]):
                decl, errs = DeclarationParser._parse_single_test(t, default_table=None, source_file=source_file, idx=idx)
                if errs:
                    errors.extend(errs)
                if decl:
                    declarations.append(decl)
        else:
            errors.append(f"YAML in '{source_file}' must define top-level 'tables' or 'tests' key.")

        return declarations, errors

    @staticmethod
    def _parse_single_test(raw: Any, default_table: str | None, source_file: str, idx: int) -> Tuple[TestDeclaration | None, List[str]]:
        errors = []
        if not isinstance(raw, dict):
            return None, [f"Test definition index {idx} in {source_file} must be a mapping."]

        table = raw.get("table") or default_table
        if not table:
            errors.append(f"Test at index {idx} in {source_file} missing required 'table'.")

        name = raw.get("name")
        if not name:
            errors.append(f"Test at index {idx} in {source_file} missing required 'name'.")

        rule_raw = raw.get("rule") or raw.get("rule_type")
        if not rule_raw:
            errors.append(f"Test '{name or idx}' in {source_file} missing required 'rule'.")
            rule_type = None
        else:
            try:
                rule_type = RuleType(str(rule_raw).lower())
            except ValueError:
                valid_rules = ", ".join([r.value for r in RuleType])
                errors.append(f"Test '{name}' in {source_file} has invalid rule '{rule_raw}'. Allowed: {valid_rules}")
                rule_type = None

        severity_raw = raw.get("severity", "ERROR").upper()
        try:
            severity = Severity(severity_raw)
        except ValueError:
            valid_sevs = ", ".join([s.value for s in Severity])
            errors.append(f"Test '{name}' in {source_file} has invalid severity '{severity_raw}'. Allowed: {valid_sevs}")
            severity = Severity.ERROR

        column = raw.get("column")
        columns = raw.get("columns")
        tenant_column = raw.get("tenant_column", "organisation_id")
        parameters = raw.get("parameters") or raw.get("params") or {}
        if not isinstance(parameters, dict):
            errors.append(f"Parameters in '{name}' must be a dictionary.")
            parameters = {}
        description = raw.get("description", "")

        # Any extra parameters specified directly on the object (like min, max, parent_table, join_key)
        for key in ["min", "max", "threshold", "parent_table", "join_key", "target_table", "allowed_values", "count_query"]:
            if key in raw and key not in parameters:
                parameters[key] = raw[key]

        if errors or not table or not name or not rule_type:
            return None, errors

        decl = TestDeclaration(
            table=table,
            rule_type=rule_type,
            name=name,
            column=column,
            columns=columns,
            severity=severity,
            parameters=parameters,
            tenant_column=tenant_column,
            description=description
        )

        validation_errs = decl.validate()
        if validation_errs:
            errors.extend([f"In '{source_file}' test '{name}': {e}" for e in validation_errs])
            return None, errors

        return decl, []


class TestDiscovery:
    """Walks configuration directories and loads all YAML declarations."""

    @staticmethod
    def discover_tests(config_dir: str | Path) -> Tuple[List[TestDeclaration], List[str]]:
        path = Path(config_dir)
        all_declarations: List[TestDeclaration] = []
        all_errors: List[str] = []

        if not path.exists():
            return [], [f"Configuration directory does not exist: {config_dir}"]

        # Find all .yaml and .yml files recursively
        yaml_files = sorted(list(path.glob("**/*.yaml")) + list(path.glob("**/*.yml")))
        if not yaml_files:
            return [], [f"No YAML configuration files found in {config_dir}"]

        for file_path in yaml_files:
            decls, errs = DeclarationParser.parse_file(file_path)
            all_declarations.extend(decls)
            all_errors.extend(errs)

        return all_declarations, all_errors
