-- ============================================================================
-- Task Engine Schema for Aura's IDE
-- Persistent tasks that survive Docker restarts, browser closes, sleep cycles.
-- ============================================================================

-- Task table
DEFINE TABLE IF NOT EXISTS task SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS task_id            ON TABLE task TYPE string;
DEFINE FIELD IF NOT EXISTS goal               ON TABLE task TYPE string;
DEFINE FIELD IF NOT EXISTS status             ON TABLE task TYPE string
    DEFAULT "queued"
    ASSERT $value IN ["queued", "running", "paused", "waiting_approval", "complete", "failed"];
DEFINE FIELD IF NOT EXISTS current_step_index ON TABLE task TYPE int    DEFAULT 0;
DEFINE FIELD IF NOT EXISTS steps              ON TABLE task TYPE array  DEFAULT [];
DEFINE FIELD IF NOT EXISTS workspace_path     ON TABLE task TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS task_memory_namespace ON TABLE task TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS created_at         ON TABLE task TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at         ON TABLE task TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS completed_at       ON TABLE task TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS resonance_scores   ON TABLE task TYPE array  DEFAULT [];
DEFINE FIELD IF NOT EXISTS blocker            ON TABLE task TYPE option<string>;
DEFINE FIELD IF NOT EXISTS blocker_info       ON TABLE task TYPE option<object>;
DEFINE FIELD IF NOT EXISTS file_annotations   ON TABLE task TYPE object DEFAULT {};
DEFINE FIELD IF NOT EXISTS file_versions      ON TABLE task TYPE object DEFAULT {};

-- Indexes for fast lookups
DEFINE INDEX IF NOT EXISTS idx_task_status ON TABLE task COLUMNS status;
DEFINE INDEX IF NOT EXISTS idx_task_created ON TABLE task COLUMNS created_at;
DEFINE INDEX IF NOT EXISTS idx_task_namespace ON TABLE task COLUMNS task_memory_namespace;

-- Memory namespace extension: add optional namespace field to existing memory table
-- This allows task-scoped memories without changing the core retrieval weights
DEFINE FIELD IF NOT EXISTS namespace ON TABLE memory TYPE option<string>;
DEFINE INDEX IF NOT EXISTS idx_memory_namespace ON TABLE memory COLUMNS namespace;

-- ============================================================================
-- Task graphs (P2-08): a plan of research / think / code nodes.
-- Nothing executes from these tables until the scheduler cards (P2-09/10).
-- ============================================================================

DEFINE TABLE IF NOT EXISTS task_graph SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS goal             ON TABLE task_graph TYPE string;
DEFINE FIELD IF NOT EXISTS status           ON TABLE task_graph TYPE string DEFAULT "planned"
    ASSERT $value IN ["planned", "running", "done", "partial", "failed", "over_budget", "interrupted", "cancelled"];
DEFINE FIELD IF NOT EXISTS budget_usd       ON TABLE task_graph TYPE float DEFAULT 0;
DEFINE FIELD IF NOT EXISTS budget_minutes   ON TABLE task_graph TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS spent_usd        ON TABLE task_graph TYPE float DEFAULT 0;
DEFINE FIELD IF NOT EXISTS created_by_turn  ON TABLE task_graph TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created_at       ON TABLE task_graph TYPE datetime;
DEFINE FIELD IF NOT EXISTS updated_at       ON TABLE task_graph TYPE datetime;

DEFINE TABLE IF NOT EXISTS task_node SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS graph            ON TABLE task_node TYPE record<task_graph>;
DEFINE FIELD IF NOT EXISTS node_id          ON TABLE task_node TYPE string;
DEFINE FIELD IF NOT EXISTS kind             ON TABLE task_node TYPE string
    ASSERT $value IN ["research", "think", "code"];
DEFINE FIELD IF NOT EXISTS brief            ON TABLE task_node TYPE string;
DEFINE FIELD IF NOT EXISTS success_criteria ON TABLE task_node TYPE string;
DEFINE FIELD IF NOT EXISTS depends_on       ON TABLE task_node TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS budget_share     ON TABLE task_node TYPE float DEFAULT 1.0;
DEFINE FIELD IF NOT EXISTS status           ON TABLE task_node TYPE string DEFAULT "pending"
    ASSERT $value IN ["pending", "running", "done", "failed", "skipped", "interrupted", "ready_to_merge"];
DEFINE FIELD IF NOT EXISTS report           ON TABLE task_node TYPE option<string>;
DEFINE FIELD IF NOT EXISTS artifacts        ON TABLE task_node TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS created_at       ON TABLE task_node TYPE datetime;
DEFINE FIELD IF NOT EXISTS updated_at       ON TABLE task_node TYPE datetime;
DEFINE INDEX IF NOT EXISTS idx_task_node_graph ON TABLE task_node COLUMNS graph;

DEFINE TABLE IF NOT EXISTS blackboard_entry SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS graph            ON TABLE blackboard_entry TYPE record<task_graph>;
DEFINE FIELD IF NOT EXISTS node             ON TABLE blackboard_entry TYPE option<record<task_node>>;
DEFINE FIELD IF NOT EXISTS kind             ON TABLE blackboard_entry TYPE string;
DEFINE FIELD IF NOT EXISTS content          ON TABLE blackboard_entry TYPE string;
DEFINE FIELD IF NOT EXISTS refs             ON TABLE blackboard_entry TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS created_at       ON TABLE blackboard_entry TYPE datetime;
DEFINE INDEX IF NOT EXISTS idx_blackboard_graph ON TABLE blackboard_entry COLUMNS graph;
