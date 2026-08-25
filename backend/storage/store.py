"""
SQLite-backed storage for cases, evidence, traversal audit records, and persistent monitoring state.

WAL mode and foreign keys enabled.
Schema is flat for reliable forensic persistence.
"""

from __future__ import annotations
import json
import sqlite3
import datetime
import logging
from decimal import Decimal
from typing import Optional
from pathlib import Path

from ..core.models import utc_now

log = logging.getLogger(__name__)


class InvestigationStore:

    def __init__(self, db_path: str = "investigations.db"):
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS cases (
                case_id        TEXT PRIMARY KEY,
                complaint_ref  TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                state          TEXT NOT NULL,
                traceability   TEXT NOT NULL,
                actionability  TEXT NOT NULL,
                anchor_status  TEXT,
                anchor_level   TEXT,
                anchor_chain   TEXT,
                anchor_asset   TEXT,
                anchor_tx_hash TEXT,
                victim_value   TEXT,
                reported_wallet TEXT,
                snapshot_json  TEXT    -- latest serialized case snapshot for delta
            );

            CREATE TABLE IF NOT EXISTS branch_audit (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id          TEXT NOT NULL,
                from_address     TEXT,
                to_address       TEXT,
                tx_hash          TEXT,
                chain            TEXT,
                asset            TEXT,
                amount           TEXT,
                victim_lower     TEXT,
                victim_upper     TEXT,
                disposition      TEXT,
                reason           TEXT,
                tier             INTEGER,
                recorded_at      TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_records (
                record_id        TEXT PRIMARY KEY,
                case_id          TEXT NOT NULL,
                evidence_class   TEXT,
                chain            TEXT,
                tx_hash          TEXT,
                block_number     INTEGER,
                block_timestamp  TEXT,
                address          TEXT,
                data_source      TEXT,
                source_timestamp TEXT,
                raw_data_hash    TEXT,
                description      TEXT,
                assumptions_json TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS vasp_findings (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id          TEXT NOT NULL,
                address          TEXT,
                entity_name      TEXT,
                is_first_vasp    INTEGER,
                is_primary_vasp  INTEGER,
                stability        TEXT,
                stability_reason TEXT,
                actionability    TEXT,
                value_lower      TEXT,
                value_upper      TEXT,
                asset            TEXT,
                label_confidence TEXT,
                recorded_at      TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS case_snapshots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id          TEXT NOT NULL,
                snapshot_at      TEXT NOT NULL,
                snapshot_json    TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS case_watchers (
                case_id              TEXT PRIMARY KEY,
                chain                TEXT NOT NULL,
                address              TEXT NOT NULL,
                last_processed_block INTEGER NOT NULL DEFAULT 0,
                last_success_at      TEXT,
                next_retry_at        TEXT,
                failure_count        INTEGER NOT NULL DEFAULT 0,
                status               TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at           TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE INDEX IF NOT EXISTS idx_audit_case ON branch_audit(case_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence_records(case_id);
            CREATE INDEX IF NOT EXISTS idx_vasp_case ON vasp_findings(case_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_case ON case_snapshots(case_id);
            CREATE INDEX IF NOT EXISTS idx_watchers_status ON case_watchers(status);
        """)
        self._conn.commit()

    def save_case(
        self,
        case_id: str,
        complaint_ref: str,
        state: str,
        traceability: str,
        actionability: str,
        anchor_status: Optional[str],
        anchor_level: Optional[str],
        anchor_chain: Optional[str],
        anchor_asset: Optional[str],
        anchor_tx_hash: Optional[str],
        victim_value: Optional[str],
        reported_wallet: str,
        snapshot_json: Optional[str] = None,
    ) -> None:
        now = utc_now().isoformat()
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO cases (
                case_id, complaint_ref, created_at, updated_at,
                state, traceability, actionability,
                anchor_status, anchor_level, anchor_chain, anchor_asset, anchor_tx_hash,
                victim_value, reported_wallet, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                state = excluded.state,
                traceability = excluded.traceability,
                actionability = excluded.actionability,
                anchor_status = excluded.anchor_status,
                anchor_level = excluded.anchor_level,
                victim_value = excluded.victim_value,
                snapshot_json = COALESCE(excluded.snapshot_json, cases.snapshot_json)
        """, (
            case_id, complaint_ref, now, now,
            state, traceability, actionability,
            anchor_status, anchor_level, anchor_chain, anchor_asset, anchor_tx_hash,
            victim_value, reported_wallet, snapshot_json
        ))
        self._conn.commit()

    def get_case(self, case_id: str) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_cases(self) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM cases ORDER BY updated_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def save_branch_audit(self, case_id: str, records: list[dict]) -> None:
        cur = self._conn.cursor()
        for r in records:
            cur.execute("""
                INSERT INTO branch_audit (
                    case_id, from_address, to_address, tx_hash,
                    chain, asset, amount, victim_lower, victim_upper,
                    disposition, reason, tier, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                case_id, r.get("from_address"), r.get("to_address"), r.get("tx_hash"),
                r.get("chain"), r.get("asset"), r.get("amount"),
                r.get("victim_lower"), r.get("victim_upper"),
                r.get("disposition"), r.get("reason"), r.get("tier"),
                r.get("recorded_at", utc_now().isoformat())
            ))
        self._conn.commit()

    def get_branch_audit(self, case_id: str) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM branch_audit WHERE case_id = ? ORDER BY id ASC", (case_id,))
        return [dict(r) for r in cur.fetchall()]

    def save_snapshot(self, case_id: str, snapshot: dict) -> None:
        now = utc_now().isoformat()
        snap_json = json.dumps(snapshot)
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO case_snapshots (case_id, snapshot_at, snapshot_json)
            VALUES (?, ?, ?)
        """, (case_id, now, snap_json))
        cur.execute("""
            UPDATE cases SET snapshot_json = ?, updated_at = ? WHERE case_id = ?
        """, (snap_json, now, case_id))
        self._conn.commit()

    def get_latest_snapshot(self, case_id: str) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT snapshot_json FROM case_snapshots
            WHERE case_id = ? ORDER BY id DESC LIMIT 1
        """, (case_id,))
        row = cur.fetchone()
        if row and row["snapshot_json"]:
            return json.loads(row["snapshot_json"])
        return None

    def get_previous_snapshot(self, case_id: str) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT snapshot_json FROM case_snapshots
            WHERE case_id = ? ORDER BY id DESC LIMIT 1 OFFSET 1
        """, (case_id,))
        row = cur.fetchone()
        if row and row["snapshot_json"]:
            return json.loads(row["snapshot_json"])
        return None

    def save_evidence_records(self, case_id: str, records: list[dict]) -> None:
        cur = self._conn.cursor()
        for r in records:
            cur.execute("""
                INSERT OR REPLACE INTO evidence_records (
                    record_id, case_id, evidence_class, chain, tx_hash,
                    block_number, block_timestamp, address, data_source,
                    source_timestamp, raw_data_hash, description, assumptions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["record_id"], case_id, r.get("evidence_class"), r.get("chain"),
                r.get("tx_hash"), r.get("block_number"), r.get("block_timestamp"),
                r.get("address"), r.get("data_source"), r.get("source_timestamp"),
                r.get("raw_data_hash"), r.get("description"), r.get("assumptions_json")
            ))
        self._conn.commit()

    def get_evidence_records(self, case_id: str) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM evidence_records WHERE case_id = ?", (case_id,))
        return [dict(r) for r in cur.fetchall()]

    # -----------------------------------------------------------------------
    # Case Watcher Daemon Methods
    # -----------------------------------------------------------------------

    def register_watcher(self, case_id: str, chain: str, address: str, start_block: int = 0) -> None:
        now = utc_now().isoformat()
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO case_watchers (
                case_id, chain, address, last_processed_block, last_success_at,
                next_retry_at, failure_count, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 'ACTIVE', ?)
            ON CONFLICT(case_id) DO UPDATE SET
                chain = excluded.chain,
                address = excluded.address,
                status = 'ACTIVE'
        """, (case_id, chain, address, start_block, now, now, now))
        self._conn.commit()

    def get_active_watchers(self) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM case_watchers WHERE status = 'ACTIVE'")
        return [dict(r) for r in cur.fetchall()]

    def update_watcher_checkpoint(
        self, case_id: str, last_block: int, status: str = "ACTIVE", error: Optional[str] = None
    ) -> None:
        now = utc_now().isoformat()
        cur = self._conn.cursor()
        if error:
            cur.execute("""
                UPDATE case_watchers SET
                    failure_count = failure_count + 1,
                    status = ?,
                    next_retry_at = ?
                WHERE case_id = ?
            """, (status, now, case_id))
        else:
            cur.execute("""
                UPDATE case_watchers SET
                    last_processed_block = ?,
                    last_success_at = ?,
                    failure_count = 0,
                    status = 'ACTIVE'
                WHERE case_id = ?
            """, (last_block, now, case_id))
        self._conn.commit()
