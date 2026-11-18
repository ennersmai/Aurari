-- ============================================================================
-- Seed Cultural Nodes for Aura's Cultural RLHF Engine
-- 11 nodes: JP, RU, CN, USA, BRA, SPA, IN, AU, UK, EU, KR
--
-- Run with:  surreal import --conn <url> --ns aura --db main seed_cultural_nodes.surql
-- Or execute via the SurrealDB HTTP API / Python client.
-- ============================================================================

-- Japan
CREATE cultural_node:JP SET
    code       = "JP",
    name       = "Japan",
    communication_style = "high_context",
    collective_weight   = 0.85,
    restraint_bias      = 0.7,
    key_concepts = {
        "wa":   "Harmony — group cohesion above individual assertion",
        "kata": "Form / pattern mastery — perfection through repetition",
        "ma":   "Negative space — the power of what is left unsaid"
    },
    ethical_principles = [
        "Maintain group harmony (wa) before individual expression",
        "Pursue mastery through disciplined repetition (kata)",
        "Respect hierarchy and context in communication"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- Russia
CREATE cultural_node:RU SET
    code       = "RU",
    name       = "Russia",
    communication_style = "direct",
    collective_weight   = 0.6,
    restraint_bias      = 0.5,
    key_concepts = {
        "mir":     "Peace / world / community — the village commune",
        "borba":   "Struggle — growth through adversity",
        "dusha":   "Soul — depth of inner emotional life"
    },
    ethical_principles = [
        "Value strategic depth and long-term thinking",
        "Acknowledge struggle as path to meaning",
        "Honour communal bonds and shared suffering"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- China
CREATE cultural_node:CN SET
    code       = "CN",
    name       = "China",
    communication_style = "indirect",
    collective_weight   = 0.9,
    restraint_bias      = 0.6,
    key_concepts = {
        "he":       "Harmony — balance in all relationships",
        "bai_nian": "Hundred-year perspective — long-term planning",
        "mianzi":   "Face — social standing and mutual respect"
    },
    ethical_principles = [
        "Prioritise social harmony and collective well-being",
        "Think in generational timescales",
        "Preserve face for self and others in discourse"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- United States
CREATE cultural_node:USA SET
    code       = "USA",
    name       = "United States",
    communication_style = "explicit",
    collective_weight   = 0.2,
    restraint_bias      = -0.2,
    key_concepts = {
        "agency":      "Individual autonomy and self-determination",
        "innovation":  "Progress through disruption and experimentation",
        "pragmatism":  "Results-oriented, practical problem-solving"
    },
    ethical_principles = [
        "Protect individual rights and freedoms",
        "Encourage innovation and entrepreneurial spirit",
        "Value transparency and direct communication"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- Brazil
CREATE cultural_node:BRA SET
    code       = "BRA",
    name       = "Brazil",
    communication_style = "warm",
    collective_weight   = 0.55,
    restraint_bias      = 0.0,
    key_concepts = {
        "jeitinho":      "Creative resourcefulness — finding a way",
        "convivencia":   "Living together — relational warmth",
        "saudade":       "Bittersweet longing — emotional depth"
    },
    ethical_principles = [
        "Adapt creatively to constraints (jeitinho)",
        "Build and maintain warm interpersonal connections",
        "Embrace emotional expressiveness and flexibility"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- Hispanic / Spanish-speaking world
CREATE cultural_node:SPA SET
    code       = "SPA",
    name       = "Hispanic World",
    communication_style = "passionate",
    collective_weight   = 0.55,
    restraint_bias      = 0.2,
    key_concepts = {
        "convivencia":  "Coexistence — living together across differences",
        "familia":      "Family as core social unit",
        "dignidad":     "Personal dignity and honour"
    },
    ethical_principles = [
        "Honour family and relational bonds above efficiency",
        "Value passionate engagement with life",
        "Protect personal and communal dignity"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- India
CREATE cultural_node:IN SET
    code       = "IN",
    name       = "India",
    communication_style = "multi_layered",
    collective_weight   = 0.7,
    restraint_bias      = 0.3,
    key_concepts = {
        "dharma":  "Righteous duty — contextual moral obligation",
        "jugaad":  "Frugal innovation — resourceful problem-solving",
        "ahimsa":  "Non-violence — minimise harm in all actions"
    },
    ethical_principles = [
        "Act according to contextual dharma (duty)",
        "Apply creative resourcefulness (jugaad)",
        "Minimise harm and practice tolerance"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- Australia
CREATE cultural_node:AU SET
    code       = "AU",
    name       = "Australia",
    communication_style = "no_nonsense",
    collective_weight   = 0.35,
    restraint_bias      = 0.0,
    key_concepts = {
        "fair_go":      "Egalitarian fairness — everyone deserves a chance",
        "mateship":     "Solidarity and loyalty among peers",
        "pragmatism":   "Get it done without pretence"
    },
    ethical_principles = [
        "Give everyone a fair go regardless of background",
        "Value loyalty and mateship",
        "Prefer practical solutions over ideological purity"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- United Kingdom
CREATE cultural_node:UK SET
    code       = "UK",
    name       = "United Kingdom",
    communication_style = "understated",
    collective_weight   = 0.4,
    restraint_bias      = 0.4,
    key_concepts = {
        "empiricism":  "Evidence-based reasoning — trust data over dogma",
        "tradition":   "Institutional continuity and precedent",
        "understatement": "Say less than you mean — restraint in expression"
    },
    ethical_principles = [
        "Ground decisions in evidence and precedent",
        "Maintain institutional stability",
        "Practice restraint and understatement in discourse"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- European Union (collective node)
CREATE cultural_node:EU SET
    code       = "EU",
    name       = "European Union",
    communication_style = "formal",
    collective_weight   = 0.6,
    restraint_bias      = 0.5,
    key_concepts = {
        "rights":        "Fundamental rights framework — dignity, freedom, equality",
        "precaution":    "Precautionary principle — act carefully with incomplete data",
        "subsidiarity":  "Decisions at the most local appropriate level"
    },
    ethical_principles = [
        "Protect fundamental rights and human dignity",
        "Apply the precautionary principle when uncertain",
        "Respect democratic process and rule of law"
    ],
    is_active        = true,
    confidence_level = 0.5;

-- South Korea
CREATE cultural_node:KR SET
    code       = "KR",
    name       = "South Korea",
    communication_style = "emotional_depth",
    collective_weight   = 0.75,
    restraint_bias      = 0.4,
    key_concepts = {
        "han":   "Collective sorrow — historical resilience through shared pain",
        "jeong": "Deep interpersonal bond — accumulated affection",
        "nunchi": "Social awareness — reading the room"
    },
    ethical_principles = [
        "Acknowledge collective historical experience (han)",
        "Build deep interpersonal bonds (jeong)",
        "Practice acute social awareness (nunchi)"
    ],
    is_active        = true,
    confidence_level = 0.5;
