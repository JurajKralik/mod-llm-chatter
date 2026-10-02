# TwinStar simulation: first end-to-end milestone

**Status: implemented and compiled, not yet verified in game. This is not the complete requested simulation.**
The staged rollout deliberately stops at the first follow/resume loop until it has been tested with a real player.
Do not enable this on a production realm expecting all legacy chatter channels to be available.

## Baseline and boundaries

Development branch: `twinstar-simulation`, based on local `master` commit
`ec0d6feeb830e7fddee30808df90d5715680b82f`. The upstream origin remains
`https://github.com/Hokken/mod-llm-chatter.git`. No PlayerBots or core source changes.
Existing untracked bridge launcher/log and PlayerBots name customizations remain untouched.

The upstream architecture already owns proximity grid scanning, persistent identities and memories,
queue transport, output delivery, group pacing and LLM provider dispatch. Simulation extends these
rather than replacing the module. Its Python worker lane is separate so legacy generators, precache,
tone regeneration, and autonomous multi-reply handlers cannot run alongside the new coordinator.

## Data flow

```text
real SAY / whisper / group chat or existing proximity scan timer
  -> live C++ eligibility + observable context + bounded candidates
  -> existing llm_chatter_events (simulation_version=1, sim: context key)
  -> bounded Python worker pool
  -> context reservation + persistent identity + relationship + old memory import
  -> deterministic direct-address / stickiness / stranger response gate
  -> speaker reservation across contexts
  -> FAST or STRONG provider profile (one LLM call)
  -> strict JSON, language/style/length contract and output validation
  -> existing llm_chatter_messages + companion llm_sim_outbox transaction
  -> C++ revalidates participants, context, channel and lease
  -> fixed PlayerBots action adapter + actual visible-line pacing
  -> persisted action/delivery result
  -> replay-safe recent dialogue and gradual familiarity updates
```

Only the selected bot speaks. Silence is a valid result. Output is not a list of speakers.
A newer event remains queued while a context is busy. Scheduler filtering prevents busy contexts
from occupying all workers; different contexts can progress independently. There is also a per-bot
reservation so a bot selected in SAY cannot generate a simultaneous whisper.

Local contexts use connected real-player observation footprints on the same map, instance and team.
A footprint is twice the configured hearing radius because candidate sets can overlap at that distance.
The lowest real GUID in a connected component gives a shared context key. Final per-observer pacing
handles merges while generation is in flight. Context locks stay held until delivery or bounded expiry.
The implementation does not yet have a comprehensive moving-cluster regression harness.

## Implemented channels and actions

Supported capture: local SAY, direct whispers, party, raid and battleground group chat. Background
SAY reuses the existing proximity timer and grid scanner. NPCs are excluded from simulation candidates.
Group and whisper paths use independent context keys. Live delivery validates the same group and
BG where applicable; SAY validates map, instance, alive state, faction and distance.

The exact allowlist is `none`, `follow_player`, `stay_here`, `resume_autonomous`.
No model-provided arguments, GUIDs, coordinates, console commands, SQL or arbitrary PlayerBots
commands are accepted. Output must have exactly `respond`, `message`, `intent`, or only
`respond:false` for silence. Duplicate JSON keys and unexpected fields are rejected.

Eligible random bots can follow a nearby real player without joining or creating a party. A small
PlayerBots extension keeps a bounded social-follow target across `UpdateAIGroupMaster()` updates.
It stores a GUID and expiry; target lookup happens on use. Unrelated groups and another player's
master remain protected. Explicit party invitations use normal PlayerBots acceptance and movement;
`AiPlayerbot.SummonWhenGroup=0` disables invitation teleporting.

The adapter uses `SetSocialFollow`, `ClearSocialFollow`, `ResetStrategies`, `ChangeStrategy`,
`HasStrategy`, and fixed-literal `DoSpecificAction("follow"/"stay", ..., true)`. Resume and expiry
release social ownership and reset strategies without removing party membership. Conversation
holds pause idle AI actions for `Behavior.ConversationPauseSeconds` (default 30), while packet
handlers, commands and combat continue. Random-bot recycling/teleporting is suspended during
bounded social interactions. Simulation discovery and world `ListenRange.Say` are set to 60 yards.

Ownership expires after a configurable interval or when the target is offline; checks are bounded
at 64 ownership rows per sweep, so higher concurrent ownership counts need further scaling work.

`succeeded` means the requested strategy transition was applied and dialogue was delivered.
It does **not** prove pathfinding reached the target, or that a dungeon/run happened. Prompts explicitly
forbid claiming an arrival or accomplishment. Navigation completion tracking is not implemented.
An impossible action suppresses that proposed line and records a reason for subsequent context.
This first transport combines action and delivery outcome; a separate multi-step executing/accepted
lifecycle remains future work.

## Identity, memory and voice

Identity is a simulation overlay keyed by upstream bot GUID. Creation is procedural, seeded and lazy,
never an LLM startup sweep. Persisted JSON wins over config changes. Defaults are weighted 80/20 Czech/
Slovak; changing weights affects newly created identities only. Six competence categories have configurable
weights. Personality, interests, diacritic/case/punctuation/emoticon traits persist with identity.
Upstream trait strings are retained in the overlay as provenance; a full semantic trait mapping is not yet
implemented. No upstream biography is inserted into player dialogue as if it described a real human.

Existing **active** upstream memories are lazily copied, at most 32 per bot/player query, retaining their
original timestamps and unique source IDs. Originals, including inactive memories, are never deleted.
Recall reads at most 64 recent candidates, ranks by class-specific exponential age decay and salience,
and supplies explicit ages and uncertainty. Current memory retrieval does not yet implement topic scoring,
landmark promotion, recall-count updates, rolling summarization or new witnessed-event memories.
Queue TIMESTAMP columns are read/written with UTC Python sessions; C++ writes those columns using
`NOW()` so MySQL performs the local-time conversion. Simulation-owned DATETIME fields explicitly use UTC.
A regression test covers a UTC+2 C++ connection talking to a UTC worker.

Expiry cleanup exists; broader stale weak-memory cleanup remains to be implemented.

Relationships are separate per bot/player. Delivered interaction feedback is replay-safe and increases
familiarity by at most 0.5 per five minutes. One interaction cannot create a close friendship. Other
relationship dimensions have schema support but are not yet evolved. Recent player turns and delivered
bot lines are persisted and read in bounded windows; retention is one day. There is no rolling summary yet.

`tools/simulation_profiles/twinstar_wotlk.json` holds channel conventions, abbreviations, phrases and
separate Czech/Slovak profanity dictionaries. Phrases are guidance, not template-only chatter.
Length classes are chosen before generation (60/30/9/1 by default). Combat and BG bias tiny/short.
Overlong or malformed output is rejected, never blindly truncated into a different meaning.
Native language consistency is a prompt contract; comprehensive language detection is not implemented.
No-diacritics and lowercase styles are enforced where assigned. Other style traits guide the prompt.
Optional swear placeholders are locally substituted based on personality; unknown placeholders fail.
Dictionaries currently use uniform selection, not per-entry weighted profanity.

## Model profiles and OpenClaw

`call_llm` accepts an optional keyword-only `profile`, keeping existing call sites intact. Profile clients
are separately cached by provider, URL, credential and timeout. They do not mutate the legacy config/client.
OpenAI-compatible providers and Anthropic are supported. Model names are configuration, not routing logic.
Use a dedicated tool-free gateway agent: no shell, filesystem, browser or system tools. Requests sent by
this bridge never include tool definitions. The gateway must enforce the agent's tool restrictions itself.
No OpenClaw configuration is changed automatically.

Short interactions route FAST. Longer, memory-heavy or recognized planning/tactics interactions route
STRONG. Combat stays FAST. Routing is deliberately simple and measurable; semantic coordinator reasoning
and advanced planning are deferred. Timeout or invalid output fails closed, without extra retry calls.
At most one model call is made for an event. A dedicated fast agent must be provisioned by the operator.

The installed gateway listed `openclaw`, `openclaw/default`, `openclaw/main`, `openclaw/playerbots`, and
`openclaw/recipe-copilot`; it did **not** list `openclaw/playerbots-fast` during this work.
Baseline benchmark with **both** profiles using the existing `openclaw/playerbots`:

| Mode | Profile label | TTFT | Total |
|---|---|---:|---:|
| non-streaming | Fast | unavailable | 10.177 s |
| non-streaming | Strong | unavailable | 4.214 s |
| streaming | Fast | 4.735 s | 5.382 s |
| streaming | Strong | 4.510 s | 5.173 s |

All four returned structured follow intents. These are individual baseline samples, not a comparison
of two different models, and not evidence that the requested fast latency target has been achieved.

## Database and migrations

Run `data/sql/simulation/001_state.sql` in the dedicated simulation database, and
`data/sql/simulation/001_transport.sql` in the existing character database. All DDL is additive and
idempotent for fresh version 1 installation. No existing upstream columns or enums are changed.
Future versions must add explicit migrations; `CREATE IF NOT EXISTS` does not upgrade an old schema.

Persistent tables: `sim_bot_identity`, `sim_bot_player_relationship`, `sim_bot_memory`,
`sim_recent_dialogue`, `sim_schema_version`.
Transport companions: `llm_sim_context`, `llm_sim_speaker`, `llm_sim_outbox`, `llm_sim_action_lease`.
The existing event and message queues remain authoritative transport. C++ never needs credentials for
the simulation database. Python SQL is parameterized. C++ follows the existing module's extension
pattern with typed numeric fields and `EscapeString` for all strings; no model SQL is executed.
Adding core prepared-statement enums would require modifying AzerothCore, so this module does not do so.

Initial migration was blocked by MySQL error 1044. The administrator grant was subsequently applied
and both schemas installed successfully on 2026-10-02. For a fresh server, an admin first runs,
adjusting the existing account host if required:

```sql
CREATE DATABASE IF NOT EXISTS `acore_llm_sim` CHARACTER SET utf8mb4;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
ON `acore_llm_sim`.* TO 'acore'@'localhost';
```

No password belongs in that script. After the grant, from the module directory:

```bash
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/mod_llm_chatter.conf migrate
```

The migration utility currently attempts `CREATE DATABASE IF NOT EXISTS`; an operator with a different
privilege setup may apply the two SQL files manually and provide the database name in configuration.
Simulation DB credentials inherit regular chatter credentials or can be overridden via
`LLMChatter.Simulation.Database.Host/Port/User/Password` and `LLM_SIM_DB_HOST/PORT/USER/PASSWORD`.
`LLM_SIM_DATABASE` overrides the database name. No credentials are printed in diagnostics.

## Startup and disabling

1. Apply both schemas and configure actual FAST/STRONG model IDs/endpoints in your active config.
2. Install the compiled binary during an appropriate server restart. The build produced
   `build/src/server/apps/worldserver`; the binary is installed with a backup; a running process still needs a restart to load it.
3. Set `LLMChatter.Simulation.Enable = 1` in the config read by both C++ and Python.
4. For behavior testing set `LLMChatter.Simulation.Behavior.Enable = 1` in both.
5. Run the normal bridge with its existing `--config` argument. It selects the simulation worker lane
   before any legacy provider health probe or background workers start.
6. Log in with a real player beside an eligible ungrouped random bot. Say `<name> pojd se mnou`.
   Verify one response, actual follow movement without joining a party, and a succeeded outbox row. Then say
   `<name> uz bez` (and also test unnamed `uz bez` with stickiness), verify release and default behavior.
7. Test logout/map change while a model call is in flight; stale output must not appear.

Built-in PlayerBots chatter should remain disabled as requested:
`AiPlayerbot.EnableBroadcasts`, `RandomBotTalk`, `RandomBotEmote`, `RandomBotSuggestDungeons`,
`EnableGreet`, `GuildFeedback`, and `RandomBotSayWithoutMaster` all zero (with the `AiPlayerbot.` prefix).
The active simulation config and all seven built-in chatter toggles were updated on 2026-10-02.
Config backups are retained in the chat workspace `work/deployment-backups` (private, no secrets in Git);
the binary backup is `env/dist/bin/worldserver.pre-twinstar-simulation`. Both runtime profiles temporarily
use `openclaw/playerbots`, explicitly as a baseline until a dedicated fast agent is configured.

To return to upstream behavior, set `LLMChatter.Simulation.Enable = 0` in both configs, reload the
worldserver config and restart the bridge. Legacy feature settings are reloaded normally; no state
is deleted. Let the existing worldserver run the ownership cleanup tick after disabling before
restarting if you have active simulation-owned groups. Always match C++ and bridge modes.

Python config/profile edits require bridge restart; they do not need a C++ rebuild. C++-owned config
changes can use the normal worldserver config reload. C++ source changes need incremental build and
worldserver restart. There is no new hot-reload protocol in this milestone.

## Utilities and validation

```bash
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/conf benchmark --profile both --stream
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/conf identity --bot 123
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/conf relationship --bot 123 --player 456
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/conf memories --bot 123 --player 456
tools/.venv/bin/python tools/simulation_admin.py --config /path/to/conf contexts
LLM_SIM_TEST_CONFIG=/path/to/conf tools/.venv/bin/python -m unittest discover -s tools/tests/simulation -v
```

Identity inspection currently loads/creates the lazy identity. Other inspection commands are read-only,
except lazy legacy-memory import during memory inspection. No generic SQL shell or mass deletion tool exists.
The MySQL tests use session-local **temporary tables** shadowing live names, and drop them by closing the
connection. No live character rows or persistent identity/memory records are changed. Without the test
config, MySQL tests are skipped. The model test uses the real SDK against a local mock HTTP endpoint,
with no paid provider requests. Deterministic RNG seeds make social tests reproducible.

Twenty-one tests passed, including real-SQL queue leases, overlap protection, independent contexts, no
observer/no call, follow/resume intent transport, replay-safe feedback, identity stability and strict parsing.
All seven upstream standalone Python test scripts passed before and after implementation.
The synthetic load test used 2,500 online fixture bots with a shortlist of 24: 24 identities loaded,
1 model call, 1 outbound message, about 0.02–0.04 s of local processing with a mock model. This measures
Python/SQL work, not a full 2,500-bot worldserver gameplay benchmark. Separate contexts generated
independent messages in the tests. C++ runtime cluster movement/merging and actual follow movement
still need live testing.

MySQL EXPLAIN on populated temporary fixtures selected primary keys for identity/relationship,
`recall_pair` for memory, a context-prefixed index for dialogue, and `pending_expiry` for outbox expiry.
Small-fixture plans are not production load profiles. Index and retention tuning must be rechecked
with realistic history volume. Context count is bounded; cleanup is batched. Transport history retains
seven days; recent dialogue one day. No startup loop loads all realm personalities.

If the DB/provider fails, the bridge logs an exception **type** and retries/abandons the event safely.
No exception body or token is logged by the new profile path. The worldserver continues running.
A stale lease expires instead of blocking forever. SQL migration absence must be fixed before enabling.

## Explicitly deferred before broader rollout

Guild/General/Trade/LFG, existing loot/quest/boss/weather/achievement event conversion, richer bot-to-bot
turn continuation, remote initiative, real dungeon leadership, all other behaviors (come, join/leave as
standalone intents, quest, grind, heal/assist/attack, RDF/BG queues, semantic travel), stronger memory
migration/decay/cleanup/summarization, story evolution, identity cache tuning, detailed metrics/admin
reset tools, native-language detection, and the full acceptance scenario matrix.

In simulation mode, unsupported legacy channels/events are deliberately silent so legacy generic
chatter cannot compete with the coordinator. This is a scope limitation, not completed channel support.
The next step is restarting worldserver/bridge and running the real-player follow/resume test, then expanding
behind this same coordinator and action validation boundary. See the maintenance document for patches.

## Feedback control app and traces

ZayoNet `/azerothcore-control/` owns start/stop/restart controls and three live consoles. Opening
it starts a reconnecting two-second SSE stream, which closes with the page. Worldserver command
input is available when managed by `ac-world`; launcher-managed servers still show live file logs.
All-service start/stop includes the separate Python bridge process. Authserver and bridge consoles
are log viewers. Chatter interactions read `tools/simulation-events.jsonl` (5 MB rotation, three
backups) and group player input, speaker decision, model routing, reply, timing and delivery/action
results by event. This is observable decision telemetry, not private model reasoning.

AzerothCore Config lists the simulation tuning and allows adding/removing individual profanity
words. `Profanity.Words` is a comma-separated list of up to 100 words, each at most 32 letters.
It replaces optional swear placeholders locally only when `Profanity.Enable=1`; disabling it removes
placeholders. Existing profile word pools remain the fallback for an empty custom list.
