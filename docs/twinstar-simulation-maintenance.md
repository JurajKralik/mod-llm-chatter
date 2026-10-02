# Upstream maintenance

Origin remains the original Hokken repository. The simulation branch is published in
`JurajKralik/mod-llm-chatter`, with companion changes in `JurajKralik/mod-playerbots`.
Custom launcher/log and name-data files are excluded from commits. The server still runs the
previously installed binary until an explicit build and deployment.

## Patched upstream files

| File | Small extension / expected conflict area |
|---|---|
| `tools/chatter_llm.py` | keyword-only profile, isolated client/config selection, secret-safe profile errors |
| `tools/llm_chatter_bridge.py` | early simulation worker-lane dispatch before legacy initialization |
| `conf/mod_llm_chatter.conf.dist` | appended documented simulation namespace |
| `src/LLMChatterConfig.cpp` | load simulation config; disable competing legacy producers in simulation mode |
| `src/LLMChatterProximity.cpp` | expose existing grid scanner; delegate simulation SAY/background capture |
| `src/LLMChatterGroupCombat.cpp` | keep local SAY capture, bypass legacy group player-message generation |
| `src/LLMChatterShared.cpp` | accept only simulation-tagged event writes; suppress instant legacy party speech |
| `src/LLMChatterDelivery.cpp` | delegate simulation-owned rows before legacy channel dispatch |
| `src/LLMChatterWorld.cpp` | action lease cleanup; reuse proximity cadence without legacy world generators |
| `src/LLMChatterScript.cpp` | register the simulation PlayerScript hooks |

The highest risk conflicts are bridge startup, provider signature, delivery claim/dispatch ordering and
proximity hook guards. Preserve the original `QueueChatterEvent` contract: extra JSON must already be
SQL-escaped. Simulation passes `EscapeString` once after constructing valid JSON. All other queue
parameters still go through upstream's own escaping. The bridge worker lane uses existing transport
tables with additive companion tables, so no event ENUM or core DB statement list is changed.

New code lives in `tools/simulation/`, `tools/simulation_admin.py`,
`tools/simulation_profiles/twinstar_wotlk.json`, `src/LLMChatterSimulation.{h,cpp}`,
`tools/tests/simulation/` and `data/sql/simulation/`. Schema DDL lives outside auto-applied upstream
base/updates intentionally: the dedicated database requires an explicit administrator grant.
No destructive migration or data reset is part of this feature.

## Rebase procedure

Commit/stash your own work first. Fetch origin, inspect changes to the ten touchpoints, and rebase
`twinstar-simulation` onto the chosen tested upstream commit. Do not overwrite the origin remote or
force-push. Review upstream schema changes before applying any new migration. Keep simulation disabled
while evaluating a major upstream update.

Run the seven existing `tools/tests/test_*.py` scripts and new simulation unittest discovery. Run import
checks with the installed bridge venv. Run CMake configuration only when the source list/build structure
changes; otherwise use `cmake --build build --target worldserver -j2`. Never delete the build directory.
Verify the small PlayerBots social-follow patch is present before building the adapter; the upstream
ungrouped-master reset must preserve a valid bounded social follow. Recheck fixed action names and
strategy APIs after rebasing.

Core lint scripts scan existing code outside this module and report pre-existing issues. The module C++
scan also reports existing upstream whitespace/qualifier/NPC-flag warnings; no diagnostic was emitted
for the new simulation adapter. The SQL linter attempts a core-repository fetch and could not complete
because core `.git/FETCH_HEAD` is read-only. Actual migration DDL and query plans were exercised with
MySQL temporary tables. Do not rewrite unrelated formatting or persistent SQL to satisfy generic lints.

Before deployment, verify the real follow/resume loop, stop/restart behavior, observer departure during
LLM latency, two nearby observers, independent remote contexts, and restoration of legacy mode. The
initial milestone has not yet passed those live gameplay checks and is not production-complete.

## Upstream integration (2026-10-02)

Merged Hokken master `9cbeb13` into the simulation branch. This imports provider compatibility,
shared personas, conversation threads, responsive player replies, richer proximity/PvP/duel
context, and Arathi Basin grounding. These legacy features remain subject to the simulation
coordinator's ownership gates; importing them does not enable parallel legacy speech.

Resolved the proximity API change (`CheckProximityChatter(bool instanceMaps)`) and scan timer
rename while preserving the simulation scanner. Refreshed CMake once to collect new upstream
source files. Upstream extracted event SQL construction into a string-returning helper;
simulation suppression now guards both event enqueue entry points, not that helper.
The Arathi snapshot test disables personality spice sampling when comparing snapshot-independent
prompts because upstream now remembers recently used spices.

PlayerBots master `037c0141` was inspected. Full promotion requires core APIs absent from the
installed core (`ModuleDatabasePool.h`, `DatabaseScript::OnModuleDatabasesLoading`). Seven
independent fixes were cherry-picked, preserving original authors and commit references:
`a22a11c2`, `7e9de982`, `9f13694c`, `c336f9b8`, `bf6190b2`, `7fcc0ffa`, `4517bfcf`.
The bounded social follow, conversation hold and walk-on-invite customizations remain present.

Before deployment, back up the character database, review upstream dated SQL updates and runtime
`ensure_tables` changes, then compile against the paired core and run gameplay acceptance. No SQL
updates or service restart were performed during this source integration. Newly imported persona,
thread and battleground features are not yet routed into the custom simulation coordinator.

Validation: 524 pytest cases and 37 subtests passed (11 database cases skipped in that run);
all 22 simulation unittest cases subsequently passed with session-local temporary MySQL tables.
PlayerBots module C++ codestyle passed. Chatter/core linters report upstream style issues;
the core SQL checker cannot fetch because core Git metadata is read-only.
