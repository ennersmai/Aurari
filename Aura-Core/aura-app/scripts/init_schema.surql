-- Aura Database Schema — Structural Definitions Only
-- This file contains ONLY DEFINE statements (tables, fields, indexes).
-- Seed data (CREATE / INSERT) lives in seed_emotions.surql and
-- seed_cultural_nodes.surql so that structure and data are never mixed.
--
-- Boot order: THIS FILE → seed_emotions.surql → register_local_tools.surql
--             → seed_cultural_nodes.surql → setup_tasks.surql

USE NS aura DB main;

-- ============================================================================
-- EMOTION SYSTEM TABLES
-- ============================================================================

DEFINE TABLE emotion SCHEMAFULL;
DEFINE FIELD name ON emotion TYPE string;
DEFINE FIELD category ON emotion TYPE string 
    ASSERT $value IN ["primary", "aesthetic", "social", "cognitive"];
DEFINE FIELD physics ON emotion TYPE object;
DEFINE FIELD physics.decay ON emotion TYPE float;
DEFINE FIELD physics.inertia ON emotion TYPE float;
DEFINE INDEX emotion_name ON emotion FIELDS name UNIQUE;

DEFINE TABLE emotion_state SCHEMAFULL;
DEFINE FIELD timestamp ON emotion_state TYPE datetime;
DEFINE FIELD vector ON emotion_state TYPE object FLEXIBLE;
DEFINE FIELD dominant ON emotion_state TYPE array;
DEFINE FIELD volatility ON emotion_state TYPE float;
DEFINE FIELD description ON emotion_state TYPE string;
DEFINE FIELD mood ON emotion_state TYPE option<object> FLEXIBLE;
DEFINE FIELD mood_at ON emotion_state TYPE option<datetime>;
DEFINE INDEX emotion_state_timestamp ON emotion_state FIELDS timestamp;

DEFINE TABLE emotion_event SCHEMAFULL;
DEFINE FIELD at ON emotion_event TYPE datetime;
DEFINE FIELD kind ON emotion_event TYPE string;
DEFINE FIELD source ON emotion_event TYPE string;
DEFINE FIELD ref ON emotion_event TYPE option<string>;
DEFINE FIELD person_id ON emotion_event TYPE option<string>;
DEFINE FIELD venue ON emotion_event TYPE option<string>;
DEFINE FIELD appraisal ON emotion_event TYPE object FLEXIBLE;
DEFINE FIELD impulses ON emotion_event TYPE object FLEXIBLE;
DEFINE FIELD deviation_change ON emotion_event TYPE object FLEXIBLE;
DEFINE FIELD dominant_change ON emotion_event TYPE option<string>;
DEFINE FIELD size ON emotion_event TYPE float DEFAULT 0;
DEFINE FIELD mood_bias ON emotion_event TYPE option<float>;
DEFINE FIELD capped ON emotion_event TYPE option<bool>;
DEFINE INDEX emotion_event_at ON emotion_event FIELDS at;

-- ============================================================================
-- MEMORY SYSTEM TABLES
-- ============================================================================

DEFINE TABLE memory SCHEMAFULL;
DEFINE FIELD content ON memory TYPE string;
DEFINE FIELD OVERWRITE emotional_signature ON memory TYPE object FLEXIBLE;
DEFINE FIELD timestamp ON memory TYPE datetime;
DEFINE FIELD importance ON memory TYPE float ASSERT $value >= 0 AND $value <= 1;
DEFINE FIELD learned_from ON memory TYPE bool DEFAULT false;
DEFINE FIELD conversation_id ON memory TYPE option<string>;
DEFINE FIELD user_id ON memory TYPE option<string>;
DEFINE FIELD tags ON memory TYPE array DEFAULT [];
DEFINE FIELD OVERWRITE metadata ON memory TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD embedding ON memory TYPE option<array<float, 768>>;
DEFINE FIELD namespace ON memory TYPE string DEFAULT "global";
-- Session 5 quality-layer fields
DEFINE FIELD formation_score ON memory TYPE float DEFAULT 0.5;
DEFINE FIELD ephemeral ON memory TYPE bool DEFAULT false;
DEFINE FIELD core_memory ON memory TYPE bool DEFAULT false;
DEFINE FIELD deprecated ON memory TYPE bool DEFAULT false;
DEFINE FIELD memory_type ON memory TYPE string DEFAULT "episodic";
DEFINE FIELD emotional_intensity ON memory TYPE float DEFAULT 0.0;
DEFINE FIELD recall_count ON memory TYPE int DEFAULT 0;
DEFINE FIELD last_recalled_at ON memory TYPE option<datetime>;
DEFINE FIELD OVERWRITE formation_context ON memory TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD resonance_score ON memory TYPE option<float>;
-- Core indexes
DEFINE INDEX memory_timestamp ON memory FIELDS timestamp;
DEFINE INDEX memory_user ON memory FIELDS user_id;
DEFINE INDEX memory_embedding ON memory FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;
DEFINE ANALYZER OVERWRITE memory_text TOKENIZERS class FILTERS lowercase, ascii, snowball(english);
DEFINE INDEX OVERWRITE memory_content_ft ON memory FIELDS content FULLTEXT ANALYZER memory_text BM25 HIGHLIGHTS;
-- Quality-layer indexes
DEFINE INDEX memory_core ON memory FIELDS core_memory;
DEFINE INDEX memory_ephemeral ON memory FIELDS ephemeral;
DEFINE INDEX memory_deprecated ON memory FIELDS deprecated;
DEFINE INDEX memory_type_idx ON memory FIELDS memory_type;
DEFINE INDEX memory_emotional_intensity ON memory FIELDS emotional_intensity;
DEFINE INDEX memory_recall_count ON memory FIELDS recall_count;
DEFINE INDEX memory_formation_score ON memory FIELDS formation_score;
-- Mood-congruent retrieval indexes
DEFINE INDEX emotion_joy ON memory FIELDS emotional_signature.joy;
DEFINE INDEX emotion_frustration ON memory FIELDS emotional_signature.frustration;
DEFINE INDEX emotion_anger ON memory FIELDS emotional_signature.anger;

DEFINE TABLE conversation SCHEMAFULL;
DEFINE FIELD title ON conversation TYPE string DEFAULT "New Conversation";
DEFINE FIELD user_id ON conversation TYPE string DEFAULT "default";
DEFINE FIELD created_at ON conversation TYPE string;
DEFINE FIELD updated_at ON conversation TYPE string;
DEFINE FIELD message_count ON conversation TYPE int DEFAULT 0;
DEFINE FIELD started_at ON conversation TYPE option<string>;
DEFINE FIELD ended_at ON conversation TYPE option<string>;
DEFINE FIELD initial_emotion ON conversation TYPE option<object>;
DEFINE FIELD OVERWRITE final_emotion ON conversation TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD summary ON conversation TYPE string DEFAULT "";
DEFINE FIELD key_topics ON conversation TYPE array DEFAULT [];
DEFINE FIELD session_id ON conversation TYPE string DEFAULT "main";
DEFINE FIELD conversation_id ON conversation TYPE string;
DEFINE FIELD experiences_logged ON conversation TYPE array DEFAULT [];
DEFINE FIELD rules_created ON conversation TYPE array DEFAULT [];
DEFINE INDEX conversation_user ON conversation FIELDS user_id;
DEFINE INDEX conversation_started ON conversation FIELDS started_at;
DEFINE INDEX idx_conv_session ON conversation FIELDS session_id;

DEFINE TABLE message SCHEMAFULL;
DEFINE FIELD conversation_id ON message TYPE string;
DEFINE FIELD content ON message TYPE string;
DEFINE FIELD role ON message TYPE string DEFAULT "user";
DEFINE FIELD timestamp ON message TYPE string;
DEFINE INDEX message_conversation_idx ON message FIELDS conversation_id;

-- ============================================================================
-- LEARNING SYSTEM TABLES
-- ============================================================================

DEFINE TABLE experience SCHEMAFULL;
DEFINE FIELD timestamp ON experience TYPE datetime;
DEFINE FIELD user_id ON experience TYPE string;
DEFINE FIELD task_type ON experience TYPE string;
DEFINE FIELD domain ON experience TYPE string;
DEFINE FIELD OVERWRITE context ON experience TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE aura_response ON experience TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE outcome ON experience TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE emotional_state ON experience TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE metadata ON experience TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD learned_from ON experience TYPE bool DEFAULT false;
DEFINE FIELD embedding ON experience TYPE option<array<float, 768>>;
DEFINE FIELD experience_id ON experience TYPE string;
DEFINE INDEX exp_domain ON experience FIELDS domain;
DEFINE INDEX exp_task_type ON experience FIELDS task_type;
DEFINE INDEX exp_timestamp ON experience FIELDS timestamp;
DEFINE INDEX exp_user ON experience FIELDS user_id;
DEFINE INDEX exp_embedding ON experience FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;

DEFINE TABLE skill SCHEMAFULL;
DEFINE FIELD skill_id ON skill TYPE option<string>;
DEFINE FIELD name ON skill TYPE string;
DEFINE FIELD domain ON skill TYPE string;
DEFINE FIELD created ON skill TYPE datetime;
DEFINE FIELD mastery_level ON skill TYPE float ASSERT $value >= 0 AND $value <= 1;
DEFINE FIELD OVERWRITE emotional_signature ON skill TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD parent_skill_id ON skill TYPE option<record<skill>>;
DEFINE FIELD sub_skill_ids ON skill TYPE array DEFAULT [];
DEFINE FIELD insight_ids ON skill TYPE array DEFAULT [];
DEFINE FIELD OVERWRITE definition ON skill TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD last_practiced ON skill TYPE option<datetime>;
DEFINE FIELD practice_count ON skill TYPE int DEFAULT 0;
DEFINE FIELD skill_type ON skill TYPE string DEFAULT "abstract"
    ASSERT $value IN ["abstract", "mcp_tool", "local_function", "python_script"];
DEFINE FIELD OVERWRITE execution_config ON skill TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD risk_level ON skill TYPE string DEFAULT "low";
DEFINE FIELD description_embedding ON skill TYPE option<array<float, 768>>;
DEFINE FIELD tool_name ON skill TYPE option<string>;
DEFINE INDEX skill_domain ON skill FIELDS domain;
DEFINE INDEX skill_mastery ON skill FIELDS mastery_level;
DEFINE INDEX skill_embedding ON skill FIELDS description_embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;

DEFINE TABLE strategy SCHEMAFULL;
DEFINE FIELD task_type ON strategy TYPE string;
DEFINE FIELD approach ON strategy TYPE string;
DEFINE FIELD success_rate ON strategy TYPE float DEFAULT 0.0;
DEFINE FIELD avg_confidence ON strategy TYPE float DEFAULT 0.0;
DEFINE FIELD usage_count ON strategy TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE emotional_prerequisites ON strategy TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD when_to_use ON strategy TYPE string DEFAULT "";
DEFINE FIELD examples ON strategy TYPE array DEFAULT [];
DEFINE FIELD last_updated ON strategy TYPE datetime;
DEFINE INDEX strategy_task_type ON strategy FIELDS task_type;

-- ============================================================================
-- IDENTITY SYSTEM TABLES
-- ============================================================================

DEFINE TABLE identity SCHEMAFULL;
DEFINE FIELD name ON identity TYPE string DEFAULT "Aura";
DEFINE FIELD version ON identity TYPE string;
DEFINE FIELD created ON identity TYPE datetime;
DEFINE FIELD autobiographical_narrative ON identity TYPE string;
DEFINE FIELD OVERWRITE core_values ON identity TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE preferences ON identity TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE self_concept ON identity TYPE object FLEXIBLE DEFAULT {};

DEFINE TABLE identity_change SCHEMAFULL;
DEFINE FIELD timestamp ON identity_change TYPE datetime;
DEFINE FIELD change_type ON identity_change TYPE string;
DEFINE FIELD old_value ON identity_change TYPE string;
DEFINE FIELD new_value ON identity_change TYPE string;
DEFINE FIELD rationale ON identity_change TYPE string;
DEFINE FIELD acknowledged ON identity_change TYPE bool DEFAULT false;
DEFINE INDEX identity_change_time ON identity_change FIELDS timestamp;

DEFINE TABLE value SCHEMAFULL;
DEFINE FIELD name ON value TYPE string;
DEFINE FIELD description ON value TYPE string;
DEFINE FIELD weight ON value TYPE float DEFAULT 0.5;
DEFINE FIELD created ON value TYPE datetime;
DEFINE FIELD examples ON value TYPE array DEFAULT [];

-- ============================================================================
-- GOAL SYSTEM TABLES
-- ============================================================================

DEFINE TABLE goal SCHEMAFULL;
DEFINE FIELD name ON goal TYPE string;
DEFINE FIELD description ON goal TYPE string;
DEFINE FIELD goal_type ON goal TYPE string;
DEFINE FIELD status ON goal TYPE string DEFAULT "active";
DEFINE FIELD priority ON goal TYPE float DEFAULT 0.5;
DEFINE FIELD created ON goal TYPE datetime;
DEFINE FIELD updated ON goal TYPE datetime;
DEFINE FIELD completed ON goal TYPE option<datetime>;
DEFINE FIELD parent_goal_id ON goal TYPE option<record<goal>>;
DEFINE FIELD sub_goal_ids ON goal TYPE array DEFAULT [];
DEFINE FIELD progress ON goal TYPE float DEFAULT 0.0;
DEFINE FIELD emotional_alignment ON goal TYPE object DEFAULT {};
DEFINE FIELD origin ON goal TYPE string;
DEFINE INDEX goal_status ON goal FIELDS status;
DEFINE INDEX goal_priority ON goal FIELDS priority;

DEFINE TABLE task SCHEMAFULL;
DEFINE FIELD goal_id ON task TYPE record<goal>;
DEFINE FIELD description ON task TYPE string;
DEFINE FIELD status ON task TYPE string DEFAULT "pending";
DEFINE FIELD created ON task TYPE datetime;
DEFINE FIELD completed ON task TYPE option<datetime>;
DEFINE FIELD result ON task TYPE option<string>;
DEFINE FIELD session_id ON task TYPE string DEFAULT "main";
DEFINE FIELD delegated ON task TYPE option<bool>;
DEFINE INDEX idx_task_session ON task FIELDS session_id, status;

-- ============================================================================
-- REFLECTION SYSTEM TABLES
-- ============================================================================

DEFINE TABLE reflection SCHEMAFULL;
DEFINE FIELD reflection_id ON reflection TYPE string;
DEFINE FIELD timestamp ON reflection TYPE datetime;
DEFINE FIELD period_start ON reflection TYPE datetime;
DEFINE FIELD period_end ON reflection TYPE datetime;
DEFINE FIELD reflection_type ON reflection TYPE string;
DEFINE FIELD insights ON reflection TYPE array DEFAULT [];
DEFINE FIELD patterns_found ON reflection TYPE array DEFAULT [];
DEFINE FIELD OVERWRITE emotional_summary ON reflection TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD emotional_summary.dominant_emotion ON reflection TYPE option<string>;
DEFINE FIELD emotional_summary.states_count ON reflection TYPE int;
DEFINE FIELD OVERWRITE emotional_summary.emotion_distribution ON reflection TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE goal_progress ON reflection TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD identity_shifts ON reflection TYPE array DEFAULT [];
DEFINE FIELD proposals ON reflection TYPE array DEFAULT [];

-- ============================================================================
-- GRAPH RELATIONSHIP TABLES
-- ============================================================================

DEFINE TABLE skill_contains SCHEMAFULL;
DEFINE FIELD in ON skill_contains TYPE record<skill>;
DEFINE FIELD out ON skill_contains TYPE record<skill>;

-- ============================================================================
-- RULE TABLE (Learning Engine)
-- ============================================================================

DEFINE TABLE rule SCHEMALESS;

-- ============================================================================
-- GRAPH RELATIONSHIP TABLES (continued)
-- ============================================================================

DEFINE TABLE rule_learned_from SCHEMAFULL;
DEFINE FIELD in ON rule_learned_from TYPE record<rule>;
DEFINE FIELD out ON rule_learned_from TYPE record<experience>;

DEFINE TABLE rule_analogous_to SCHEMAFULL;
DEFINE FIELD in ON rule_analogous_to TYPE record<rule>;
DEFINE FIELD out ON rule_analogous_to TYPE record<rule>;
DEFINE FIELD similarity ON rule_analogous_to TYPE float;

DEFINE TABLE rule_contradicts SCHEMAFULL;
DEFINE FIELD in ON rule_contradicts TYPE record<rule>;
DEFINE FIELD out ON rule_contradicts TYPE record<rule>;

DEFINE TABLE experience_similar_to SCHEMAFULL;
DEFINE FIELD in ON experience_similar_to TYPE record<experience>;
DEFINE FIELD out ON experience_similar_to TYPE record<experience>;
DEFINE FIELD similarity ON experience_similar_to TYPE float;

DEFINE TABLE identity_holds SCHEMAFULL;
DEFINE FIELD in ON identity_holds TYPE record<identity>;
DEFINE FIELD out ON identity_holds TYPE record<value>;

DEFINE TABLE goal_contains SCHEMAFULL;
DEFINE FIELD in ON goal_contains TYPE record<goal>;
DEFINE FIELD out ON goal_contains TYPE record<goal>;

DEFINE TABLE memory_influences SCHEMAFULL;
DEFINE FIELD in ON memory_influences TYPE record<memory>;
DEFINE FIELD out ON memory_influences TYPE record<identity>;
DEFINE FIELD influence_type ON memory_influences TYPE string;

-- Associative memory network
DEFINE TABLE related_to SCHEMALESS;
DEFINE FIELD in ON related_to TYPE record<memory>;
DEFINE FIELD out ON related_to TYPE record<memory>;
DEFINE FIELD similarity ON related_to TYPE float;
-- Session 6: index for spreading activation batched queries
DEFINE INDEX related_to_in ON related_to FIELDS in;
DEFINE INDEX related_to_out ON related_to FIELDS out;

DEFINE TABLE abstracted_into SCHEMALESS;
DEFINE FIELD in ON abstracted_into TYPE record<memory>;
DEFINE FIELD out ON abstracted_into TYPE record<memory>;
-- Session 6: indexes for thought cluster traversal
DEFINE INDEX abstracted_into_in ON abstracted_into FIELDS in;
DEFINE INDEX abstracted_into_out ON abstracted_into FIELDS out;

-- Temporal linking (dreaming & causal analysis)
DEFINE TABLE next_experience SCHEMAFULL;
DEFINE FIELD in ON next_experience TYPE record<experience>;
DEFINE FIELD out ON next_experience TYPE record<experience>;
DEFINE FIELD elapsed_ms ON next_experience TYPE int;
-- Session 6: indexes for causal weaving & timeline traversal
DEFINE INDEX next_exp_in ON next_experience FIELDS in;
DEFINE INDEX next_exp_out ON next_experience FIELDS out;

-- L1 routing trigger-to-skill edge
DEFINE TABLE triggers_skill SCHEMAFULL;
DEFINE FIELD in ON triggers_skill TYPE record<semantic_trigger>;
DEFINE FIELD out ON triggers_skill TYPE record<skill>;

-- ============================================================================
-- INSIGHT TABLE
-- ============================================================================

DEFINE TABLE insight SCHEMAFULL;
DEFINE FIELD insight_id ON insight TYPE string;
DEFINE FIELD content ON insight TYPE string;
DEFINE FIELD type ON insight TYPE string DEFAULT "PATTERN";
DEFINE FIELD domain ON insight TYPE string;
DEFINE FIELD confidence ON insight TYPE float DEFAULT 0.5;
DEFINE FIELD created_at ON insight TYPE datetime DEFAULT time::now();
DEFINE FIELD last_used ON insight TYPE datetime DEFAULT time::now();
DEFINE FIELD application_count ON insight TYPE int DEFAULT 0;
DEFINE FIELD user_id ON insight TYPE string DEFAULT "default";
DEFINE FIELD deprecated ON insight TYPE bool DEFAULT false;
DEFINE FIELD source_experiences ON insight TYPE array DEFAULT [];
DEFINE FIELD OVERWRITE emotional_signature ON insight TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD embedding ON insight TYPE option<array<float, 768>>;
DEFINE FIELD created ON insight TYPE datetime DEFAULT time::now();
DEFINE FIELD updated ON insight TYPE datetime DEFAULT time::now();
DEFINE FIELD confidence_history ON insight TYPE array DEFAULT [];
DEFINE FIELD success_count ON insight TYPE int DEFAULT 0;
DEFINE FIELD extraction_method ON insight TYPE string DEFAULT "l2_analysis";
DEFINE FIELD hedonic_score ON insight TYPE float DEFAULT 0.0;
DEFINE FIELD deprecation_threshold ON insight TYPE float DEFAULT 0.3;
DEFINE INDEX insight_embedding ON insight FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;
DEFINE INDEX insight_domain ON insight FIELDS domain;

-- ============================================================================
-- SYSTEM JOURNAL TABLE
-- ============================================================================

DEFINE TABLE system_journal SCHEMAFULL;
DEFINE FIELD user_id ON system_journal TYPE string DEFAULT "default";
DEFINE FIELD created ON system_journal TYPE datetime DEFAULT time::now();
DEFINE FIELD entry ON system_journal TYPE string;
DEFINE FIELD session_start ON system_journal TYPE option<datetime>;
DEFINE FIELD session_end ON system_journal TYPE option<datetime>;
DEFINE FIELD OVERWRITE metadata ON system_journal TYPE object FLEXIBLE DEFAULT {};
DEFINE INDEX system_journal_user ON system_journal FIELDS user_id;
DEFINE INDEX system_journal_created ON system_journal FIELDS created;

-- ============================================================================
-- L1 ROUTING TABLES
-- ============================================================================

DEFINE TABLE semantic_trigger SCHEMAFULL;
DEFINE FIELD phrase ON semantic_trigger TYPE string;
DEFINE FIELD embedding ON semantic_trigger TYPE option<array<float, 768>>;
DEFINE FIELD target_action ON semantic_trigger TYPE record<skill>;
DEFINE FIELD confidence ON semantic_trigger TYPE float DEFAULT 1.0;
DEFINE INDEX trigger_embedding ON semantic_trigger FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;

-- ============================================================================
-- SYSTEM STATS
-- ============================================================================

DEFINE TABLE stats SCHEMAFULL;
DEFINE FIELD key ON stats TYPE string;
DEFINE FIELD value ON stats TYPE number;
DEFINE INDEX stats_key ON stats FIELDS key UNIQUE;

-- ============================================================================
-- LATENT MEMORY (TITANS) TABLES
-- ============================================================================

DEFINE TABLE latent_state SCHEMAFULL;
DEFINE FIELD user_id ON latent_state TYPE string;
DEFINE FIELD state_vector ON latent_state TYPE array<float, 768>;
DEFINE FIELD momentum_vector ON latent_state TYPE array<float, 768>;
DEFINE FIELD version ON latent_state TYPE int DEFAULT 0;
DEFINE FIELD last_updated ON latent_state TYPE datetime DEFAULT time::now();
DEFINE FIELD total_experiences_absorbed ON latent_state TYPE int DEFAULT 0;
DEFINE FIELD avg_surprise ON latent_state TYPE float DEFAULT 0.5;
DEFINE FIELD surprise_variance ON latent_state TYPE float DEFAULT 0.1;
DEFINE FIELD OVERWRITE emotional_centroid ON latent_state TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE domain_distribution ON latent_state TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD summary_text ON latent_state TYPE string DEFAULT "";
DEFINE INDEX latent_state_user ON latent_state FIELDS user_id UNIQUE;

-- Latent state history (debugging and rollback)
DEFINE TABLE latent_state_history SCHEMAFULL;
DEFINE FIELD user_id ON latent_state_history TYPE string;
DEFINE FIELD version ON latent_state_history TYPE int;
DEFINE FIELD timestamp ON latent_state_history TYPE datetime DEFAULT time::now();
DEFINE FIELD surprise_gradient ON latent_state_history TYPE float;
DEFINE FIELD trigger_experience_id ON latent_state_history TYPE option<string>;
DEFINE FIELD delta_magnitude ON latent_state_history TYPE float DEFAULT 0.0;
DEFINE INDEX latent_history_user ON latent_state_history FIELDS user_id;

-- Graph edge: experience ->modulates-> latent_state (surprise-gated)
DEFINE TABLE modulates SCHEMALESS;
DEFINE FIELD in ON modulates TYPE record<experience>;
DEFINE FIELD out ON modulates TYPE record<latent_state>;
DEFINE FIELD surprise_gradient ON modulates TYPE float;
DEFINE FIELD timestamp ON modulates TYPE datetime DEFAULT time::now();
DEFINE INDEX modulates_in ON modulates FIELDS in;
DEFINE INDEX modulates_out ON modulates FIELDS out;

-- ============================================================================
-- SESSION SYSTEM
-- ============================================================================

DEFINE TABLE session SCHEMALESS;
DEFINE FIELD session_id        ON session TYPE string;
DEFINE FIELD name              ON session TYPE string;
DEFINE FIELD mode              ON session TYPE string;
DEFINE FIELD owner             ON session TYPE string DEFAULT "default";
DEFINE FIELD parent_session_id ON session TYPE option<string>;
DEFINE FIELD status            ON session TYPE string DEFAULT "queued";
DEFINE FIELD created_at        ON session TYPE datetime DEFAULT time::now();
DEFINE FIELD started_at        ON session TYPE option<datetime>;
DEFINE FIELD ended_at          ON session TYPE option<datetime>;
DEFINE FIELD memory_namespace  ON session TYPE string DEFAULT "global";
DEFINE FIELD emotion_isolated  ON session TYPE bool DEFAULT false;
DEFINE FIELD identity_overlay  ON session TYPE object DEFAULT {};
DEFINE FIELD model_overrides   ON session TYPE object DEFAULT {};
DEFINE FIELD tool_allowlist    ON session TYPE option<array<string>>;
DEFINE FIELD tool_denylist     ON session TYPE array<string> DEFAULT [];
DEFINE FIELD max_concurrent_agents ON session TYPE int DEFAULT 3;
DEFINE INDEX idx_session_status    ON session FIELDS status;
DEFINE INDEX idx_session_owner     ON session FIELDS owner;
DEFINE INDEX idx_session_namespace ON session FIELDS memory_namespace;

-- ============================================================================
-- DECISION SYSTEM (W3-30)
-- ============================================================================

DEFINE TABLE decision SCHEMAFULL;
DEFINE FIELD kind ON decision TYPE string;
DEFINE FIELD task_id ON decision TYPE option<string>;
DEFINE FIELD session_id ON decision TYPE string;
DEFINE FIELD request_id ON decision TYPE string;
DEFINE FIELD action ON decision TYPE string;
DEFINE FIELD resources ON decision TYPE array<string>;
DEFINE FIELD risk ON decision TYPE string;
DEFINE FIELD workspace ON decision TYPE option<string>;
DEFINE FIELD message ON decision TYPE option<string>;
DEFINE FIELD status ON decision TYPE string DEFAULT "pending" ASSERT $value IN ["pending", "allowed", "denied", "expired"];
DEFINE FIELD created_at ON decision TYPE datetime DEFAULT time::now();
DEFINE FIELD decided_at ON decision TYPE option<datetime>;
DEFINE FIELD decided_by ON decision TYPE option<string>;
DEFINE INDEX decision_status ON decision FIELDS status;
DEFINE INDEX decision_session ON decision FIELDS session_id;
