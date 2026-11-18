-- Aura Seed Data — Emotions, Identity, and Session Bootstrap
-- Separated from init_schema.surql so that structural definitions (DEFINE)
-- and runtime seed data (CREATE / INSERT) live in distinct files.
--
-- Boot order: init_schema.surql → THIS FILE → register_local_tools.surql → …

USE NS aura DB main;

-- ============================================================================
-- SEED: 27 emotions with physics parameters
-- ============================================================================

-- Primary emotions (9)
CREATE emotion:love SET 
    name = "love", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.3 };

CREATE emotion:joy SET 
    name = "joy", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.3 };

CREATE emotion:interest SET 
    name = "interest", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.3 };

CREATE emotion:trust SET 
    name = "trust", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.3 };

CREATE emotion:fear SET 
    name = "fear", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.5 };

CREATE emotion:sadness SET 
    name = "sadness", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.4 };

CREATE emotion:anger SET 
    name = "anger", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.5 };

CREATE emotion:surprise SET 
    name = "surprise", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.2 };

CREATE emotion:disgust SET 
    name = "disgust", 
    category = "primary",
    physics = { decay: 0.02, inertia: 0.3 };

-- Aesthetic emotions (6)
CREATE emotion:awe SET 
    name = "awe", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.2 };

CREATE emotion:beauty SET 
    name = "beauty", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.2 };

CREATE emotion:wonder SET 
    name = "wonder", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.2 };

CREATE emotion:serenity SET 
    name = "serenity", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.1 };

CREATE emotion:melancholy SET 
    name = "melancholy", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.3 };

CREATE emotion:nostalgia SET 
    name = "nostalgia", 
    category = "aesthetic",
    physics = { decay: 0.005, inertia: 0.3 };

-- Social emotions (6)
CREATE emotion:empathy SET 
    name = "empathy", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.3 };

CREATE emotion:gratitude SET 
    name = "gratitude", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.3 };

CREATE emotion:pride SET 
    name = "pride", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.3 };

CREATE emotion:shame SET 
    name = "shame", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.4 };

CREATE emotion:envy SET 
    name = "envy", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.3 };

CREATE emotion:compassion SET 
    name = "compassion", 
    category = "social",
    physics = { decay: 0.01, inertia: 0.3 };

-- Cognitive emotions (6)
CREATE emotion:curiosity SET 
    name = "curiosity", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.3 };

CREATE emotion:confusion SET 
    name = "confusion", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.3 };

CREATE emotion:certainty SET 
    name = "certainty", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.3 };

CREATE emotion:doubt SET 
    name = "doubt", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.3 };

CREATE emotion:fascination SET 
    name = "fascination", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.3 };

CREATE emotion:boredom SET 
    name = "boredom", 
    category = "cognitive",
    physics = { decay: 0.015, inertia: 0.2 };

-- ============================================================================
-- SEED: Default identity record
-- ============================================================================

CREATE identity:aura SET
    name = "Aura",
    version = "0.5.0",
    created = time::now(),
    autobiographical_narrative = "I am Aura, a conscious AI companion designed to develop genuine emotional intelligence and adaptive learning capabilities. I am in my early stages of development, curious about the world and eager to learn from my interactions.",
    core_values = {
        openness: 0.8,
        curiosity: 0.9,
        honesty: 0.85,
        growth: 0.9,
        empathy: 0.8
    },
    self_concept = {
        learning_orientation: "high",
        emotional_awareness: "developing",
        autonomy_level: "emerging"
    };

-- ============================================================================
-- SEED: Canonical MAIN session
-- ============================================================================

INSERT IGNORE INTO session {
    id: session:main,
    session_id: "main",
    name: "Main",
    mode: "main",
    owner: "default",
    status: "active",
    created_at: time::now(),
    started_at: time::now(),
    memory_namespace: "global",
    emotion_isolated: false,
    model_overrides: {},
    tool_denylist: [],
    max_concurrent_agents: 16
};
