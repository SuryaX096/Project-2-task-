"""Zero-dependency HTTP Dashboard Server for the Data Quality Framework.
Runs on http://localhost:8080 without external web framework requirements.
"""
from __future__ import annotations
import http.server
import socketserver
import json
import urllib.parse
from pathlib import Path
from dq_framework.database import SQLiteAdapter, DuckDBAdapter
from dq_framework.discovery import TestDiscovery
from dq_framework.engine import ExecutionEngine
from dq_framework.multi_tenancy import MultiTenancyGuardSuite
from dq_framework.reporter import Reporter
from dq_framework.fixtures import seed_synthetic_data

PORT = 8080

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data Quality & Testing Framework Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --critical: #dc2626;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 24px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .title h1 { font-size: 24px; font-weight: 700; }
    .title p { color: var(--text-muted); font-size: 14px; margin-top: 4px; }
    .controls {
      display: flex;
      gap: 12px;
      align-items: center;
    }
    button {
      padding: 10px 18px;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      font-size: 14px;
      transition: all 0.2s;
    }
    .btn-run-corrupt {
      background: var(--danger);
      color: white;
    }
    .btn-run-corrupt:hover { background: #b91c1c; }
    .btn-run-clean {
      background: var(--success);
      color: white;
    }
    .btn-run-clean:hover { background: #059669; }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }
    .stat-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }
    .stat-val { font-size: 28px; font-weight: 700; margin-top: 6px; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 700;
    }
    .badge-halted { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }
    .badge-passed { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; }
    .badge-pass { color: var(--success); }
    .badge-fail { color: var(--danger); font-weight: bold; }
    .badge-sev-critical { color: #fca5a5; font-weight: bold; }
    .badge-sev-error { color: #f87171; }
    .badge-sev-warning { color: #fbbf24; }
    .table-container {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 13px;
    }
    th {
      background: #0f172a;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      color: var(--text-muted);
      font-weight: 600;
    }
    td {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }
    tr:hover { background: rgba(255, 255, 255, 0.02); }
    .query-code {
      font-family: monospace;
      font-size: 11px;
      color: #93c5fd;
      background: rgba(0,0,0,0.3);
      padding: 4px 8px;
      border-radius: 4px;
      display: inline-block;
      max-width: 480px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .pii-safe-banner {
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.3);
      padding: 10px 16px;
      border-radius: 6px;
      font-size: 13px;
      color: #bfdbfe;
      margin-bottom: 20px;
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <h1>Data Quality & Multi-Tenancy Guard Suite</h1>
      <p>10-Table Relational Multi-Tenant Data Testing Framework (Strict Count-Only Aggregation)</p>
    </div>
    <div class="controls">
      <button class="btn-run-corrupt" onclick="runSuite(true)">Simulate Planted Corruptions</button>
      <button class="btn-run-clean" onclick="runSuite(false)">Run Against Clean Ingestion</button>
    </div>
  </div>

  <div class="pii-safe-banner">
    🔒 <strong>Zero PII Leakage Guarantee:</strong> All assertion queries are compiled into aggregate scalar scalar count statements. No customer emails, names, or raw rows are ever read or transmitted.
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Pipeline Status</div>
      <div class="stat-val" id="stat-status">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Tests Executed</div>
      <div class="stat-val" id="stat-total">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Passed Assertions</div>
      <div class="stat-val" style="color: var(--success);" id="stat-passed">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Violations Caught</div>
      <div class="stat-val" style="color: var(--danger);" id="stat-failed">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Suite Latency</div>
      <div class="stat-val" id="stat-time">-</div>
    </div>
  </div>

  <div class="table-container">
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Severity</th>
          <th>Table</th>
          <th>Rule Name</th>
          <th>Violations</th>
          <th>Latency (ms)</th>
          <th>Aggregate Query Executed (PII-Safe)</th>
        </tr>
      </thead>
      <tbody id="results-tbody">
        <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 32px;">Click one of the buttons above to run the suite.</td></tr>
      </tbody>
    </table>
  </div>

  <script>
    async function runSuite(injectCorruptions) {
      document.getElementById('results-tbody').innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 24px;">Executing quality assertions across 10 normalized tables...</td></tr>';
      
      const res = await fetch('/api/run?corruptions=' + injectCorruptions);
      const data = await res.json();
      const s = data.summary;

      document.getElementById('stat-status').innerHTML = s.pipeline_halted 
        ? '<span class="badge badge-halted">HALTED / BLOCKED</span>' 
        : '<span class="badge badge-passed">PASSED</span>';
      document.getElementById('stat-total').innerText = s.total_tests;
      document.getElementById('stat-passed').innerText = s.passed_tests;
      document.getElementById('stat-failed').innerText = s.failed_tests;
      document.getElementById('stat-time').innerText = s.total_duration_ms.toFixed(2) + ' ms';

      const tbody = document.getElementById('results-tbody');
      tbody.innerHTML = '';

      data.results.forEach(r => {
        const tr = document.createElement('tr');
        const statusHtml = r.passed 
          ? '<span class="badge-pass">PASS</span>' 
          : '<span class="badge-fail">FAIL</span>';
        
        let sevClass = 'badge-sev-error';
        if (r.severity === 'CRITICAL') sevClass = 'badge-sev-critical';
        if (r.severity === 'WARNING') sevClass = 'badge-sev-warning';

        tr.innerHTML = `
          <td>${statusHtml}</td>
          <td class="${sevClass}">${r.severity}</td>
          <td><strong>${r.table}</strong></td>
          <td>${r.rule_name}</td>
          <td style="color: ${r.failed_count > 0 ? 'var(--danger)' : 'inherit'}; font-weight: ${r.failed_count > 0 ? '700' : 'normal'}">${r.failed_count}</td>
          <td>${r.execution_time_ms.toFixed(2)}</td>
          <td><span class="query-code" title="${r.query_executed}">${r.query_executed}</span></td>
        `;
        tbody.appendChild(tr);
      });
    }

    // Auto load corrupted run on load
    window.addEventListener('DOMContentLoaded', () => runSuite(true));
  </script>
</body>
</html>
"""

def execute_run(inject_corruptions: bool = True) -> dict:
    adapter = SQLiteAdapter(":memory:")
    seed_synthetic_data(adapter, inject_corruptions=inject_corruptions)
    declarations, _ = TestDiscovery.discover_tests("config/rules")
    
    table_configs = {
        "organisations": {"primary_key": "organisation_id"},
        "users": {"primary_key": "user_id"},
        "products": {"primary_key": "product_id"},
        "customers": {"primary_key": "customer_id"},
        "orders": {"primary_key": "order_id"},
        "order_items": {"primary_key": "item_id"},
        "payments": {"primary_key": "payment_id"},
        "invoices": {"primary_key": "invoice_id"},
        "audit_logs": {"primary_key": "log_id"},
        "shipments": {"primary_key": "shipment_id"},
    }
    relationships = [
        {"child_table": "invoices", "parent_table": "orders", "join_key": "order_id"},
        {"child_table": "order_items", "parent_table": "orders", "join_key": "order_id"},
        {"child_table": "shipments", "parent_table": "orders", "join_key": "order_id"},
    ]
    reconciliations = [
        {"source_table": "orders", "target_table": "staging_orders", "max_allowed_diff": 0}
    ]
    auto_guards = MultiTenancyGuardSuite.generate_suite_for_dataset(
        table_configs=table_configs,
        relationships=relationships,
        reconciliations=reconciliations
    )
    all_decls = auto_guards + declarations
    engine = ExecutionEngine(adapter)
    summary = engine.execute_suite(all_decls)
    report = Reporter.to_json_report(summary)
    adapter.close()
    return report


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif parsed.path == "/api/run":
            query = urllib.parse.parse_qs(parsed.query)
            inject_corrupt = query.get("corruptions", ["true"])[0].lower() == "true"
            data = execute_run(inject_corruptions=inject_corrupt)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence raw access logs
        return


def start_server():
    server = socketserver.TCPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"[SERVER] Data Quality Framework Dashboard running at: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.server_close()


if __name__ == "__main__":
    start_server()
