"""Synthetic enterprise dataset generator for 10 relational normalized multi-tenant tables.
Supports generating clean datasets and datasets with intentionally planted corruptions.
"""
from __future__ import annotations
import random
from typing import Dict, List, Tuple
from .database import DatabaseAdapter


# Table DDL definitions (Relational B2B SaaS E-Commerce / Billing schema)
DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS organisations (
        organisation_id TEXT PRIMARY KEY,
        org_name TEXT NOT NULL,
        plan_tier TEXT NOT NULL,
        is_active INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        email TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        sku TEXT NOT NULL,
        price REAL NOT NULL,
        stock_quantity INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        name TEXT NOT NULL,
        loyalty_tier TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        customer_id TEXT NOT NULL,
        total_amount REAL NOT NULL,
        status TEXT NOT NULL,
        order_date TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        item_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        order_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        order_id TEXT NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL,
        status TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS invoices (
        invoice_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        order_id TEXT NOT NULL,
        amount_due REAL NOT NULL,
        due_date TEXT NOT NULL,
        is_paid INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        log_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS shipments (
        shipment_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        order_id TEXT NOT NULL,
        tracking_number TEXT NOT NULL,
        carrier TEXT NOT NULL,
        shipped_date TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS staging_orders (
        order_id TEXT PRIMARY KEY,
        organisation_id TEXT,
        customer_id TEXT NOT NULL,
        total_amount REAL NOT NULL,
        status TEXT NOT NULL,
        order_date TEXT NOT NULL
    );
    """
]


def initialize_schema(adapter: DatabaseAdapter) -> None:
    """Execute DDL statements to create all 10 normalized tables + staging table."""
    for ddl in DDL_STATEMENTS:
        adapter.execute_ddl(ddl)


def seed_synthetic_data(adapter: DatabaseAdapter, inject_corruptions: bool = True) -> Dict[str, any]:
    """Seed synthetic data across all 10 relational tables.
    
    If inject_corruptions is True, injects exactly 3 deliberate bugs:
      Bug 1: NULL organisation_id in products table (null_check violation)
      Bug 2: Duplicate primary key in orders table (unique_key deduplication violation)
      Bug 3: Cross-tenant data collision in invoices table where child invoice has org_alpha
             referencing an order belonging to org_beta (cross_tenant_check violation)
    """
    initialize_schema(adapter)

    # 1. Organisations (Clean: 3 tenants: org_alpha, org_beta, org_gamma)
    org_sql = """
    INSERT INTO organisations (organisation_id, org_name, plan_tier, is_active) VALUES
    ('org_alpha', 'Alpha Corp', 'enterprise', 1),
    ('org_beta', 'Beta Logistics', 'pro', 1),
    ('org_gamma', 'Gamma Retail', 'starter', 1);
    """
    adapter.execute_ddl(org_sql)

    # 2. Users (Clean)
    user_sql = """
    INSERT INTO users (user_id, organisation_id, email, role, created_at) VALUES
    ('usr_101', 'org_alpha', 'alice@alpha.com', 'admin', '2026-01-01'),
    ('usr_102', 'org_alpha', 'bob@alpha.com', 'analyst', '2026-01-02'),
    ('usr_201', 'org_beta', 'carol@beta.com', 'admin', '2026-01-01'),
    ('usr_202', 'org_beta', 'dave@beta.com', 'viewer', '2026-01-03'),
    ('usr_301', 'org_gamma', 'eve@gamma.com', 'admin', '2026-01-01');
    """
    adapter.execute_ddl(user_sql)

    # 3. Products
    # BUG 1 PLANTED HERE if inject_corruptions: 1 record has NULL organisation_id
    if inject_corruptions:
        prod_sql = """
        INSERT INTO products (product_id, organisation_id, sku, price, stock_quantity) VALUES
        ('prd_1', 'org_alpha', 'SKU-A1', 49.99, 100),
        ('prd_2', 'org_alpha', 'SKU-A2', 89.99, 50),
        ('prd_3', NULL, 'SKU-CORRUPT-NULL-ORG', 19.99, 20), -- BUG 1: NULL org_id
        ('prd_4', 'org_beta', 'SKU-B1', 120.00, 30),
        ('prd_5', 'org_beta', 'SKU-B2', 15.50, 200),
        ('prd_6', 'org_gamma', 'SKU-G1', 5.00, 500);
        """
    else:
        prod_sql = """
        INSERT INTO products (product_id, organisation_id, sku, price, stock_quantity) VALUES
        ('prd_1', 'org_alpha', 'SKU-A1', 49.99, 100),
        ('prd_2', 'org_alpha', 'SKU-A2', 89.99, 50),
        ('prd_3', 'org_alpha', 'SKU-A3', 19.99, 20),
        ('prd_4', 'org_beta', 'SKU-B1', 120.00, 30),
        ('prd_5', 'org_beta', 'SKU-B2', 15.50, 200),
        ('prd_6', 'org_gamma', 'SKU-G1', 5.00, 500);
        """
    adapter.execute_ddl(prod_sql)

    # 4. Customers (Clean)
    cust_sql = """
    INSERT INTO customers (customer_id, organisation_id, name, loyalty_tier) VALUES
    ('cust_1', 'org_alpha', 'Acme Trading', 'gold'),
    ('cust_2', 'org_alpha', 'Apex Global', 'silver'),
    ('cust_3', 'org_beta', 'Beacon Shipping', 'platinum'),
    ('cust_4', 'org_gamma', 'Green Express', 'bronze');
    """
    adapter.execute_ddl(cust_sql)

    # 5. Orders & Staging Orders
    # BUG 2 PLANTED HERE if inject_corruptions: Duplicate key in orders table
    # (Note: SQLite handles primary key duplicate insert by rejecting if declared PRIMARY KEY,
    # so we insert duplicate into a table or deduplication column. To test deduplication rule,
    # we can use composite dedup or allow duplicates if table allows or use staging_orders/orders)
    # Let's inspect: In orders table, if we want duplicate rows, we can temporarily drop or omit PK constraint
    # on order_id in SQLite or test deduplication key column 'order_id' or insert into staging/orders.
    # To ensure SQLite allows duplicate key insertion for the test:
    if inject_corruptions:
        # Recreate orders table without strict unique constraint on SQLite so corrupt row can sit in it
        adapter.execute_ddl("DROP TABLE IF EXISTS orders;")
        adapter.execute_ddl("""
        CREATE TABLE orders (
            order_id TEXT,
            organisation_id TEXT,
            customer_id TEXT NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT NOT NULL,
            order_date TEXT NOT NULL
        );
        """)
        ord_sql = """
        INSERT INTO orders (order_id, organisation_id, customer_id, total_amount, status, order_date) VALUES
        ('ord_1001', 'org_alpha', 'cust_1', 250.00, 'completed', '2026-02-01'),
        ('ord_1002', 'org_alpha', 'cust_2', 450.00, 'completed', '2026-02-02'),
        ('ord_1002', 'org_alpha', 'cust_2', 450.00, 'completed', '2026-02-02'), -- BUG 2: DUPLICATE KEY
        ('ord_2001', 'org_beta', 'cust_3', 900.00, 'processing', '2026-02-01'),
        ('ord_3001', 'org_gamma', 'cust_4', 50.00, 'completed', '2026-02-03');
        """
    else:
        adapter.execute_ddl("DROP TABLE IF EXISTS orders;")
        adapter.execute_ddl("""
        CREATE TABLE orders (
            order_id TEXT,
            organisation_id TEXT,
            customer_id TEXT NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT NOT NULL,
            order_date TEXT NOT NULL
        );
        """)
        ord_sql = """
        INSERT INTO orders (order_id, organisation_id, customer_id, total_amount, status, order_date) VALUES
        ('ord_1001', 'org_alpha', 'cust_1', 250.00, 'completed', '2026-02-01'),
        ('ord_1002', 'org_alpha', 'cust_2', 450.00, 'completed', '2026-02-02'),
        ('ord_2001', 'org_beta', 'cust_3', 900.00, 'processing', '2026-02-01'),
        ('ord_3001', 'org_gamma', 'cust_4', 50.00, 'completed', '2026-02-03');
        """
    adapter.execute_ddl(ord_sql)

    # 5b. Staging orders (for row count reconciliation)
    staging_sql = """
    INSERT INTO staging_orders (order_id, organisation_id, customer_id, total_amount, status, order_date) VALUES
    ('ord_1001', 'org_alpha', 'cust_1', 250.00, 'completed', '2026-02-01'),
    ('ord_1002', 'org_alpha', 'cust_2', 450.00, 'completed', '2026-02-02'),
    ('ord_2001', 'org_beta', 'cust_3', 900.00, 'processing', '2026-02-01'),
    ('ord_3001', 'org_gamma', 'cust_4', 50.00, 'completed', '2026-02-03');
    """
    adapter.execute_ddl(staging_sql)

    # 6. Order items (Clean)
    items_sql = """
    INSERT INTO order_items (item_id, organisation_id, order_id, product_id, quantity, unit_price) VALUES
    ('itm_1', 'org_alpha', 'ord_1001', 'prd_1', 2, 49.99),
    ('itm_2', 'org_alpha', 'ord_1002', 'prd_2', 1, 89.99),
    ('itm_3', 'org_beta', 'ord_2001', 'prd_4', 3, 120.00),
    ('itm_4', 'org_gamma', 'ord_3001', 'prd_6', 10, 5.00);
    """
    adapter.execute_ddl(items_sql)

    # 7. Payments (Clean)
    pay_sql = """
    INSERT INTO payments (payment_id, organisation_id, order_id, amount, payment_method, status) VALUES
    ('pay_1', 'org_alpha', 'ord_1001', 250.00, 'credit_card', 'success'),
    ('pay_2', 'org_alpha', 'ord_1002', 450.00, 'wire', 'success'),
    ('pay_3', 'org_beta', 'ord_2001', 900.00, 'credit_card', 'pending'),
    ('pay_4', 'org_gamma', 'ord_3001', 50.00, 'credit_card', 'success');
    """
    adapter.execute_ddl(pay_sql)

    # 8. Invoices
    # BUG 3 PLANTED HERE if inject_corruptions: Cross-Tenant data collision
    # Child invoice inv_999 is labelled 'org_alpha', but its order_id 'ord_2001' belongs to 'org_beta'!
    if inject_corruptions:
        inv_sql = """
        INSERT INTO invoices (invoice_id, organisation_id, order_id, amount_due, due_date, is_paid) VALUES
        ('inv_1', 'org_alpha', 'ord_1001', 250.00, '2026-03-01', 1),
        ('inv_2', 'org_alpha', 'ord_1002', 450.00, '2026-03-01', 1),
        ('inv_3', 'org_beta', 'ord_2001', 900.00, '2026-03-01', 0),
        ('inv_4', 'org_gamma', 'ord_3001', 50.00, '2026-03-01', 1),
        ('inv_999_leak', 'org_alpha', 'ord_2001', 900.00, '2026-03-01', 0); -- BUG 3: Cross-tenant collision!
        """
    else:
        inv_sql = """
        INSERT INTO invoices (invoice_id, organisation_id, order_id, amount_due, due_date, is_paid) VALUES
        ('inv_1', 'org_alpha', 'ord_1001', 250.00, '2026-03-01', 1),
        ('inv_2', 'org_alpha', 'ord_1002', 450.00, '2026-03-01', 1),
        ('inv_3', 'org_beta', 'ord_2001', 900.00, '2026-03-01', 0),
        ('inv_4', 'org_gamma', 'ord_3001', 50.00, '2026-03-01', 1);
        """
    adapter.execute_ddl(inv_sql)

    # 9. Audit Logs (Clean)
    audit_sql = """
    INSERT INTO audit_logs (log_id, organisation_id, user_id, action, timestamp) VALUES
    ('log_1', 'org_alpha', 'usr_101', 'LOGIN', '2026-02-01 10:00:00'),
    ('log_2', 'org_alpha', 'usr_102', 'VIEW_ORDER', '2026-02-01 10:05:00'),
    ('log_3', 'org_beta', 'usr_201', 'CREATE_ORDER', '2026-02-01 11:00:00'),
    ('log_4', 'org_gamma', 'usr_301', 'LOGIN', '2026-02-01 12:00:00');
    """
    adapter.execute_ddl(audit_sql)

    # 10. Shipments (Clean)
    ship_sql = """
    INSERT INTO shipments (shipment_id, organisation_id, order_id, tracking_number, carrier, shipped_date) VALUES
    ('shp_1', 'org_alpha', 'ord_1001', 'TRK-ALPHA-01', 'FedEx', '2026-02-02'),
    ('shp_2', 'org_alpha', 'ord_1002', 'TRK-ALPHA-02', 'UPS', '2026-02-03'),
    ('shp_3', 'org_beta', 'ord_2001', 'TRK-BETA-01', 'DHL', '2026-02-02'),
    ('shp_4', 'org_gamma', 'ord_3001', 'TRK-GAMMA-01', 'USPS', '2026-02-04');
    """
    adapter.execute_ddl(ship_sql)

    return {
        "status": "seeded",
        "corruptions_injected": inject_corruptions,
        "tables": [
            "organisations", "users", "products", "customers", "orders",
            "order_items", "payments", "invoices", "audit_logs", "shipments"
        ]
    }
