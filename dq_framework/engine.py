"""Engine for executing data quality test declarations against any DatabaseAdapter."""
from __future__ import annotations
import time
from typing import List, Optional
from .models import TestDeclaration, TestResult, SuiteExecutionSummary, Severity
from .database import DatabaseAdapter
from .sql_generator import SqlGenerator


class ExecutionEngine:
    """Core execution engine for Data Quality assertions.
    
    Agnostic of underlying storage layer; interacts only through DatabaseAdapter.
    Strictly records violation counts and metadata.
    """

    def __init__(self, db_adapter: DatabaseAdapter):
        self.db = db_adapter

    def execute_test(self, decl: TestDeclaration, cached_totals: Optional[dict] = None) -> TestResult:
        """Execute a single test declaration and return TestResult."""
        errors = decl.validate()
        if errors:
            return TestResult(
                rule_name=decl.name,
                table=decl.table,
                rule_type=decl.rule_type,
                severity=decl.severity,
                passed=False,
                failed_count=1,
                total_evaluated_count=0,
                threshold=0,
                execution_time_ms=0.0,
                query_executed="N/A",
                error_message=f"Validation error: {'; '.join(errors)}"
            )

        violation_query = SqlGenerator.generate_violation_count_query(decl)
        threshold = int(decl.parameters.get("threshold", 0))

        start_time = time.perf_counter()
        try:
            violation_count = self.db.execute_scalar(violation_query)
            
            # Use cached table total count if provided to prevent redundant query lag
            if cached_totals is not None and decl.table in cached_totals:
                total_evaluated = cached_totals[decl.table]
            else:
                try:
                    total_eval_query = SqlGenerator.generate_total_evaluated_query(decl)
                    total_evaluated = self.db.execute_scalar(total_eval_query)
                    if cached_totals is not None:
                        cached_totals[decl.table] = total_evaluated
                except Exception:
                    total_evaluated = 0

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            passed = violation_count <= threshold

            return TestResult(
                rule_name=decl.name,
                table=decl.table,
                rule_type=decl.rule_type,
                severity=decl.severity,
                passed=passed,
                failed_count=violation_count,
                total_evaluated_count=total_evaluated,
                threshold=threshold,
                execution_time_ms=round(duration_ms, 2),
                query_executed=violation_query,
                details={
                    "parameters": decl.parameters,
                    "column": decl.column or decl.columns,
                    "description": decl.description
                }
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return TestResult(
                rule_name=decl.name,
                table=decl.table,
                rule_type=decl.rule_type,
                severity=decl.severity,
                passed=False,
                failed_count=1,
                total_evaluated_count=0,
                threshold=threshold,
                execution_time_ms=round(duration_ms, 2),
                query_executed=violation_query,
                error_message=f"Execution error: {str(e)}"
            )

    def execute_suite(self, declarations: List[TestDeclaration], stop_on_first_error: bool = False) -> SuiteExecutionSummary:
        """Execute a full suite of declarations.
        
        If stop_on_first_error is True, halts execution immediately upon encountering an ERROR/CRITICAL failure.
        """
        summary = SuiteExecutionSummary()
        cached_totals: dict = {}
        for decl in declarations:
            result = self.execute_test(decl, cached_totals=cached_totals)
            summary.add_result(result)
            if stop_on_first_error and result.is_blocking:
                break
        return summary
