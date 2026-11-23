"""Task graph storage (P2-08). Persistence only; the scheduler is P2-09/10."""

import logging
from typing import Any
from uuid import uuid4

from surrealdb import RecordID

from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows
from aura.models.task_graph import (
    BlackboardEntry,
    GraphStatus,
    NodeStatus,
    TaskGraph,
    TaskNode,
)

logger = logging.getLogger(__name__)


def _rid(value: Any) -> RecordID:
    """A 'table:id' string as a RecordID; a RecordID passes through."""
    if isinstance(value, RecordID):
        return value
    table, _, ident = str(value).partition(":")
    return RecordID(table, ident)


def _rid_str(value: Any) -> str:
    if isinstance(value, RecordID):
        return f"{value.table_name}:{value.id}"
    return str(value)


def _node_rid(graph_id: Any, node_id: str) -> RecordID:
    return RecordID("task_node", f"{_rid(graph_id).id}_{node_id}")


def _to_graph(row: dict[str, Any]) -> TaskGraph:
    data = dict(row)
    data["id"] = _rid_str(data.get("id", ""))
    return TaskGraph(**data)


def _to_node(row: dict[str, Any]) -> TaskNode:
    return TaskNode(
        id=row["node_id"],
        graph=_rid_str(row["graph"]),
        kind=row["kind"],
        brief=row["brief"],
        success_criteria=row["success_criteria"],
        depends_on=list(row.get("depends_on") or []),
        budget_share=row.get("budget_share", 1.0),
        status=row.get("status", "pending"),
        report=row.get("report"),
        transcript=row.get("transcript"),
        artifacts=list(row.get("artifacts") or []),
    )


class TaskGraphStore:
    """SurrealDB-backed store for task graphs, nodes and the blackboard."""

    def __init__(self, db: Any = None) -> None:
        self.db = db if db is not None else get_db_client()

    async def create_graph(
        self,
        goal: str,
        nodes: list[TaskNode],
        budget_usd: float,
        budget_minutes: int,
        created_by_turn: str | None = None,
    ) -> TaskGraph:
        """Store a planned graph and its nodes; returns the graph with its id."""
        now = get_clock().now()
        graph_rid = RecordID("task_graph", uuid4().hex[:12])
        await self.db.query(
            "CREATE $rid CONTENT $data",
            {
                "rid": graph_rid,
                "data": {
                    "goal": goal,
                    "status": GraphStatus.PLANNED.value,
                    "budget_usd": float(budget_usd),
                    "budget_minutes": int(budget_minutes),
                    "spent_usd": 0.0,
                    "created_by_turn": created_by_turn,
                    "created_at": now,
                    "updated_at": now,
                },
            },
        )
        for node in nodes:
            await self.db.query(
                "CREATE $rid CONTENT $data",
                {
                    "rid": _node_rid(graph_rid, node.id),
                    "data": {
                        "graph": graph_rid,
                        "node_id": node.id,
                        "kind": node.kind,
                        "brief": node.brief,
                        "success_criteria": node.success_criteria,
                        "depends_on": list(node.depends_on),
                        "budget_share": float(node.budget_share),
                        "status": NodeStatus.PENDING.value,
                        "report": None,
                        "artifacts": [],
                        "created_at": now,
                        "updated_at": now,
                    },
                },
            )
        graph = await self.get_graph(_rid_str(graph_rid))
        if graph is None:
            raise RuntimeError("task graph was not stored")
        return graph

    async def get_graph(self, graph_id: str) -> TaskGraph | None:
        rows = extract_rows(await self.db.query("SELECT * FROM $rid", {"rid": _rid(graph_id)}))
        return _to_graph(rows[0]) if rows else None

    async def list_nodes(self, graph_id: str) -> list[TaskNode]:
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM task_node WHERE graph = $graph ORDER BY created_at ASC, node_id ASC",
                {"graph": _rid(graph_id)},
            )
        )
        return [_to_node(r) for r in rows]

    async def update_node_status(
        self,
        graph_id: str,
        node_id: str,
        status: NodeStatus,
        report: str | None = None,
        artifacts: list[str] | None = None,
        transcript: str | None = None,
    ) -> None:
        """Set a node's status; report, artifacts and transcript only when given."""
        sets = ["status = $status", "updated_at = $now"]
        params: dict[str, Any] = {
            "rid": _node_rid(graph_id, node_id),
            "status": NodeStatus(status).value,
            "now": get_clock().now(),
        }
        if report is not None:
            sets.append("report = $report")
            params["report"] = report
        if artifacts is not None:
            sets.append("artifacts = $artifacts")
            params["artifacts"] = list(artifacts)
        if transcript is not None:
            sets.append("transcript = $transcript")
            params["transcript"] = transcript
        await self.db.query(f"UPDATE $rid SET {', '.join(sets)}", params)

    async def update_graph(
        self,
        graph_id: str,
        status: GraphStatus | None = None,
        spent_usd: float | None = None,
    ) -> None:
        """Set a graph's status and/or spent_usd (P2-09)."""
        sets = ["updated_at = $now"]
        params: dict[str, Any] = {"rid": _rid(graph_id), "now": get_clock().now()}
        if status is not None:
            sets.append("status = $status")
            params["status"] = GraphStatus(status).value
        if spent_usd is not None:
            sets.append("spent_usd = $spent")
            params["spent"] = float(spent_usd)
        await self.db.query(f"UPDATE $rid SET {', '.join(sets)}", params)

    async def list_graphs(self, status: GraphStatus) -> list[TaskGraph]:
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM task_graph WHERE status = $status",
                {"status": GraphStatus(status).value},
            )
        )
        return [_to_graph(r) for r in rows]

    async def recover_interrupted_graphs(self) -> list[TaskGraph]:
        """Boot recovery (P2-09): running graphs and their running nodes become interrupted."""
        graphs = await self.list_graphs(GraphStatus.RUNNING)
        for graph in graphs:
            for node in await self.list_nodes(graph.id):
                if node.status == NodeStatus.RUNNING.value:
                    await self.update_node_status(graph.id, node.id, NodeStatus.INTERRUPTED)
            await self.update_graph(graph.id, status=GraphStatus.INTERRUPTED)
        return graphs

    async def write_blackboard(
        self,
        graph_id: str,
        kind: str,
        content: str,
        node_id: str | None = None,
        refs: list[str] | None = None,
    ) -> BlackboardEntry:
        now = get_clock().now()
        graph_rid = _rid(graph_id)
        node_rid = _node_rid(graph_rid, node_id) if node_id else None
        await self.db.query(
            "CREATE blackboard_entry:ulid() CONTENT $data",
            {
                "data": {
                    "graph": graph_rid,
                    "node": node_rid,
                    "kind": kind,
                    "content": content,
                    "refs": list(refs or []),
                    "created_at": now,
                }
            },
        )
        return BlackboardEntry(
            graph=_rid_str(graph_rid),
            node=_rid_str(node_rid) if node_rid else None,
            kind=kind,
            content=content,
            refs=list(refs or []),
            created_at=now,
        )

    async def list_blackboard(self, graph_id: str) -> list[BlackboardEntry]:
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM blackboard_entry WHERE graph = $graph ORDER BY created_at ASC, id ASC",
                {"graph": _rid(graph_id)},
            )
        )
        return [
            BlackboardEntry(
                graph=_rid_str(r["graph"]),
                node=_rid_str(r["node"]) if r.get("node") else None,
                kind=r["kind"],
                content=r["content"],
                refs=list(r.get("refs") or []),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]


_store: TaskGraphStore | None = None


def get_task_graph_store() -> TaskGraphStore:
    """The global TaskGraphStore singleton."""
    global _store
    if _store is None:
        _store = TaskGraphStore()
    return _store
