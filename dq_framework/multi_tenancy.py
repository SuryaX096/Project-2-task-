"""Multi-Tenancy Guard Suite Generator.
Automatically injects baseline data quality and multi-tenancy assertions for tables.
"""
from __future__ import annotations
from typing import Dict, List, Optional
from .models import TestDeclaration, RuleType, Severity


class MultiTenancyGuardSuite:
    """Generates baseline enterprise multi-tenancy and data hygiene checks.
    
    Automatically creates:
    1. Null check on organisation_id (tenancy isolation)
    2. Primary / Deduplication key uniqueness check
    3. Cross-tenant leakage checks between child and parent tables
    4. Row count reconciliation check between raw/staging and processed tables
    """

    @staticmethod
    def generate_table_guard(
        table: str,
        primary_key: str,
        tenant_column: str = "organisation_id",
        severity: Severity = Severity.ERROR
    ) -> List[TestDeclaration]:
        """Generate baseline tenancy and unique key checks for a single table."""
        return [
            TestDeclaration(
                table=table,
                rule_type=RuleType.NULL_CHECK,
                name=f"auto_guard_{table}_tenant_not_null",
                column=tenant_column,
                severity=severity,
                description=f"Auto-injected guard: verify {tenant_column} is never NULL in {table}."
            ),
            TestDeclaration(
                table=table,
                rule_type=RuleType.UNIQUE_KEY,
                name=f"auto_guard_{table}_unique_key",
                column=primary_key,
                severity=severity,
                description=f"Auto-injected guard: verify deduplication key {primary_key} is strictly unique in {table}."
            ),
        ]

    @staticmethod
    def generate_cross_tenant_guard(
        child_table: str,
        parent_table: str,
        join_key: str,
        tenant_column: str = "organisation_id",
        severity: Severity = Severity.CRITICAL
    ) -> TestDeclaration:
        """Generate cross-tenant boundary verification."""
        return TestDeclaration(
            table=child_table,
            rule_type=RuleType.CROSS_TENANT_CHECK,
            name=f"auto_guard_cross_tenant_{child_table}_vs_{parent_table}",
            tenant_column=tenant_column,
            severity=severity,
            parameters={
                "parent_table": parent_table,
                "join_key": join_key
            },
            description=f"Auto-injected guard: ensure records in {child_table} belong to the exact same {tenant_column} as referenced records in {parent_table}."
        )

    @staticmethod
    def generate_reconciliation_guard(
        source_table: str,
        target_table: str,
        max_allowed_diff: int = 0,
        severity: Severity = Severity.ERROR
    ) -> TestDeclaration:
        """Generate row count reconciliation check between two tables."""
        return TestDeclaration(
            table=source_table,
            rule_type=RuleType.ROW_COUNT_RECONCILIATION,
            name=f"auto_guard_reconcile_{source_table}_to_{target_table}",
            severity=severity,
            parameters={
                "target_table": target_table,
                "threshold": max_allowed_diff
            },
            description=f"Auto-injected guard: verify row count reconciliation between {source_table} and {target_table} with threshold {max_allowed_diff}."
        )

    @staticmethod
    def generate_suite_for_dataset(
        table_configs: Dict[str, Dict[str, any]],
        relationships: Optional[List[Dict[str, str]]] = None,
        reconciliations: Optional[List[Dict[str, any]]] = None,
        tenant_column: str = "organisation_id"
    ) -> List[TestDeclaration]:
        """Automatically builds an exhaustive guard suite for an entire multi-tenant schema."""
        suite: List[TestDeclaration] = []

        # 1. Base table hygiene (tenant NOT NULL, PK unique)
        for tbl_name, conf in table_configs.items():
            pk = conf.get("primary_key", "id")
            sev = conf.get("severity", Severity.ERROR)
            suite.extend(MultiTenancyGuardSuite.generate_table_guard(
                table=tbl_name,
                primary_key=pk,
                tenant_column=tenant_column,
                severity=sev
            ))

        # 2. Cross-tenant leakage guards
        if relationships:
            for rel in relationships:
                suite.append(MultiTenancyGuardSuite.generate_cross_tenant_guard(
                    child_table=rel["child_table"],
                    parent_table=rel["parent_table"],
                    join_key=rel["join_key"],
                    tenant_column=tenant_column,
                    severity=rel.get("severity", Severity.CRITICAL)
                ))

        # 3. Row count reconciliation guards
        if reconciliations:
            for rec in reconciliations:
                suite.append(MultiTenancyGuardSuite.generate_reconciliation_guard(
                    source_table=rec["source_table"],
                    target_table=rec["target_table"],
                    max_allowed_diff=rec.get("max_allowed_diff", 0),
                    severity=rec.get("severity", Severity.ERROR)
                ))

        return suite
