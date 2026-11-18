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
