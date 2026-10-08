"""Unit test suite for the Data Quality Framework.
Runs in SECONDS without requiring an external database, using SQLite in-memory and MockDatabaseAdapter.
Tests verify:
1. Database abstraction & Mock execution without any database
2. Count-only aggregation enforcement (zero PII leakage)
3. Schema parsing and validation rules
4. Auto-generated multi-tenancy suite injection
5. Live break-and-catch for all 3 seeded corruptions
6. Pipeline halting behavior on ERROR vs warning continuation on WARNING
"""
import pytest
from dq_framework.models import TestDeclaration, RuleType, Severity, TestResult, SuiteExecutionSummary
from dq_framework.database import MockDatabaseAdapter, SQLiteAdapter, DuckDBAdapter
from dq_framework.sql_generator import SqlGenerator
from dq_framework.engine import ExecutionEngine
from dq_framework.discovery import DeclarationParser, TestDiscovery
from dq_framework.multi_tenancy import MultiTenancyGuardSuite
from dq_framework.fixtures import seed_synthetic_data
from dq_framework.reporter import Reporter


# =========================================================================
# 1. DATABASE ABSTRACTION & MOCK EXECUTION (RUNS WITHOUT DATABASE IN SECONDS)
# =========================================================================
def test_engine_runs_with_mock_database():
    """Verify execution engine runs without a database connection in milliseconds."""
    mock_db = MockDatabaseAdapter(
        table_names=["orders", "products"],
        return_values={"violation_count": 0}
    )
    engine = ExecutionEngine(mock_db)

    decl = TestDeclaration(
        table="orders",
        rule_type=RuleType.NULL_CHECK,
        name="test_order_tenant_mock",
        column="organisation_id",
        severity=Severity.ERROR
    )

    result = engine.execute_test(decl)
    assert result.passed is True
    assert result.failed_count == 0
    assert "organisation_id IS NULL" in result.query_executed
    assert len(mock_db.executed_queries) >= 1


def test_mock_engine_catches_simulated_violation():
    """Verify mock adapter triggers pipeline failure upon returned count."""
    mock_db = MockDatabaseAdapter(
        return_values={"violation_count": 5}
    )
    engine = ExecutionEngine(mock_db)

    decl = TestDeclaration(
        table="orders",
        rule_type=RuleType.UNIQUE_KEY,
        name="test_unique_key_failure",
        column="order_id",
        severity=Severity.ERROR
    )

    result = engine.execute_test(decl)
    assert result.passed is False
    assert result.failed_count == 5
    assert result.is_blocking is True


# =========================================================================
# 2. PII SAFETY & COUNT-ONLY ENFORCEMENT
# =========================================================================
def test_sql_generator_strictly_enforces_count_only():
    """Verify all generated SQL queries use COUNT(*) aggregation and never select raw columns."""
    # Test NULL check
    q1 = SqlGenerator.generate_violation_count_query(TestDeclaration(
        table="users", rule_type=RuleType.NULL_CHECK, name="null_check", column="email"
    ))
    assert q1.startswith("SELECT COUNT(*) AS violation_count FROM users")
    assert "SELECT email" not in q1

    # Test UNIQUE key check
    q2 = SqlGenerator.generate_violation_count_query(TestDeclaration(
        table="users", rule_type=RuleType.UNIQUE_KEY, name="uniq_check", column="email"
    ))
    assert q2.startswith("SELECT COUNT(*) AS violation_count FROM (")
    assert "HAVING COUNT(*) > 1" in q2

    # Test CROSS TENANT check
    q3 = SqlGenerator.generate_violation_count_query(TestDeclaration(
        table="invoices",
        rule_type=RuleType.CROSS_TENANT_CHECK,
        name="cross_tenant",
        tenant_column="organisation_id",
        parameters={"parent_table": "orders", "join_key": "order_id"}
    ))
    assert q3.startswith("SELECT COUNT(*) AS violation_count FROM (")
    assert "WHERE c.organisation_id != p.organisation_id" in q3

    # Test ROW COUNT RECONCILIATION
    q4 = SqlGenerator.generate_violation_count_query(TestDeclaration(
        table="orders",
        rule_type=RuleType.ROW_COUNT_RECONCILIATION,
        name="reconcile",
        parameters={"target_table": "staging_orders"}
    ))
    assert q4.startswith("SELECT ABS((SELECT COUNT(*) FROM orders) - (SELECT COUNT(*) FROM staging_orders))")


def test_test_result_model_contains_no_raw_customer_rows():
    """Verify TestResult dataclass enforces telemetry metrics without storing record rows."""
    res = TestResult(
        rule_name="pii_check",
        table="users",
        rule_type=RuleType.NULL_CHECK,
        severity=Severity.ERROR,
        passed=False,
        failed_count=42,
        total_evaluated_count=1000,
        threshold=0,
        execution_time_ms=1.2,
        query_executed="SELECT COUNT(*) AS violation_count FROM users WHERE email IS NULL"
    )
    # Check attributes
    assert hasattr(res, "failed_count")
    assert hasattr(res, "total_evaluated_count")
    assert not hasattr(res, "records")
    assert not hasattr(res, "raw_rows")
    assert not hasattr(res, "violations_sample")


# =========================================================================
# 3. DECLARATION PARSER & SCHEMA VALIDATION
# =========================================================================
def test_declaration_parser_validates_required_fields():
    """Test validation errors for incomplete declarations."""
    raw_invalid = {
        "tables": {
            "orders": [
                {"name": "missing_rule"},  # missing rule
                {"name": "bad_rule", "rule": "non_existent_rule", "column": "id"},
                {"name": "missing_min_max", "rule": "range_check", "column": "amount"},
                {"name": "missing_parent", "rule": "cross_tenant_check"},
            ]
        }
    }
    decls, errors = DeclarationParser.parse_dict(raw_invalid, source_file="test.yaml")
    assert len(decls) == 0
    assert len(errors) >= 4


def test_discovery_reads_yaml_configs():
    """Test reading test declarations from config directory."""
    decls, errors = TestDiscovery.discover_tests("config/rules")
    assert len(errors) == 0
    assert len(decls) >= 30
    tables = {d.table for d in decls}
    assert len(tables) >= 10


# =========================================================================
# 4. AUTO-GENERATED MULTI-TENANCY GUARD SUITE
# =========================================================================
def test_auto_guard_suite_generation():
    """Test auto-injected checks for multi-tenancy and data hygiene."""
    table_configs = {
        "orders": {"primary_key": "order_id"},
        "invoices": {"primary_key": "invoice_id"}
    }
    relationships = [
        {"child_table": "invoices", "parent_table": "orders", "join_key": "order_id"}
    ]
    reconciliations = [
        {"source_table": "orders", "target_table": "staging_orders", "max_allowed_diff": 0}
    ]

    guards = MultiTenancyGuardSuite.generate_suite_for_dataset(
        table_configs=table_configs,
        relationships=relationships,
        reconciliations=reconciliations
    )

    # 2 tables * 2 guards (tenant_not_null, unique_key) = 4
    # + 1 cross-tenant check
    # + 1 reconciliation check = 6 total
    assert len(guards) == 6
    names = [g.name for g in guards]
    assert "auto_guard_orders_tenant_not_null" in names
    assert "auto_guard_orders_unique_key" in names
    assert "auto_guard_cross_tenant_invoices_vs_orders" in names
    assert "auto_guard_reconcile_orders_to_staging_orders" in names


# =========================================================================
# 5. LIVE BREAK-AND-CATCH: 3 SYNTHETIC CORRUPTIONS & PIPELINE HALTING
# =========================================================================
def test_live_break_and_catch_planted_corruptions():
    """Demonstrate live break-and-catch for all 3 planted synthetic corruptions:
    Bug 1: NULL organisation_id in products table
    Bug 2: Duplicate key in orders table
    Bug 3: Cross-tenant data collision in invoices table
    """
    adapter = SQLiteAdapter(":memory:")
    seed_synthetic_data(adapter, inject_corruptions=True)
    engine = ExecutionEngine(adapter)

    # Bug 1 Assertion: NULL organisation_id in products
    b1_decl = TestDeclaration(
        table="products",
        rule_type=RuleType.NULL_CHECK,
        name="test_catch_null_org_id",
        column="organisation_id",
        severity=Severity.ERROR
    )
    res1 = engine.execute_test(b1_decl)
    assert res1.passed is False
    assert res1.failed_count == 1  # Catches exactly 1 corrupted row prd_3
    assert res1.is_blocking is True

    # Bug 2 Assertion: Duplicate key in orders
    b2_decl = TestDeclaration(
        table="orders",
        rule_type=RuleType.UNIQUE_KEY,
        name="test_catch_duplicate_order_id",
        column="order_id",
        severity=Severity.ERROR
    )
    res2 = engine.execute_test(b2_decl)
    assert res2.passed is False
    assert res2.failed_count == 1  # Duplicate order_id 'ord_1002'
    assert res2.is_blocking is True

    # Bug 3 Assertion: Cross-tenant collision in invoices
    b3_decl = TestDeclaration(
        table="invoices",
        rule_type=RuleType.CROSS_TENANT_CHECK,
        name="test_catch_cross_tenant_leak",
        tenant_column="organisation_id",
        severity=Severity.CRITICAL,
        parameters={"parent_table": "orders", "join_key": "order_id"}
    )
    res3 = engine.execute_test(b3_decl)
    assert res3.passed is False
    assert res3.failed_count == 1  # Catches inv_999_leak where org_alpha referenced org_beta order
    assert res3.is_blocking is True

    adapter.close()


def test_clean_dataset_passes_all_assertions():
    """Verify that when clean data is loaded, all assertions pass with zero failures."""
    adapter = SQLiteAdapter(":memory:")
    seed_synthetic_data(adapter, inject_corruptions=False)
    engine = ExecutionEngine(adapter)

    # 1. Product null check passes
    res1 = engine.execute_test(TestDeclaration(
        table="products", rule_type=RuleType.NULL_CHECK, name="null_chk", column="organisation_id"
    ))
    assert res1.passed is True
    assert res1.failed_count == 0

    # 2. Order unique key passes
    res2 = engine.execute_test(TestDeclaration(
        table="orders", rule_type=RuleType.UNIQUE_KEY, name="uniq_chk", column="order_id"
    ))
    assert res2.passed is True
    assert res2.failed_count == 0

    # 3. Cross tenant check passes
    res3 = engine.execute_test(TestDeclaration(
        table="invoices",
        rule_type=RuleType.CROSS_TENANT_CHECK,
        name="cross_tenant_chk",
        tenant_column="organisation_id",
        parameters={"parent_table": "orders", "join_key": "order_id"}
    ))
    assert res3.passed is True
    assert res3.failed_count == 0

    adapter.close()


# =========================================================================
# 6. PIPELINE HALTING ON ERROR VS CONTINUATION ON WARNING
# =========================================================================
def test_pipeline_halts_on_error_but_continues_on_warning():
    """Verify ERROR severity marks pipeline as halted, while WARNING does not halt."""
    summary = SuiteExecutionSummary()

    # Add WARNING test failure
    warning_result = TestResult(
        rule_name="warn_rule",
        table="users",
        rule_type=RuleType.SET_MEMBERSHIP,
        severity=Severity.WARNING,
        passed=False,
        failed_count=2,
        total_evaluated_count=100,
        threshold=0,
        execution_time_ms=0.5,
        query_executed="SELECT COUNT(*)..."
    )
    summary.add_result(warning_result)

    assert summary.warning_tests == 1
    assert summary.error_tests == 0
    assert summary.pipeline_halted is False  # WARNING does not halt pipeline!

    # Add ERROR test failure
    error_result = TestResult(
        rule_name="err_rule",
        table="orders",
        rule_type=RuleType.NULL_CHECK,
        severity=Severity.ERROR,
        passed=False,
        failed_count=1,
        total_evaluated_count=100,
        threshold=0,
        execution_time_ms=0.5,
        query_executed="SELECT COUNT(*)..."
    )
    summary.add_result(error_result)

    assert summary.error_tests == 1
    assert summary.pipeline_halted is True  # ERROR immediately halts pipeline!


# =========================================================================
# 7. PERFORMANCE & LATENCY CACHING OPTIMIZATION VERIFICATION
# =========================================================================
def test_engine_cached_totals_eliminates_query_lag():
    """Verify that execution engine reuses cached totals to eliminate redundant queries."""
    mock_db = MockDatabaseAdapter(
        table_names=["orders"],
        return_values={"total_count": 500, "violation_count": 0}
    )
    engine = ExecutionEngine(mock_db)

    decls = [
        TestDeclaration(table="orders", rule_type=RuleType.NULL_CHECK, name="c1", column="organisation_id"),
        TestDeclaration(table="orders", rule_type=RuleType.UNIQUE_KEY, name="c2", column="order_id"),
        TestDeclaration(table="orders", rule_type=RuleType.RANGE_CHECK, name="c3", column="total_amount", parameters={"min": 0}),
    ]

    summary = engine.execute_suite(decls)
    assert summary.total_tests == 3
    # Check that total_count query was executed only ONCE for the table, not 3 times
    total_eval_queries = [q for q in mock_db.executed_queries if "total_count" in q.lower()]
    assert len(total_eval_queries) == 1


def test_sql_generator_handles_string_and_boolean_types_safely():
    """Verify SQL generator properly quotes strings and boolean values in set_membership."""
    decl = TestDeclaration(
        table="users",
        rule_type=RuleType.SET_MEMBERSHIP,
        name="test_membership",
        column="role",
        parameters={"allowed_values": ["admin", "user's_role", True, 42]}
    )
    sql = SqlGenerator.generate_violation_count_query(decl)
    assert "'user''s_role'" in sql
    assert "'admin'" in sql
    assert "1" in sql
    assert "42" in sql

