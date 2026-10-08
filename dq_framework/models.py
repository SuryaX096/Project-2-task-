"""Core domain models for Data Quality assertions, rules, and results."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RuleType(str, Enum):
    NULL_CHECK = "null_check"
    UNIQUE_KEY = "unique_key"
    RANGE_CHECK = "range_check"
    CROSS_TENANT_CHECK = "cross_tenant_check"
    ROW_COUNT_RECONCILIATION = "row_count_reconciliation"
    SET_MEMBERSHIP = "set_membership"
    CUSTOM_SQL = "custom_sql"


@dataclass(frozen=True)
class TestDeclaration:
    """Declared test specification parsed from YAML or auto-generated."""
    table: str
    rule_type: RuleType
    name: str
    column: Optional[str] = None
    columns: Optional[List[str]] = None
    severity: Severity = Severity.ERROR
    parameters: Dict[str, Any] = field(default_factory=dict)
    tenant_column: str = "organisation_id"
    description: str = ""

    def validate(self) -> List[str]:
        """Validate declaration schema integrity."""
        errors = []
        if not self.table or not self.table.strip():
            errors.append("Declaration must specify a non-empty 'table'.")
        if not self.name or not self.name.strip():
            errors.append("Declaration must specify a non-empty 'name'.")
        
        if self.rule_type == RuleType.NULL_CHECK and not self.column and not self.columns:
            errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'column' or 'columns'.")
            
        if self.rule_type == RuleType.UNIQUE_KEY and not self.column and not self.columns:
            errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'column' or 'columns'.")
            
        if self.rule_type == RuleType.RANGE_CHECK:
            if not self.column:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'column'.")
            if "min" not in self.parameters and "max" not in self.parameters:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires at least 'min' or 'max' in parameters.")

        if self.rule_type == RuleType.CROSS_TENANT_CHECK:
            if "parent_table" not in self.parameters or "join_key" not in self.parameters:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'parent_table' and 'join_key' in parameters.")

        if self.rule_type == RuleType.ROW_COUNT_RECONCILIATION:
            if "target_table" not in self.parameters:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'target_table' in parameters.")

        if self.rule_type == RuleType.SET_MEMBERSHIP:
            if not self.column:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'column'.")
            if "allowed_values" not in self.parameters or not isinstance(self.parameters["allowed_values"], list):
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'allowed_values' list in parameters.")

        if self.rule_type == RuleType.CUSTOM_SQL:
            if "count_query" not in self.parameters:
                errors.append(f"Rule '{self.name}' ({self.rule_type.value}) requires 'count_query' in parameters.")

        return errors


@dataclass
class TestResult:
    """Execution result of a test declaration.
    
    CRITICAL SECURITY INVARIANT:
    No raw row data, sample customer strings, or PII can be stored here.
    Only aggregated counts, metadata, status, and execution duration.
    """
    rule_name: str
    table: str
    rule_type: RuleType
    severity: Severity
    passed: bool
    failed_count: int
    total_evaluated_count: int
    threshold: int
    execution_time_ms: float
    query_executed: str
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    @property
    def is_blocking(self) -> bool:
        """Determines if failure halts pipeline execution."""
        return not self.passed and self.severity in (Severity.ERROR, Severity.CRITICAL)


@dataclass
class SuiteExecutionSummary:
    """Summary of a suite execution."""
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    warning_tests: int = 0
    error_tests: int = 0
    total_duration_ms: float = 0.0
    results: List[TestResult] = field(default_factory=list)

    @property
    def pipeline_halted(self) -> bool:
        """True if any blocking test failed."""
        return any(r.is_blocking for r in self.results)

    def add_result(self, result: TestResult) -> None:
        self.results.append(result)
        self.total_tests += 1
        self.total_duration_ms += result.execution_time_ms
        if result.passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
            if result.severity in (Severity.ERROR, Severity.CRITICAL):
                self.error_tests += 1
            elif result.severity == Severity.WARNING:
                self.warning_tests += 1
