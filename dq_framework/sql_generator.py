"""SQL Generator strictly enforcing count-only aggregation queries without raw PII retrieval."""
from __future__ import annotations
from typing import List, Optional
from .models import TestDeclaration, RuleType


class SqlGenerator:
    """Generates pure aggregation COUNT SQL statements for data quality checks.
    
    SECURITY PRINCIPLE:
    No query should ever do 'SELECT *', 'SELECT email', etc.
    Every query returns 'SELECT COUNT(*) AS violation_count ...'
    """

    @staticmethod
    def generate_violation_count_query(decl: TestDeclaration) -> str:
        """Compile a test declaration into an aggregate violation count query."""
        if decl.rule_type == RuleType.NULL_CHECK:
            return SqlGenerator._null_check_sql(decl)
        elif decl.rule_type == RuleType.UNIQUE_KEY:
            return SqlGenerator._unique_key_sql(decl)
        elif decl.rule_type == RuleType.RANGE_CHECK:
            return SqlGenerator._range_check_sql(decl)
        elif decl.rule_type == RuleType.CROSS_TENANT_CHECK:
            return SqlGenerator._cross_tenant_sql(decl)
        elif decl.rule_type == RuleType.ROW_COUNT_RECONCILIATION:
            return SqlGenerator._row_count_reconciliation_sql(decl)
        elif decl.rule_type == RuleType.SET_MEMBERSHIP:
            return SqlGenerator._set_membership_sql(decl)
        elif decl.rule_type == RuleType.CUSTOM_SQL:
            return SqlGenerator._custom_sql(decl)
        else:
            raise ValueError(f"Unsupported rule type: {decl.rule_type}")

    @staticmethod
    def _null_check_sql(decl: TestDeclaration) -> str:
        columns = [decl.column] if decl.column else (decl.columns or [])
        conditions = [f"({col} IS NULL)" for col in columns]
        where_clause = " OR ".join(conditions)
        return f"SELECT COUNT(*) AS violation_count FROM {decl.table} WHERE {where_clause}"

    @staticmethod
    def _unique_key_sql(decl: TestDeclaration) -> str:
        columns = [decl.column] if decl.column else (decl.columns or [])
        cols_str = ", ".join(columns)
        return (
            f"SELECT COUNT(*) AS violation_count FROM ("
            f"SELECT {cols_str}, COUNT(*) AS cnt "
            f"FROM {decl.table} "
            f"GROUP BY {cols_str} "
            f"HAVING COUNT(*) > 1"
            f") subq"
        )

    @staticmethod
    def _range_check_sql(decl: TestDeclaration) -> str:
        col = decl.column
        conditions = []
        if "min" in decl.parameters:
            min_val = decl.parameters["min"]
            # Validate numeric parameter
            if not isinstance(min_val, (int, float)):
                min_val = float(min_val)
            conditions.append(f"{col} < {min_val}")
        if "max" in decl.parameters:
            max_val = decl.parameters["max"]
            # Validate numeric parameter
            if not isinstance(max_val, (int, float)):
                max_val = float(max_val)
            conditions.append(f"{col} > {max_val}")
        where_clause = " OR ".join(conditions)
        return f"SELECT COUNT(*) AS violation_count FROM {decl.table} WHERE ({where_clause}) AND {col} IS NOT NULL"

    @staticmethod
    def _cross_tenant_sql(decl: TestDeclaration) -> str:
        """Cross-tenant collision check.
        Checks if child records join with parent records where tenant IDs don't match,
        or where parent records have different organisation_id for the given join_key.
        """
        child_tbl = decl.table
        parent_tbl = decl.parameters["parent_table"]
        join_key = decl.parameters["join_key"]
        tenant_col = decl.tenant_column
        
        # Check mismatched organisation_id between joined child and parent
        return (
            f"SELECT COUNT(*) AS violation_count FROM ("
            f"SELECT c.{tenant_col} AS child_tenant, p.{tenant_col} AS parent_tenant "
            f"FROM {child_tbl} c "
            f"JOIN {parent_tbl} p ON c.{join_key} = p.{join_key} "
            f"WHERE c.{tenant_col} != p.{tenant_col}"
            f") subq"
        )

    @staticmethod
    def _row_count_reconciliation_sql(decl: TestDeclaration) -> str:
        """Reconciles total row counts between source and target tables.
        Returns the absolute difference between table counts (0 means identical).
        """
        source_tbl = decl.table
        target_tbl = decl.parameters["target_table"]
        # In SQL, ABS((SELECT COUNT(*) FROM a) - (SELECT COUNT(*) FROM b))
        return (
            f"SELECT ABS("
            f"(SELECT COUNT(*) FROM {source_tbl}) - "
            f"(SELECT COUNT(*) FROM {target_tbl})"
            f") AS violation_count"
        )

    @staticmethod
    def _set_membership_sql(decl: TestDeclaration) -> str:
        col = decl.column
        allowed = decl.parameters["allowed_values"]
        # Format values properly and safely for SQL
        formatted = []
        for v in allowed:
            if isinstance(v, bool):
                formatted.append("1" if v else "0")
            elif isinstance(v, (int, float)):
                formatted.append(str(v))
            else:
                clean_v = str(v).replace("'", "''")
                formatted.append(f"'{clean_v}'")
        in_list = ", ".join(formatted)
        return f"SELECT COUNT(*) AS violation_count FROM {decl.table} WHERE {col} NOT IN ({in_list}) AND {col} IS NOT NULL"

    @staticmethod
    def _custom_sql(decl: TestDeclaration) -> str:
        query = decl.parameters["count_query"].strip()
        # Ensure query strictly behaves as a scalar count query
        if not query.upper().startswith("SELECT COUNT"):
            # Wrap query if user provided an inner violation filter query
            return f"SELECT COUNT(*) AS violation_count FROM ({query}) subq"
        return query

    @staticmethod
    def generate_total_evaluated_query(decl: TestDeclaration) -> str:
        """Query to fetch total rows evaluated in the subject table."""
        return f"SELECT COUNT(*) AS total_count FROM {decl.table}"
