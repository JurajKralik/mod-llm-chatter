# Remaining work and acceptance ledger

This ledger preserves the scope of the original request. A compiled milestone is not completion.
Do not expand the behavior allowlist until the named follow/resume loop works with a real player.

| Phase | Current evidence | Remaining |
|---|---|---|
| 0 research | Installed code/docs, PlayerBots master/strategy APIs, remotes inspected; 7 baseline scripts passed | Keep validating actual gameplay APIs as actions expand |
| 1 schema/config | Dedicated DB and additive transport installed; indexed temporary-DB tests | Versioned upgrade runner beyond initial schema |
| 2 identity/language | Lazy persisted language/style/personality/competence; 2,500 identity distribution test | Meaningful upstream trait mapping, story evolution, bounded cache |
| 3 memory/relationships | Original active memories retained with age; bounded recent turns and familiarity | New witnessed events, rolling summaries, richer relationships, decay cleanup, significant landmarks |
| 4 coordinator | Context and speaker reservations, direct selection, stickiness, 30% stranger gate | Live moving-cluster dedup, busy-state breadth, coordinated later bot turns |
| 5 model routing | Configurable FAST/STRONG, SDK mock and actual gateway benchmark, TTFT tool | Dedicated faster model/agent; realistic percentile benchmarks; detailed metrics |
| 6 voice | CZ/SK contract, profile data, length classes, partial typography, profanity placeholders | Language validation, weighted slang/profanity entries, realistic typo tuning |
| 7 event integration | SAY/whisper/group player messages and proximity background path | Guild/General/Trade/LFG, loot/quests/achievements/weather/raid/BG events; no competing legacy path |
| 8 behavior transport | Strict three-action schema, result persistence, expiry and ownership | Separate accepted/executing/completion semantics, replay/crash stress matrix |
| 9 adapter | Follow/stay/resume C++ compiled; actual grouping to preserve random-bot master | Live movement, come/join/leave, quest/grind, support/combat, RDF/BG, semantic travel |
| 10 coherence | Actual delivery feeds bounded history, action failures enter future prompts | Dungeon organization, logical remote initiative, witnessed outcomes and memory |
| 11 performance | 2,500 fixture bots -> 24 identities / 1 call / 1 message; EXPLAIN checks | Sustained live 2,500-bot test, two real players, production SQL/history profiling |
| 12 docs | Architecture, setup/disable, configuration, baseline metrics and rebase notes | Final 26-point completion report after all accepted scope is implemented |

## Required next live checks

- Restart worldserver and bridge to load the installed binary and config.
- With a real player near an eligible ungrouped random bot: `<name> pojd se mnou`.
- Check exactly one reply, actual group membership and following, plus succeeded outbox feedback.
- Say `<name> uz bez` and then test the unnamed continuation `uz bez` in another run.
- Check group release and normal autonomous behavior. Repeat through party chat and whisper.
- Log out or move away during generation: no stale local line/action.
- Confirm a bot already owned/grouped by another real player is not taken over.
- Confirm two distant observers can progress independently and nearby observers do not get duplicate scenes.

As of deployment preparation no real player was online, no simulation event had been captured, and no
outbox action result existed. These live checks remain pending and must not be reported as passed.
