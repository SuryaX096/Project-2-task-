"""Database abstraction interface and drivers (SQLite, DuckDB, ClickHouse-ready, Mock)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import sqlite3
import time


class DatabaseAdapter(ABC):
    """Abstract interface for database engines."""

    @abstractmethod
    def execute_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Execute a query that returns a single aggregate scalar integer count.
        
        ENFORCEMENT: Never returns raw rows. Only count integers.
        """
        pass

    @abstractmethod
    def execute_ddl(self, sql: str) -> None:
        """Execute table creation, insertion, or maintenance DDL/DML."""
        pass

    @abstractmethod
    def list_tables(self) -> List[str]:
        """List tables in the database."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connection."""
        pass


class SQLiteAdapter(DatabaseAdapter):
    """In-memory or file-backed SQLite database adapter for lightning-fast testing without external DBs."""

    def __init__(self, connection_string: str = ":memory:"):
        self.connection_string = connection_string
        self.conn = sqlite3.connect(connection_string, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def execute_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        cursor = self.conn.cursor()
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            row = cursor.fetchone()
            if row is None:
                return 0
            val = row[0]
            return int(val) if val is not None else 0
        finally:
            cursor.close()

    def execute_ddl(self, sql: str) -> None:
        cursor = self.conn.cursor()
        try:
            cursor.executescript(sql)
            self.conn.commit()
        finally:
            cursor.close()

    def list_tables(self) -> List[str]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            rows = cursor.fetchall()
            return [r[0] for r in rows]
        finally:
            cursor.close()

    def close(self) -> None:
        self.conn.close()


class DuckDBAdapter(DatabaseAdapter):
    """DuckDB adapter supporting OLAP analytical queries (ClickHouse-like dialect)."""

    def __init__(self, path: str = ":memory:"):
        import duckdb
        self.path = path
        self.conn = duckdb.connect(path)

    def execute_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        try:
            res = self.conn.execute(sql).fetchone()
            if res is None:
                return 0
            val = res[0]
            return int(val) if val is not None else 0
        except Exception as e:
            raise RuntimeError(f"DuckDB query execution failed: {e}\nSQL: {sql}") from e

    def execute_ddl(self, sql: str) -> None:
        self.conn.execute(sql)

    def list_tables(self) -> List[str]:
        res = self.conn.execute("SHOW TABLES").fetchall()
        return [r[0] for r in res]

    def close(self) -> None:
        self.conn.close()


class MockDatabaseAdapter(DatabaseAdapter):
    """Pure mock database adapter for zero-overhead unit testing with controlled return counts."""

    def __init__(self, table_names: Optional[List[str]] = None, return_values: Optional[Dict[str, int]] = None):
        self.table_names = table_names or []
        self.return_values = return_values or {}
        self.executed_queries: List[str] = []
        self.default_return: int = 0

    def execute_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        self.executed_queries.append(sql)
        for key, val in self.return_values.items():
            if key.lower() in sql.lower():
                return val
        return self.default_return

    def execute_ddl(self, sql: str) -> None:
        self.executed_queries.append(sql)

    def list_tables(self) -> List[str]:
        return list(self.table_names)

    def close(self) -> None:
        pass


class ClickHouseAdapter(DatabaseAdapter):
    """Production ClickHouse adapter using HTTP / native client when clickhouse-connect is available."""

    def __init__(self, host: str = "localhost", port: int = 8123, username: str = "default", password: str = "", database: str = "default"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            import clickhouse_connect
            self.client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                database=self.database
            )
        except ImportError:
            # Fallback mock/simulated connection message if driver not installed in env
            self.client = None

    def execute_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        if self.client is None:
            raise RuntimeError("clickhouse-connect is not installed or ClickHouse server is unreachable.")
        res = self.client.command(sql)
        if isinstance(res, (int, float)):
            return int(res)
        if isinstance(res, list) and len(res) > 0:
            return int(res[0])
        return 0

    def execute_ddl(self, sql: str) -> None:
        if self.client is None:
            raise RuntimeError("clickhouse-connect is not installed.")
        self.client.command(sql)

    def list_tables(self) -> List[str]:
        if self.client is None:
            return []
        res = self.client.query("SHOW TABLES").result_rows
        return [r[0] for r in res]

    def close(self) -> None:
        if self.client:
            self.client.close()
