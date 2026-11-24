-- Behaviour schema (B1-01). Idempotent.
USE NS aura DB main;

DEFINE TABLE IF NOT EXISTS autonomy_control SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS level ON autonomy_control TYPE string;
DEFINE FIELD IF NOT EXISTS muted_kinds ON autonomy_control TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS killed ON autonomy_control TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS killed_at ON autonomy_control TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS updated_at ON autonomy_control TYPE datetime;

DEFINE TABLE IF NOT EXISTS autonomy_trace SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS source ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS action ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS why ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS cost ON autonomy_trace TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD IF NOT EXISTS refs ON autonomy_trace TYPE array DEFAULT [];
DEFINE FIELD IF NOT EXISTS at ON autonomy_trace TYPE datetime;
DEFINE FIELD IF NOT EXISTS allowed ON autonomy_trace TYPE bool;
DEFINE INDEX IF NOT EXISTS autonomy_trace_at ON autonomy_trace FIELDS at;

-- Agenda (B1-02)
DEFINE TABLE IF NOT EXISTS agenda_item SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS kind ON agenda_item TYPE string
    ASSERT $value IN ['finding', 'task_done', 'needs_decision', 'question_for_you', 'reminder', 'observation'];
DEFINE FIELD IF NOT EXISTS content ON agenda_item TYPE string;
DEFINE FIELD IF NOT EXISTS refs ON agenda_item TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS priority ON agenda_item TYPE float DEFAULT 0.5;
DEFINE FIELD IF NOT EXISTS venue ON agenda_item TYPE string DEFAULT 'app';
DEFINE FIELD IF NOT EXISTS created_at ON agenda_item TYPE datetime;
DEFINE FIELD IF NOT EXISTS expires_at ON agenda_item TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS state ON agenda_item TYPE string DEFAULT 'pending'
    ASSERT $value IN ['pending', 'delivered', 'acknowledged', 'dismissed', 'expired'];
DEFINE FIELD IF NOT EXISTS delivered_at ON agenda_item TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS resolved_at ON agenda_item TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS source ON agenda_item TYPE string DEFAULT '';
DEFINE FIELD IF NOT EXISTS due_at ON agenda_item TYPE option<datetime>;
DEFINE INDEX IF NOT EXISTS agenda_item_state ON agenda_item FIELDS state;

-- Goals v2 (B3-01): optional fields so existing goal rows still load.
DEFINE FIELD IF NOT EXISTS criteria ON goal TYPE option<array<object>> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS abandon_reason ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS last_evidence_at ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS evidence ON goal TYPE option<array<object>> FLEXIBLE;

-- Drives (B2-01): singleton drive_state:main
DEFINE TABLE IF NOT EXISTS drive_state SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS curiosity ON drive_state TYPE float DEFAULT 0.3;
DEFINE FIELD IF NOT EXISTS competence ON drive_state TYPE float DEFAULT 0.3;
DEFINE FIELD IF NOT EXISTS connection ON drive_state TYPE float DEFAULT 0.3;
DEFINE FIELD IF NOT EXISTS coherence ON drive_state TYPE float DEFAULT 0.3;
DEFINE FIELD IF NOT EXISTS rest ON drive_state TYPE float DEFAULT 0.3;
DEFINE FIELD IF NOT EXISTS updated_at ON drive_state TYPE datetime;

-- Goal evidence (B3-02): set true on a task whose tests passed (test_pass criteria).
DEFINE FIELD IF NOT EXISTS tests_passed ON task TYPE option<bool>;
