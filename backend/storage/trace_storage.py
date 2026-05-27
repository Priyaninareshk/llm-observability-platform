import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_observability.storage")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///traces.db")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TraceRecord:
    trace_id: str
    endpoint: str
    prompt: str
    response: str
    model_name: str
    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Cost
    prompt_cost: float = 0.0
    completion_cost: float = 0.0
    total_cost: float = 0.0
    # Latency (ms)
    latency_total_ms: float = 0.0
    latency_llm_ms: float = 0.0
    # Error info
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    # Hallucination
    faithfulness_score: Optional[float] = None
    faithfulness_label: Optional[str] = None
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Extra JSON blob for forward-compat
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chat_response(
        cls,
        trace_id: str,
        prompt: str,
        response_data: Dict[str, Any],
        endpoint: str = "/chat",
    ) -> "TraceRecord":
        lat = response_data.get("latency", {})
        tok = response_data.get("token_usage", {})
        cost = response_data.get("cost", {})
        return cls(
            trace_id=trace_id,
            endpoint=endpoint,
            prompt=prompt,
            response=response_data.get("response", ""),
            model_name=tok.get("model_name", "unknown"),
            prompt_tokens=tok.get("prompt_tokens", 0),
            completion_tokens=tok.get("completion_tokens", 0),
            total_tokens=tok.get("total_tokens", 0),
            prompt_cost=cost.get("prompt_cost", 0.0),
            completion_cost=cost.get("completion_cost", 0.0),
            total_cost=cost.get("total_cost", 0.0),
            latency_total_ms=lat.get("total_ms", 0.0),
            latency_llm_ms=lat.get("llm_ms", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["metadata"] = json.dumps(d["metadata"])
        return d


# ---------------------------------------------------------------------------
# Storage backend
# ---------------------------------------------------------------------------

class TraceStorage:
    """
    Thin persistence layer.  Uses SQLite by default; swap DATABASE_URL
    to a postgres DSN for TimescaleDB in production.
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS llm_traces (
        trace_id            TEXT PRIMARY KEY,
        endpoint            TEXT NOT NULL,
        prompt              TEXT,
        response            TEXT,
        model_name          TEXT,
        prompt_tokens       INTEGER DEFAULT 0,
        completion_tokens   INTEGER DEFAULT 0,
        total_tokens        INTEGER DEFAULT 0,
        prompt_cost         REAL    DEFAULT 0,
        completion_cost     REAL    DEFAULT 0,
        total_cost          REAL    DEFAULT 0,
        latency_total_ms    REAL    DEFAULT 0,
        latency_llm_ms      REAL    DEFAULT 0,
        error_type          TEXT,
        error_message       TEXT,
        faithfulness_score  REAL,
        faithfulness_label  TEXT,
        created_at          TEXT    NOT NULL,
        metadata            TEXT    DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_traces_created_at  ON llm_traces(created_at);
    CREATE INDEX IF NOT EXISTS idx_traces_model_name  ON llm_traces(model_name);
    CREATE INDEX IF NOT EXISTS idx_traces_faithfulness ON llm_traces(faithfulness_label);
    CREATE INDEX IF NOT EXISTS idx_traces_error_type  ON llm_traces(error_type);
    """

    def __init__(self, db_url: str = DATABASE_URL):
        self.db_url = db_url
        self._is_sqlite = db_url.startswith("sqlite")
        self._db_path = db_url.replace("sqlite:///", "") if self._is_sqlite else None
        self._init_db()

    def _init_db(self) -> None:
        if self._is_sqlite:
            with self._connect() as conn:
                for stmt in self.CREATE_TABLE_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
            logger.info("Trace storage initialised (SQLite: %s)", self._db_path)
        else:
            logger.info("Trace storage pointing at external DB: %s (schema must be applied separately)", self.db_url)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_trace(self, record: TraceRecord) -> str:
        """Persist a trace. Returns trace_id."""
        if not record.trace_id:
            record.trace_id = str(uuid.uuid4())

        d = record.to_dict()
        placeholders = ", ".join("?" * len(d))
        columns = ", ".join(d.keys())
        sql = f"INSERT OR REPLACE INTO llm_traces ({columns}) VALUES ({placeholders})"

        with self._connect() as conn:
            conn.execute(sql, list(d.values()))

        logger.debug("Trace saved: %s", record.trace_id)
        return record.trace_id

    def update_hallucination(
        self,
        trace_id: str,
        score: float,
        label: str,
    ) -> None:
        """Patch faithfulness fields after async scoring completes."""
        sql = """
        UPDATE llm_traces
        SET faithfulness_score = ?, faithfulness_label = ?
        WHERE trace_id = ?
        """
        with self._connect() as conn:
            conn.execute(sql, [score, label, trace_id])
        logger.debug("Hallucination updated for trace %s: %s (%.3f)", trace_id, label, score)

    # ------------------------------------------------------------------
    # Read (US-12 filtering is built on these)
    # ------------------------------------------------------------------

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM llm_traces WHERE trace_id = ?", [trace_id]
            ).fetchone()
        return dict(row) if row else None

    def list_traces(
        self,
        limit: int = 100,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        order_by: str = "created_at",
        order_dir: str = "DESC",
    ) -> List[Dict[str, Any]]:
        """
        Flexible listing – see QueryableTraceInterface for a higher-level API.
        filters keys: model_name, error_type, faithfulness_label,
                      min_latency_ms, max_latency_ms,
                      min_cost, max_cost,
                      start_time, end_time (ISO strings)
        """
        where_clauses, params = [], []
        filters = filters or {}

        for col in ("model_name", "error_type", "faithfulness_label", "endpoint"):
            if col in filters:
                where_clauses.append(f"{col} = ?")
                params.append(filters[col])

        if "min_latency_ms" in filters:
            where_clauses.append("latency_total_ms >= ?")
            params.append(filters["min_latency_ms"])
        if "max_latency_ms" in filters:
            where_clauses.append("latency_total_ms <= ?")
            params.append(filters["max_latency_ms"])
        if "min_cost" in filters:
            where_clauses.append("total_cost >= ?")
            params.append(filters["min_cost"])
        if "max_cost" in filters:
            where_clauses.append("total_cost <= ?")
            params.append(filters["max_cost"])
        if "start_time" in filters:
            where_clauses.append("created_at >= ?")
            params.append(filters["start_time"])
        if "end_time" in filters:
            where_clauses.append("created_at <= ?")
            params.append(filters["end_time"])
        if "has_error" in filters and filters["has_error"]:
            where_clauses.append("error_type IS NOT NULL")
        if "search" in filters:
            where_clauses.append("(prompt LIKE ? OR response LIKE ?)")
            pattern = f"%{filters['search']}%"
            params.extend([pattern, pattern])

        safe_dir = "DESC" if order_dir.upper() == "DESC" else "ASC"
        allowed_cols = {
            "created_at", "latency_total_ms", "total_cost",
            "total_tokens", "faithfulness_score",
        }
        safe_col = order_by if order_by in allowed_cols else "created_at"

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"""
        SELECT * FROM llm_traces
        {where_sql}
        ORDER BY {safe_col} {safe_dir}
        LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_traces(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Return total count matching filters using a SQL COUNT (no row loading)."""
        where_clauses, params = [], []
        filters = filters or {}

        for col in ("model_name", "error_type", "faithfulness_label", "endpoint"):
            if col in filters:
                where_clauses.append(f"{col} = ?")
                params.append(filters[col])

        if "min_latency_ms" in filters:
            where_clauses.append("latency_total_ms >= ?")
            params.append(filters["min_latency_ms"])
        if "max_latency_ms" in filters:
            where_clauses.append("latency_total_ms <= ?")
            params.append(filters["max_latency_ms"])
        if "min_cost" in filters:
            where_clauses.append("total_cost >= ?")
            params.append(filters["min_cost"])
        if "max_cost" in filters:
            where_clauses.append("total_cost <= ?")
            params.append(filters["max_cost"])
        if "start_time" in filters:
            where_clauses.append("created_at >= ?")
            params.append(filters["start_time"])
        if "end_time" in filters:
            where_clauses.append("created_at <= ?")
            params.append(filters["end_time"])
        if "has_error" in filters and filters["has_error"]:
            where_clauses.append("error_type IS NOT NULL")
        if "search" in filters:
            where_clauses.append("(prompt LIKE ? OR response LIKE ?)")
            pattern = f"%{filters['search']}%"
            params.extend([pattern, pattern])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT COUNT(*) FROM llm_traces {where_sql}"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def get_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                   AS total_traces,
                    AVG(latency_total_ms)      AS avg_latency_ms,
                    AVG(total_cost)            AS avg_cost,
                    SUM(total_tokens)          AS total_tokens,
                    SUM(total_cost)            AS total_cost,
                    COUNT(error_type)          AS total_errors,
                    AVG(faithfulness_score)    AS avg_faithfulness
                FROM llm_traces
            """).fetchone()
        return dict(row) if row else {}


# Singleton
trace_storage = TraceStorage()
