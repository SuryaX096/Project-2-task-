# Enterprise Data Quality & Testing Framework From Scratch (DATA-2)

An extensible, database-agnostic data quality assertion and multi-tenancy testing engine built from scratch in Python. Designed to prevent corrupt records, duplicate keys, and cross-tenant data collisions from propagating into production analytics dashboards.

---

## Key Highlights

1. **10+ Normalized Relational Tables Coverage**: Complete relational schema (`organisations`, `users`, `products`, `customers`, `orders`, `order_items`, `payments`, `invoices`, `audit_logs`, `shipments`) + staging tables.
2. **Database-Agnostic Execution Engine**: Pluggable driver interface supporting **In-Memory SQLite**, **DuckDB (OLAP)**, **Pure Mock**, and **ClickHouse**. Unit tests run in milliseconds without requiring any external database servers.
3. **Strict PII & Privacy Guard (Count-Only Enforcement)**: All assertions execute pure aggregate `COUNT(*)` scalar queries. No raw customer records, email addresses, or PII ever touch engine state, memory buffers, or log files.
4. **Auto-Generated Multi-Tenancy Guard Suite**: Automatically scans table definitions and injects default multi-tenancy guards:
   - Tenant column (`organisation_id`) non-null validation
   - Deduplication key uniqueness assertions
   - Zero cross-tenant relational collision checks
   - Row count reconciliation against staging tables
5. **Demonstrated Live Break-and-Catch**: Planted 3 distinct synthetic data bugs:
   - **Bug 1 (Missing Tenant)**: NULL `organisation_id` in `products`.
   - **Bug 2 (Duplicate Key)**: Duplicate `order_id` in `orders`.
   - **Bug 3 (Cross-Tenant Collision)**: Child invoice belonging to Tenant A referencing an order belonging to Tenant B.
6. **Continuous Integration (CI) Validator**: Standalone CLI tool (`dq_framework.ci_validator`) to validate YAML test declarations before merging.
7. **Remediation Runbooks**: Complete documentation in `docs/REMEDIATION_RUNBOOK.md` detailing failure taxonomy and step-by-step SQL/ETL runbooks.

---

## Architecture & Directory Layout

```
project 2/
├── config/
│   └── rules/
│       ├── 01_core_entities.yaml   # Declarations for organisations, users, products, customers
│       ├── 02_transactions.yaml    # Declarations for orders, order_items, staging reconciliations
│       └── 03_billing_ops.yaml     # Declarations for payments, invoices, shipments, audit_logs
├── dq_framework/
│   ├── __init__.py
│   ├── ci_validator.py            # CI pre-merge test declaration validator
│   ├── database.py                # DatabaseAdapter (SQLite, DuckDB, ClickHouse, Mock)
│   ├── discovery.py               # YAML test parser & config directory scanner
│   ├── engine.py                  # Database-agnostic test execution engine
│   ├── fixtures.py                # Synthetic generator for 10 normalized tables & planted bugs
│   ├── models.py                  # Domain models (TestDeclaration, TestResult, Severity)
│   ├── multi_tenancy.py           # Auto-injected multi-tenancy guard generator
│   ├── reporter.py                # PII-safe console & JSON reporting
│   ├── runner.py                  # Test runner CLI with pipeline halting demonstration
│   └── sql_generator.py           # Count-only query compiler
├── docs/
│   └── REMEDIATION_RUNBOOK.md     # Production remediation runbooks and error definitions
├── tests/
│   └── test_dq_framework.py       # Full pytest suite (runs in 0.07 seconds without database)
├── pytest.ini
└── README.md
```

---

## Getting Started

### 1. Run Unit Tests (Runs in < 0.1s without external database)
```bash
pytest
```
Output:
```text
tests\test_dq_framework.py .......... [100%]
10 passed in 0.07s
```

### 2. Run CI Test Declaration Validator
Verify that all YAML files conform to the test declaration schema:
```bash
python -m dq_framework.ci_validator -c config/rules
```

### 3. Demonstrate Live Break-and-Catch (Halts Pipeline on Planted Bugs)
Run the framework against the synthetic dataset containing the 3 planted corruptions:
```bash
python -m dq_framework.runner
```
The framework executes 55 assertions, detects the planted bugs, and exits with code `1`:
```text
[HALTED] PIPELINE HALTED: One or more ERROR or CRITICAL data quality checks failed.
         Downstream dashboard ingestion and production replication have been aborted.
```

### 4. Verify Clean Ingestion (Zero Errors)
Run against clean synthetic data:
```bash
python -m dq_framework.runner --clean
```
Output exits with code `0`:
```text
[SUCCESS] QUALITY GATES PASSED: All critical assertions succeeded.
```

### 5. Run with Analytical DuckDB Engine
```bash
python -m dq_framework.runner --engine duckdb
```

---

## Review Q&A Check

### Q1: "Does your unit test suite run without a database connection?"
**Answer:**
Yes. The core execution engine is decoupled behind the `DatabaseAdapter` interface. In `tests/test_dq_framework.py`, unit tests run against `MockDatabaseAdapter` and in-memory SQLite (`:memory:`). The entire 10-test suite runs in under **0.08 seconds** with zero external database dependencies.

### Q2: "Demonstrate a live data break on your 10-table dataset and show your engine catch it."
**Answer:**
We injected 3 synthetic corruptions into the 10-table normalized dataset in `dq_framework/fixtures.py`:
1. `products`: A product row with `organisation_id IS NULL`. Caught by rule `product_tenant_not_null` (`violation_count: 1`).
2. `orders`: An order row duplicated with key `ord_1002`. Caught by rule `order_id_unique` (`violation_count: 1`).
3. `invoices`: Invoice `inv_999_leak` associated with `org_alpha` references an order belonging to `org_beta`. Caught by `invoice_cross_tenant_collision_check` (`violation_count: 1`).

When executed via `python -m dq_framework.runner`, the engine immediately halts the pipeline with status `[HALTED / BLOCKED]` and exit code `1`.

### Q3: "How does your engine prevent raw row leakage in log files?"
**Answer:**
1. **Compilation Invariant**: The query compiler (`dq_framework/sql_generator.py`) only emits scalar count aggregations (`SELECT COUNT(*) AS violation_count ...`). It never issues `SELECT *` or selects individual column payloads.
2. **Data Structure Invariant**: The `TestResult` class stores only integer violation counts, execution latency, threshold limits, and query metadata. It contains no fields or buffers for row values.
3. **Log & Report Invariant**: Both the terminal console formatter (`Reporter.format_terminal_report`) and structured JSON exporter (`Reporter.to_json_report`) strictly output aggregated metrics and never log raw rows.
