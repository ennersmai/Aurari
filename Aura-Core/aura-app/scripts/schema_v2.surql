-- Aura Database Schema v2 — Memory data model (PRD 4.1 to 4.5, M4)
-- Structural definitions only, all idempotent (IF NOT EXISTS) so this file
-- can be applied on every boot after init_schema.surql.
--
-- Boot order: init_schema.surql → schema_v2.surql → seed_emotions.surql
--             → register_local_tools.surql → seed_cultural_nodes.surql
--             → setup_tasks.surql

USE NS aura DB main;

-- ============================================================================
-- MEMORY V2 NODE TABLES
-- ============================================================================

-- person, project, place, tool, concept or other
DEFINE TABLE IF NOT EXISTS entity SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON entity TYPE string;
DEFINE FIELD IF NOT EXISTS type ON entity TYPE string
    ASSERT $value IN ["person", "project", "place", "tool", "concept", "other"];
DEFINE FIELD IF NOT EXISTS aliases ON entity TYPE array<string> DEFAULT []
    VALUE $value.map(|$v| string::lowercase($v));
DEFINE FIELD IF NOT EXISTS summary ON entity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS embedding ON entity TYPE option<array<float, 768>>;
DEFINE FIELD IF NOT EXISTS created_at ON entity TYPE datetime;
DEFINE FIELD IF NOT EXISTS summary_updated_at ON entity TYPE option<datetime>;

-- One conversational turn or event, verbatim. The evidence layer.
DEFINE TABLE IF NOT EXISTS episode SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS user_text ON episode TYPE string;
DEFINE FIELD IF NOT EXISTS aura_text ON episode TYPE string;
DEFINE FIELD IF NOT EXISTS speaker ON episode TYPE record<entity>;
DEFINE FIELD IF NOT EXISTS venue ON episode TYPE string;
DEFINE FIELD IF NOT EXISTS conversation_id ON episode TYPE option<string>;
DEFINE FIELD IF NOT EXISTS embedding ON episode TYPE option<array<float, 768>>;
DEFINE FIELD IF NOT EXISTS emotional_signature ON episode TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD IF NOT EXISTS salience ON episode TYPE float DEFAULT 0;
DEFINE FIELD IF NOT EXISTS ephemeral ON episode TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS archived ON episode TYPE option<bool> DEFAULT false;
DEFINE FIELD IF NOT EXISTS recorded_at ON episode TYPE datetime;
DEFINE FIELD IF NOT EXISTS extraction_status ON episode TYPE string DEFAULT "pending"
    ASSERT $value IN ["pending", "done", "failed", "skipped"];
DEFINE FIELD IF NOT EXISTS extraction_attempts ON episode TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS extraction_error ON episode TYPE option<string>;
DEFINE FIELD IF NOT EXISTS extraction ON episode TYPE option<object> FLEXIBLE;

-- One atomic statement in plain language. What gets injected most.
DEFINE TABLE IF NOT EXISTS fact SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS content ON fact TYPE string;
DEFINE FIELD IF NOT EXISTS kind ON fact TYPE string
    ASSERT $value IN ["fact", "preference", "pattern", "decision", "event"];
DEFINE FIELD IF NOT EXISTS subject ON fact TYPE option<string>;
DEFINE FIELD IF NOT EXISTS predicate ON fact TYPE option<string>;
DEFINE FIELD IF NOT EXISTS object ON fact TYPE option<string>;
DEFINE FIELD IF NOT EXISTS provenance ON fact TYPE string
    ASSERT $value IN ["observed", "hearsay", "inferred", "imagined", "external"];
DEFINE FIELD IF NOT EXISTS visibility ON fact TYPE string;
DEFINE FIELD IF NOT EXISTS confidence ON fact TYPE float
    ASSERT $value >= 0 AND $value <= 1;
DEFINE FIELD IF NOT EXISTS valid_from ON fact TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS valid_to ON fact TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS recorded_at ON fact TYPE datetime;
DEFINE FIELD IF NOT EXISTS embedding ON fact TYPE option<array<float, 768>>;
DEFINE FIELD IF NOT EXISTS salience ON fact TYPE float DEFAULT 0;
DEFINE FIELD IF NOT EXISTS pinned ON fact TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS archived ON fact TYPE option<bool> DEFAULT false;
DEFINE FIELD IF NOT EXISTS use_count ON fact TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS last_used_at ON fact TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS unused_streak ON fact TYPE int DEFAULT 0;

-- Something Aura does not know or has found contradictory (feeds curiosity).
DEFINE TABLE IF NOT EXISTS question SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS content ON question TYPE string;
DEFINE FIELD IF NOT EXISTS visibility ON question TYPE string;
DEFINE FIELD IF NOT EXISTS status ON question TYPE string DEFAULT "open";
DEFINE FIELD IF NOT EXISTS recorded_at ON question TYPE datetime;

-- A cluster of related facts and entities (produced by dreaming).
DEFINE TABLE IF NOT EXISTS theme SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS content ON theme TYPE string;
DEFINE FIELD IF NOT EXISTS recorded_at ON theme TYPE datetime;
DEFINE FIELD IF NOT EXISTS visibility ON theme TYPE option<string>;
DEFINE FIELD IF NOT EXISTS embedding ON theme TYPE option<array<float, 768>>;
DEFINE FIELD IF NOT EXISTS updated_at ON theme TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS fact_count ON theme TYPE option<int>;

-- Something Aura expects about the user or a task, scored once known.
DEFINE TABLE IF NOT EXISTS prediction SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS content ON prediction TYPE string;
DEFINE FIELD IF NOT EXISTS recorded_at ON prediction TYPE datetime;
DEFINE FIELD IF NOT EXISTS outcome ON prediction TYPE option<string>;
DEFINE FIELD IF NOT EXISTS error ON prediction TYPE option<float>;

-- ============================================================================
-- MEMORY V2 TYPED RELATIONS (PRD 4.3)
-- ============================================================================
-- led_to and abstracted_into are left for M5 to M7.

DEFINE TABLE IF NOT EXISTS derived_from TYPE RELATION IN fact OUT episode SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS about TYPE RELATION IN fact OUT entity SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS mentions TYPE RELATION IN episode OUT entity SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS next TYPE RELATION IN episode OUT episode SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS supersedes TYPE RELATION IN fact OUT fact SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS contradicts TYPE RELATION IN fact OUT fact SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS answers TYPE RELATION IN fact OUT question SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS member_of TYPE RELATION IN fact OUT theme SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS co_used TYPE RELATION IN fact OUT fact SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS weight ON co_used TYPE float DEFAULT 1;
-- One edge per stored pair: feedback strengthens it rather than adding a twin.
DEFINE INDEX IF NOT EXISTS co_used_pair ON co_used FIELDS in, out UNIQUE;

-- ============================================================================
-- MEMORY V2 INDEXES (PRD 4.5)
-- ============================================================================

-- Dense retrieval: HNSW on every embedded node.
DEFINE INDEX IF NOT EXISTS fact_embedding ON fact FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;
DEFINE INDEX IF NOT EXISTS episode_embedding ON episode FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;
DEFINE INDEX IF NOT EXISTS entity_embedding ON entity FIELDS embedding HNSW DIMENSION 768 TYPE F32 DIST COSINE;

-- Lexical retrieval: one analyzer and a BM25 full-text index per text field.
DEFINE ANALYZER IF NOT EXISTS v2_text TOKENIZERS class FILTERS lowercase, ascii, snowball(english);
DEFINE INDEX IF NOT EXISTS fact_content_ft ON fact FIELDS content FULLTEXT ANALYZER v2_text BM25 HIGHLIGHTS;
DEFINE INDEX IF NOT EXISTS episode_user_text_ft ON episode FIELDS user_text FULLTEXT ANALYZER v2_text BM25 HIGHLIGHTS;
DEFINE INDEX IF NOT EXISTS entity_name_ft ON entity FIELDS name FULLTEXT ANALYZER v2_text BM25 HIGHLIGHTS;

-- Standard indexes for the filters and orderings the recall path uses.
DEFINE INDEX IF NOT EXISTS fact_visibility ON fact FIELDS visibility;
DEFINE INDEX IF NOT EXISTS fact_valid_to ON fact FIELDS valid_to;
DEFINE INDEX IF NOT EXISTS fact_archived ON fact FIELDS archived;
DEFINE INDEX IF NOT EXISTS episode_archived ON episode FIELDS archived;
DEFINE INDEX IF NOT EXISTS fact_provenance ON fact FIELDS provenance;
DEFINE INDEX IF NOT EXISTS fact_recorded_at ON fact FIELDS recorded_at;
DEFINE INDEX IF NOT EXISTS entity_aliases ON entity FIELDS aliases;
DEFINE INDEX IF NOT EXISTS episode_venue ON episode FIELDS venue;
DEFINE INDEX IF NOT EXISTS episode_extraction_status ON episode FIELDS extraction_status;