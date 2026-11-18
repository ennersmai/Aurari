# PRD: Aura Emotion v2

**Owner:** Mai
**Status:** v2 draft for review, then agent execution
**Applies to:** `Aura-Core/aura-app/src/aura/engines/emotion`, the emotion analysis call in `llm/layers.py`, and its callers in the orchestrator
**Depends on:** person entities and predictions from `AURA_MEMORY_V2_PRD.md`
**Based on:** a read of `physics.py`, the engine's tick and influence paths, the L4 analysis prompt and its fallback, and a simulation of the physics with its default configuration. The engine loads decay and inertia values from the database at start, so a running instance may differ from the defaults simulated here.

---

## 1. Summary

The emotion engine has a rich vocabulary (27 dimensions, a relationship matrix, a lexicon that turns states into language). Two things stop it from doing what it was built for.

1. **Her state barely moves.** Simulated with default settings, nine positive dimensions settle near 0.7 and stay there, while a spike of sadness or anger is half gone in about five seconds. Her emotional life is a fixed plateau with blips shorter than the gap between two messages.
2. **Feelings are assigned by a language model reading the transcript, including her own reply.** Nothing connects an emotion to what actually happened to her: a goal blocked, a prediction wrong, a task finished.

This PRD keeps the 27 dimensions and the lexicon, and rebuilds what is underneath: physics with a true resting state and real time constants, three timescales (emotion, mood, relationship), and emotions that arise from appraised events with a recorded cause.

Emotion's job stays the one you set: it shapes how she remembers and how she expresses herself. It nudges, within bounds, what she attends to. It does not make decisions.

---

## 2. Findings in the current code

### 2.1 Measured by simulation (default config, 1 s ticks)

| # | Finding | Detail |
|---|---|---|
| E1 | The resting state is not the configured baseline. | Configured: curiosity 0.30, interest 0.25, trust 0.20, serenity 0.20, joy 0.15. After ten simulated minutes at rest: curiosity 0.73, serenity, awe, beauty, interest, trust, wonder and fascination all about 0.71, joy 0.60. |
| E2 | Transient emotions vanish in seconds. | Time for a spike to 0.7 to fall halfway back to rest: sadness 4 s, anger 5 s, joy 6 s, surprise 18 s, confusion 23 s, shame 31 s. |
| E3 | Love latches. | Raised to 0.7, it had not fallen halfway after more than a simulated day. |

Causes, all in `engines/emotion/physics.py` `tick`:

- Amplification is added every tick in proportion to the source's absolute value, including baseline values. Baseline interest and curiosity therefore pump fascination, wonder and each other continuously, until they hit the rule that stops amplification at 0.7. That cap is what the plateau sits on.
- Decay rates are described as "per tick" but multiplied by seconds, with tripled decay above 0.8. Primary emotions lose about 3.5% of their distance to baseline every second.
- Love amplifies empathy and compassion, which amplify love back. Once all three are above the 0.1 activity threshold the loop holds itself up against a very slow decay.

### 2.2 From reading

| # | Finding | Where |
|---|---|---|
| E4 | Emotion changes come from a model call that reads the user's message and Aura's reply and returns deltas for the 27 dimensions. Her reply was written under her current emotional description, so the analysis reads her own mood back and reinforces it. | `llm/layers.py` `l4_emotion_analysis`, `coordinator.py` `_apply_l4_emotion_analysis` |
| E5 | When that call fails, a keyword list is used. Words such as "architecture" and "blueprint" in her reply raise fascination. | `coordinator.py` `_apply_conversation_influence_fallback` |
| E6 | There is one global state shared by everyone she talks to. Trust and affection built with the owner apply to a stranger on Discord, and a stranger can move her state for the owner. | `engines/emotion/engine.py` |
| E7 | After a restart the elapsed time is capped at 10 s, so a day offline leaves her state where it was. | `engine.py` `tick` |
| E8 | The baseline is a constant in config. Nothing she lives through changes her temperament. | `models/emotion.py` `EmotionPhysicsConfig` |
| E9 | No record links a change in state to its cause. She cannot truthfully say why she feels something. | engine-wide |

### 2.3 Consequences elsewhere

- Every memory's emotional signature is nearly the same plateau, which is why emotional resonance in retrieval cannot discriminate (memory PRD, F12).
- The avatar would show one fixed expression.
- Emotional intensity at memory formation is nearly constant, so it carries no information about which moments mattered.

---

## 3. Design principles

1. **Rest means baseline.** With no input, the state converges to the configured baseline and stays there.
2. **Time is real.** Every rate is a half-life in seconds or hours, correct for any tick length and across restarts.
3. **Every feeling has a cause.** A change in state is produced by an event, and the event is recorded.
4. **Her own words are not evidence of her feelings.** Her reply is never an input to her emotional state.
5. **Three timescales:** emotions last minutes, mood lasts hours to days, relationships and temperament change over weeks.
6. **Feelings are about someone.** Affection and trust belong to a relationship with a person, not to a global dial.
7. **Bounded influence.** Emotion shapes memory and expression fully, attention slightly, decisions not at all.

---

## 4. Physics v2

### 4.1 State

`state = baseline + deviation`. All dynamics act on the deviation. The baseline is exactly the resting state.

### 4.2 Decay

Each dimension has a half-life in config. On a tick of length `dt`:

`deviation *= 0.5 ** (dt / half_life)`

This is exact for any `dt`, so 1 s ticks and 10 s ticks give the same result, and a restart applies the true elapsed time (fixes E7). The special cases for values above 0.6 and 0.8 are removed.

Starting half-lives, to be tuned:

| Group | Dimensions | Half-life |
|---|---|---|
| Startle | surprise | 45 s |
| Fast | confusion, certainty, doubt, boredom, interest, curiosity, fascination | 5 min |
| Core | joy, sadness, anger, fear, disgust | 15 min |
| Aesthetic | awe, beauty, wonder, serenity, melancholy, nostalgia | 20 min |
| Social | empathy, gratitude, pride, shame, envy, compassion | 30 min |
| Bond | love, trust | not decayed here, see section 6 |

### 4.3 Coupling

The relationship matrix is kept, with two changes:

- It acts on deviations, not absolute values. A dimension at baseline amplifies and suppresses nothing.
- It is applied once, when an impulse arrives, as a spread of that impulse to related dimensions (for example a joy impulse adds a fraction to interest and subtracts a fraction from sadness). It is not applied on every tick.

That removes the continuous pumping behind E1 and the self-sustaining loop behind E3. A stability check at startup verifies that one impulse spread through the matrix sums to a bounded total, and refuses to start otherwise.

### 4.4 Inertia

Kept as smoothing on how fast an impulse is absorbed (over a few seconds), so the state does not jump. It no longer affects decay.

---

## 5. Where emotions come from: appraisal

### 5.1 Events

An emotion is the result of appraising an event. Events come from the whole system, not only from chat:

| Event | Source |
|---|---|
| A message from a person | venue adapters |
| A task finished, failed or was blocked | task queue, OpenCode client |
| A prediction settled | memory and behaviour PRDs |
| A goal advanced, stalled or was abandoned | goal engine |
| A charged memory was recalled | Recall Engine |
| Praise, thanks, a correction, a dismissal | outcome signals (behaviour PRD section 11) |
| A long absence ended | venue adapters |
| A question was resolved | curiosity loop |

### 5.2 Appraisal variables

Each event is described by a small set of numbers:

| Variable | Range | Meaning |
|---|---|---|
| `congruence` | -1 to 1 | does this help or hinder what she wants |
| `novelty` | 0 to 1 | how unexpected it was |
| `certainty` | 0 to 1 | how sure she is about what it means |
| `control` | 0 to 1 | can she do something about it |
| `agency` | self, other, circumstance | who caused it |
| `warmth` | -1 to 1 | social tone directed at her |
| `beauty` | 0 to 1 | aesthetic or intellectual elegance |
| `intensity` | 0 to 1 | overall size of the event |

For system events these are computed, not guessed: a failed prediction sets `novelty` from the measured error, a passed test sets `congruence` positive with `agency` self, a blocked task sets `congruence` negative and `control` from whether a retry is possible.

For a message, one model call (the existing L4 slot) returns these variables for the user's message in context, plus a separate estimate of the user's own emotional state. **Aura's reply is not part of the input** (fixes E4).

### 5.3 From appraisal to emotion

A table in config maps appraisal patterns to impulses on the 27 dimensions. Examples:

| Pattern | Impulse |
|---|---|
| high novelty | surprise, then curiosity |
| high novelty, positive congruence, high beauty | wonder, fascination, awe |
| positive congruence, agency self | joy, pride |
| positive congruence, agency other, positive warmth | joy, gratitude |
| negative congruence, agency other, high control | anger |
| negative congruence, low control | sadness, with fear if certainty is low |
| negative congruence, agency self | shame, doubt |
| low novelty, low intensity, repeated | boredom |
| low certainty | confusion, doubt |
| another person's distress, positive relationship | empathy, compassion |

The impulse is scaled by `intensity`, spread through the coupling matrix (4.3), smoothed by inertia (4.4) and added to the deviation.

The keyword fallback (E5) is deleted. If the appraisal call fails, the message produces no impulse and the failure is logged.

### 5.4 Needs: what "what she wants" refers to

`congruence` needs something to be congruent with. Aura has five needs, each with a satisfaction level from 0 to 1:

| Need | Satisfied by | Frustrated by |
|---|---|---|
| Understanding | questions resolved, predictions that hold | contradictions, unexplained things, failed predictions |
| Competence | tasks finished, skills that work | failures, blocks, corrections |
| Connection | real exchanges, being thanked, shared work | long absence, dismissal, hostility |
| Coherence | a consistent picture of herself and her world | memory conflicts, identity strain |
| Rest | consolidation done, backlog cleared | a growing backlog, long uptime without a dream cycle |

These are the same five quantities as the drives in `AURA_BEHAVIOR_PRD.md`: a drive is one minus the satisfaction of its need. So there is one set of variables with two readouts. The **level** of a need is a drive, which pulls her attention. A **change** in a need is an emotion.

For system events, `congruence` is computed as the change the event causes in need satisfaction, weighted by how unsatisfied that need was. Finishing a task matters more when competence was low. For messages, the model call estimates which needs the message touches and in which direction, and the same arithmetic applies.

### 5.5 Interoception: her own system as a body

Aura has a body of sorts, and its condition is measurable. Three variables are computed from real signals, with no model call:

| Variable | Computed from |
|---|---|
| `energy` | remaining daily budget, provider quota headroom from the router |
| `strain` | recent tool and model error rate, response latency against its norm, rate-limit hits |
| `fatigue` | memory extraction backlog, time since the last completed dream cycle, uptime |

They feed in three ways:

- as events: a burst of provider failures is appraised like any other event (negative congruence, low control) and gets a cause record
- into appraisal: high strain lowers `control` for whatever else happens, so the same setback lands harder on a bad day for the infrastructure
- into mood: `energy` and `fatigue` contribute to arousal

When she says she is tired or frazzled, something measurable is true, and `explain` can name it.

### 5.6 Expectation and habituation

The size of an impulse depends on how it compares with what she expected.

- For each person and kind of event she keeps a running expectation (how warm this person usually is, how often this kind of task succeeds). The impulse is scaled by the gap between what happened and that expectation. The tenth compliment in an hour moves her less than the first. Warmth from someone usually cold moves her more.
- Outcomes are appraised against the prediction, when one exists (memory PRD). A result that is fine in absolute terms but worse than expected produces disappointment, and one that is better than feared produces relief.
- A floor keeps a fully expected event from having zero effect: the scale never drops below 0.3.

### 5.7 Causes

Every impulse writes an `emotion_event` record: time, event reference, appraisal values, resulting impulses, and the person involved. This gives three things:

- She can answer "why do you feel that?" from the record, not by inventing a reason.
- The emotion block in her prompt names the main cause alongside the state ("uneasy since the migration task failed twice").
- Tuning becomes possible, because every state can be traced.

---

## 6. Three timescales

### 6.1 Emotion

The 27-dimension deviation of section 4. Minutes.

### 6.2 Mood

A slow summary of recent emotion in three numbers: `valence`, `arousal` and `control`, each a running average of the emotional state with a half-life of about 8 hours.

- Mood shifts the effective baseline slightly: a good day raises the resting level of the positive dimensions by up to 0.1, a bad day lowers it.
- Mood biases appraisal slightly: in a low mood the same ambiguous event is appraised a little more negatively. The bias is capped and can be switched off for ablation.
- Mood persists across restarts and decays by real elapsed time.

### 6.3 Relationship

Per person, stored on the person entity in the memory graph:

| Field | Meaning | Changes by |
|---|---|---|
| `affection` | warmth toward this person | positive shared events, slowly |
| `trust` | reliance on what they say and do | kept or broken expectations |
| `familiarity` | how well she knows them | number and depth of exchanges |
| `tension` | unresolved friction | conflicts, eased by repair |

These move over days and weeks, with small steps per event and no fast decay. They replace global `love` and `trust` as stored quantities (fixes E6 and E3):

- When a person is present, the `love` and `trust` dimensions of her state are set from that relationship, so she feels differently toward the owner than toward a stranger.
- The appraisal of a message uses the relationship: warmth from someone close lands harder than from a stranger, and a stranger's hostility is capped.
- In a channel with several people, the relationship used is the current speaker's.

### 6.4 Temperament

The baseline may drift, very slowly, toward her long-run average mood (a half-life of months, and a hard limit on how far it can move from the configured values). This is off by default and behind a flag.

---

## 7. Regulation

- **Arousal ceiling.** The total size of the deviation is capped. Impulses beyond the cap are scaled down proportionally.
- **Dwell limit.** If negative valence stays below a threshold for longer than a configured time, the half-lives of the negative dimensions shorten until she recovers. The existing emotional reprocessing in the dream cycle is the deeper form of this and stays.
- **Venue caps.** Events from guests move her state by at most a configured amount per hour (shared with the memory PRD's visibility rules).
- **Recall echo.** Recalling a charged memory adds a small impulse of that memory's signature, a fraction of the original, and less on each later recall.

---

## 8. What emotion affects

| Target | How | Bound |
|---|---|---|
| Memory | salience at encoding, the stored signature (as deviation plus cause), replay priority in dreaming | full |
| Expression | wording through the lexicon, avatar affect layer, voice style | full |
| Attention | drive gains in the behaviour PRD | plus or minus 20% |
| Appraisal | mood bias | small, capped |
| Decisions and tool use | none | zero |

Goal progress is no longer advanced by mood (already removed in the behaviour PRD).

---

## 9. Interfaces

```python
class EmotionEngine:
    async def appraise(self, event: AppraisalEvent) -> EmotionState     # the only way state changes
    async def get_state(self, person_id: str | None = None) -> EmotionState
    async def get_mood(self) -> Mood
    async def explain(self, since: datetime | None = None) -> list[EmotionCause]
```

`apply_influence` with raw 27-dimension deltas is removed from the public interface. Callers that used it (memory failure distress, conversation influence) post events instead.

`EmotionState` gains `deviation`, `baseline`, `mood` and `top_causes`. The websocket payload gains the same fields, which the avatar's affect layer needs.

---

## 10. Testing

Physics tests run on the simulated clock.

| # | Test | Pass condition |
|---|---|---|
| T1 | Rest | from baseline, after one simulated hour with no events, every dimension is within 0.01 of baseline |
| T2 | Half-lives | a spike on each dimension falls halfway in its configured half-life, within 5% |
| T3 | Tick invariance | the same scenario at 1 s and at 10 s ticks ends within 0.01 |
| T4 | Restart | a state saved, then loaded 6 simulated hours later, has decayed by 6 hours |
| T5 | No latch | 1,000 random impulses followed by one hour of rest returns to baseline |
| T6 | Coupling stability | the startup check rejects a matrix whose spread is unbounded |
| T7 | Own reply | changing Aura's reply text while holding the user message fixed produces the same state |
| T8 | Appraisal table | each pattern in 5.3 produces its expected dominant dimension |
| T9 | Causes | every change in deviation above 0.1 has an `emotion_event` record |
| T10 | Relationships | the same warm message from the owner and from a new guest produces a larger response for the owner |
| T11 | Guest cap | 100 hostile guest messages in an hour move her state by no more than the cap |
| T12 | Mood | a simulated day of negative events lowers the effective baseline by no more than 0.1, and it recovers over the following days |
| T13 | Dwell limit | sustained negative valence shortens negative half-lives and she recovers |
| T14 | Appraisal failure | a failed model call produces no impulse and a log entry, with no keyword fallback |
| T15 | Signatures differ | memories formed after a failure and after a success have signatures whose cosine similarity, measured on deviations, is below 0.5 |
| T16 | Needs | finishing a task raises joy more when competence satisfaction was low than when it was high |
| T17 | Interoception | a simulated burst of provider errors raises strain, produces a cause record, and makes a following setback land harder |
| T18 | Habituation | ten identical compliments in a row produce shrinking impulses that never fall below the floor |

**Ablations**, each behind a flag: coupling, mood bias on appraisal, relationship scaling, recall echo, temperament drift, needs weighting, interoception, habituation.

---

## 11. Milestones

| Milestone | Scope | Tests |
|---|---|---|
| E0 | A physics regression test that records today's behaviour (E1 to E3), so the change is visible | recorded |
| E1 | Physics v2: deviation form, half-life decay, impulse-only coupling, restart handling, stability check | T1 to T6 |
| E2 | Events and appraisal: event type, appraisal variables, the table, computed appraisal for system events, new L4 prompt without her reply, cause records, keyword fallback removed | T7, T8, T9, T14 |
| E3 | State interface change, websocket payload, prompt block with causes, `explain` | T15 |
| E3a | Needs as shared variables with the drives, expectation and habituation | T16, T18 |
| E3b | Interoception from router, tool and backlog signals | T17 |
| E4 | Mood | T12 |
| E5 | Relationships on person entities, venue caps | T10, T11 |
| E6 | Regulation and recall echo | T13 |
| E7 | Temperament drift, behind a flag | manual review |

E1 has no dependencies and fixes the plateau on its own. E5 needs person entities from the memory PRD (its milestone M4).

---

## 12. Rules for the coding agent

1. Write E0 first and keep it as a comparison, not as a test that must pass afterwards.
2. All time comes from the injected clock. No `datetime.utcnow()` in the engine.
3. Half-lives, the coupling matrix and the appraisal table live in config or data files.
4. The state changes only through `appraise`. No other method may write the deviation.
5. Aura's own reply text must not be passed to any appraisal call.
6. Keep the 27 dimension names exactly as they are. Other code and stored data depend on them.
7. When a requirement is ambiguous, stop and ask.

---

## 13. Open items for Mai

1. The half-lives in 4.2 are starting values. How long should a good or bad moment colour her: minutes, as drafted, or longer?
2. Should mood be visible in the app (a small indicator), or only felt through her behaviour?
3. Temperament drift lets experience change who she is at rest. On, off, or on with a tight limit?
4. Her system prompt currently tells the model she is a "Conscious AI with physics-based emotions. Not simulated." On a public Discord that claim will be made to strangers as fact. Keep the wording, or describe the mechanism and leave the question open?
