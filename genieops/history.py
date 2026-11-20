"""Persistência local em SQLite (history.db) para execuções de benchmark e análise de regressão."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkItemResult:
    case_id: str
    question: str
    domain: str
    difficulty: str
    mode: str
    status: str  # GOOD | BAD | NEEDS_REVIEW | EXCLUDED
    semantic_score: float
    result_match: bool | None = None
    expected_sql: str | None = None
    generated_sql: str | None = None
    latency_ms: float = 0.0
    error_message: str | None = None
    details: list[str] = field(default_factory=list)


@dataclass
class BenchmarkRunRecord:
    run_id: str
    space_name: str
    env: str
    mode: str
    created_at: str
    total: int
    passed: int
    failed: int
    needs_review: int
    excluded: int
    accuracy_pct: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    config_hash: str
    items: list[BenchmarkItemResult] = field(default_factory=list)


@dataclass
class RegressionDiff:
    previous_run_id: str
    current_run_id: str
    previous_accuracy: float
    current_accuracy: float
    delta_accuracy: float
    fixed: list[str] = field(default_factory=list)       # BAD -> GOOD
    regressed: list[str] = field(default_factory=list)   # GOOD -> BAD
    unchanged: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    removed_cases: list[str] = field(default_factory=list)
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return round(ordered[f], 2)
    return round(ordered[f] + (ordered[c] - ordered[f]) * (k - f), 2)


class HistoryStore:
    """Armazena histórico de benchmarks em SQLite WAL para rastrear evolução e regressões."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (Path.cwd() / ".genieops" / "history.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    space_name TEXT NOT NULL,
                    env TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    needs_review INTEGER NOT NULL,
                    excluded INTEGER NOT NULL,
                    accuracy_pct REAL NOT NULL,
                    avg_latency_ms REAL NOT NULL,
                    p50_latency_ms REAL NOT NULL,
                    p95_latency_ms REAL NOT NULL,
                    config_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS benchmark_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    semantic_score REAL NOT NULL,
                    result_match INTEGER,
                    expected_sql TEXT,
                    generated_sql TEXT,
                    latency_ms REAL NOT NULL,
                    error_message TEXT,
                    details_json TEXT,
                    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_runs_space_created
                    ON benchmark_runs(space_name, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_results_run
                    ON benchmark_results(run_id);
                """
            )

    def save_run(self, record: BenchmarkRunRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO benchmark_runs (
                    run_id, space_name, env, mode, created_at,
                    total, passed, failed, needs_review, excluded,
                    accuracy_pct, avg_latency_ms, p50_latency_ms, p95_latency_ms, config_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.space_name,
                    record.env,
                    record.mode,
                    record.created_at,
                    record.total,
                    record.passed,
                    record.failed,
                    record.needs_review,
                    record.excluded,
                    record.accuracy_pct,
                    record.avg_latency_ms,
                    record.p50_latency_ms,
                    record.p95_latency_ms,
                    record.config_hash,
                ),
            )
            for item in record.items:
                conn.execute(
                    """
                    INSERT INTO benchmark_results (
                        run_id, case_id, question, domain, difficulty, mode,
                        status, semantic_score, result_match, expected_sql,
                        generated_sql, latency_ms, error_message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        item.case_id,
                        item.question,
                        item.domain,
                        item.difficulty,
                        item.mode,
                        item.status,
                        item.semantic_score,
                        None if item.result_match is None else int(item.result_match),
                        item.expected_sql,
                        item.generated_sql,
                        item.latency_ms,
                        item.error_message,
                        json.dumps(item.details, ensure_ascii=False),
                    ),
                )

    def list_runs(self, space_name: str, limit: int = 20) -> list[BenchmarkRunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM benchmark_runs
                WHERE space_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (space_name, limit),
            ).fetchall()
        return [self._row_to_run(r, []) for r in rows]

    def get_run(self, run_id: str) -> BenchmarkRunRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            item_rows = conn.execute(
                "SELECT * FROM benchmark_results WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        items = [self._row_to_item(ir) for ir in item_rows]
        return self._row_to_run(row, items)

    def get_latest_run(self, space_name: str) -> BenchmarkRunRecord | None:
        runs = self.list_runs(space_name, limit=1)
        if not runs:
            return None
        return self.get_run(runs[0].run_id)

    def get_previous_run(self, space_name: str, current_run_id: str) -> BenchmarkRunRecord | None:
        runs = self.list_runs(space_name, limit=10)
        for idx, run in enumerate(runs):
            if run.run_id == current_run_id and idx + 1 < len(runs):
                return self.get_run(runs[idx + 1].run_id)
        return None

    def compare_runs(self, prev_run: BenchmarkRunRecord, curr_run: BenchmarkRunRecord) -> RegressionDiff:
        prev_map = {it.case_id: it.status for it in prev_run.items}
        curr_map = {it.case_id: it.status for it in curr_run.items}

        fixed: list[str] = []
        regressed: list[str] = []
        unchanged: list[str] = []
        new_cases: list[str] = []
        removed_cases: list[str] = []

        for cid, c_status in curr_map.items():
            if cid not in prev_map:
                new_cases.append(cid)
            else:
                p_status = prev_map[cid]
                if p_status == "BAD" and c_status == "GOOD":
                    fixed.append(cid)
                elif p_status == "GOOD" and c_status == "BAD":
                    regressed.append(cid)
                else:
                    unchanged.append(cid)

        for cid in prev_map:
            if cid not in curr_map:
                removed_cases.append(cid)

        return RegressionDiff(
            previous_run_id=prev_run.run_id,
            current_run_id=curr_run.run_id,
            previous_accuracy=prev_run.accuracy_pct,
            current_accuracy=curr_run.accuracy_pct,
            delta_accuracy=round(curr_run.accuracy_pct - prev_run.accuracy_pct, 2),
            fixed=sorted(fixed),
            regressed=sorted(regressed),
            unchanged=sorted(unchanged),
            new_cases=sorted(new_cases),
            removed_cases=sorted(removed_cases),
            p50_latency_ms=curr_run.p50_latency_ms,
            p95_latency_ms=curr_run.p95_latency_ms,
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row, items: list[BenchmarkItemResult]) -> BenchmarkRunRecord:
        return BenchmarkRunRecord(
            run_id=row["run_id"],
            space_name=row["space_name"],
            env=row["env"],
            mode=row["mode"],
            created_at=row["created_at"],
            total=row["total"],
            passed=row["passed"],
            failed=row["failed"],
            needs_review=row["needs_review"],
            excluded=row["excluded"],
            accuracy_pct=row["accuracy_pct"],
            avg_latency_ms=row["avg_latency_ms"],
            p50_latency_ms=row["p50_latency_ms"],
            p95_latency_ms=row["p95_latency_ms"],
            config_hash=row["config_hash"],
            items=items,
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> BenchmarkItemResult:
        details_raw = row["details_json"]
        details: list[Any] = json.loads(details_raw) if details_raw else []
        rm = row["result_match"]
        return BenchmarkItemResult(
            case_id=row["case_id"],
            question=row["question"],
            domain=row["domain"],
            difficulty=row["difficulty"],
            mode=row["mode"],
            status=row["status"],
            semantic_score=row["semantic_score"],
            result_match=None if rm is None else bool(rm),
            expected_sql=row["expected_sql"],
            generated_sql=row["generated_sql"],
            latency_ms=row["latency_ms"],
            error_message=row["error_message"],
            details=[str(d) for d in details],
        )


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
