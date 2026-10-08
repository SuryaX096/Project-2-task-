# Data Quality & Remediation Runbook

## Overview
This runbook provides on-call Data Engineers, Analytics Engineers, and Incident Commanders with instructions on interpreting Data Quality (DQ) test execution reports, understanding error taxonomies, and executing step-by-step remediation procedures when quality gates fail.

---

## 1. Quality Gate Failure Definitions & Severity Taxonomy

| Severity | Definition | Engine Action | Alerting & Escalation |
| :--- | :--- | :--- | :--- |
| **CRITICAL** | Cross-tenant data leakage or corruption of primary tenancy isolation boundaries. Direct threat of customer data breach. | **Pipeline Aborted Immediately** (Exit Code 1). Downstream dashboard ingestion and production replication blocked. | PagerDuty high-priority page to Data On-Call & Security Team. |
| **ERROR** | Uniqueness violation (duplicate primary key), NULL foreign keys, or un-reconciled ETL totals. | **Pipeline Aborted Immediately** (Exit Code 1). Ingestion paused until reconciliation. | Slack `#data-alerts` channel notification, Jira incident ticket generated. |
| **WARNING** | Out-of-spec category values, newly observed non-critical statuses, soft metric drifts. | **Execution Continues** (Exit Code 0). Pipeline does not halt. | Warning logged in run summary, posted to `#data-quality-warnings`. |
| **INFO** | Informational baseline metadata or execution telemetry. | Non-blocking. | Internal logging. |

---

## 2. Interpreting Execution Reports

The engine outputs both an ASCII terminal summary table and an optional structured JSON report (`--json-out`).

### Terminal Report Fields
- `STATUS`: `PASS` or `FAIL`
- `SEVERITY`: `CRITICAL`, `ERROR`, or `WARNING`
- `TABLE`: Target relational table evaluated
- `VIOLATIONS`: Absolute number of records violating the rule (e.g., duplicate count or NULL count)
- `TIME(ms)`: Total execution latency in milliseconds for that assertion
- `RULE NAME`: Declared or auto-injected identifier of the check

### PII Protection Invariant
Under no circumstances does the report or execution log contain raw customer records (e.g. email addresses, names, card numbers). The framework executes pure aggregation scalar statements (`SELECT COUNT(*) AS violation_count ...`).

---

## 3. Step-by-Step Remediation Runbooks

### Runbook 1: Remediating NULL `organisation_id` (`null_check`)
- **Trigger**: `product_tenant_not_null` or `auto_guard_*_tenant_not_null` fails with violation count > 0.
- **Root Cause**: An upstream ETL worker omitted the tenant context during an insert/sync job, or an unmapped API ingestion payload passed validation.
- **Impact**: Unscoped multi-tenant data that risks global exposure or ingestion corruption.
- **Remediation Steps**:
  1. **Locate affected ingestion batch**: Check ETL worker logs for the sync run corresponding to the timestamp of the DQ run.
  2. **Isolate records in staging**:
     ```sql
     -- Safe inspection in quarantine environment
     SELECT batch_id, source_system, count(*) 
     FROM staging_products 
     WHERE organisation_id IS NULL 
     GROUP BY batch_id, source_system;
     ```
  3. **Backfill tenant attribution**:
     ```sql
     UPDATE products 
     SET organisation_id = (SELECT default_org_id FROM source_sync_metadata WHERE source_sync_metadata.product_id = products.product_id)
     WHERE organisation_id IS NULL;
     ```
  4. **Re-run Quality Framework**:
     ```bash
     python -m dq_framework.runner --engine sqlite
     ```

---

### Runbook 2: Remediating Duplicate Keys (`unique_key`)
- **Trigger**: `order_id_unique` or `auto_guard_*_unique_key` fails with violation count > 0.
- **Root Cause**: Upstream message retry / replay without idempotent deduplication (e.g., Kafka consumer duplicate read or network retry on webhook).
- **Impact**: Double-counted revenue in dashboards, duplicate invoices issued, erroneous metric reporting.
- **Remediation Steps**:
  1. **Identify duplicated deduplication keys in quarantine**:
     ```sql
     SELECT order_id, count(*) 
     FROM orders 
     GROUP BY order_id 
     HAVING count(*) > 1;
     ```
  2. **Deduplicate via window function (retain latest timestamp / lowest rowid)**:
     ```sql
     DELETE FROM orders 
     WHERE rowid NOT IN (
         SELECT min(rowid) 
         FROM orders 
         GROUP BY order_id
     );
     ```
  3. **Re-run Quality Framework**:
     ```bash
     python -m dq_framework.runner --engine sqlite
     ```

---

### Runbook 3: Remediating Cross-Tenant Data Collision (`cross_tenant_check`)
- **Trigger**: `invoice_cross_tenant_collision_check` or `auto_guard_cross_tenant_*` fails with violation count > 0.
- **Root Cause**: Child relational entity (e.g., `invoices` or `order_items`) associated with a foreign key belonging to a different customer/tenant.
- **Impact**: Critical security breach: Tenant A will see billing or item data belonging to Tenant B on their dashboard.
- **Remediation Steps**:
  1. **Immediately Quarantine Affected Records**:
     ```sql
     CREATE TABLE quarantined_invoices AS 
     SELECT c.* 
     FROM invoices c 
     JOIN orders p ON c.order_id = p.order_id 
     WHERE c.organisation_id != p.organisation_id;
     
     DELETE FROM invoices 
     WHERE invoice_id IN (SELECT invoice_id FROM quarantined_invoices);
     ```
  2. **Audit Originating API / Pipeline**:
     - Check the API endpoint or worker that minted the invoice ID.
     - Verify if customer session authentication tokens were reused across requests.
  3. **Re-run Quality Framework**:
     ```bash
     python -m dq_framework.runner --engine sqlite
     ```
