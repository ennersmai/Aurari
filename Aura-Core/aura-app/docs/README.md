# Aura and Sluice specs

## Start here

1. `AURA_BUILD_PLAN.md` is the entry point for the Aura work. It sequences everything else and holds the task cards.
2. `ROUTER_PRD.md` is the Sluice router. It is a separate repository and is already being built.

## The five Aura specs

The build plan pulls from these. Agents read the one a card names. You do not hand them over whole.

| File | Area | First needed in |
|---|---|---|
| `AURA_MEMORY_V2_PRD.md` | memory and the Recall Engine | wave 0 |
| `AURA_EMOTION_PRD.md` | emotion | wave 0 |
| `AURA_AGENCY_PRD.md` | OpenCode, tools, skills, learning | wave 1 |
| `AURA_BEHAVIOR_PRD.md` | initiative, curiosity, goals | wave 2 |
| `AURA_AVATAR_PRD.md` | avatar | wave 2 |

## Order of execution

1. Put all seven files in a `docs/specs/` folder in the Aura repository.
2. Wave 0 from the build plan (cards W0-01 to W0-05). Nothing changes behaviour.
3. Wave 1 (cards W1-01 to W1-16). W1-01 and W1-02 first: they are the security fixes.
4. Review between waves with the stronger model (build plan section 1.4).
5. Waves 2 to 5 are listed in the build plan by milestone. Their cards are written when the previous wave has landed.

## By hand, by Mai

Listed in section 6 of the build plan. The first is purging the database from git history.
