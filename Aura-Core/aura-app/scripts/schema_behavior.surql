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

-- Goals v3 (P2-31): stage and the crystal checklist. All option<...>: the goal table has rows.
-- (The legacy `origin` string is kept; the typed lineage is `origin_link`.)
DEFINE FIELD IF NOT EXISTS stage ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS stage_changed ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS outcome ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS done_criteria ON goal TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS owner ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS horizon ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS first_action ON goal TYPE option<string>;
DEFINE FIELD IF NOT EXISTS origin_link ON goal TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS milestones ON goal TYPE option<array<object>> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS close_reason ON goal TYPE option<string>;
-- P2-32: proposals, milestone planning, flags (all option<...>: the goal table has rows)
DEFINE FIELD IF NOT EXISTS proposed ON goal TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS outcome_changed_at ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS plan_requested_at ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS swift_checked_at ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS orphan_flagged_at ON goal TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS conflict_flags ON goal TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS conflict_checked ON goal TYPE option<array<string>>;

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

-- Pursuit grants (B3-04): owner permission for autonomous work above read.
DEFINE TABLE IF NOT EXISTS pursuit_grant SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS goal_id ON pursuit_grant TYPE string;
DEFINE FIELD IF NOT EXISTS scope ON pursuit_grant TYPE string ASSERT $value IN ['write', 'execute', 'send'];
DEFINE FIELD IF NOT EXISTS budget ON pursuit_grant TYPE object DEFAULT {};
DEFINE FIELD IF NOT EXISTS budget.tokens ON pursuit_grant TYPE option<int>;
DEFINE FIELD IF NOT EXISTS budget.minutes ON pursuit_grant TYPE option<int>;
DEFINE FIELD IF NOT EXISTS budget.calls ON pursuit_grant TYPE option<int>;
DEFINE FIELD IF NOT EXISTS granted_by ON pursuit_grant TYPE string;
DEFINE FIELD IF NOT EXISTS granted_at ON pursuit_grant TYPE datetime;
DEFINE FIELD IF NOT EXISTS expires_at ON pursuit_grant TYPE datetime;
DEFINE FIELD IF NOT EXISTS revoked_at ON pursuit_grant TYPE option<datetime>;
DEFINE INDEX IF NOT EXISTS pursuit_grant_goal ON pursuit_grant FIELDS goal_id;

-- Question scoring (B4-01): option fields on the existing question table.
DEFINE FIELD IF NOT EXISTS score ON question TYPE option<float>;
DEFINE FIELD IF NOT EXISTS scored_at ON question TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS tractability ON question TYPE option<float>;
DEFINE FIELD IF NOT EXISTS parked_reason ON question TYPE option<string>;
DEFINE FIELD IF NOT EXISTS resolved_by ON question TYPE option<string>;

-- Investigations (B4-02): progress and outcome on the question; sources on external facts.
DEFINE FIELD IF NOT EXISTS investigation ON question TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS sources ON fact TYPE option<array<string>>;

-- Dismissal learning (B5-03): per-kind learned state; ignored marker on agenda items.
DEFINE TABLE IF NOT EXISTS agenda_kind_stats SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS kind ON agenda_kind_stats TYPE string;
DEFINE FIELD IF NOT EXISTS threshold_delta ON agenda_kind_stats TYPE float DEFAULT 0.0;
DEFINE FIELD IF NOT EXISTS consecutive_dismissals ON agenda_kind_stats TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS muted_until ON agenda_kind_stats TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS delivered ON agenda_kind_stats TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS acknowledged ON agenda_kind_stats TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS dismissed ON agenda_kind_stats TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS ignored ON agenda_kind_stats TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS updated_at ON agenda_kind_stats TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS ignored ON agenda_item TYPE option<bool>;

-- Curiosity daily budget (B4-03): one row per local day (YYYY-MM-DD in app_timezone).
DEFINE TABLE IF NOT EXISTS curiosity_budget SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS day ON curiosity_budget TYPE string;
DEFINE FIELD IF NOT EXISTS investigations ON curiosity_budget TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS tokens ON curiosity_budget TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS spend_usd ON curiosity_budget TYPE float DEFAULT 0.0;
DEFINE FIELD IF NOT EXISTS updated_at ON curiosity_budget TYPE datetime;
DEFINE INDEX IF NOT EXISTS curiosity_budget_day ON curiosity_budget FIELDS day UNIQUE;

-- Diverge lineage (P2-28): a creative run, its ideas (seed, candidate, final) and lens yield.
DEFINE TABLE IF NOT EXISTS creative_run SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS question ON creative_run TYPE string;
DEFINE FIELD IF NOT EXISTS created_at ON creative_run TYPE datetime;
DEFINE FIELD IF NOT EXISTS explored_at ON creative_run TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS finalized_at ON creative_run TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS final_count ON creative_run TYPE option<int>;
DEFINE FIELD IF NOT EXISTS novelty ON creative_run TYPE option<float>;
DEFINE TABLE IF NOT EXISTS creative_idea SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS run ON creative_idea TYPE string;
DEFINE FIELD IF NOT EXISTS role ON creative_idea TYPE string;
DEFINE FIELD IF NOT EXISTS text ON creative_idea TYPE string;
DEFINE FIELD IF NOT EXISTS model ON creative_idea TYPE option<string>;
DEFINE FIELD IF NOT EXISTS lens ON creative_idea TYPE option<string>;
DEFINE FIELD IF NOT EXISTS parent_ids ON creative_idea TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS duplicate_of ON creative_idea TYPE option<string>;
DEFINE FIELD IF NOT EXISTS overlaps_seed ON creative_idea TYPE option<bool>;
DEFINE FIELD IF NOT EXISTS survived ON creative_idea TYPE option<bool>;
DEFINE FIELD IF NOT EXISTS created_at ON creative_idea TYPE datetime;
DEFINE INDEX IF NOT EXISTS creative_idea_run ON creative_idea FIELDS run;
DEFINE TABLE IF NOT EXISTS lens_yield SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS model ON lens_yield TYPE string;
DEFINE FIELD IF NOT EXISTS lens ON lens_yield TYPE string;
DEFINE FIELD IF NOT EXISTS offered ON lens_yield TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS survived ON lens_yield TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS updated_at ON lens_yield TYPE option<datetime>;
DEFINE INDEX IF NOT EXISTS lens_yield_key ON lens_yield FIELDS model, lens UNIQUE;

-- Autonomy slider (P2-33): numeric level 0..3 on the control row (the B1-01 name row is
-- migrated on load), daily budget counters per local day, and the origin of a task.
DEFINE FIELD IF NOT EXISTS autonomy_level ON autonomy_control TYPE option<int>;
DEFINE TABLE IF NOT EXISTS autonomy_budget SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS day ON autonomy_budget TYPE string;
DEFINE FIELD IF NOT EXISTS messages ON autonomy_budget TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS sage_calls ON autonomy_budget TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS task_graphs ON autonomy_budget TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS updated_at ON autonomy_budget TYPE datetime;
DEFINE FIELD IF NOT EXISTS origin ON task TYPE option<string>;
