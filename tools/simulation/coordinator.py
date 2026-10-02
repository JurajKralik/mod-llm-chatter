"""One reservation per observable context through actual visible delivery."""
import json
import logging
import random
import time
from datetime import datetime, timezone

from simulation.domain import select_speaker, route, length_class, parse_response, relationship_label
from simulation.prompts import build_prompt
from simulation.store import Store, connect
from simulation.telemetry import record

log = logging.getLogger(__name__)


def handle(event, transport, settings, rng=None, llm=None):
    rng = rng or random.Random()
    if llm is None:
        from chatter_llm import call_llm
        llm = call_llm
    payload = event['extra_data']
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict) or payload.get('simulation_version') != 1:
        return finish(transport, event['id'], 'skipped')
    context = payload['context_key']
    record('received', event=event['id'], context=context, channel=payload.get('channel'),
           player=payload.get('player_name'), message=payload.get('player_message', ''),
           candidates=[c['name'] for c in payload.get('candidates', [])])
    created = event['created_at']
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() > settings['Conversation.EventMaxAgeSeconds']:
        return finish(transport, event['id'], 'expired')
    with transport.cursor(dictionary=True) as cur:
        cur.execute('SELECT online FROM characters WHERE guid=%s', (payload['player_guid'],))
        player = cur.fetchone()
        if not player or not player['online']:
            return finish(transport, event['id'], 'skipped')
        cur.execute('SELECT COUNT(*) AS n FROM llm_sim_context')
        count = cur.fetchone()['n']
        cur.execute('SELECT context_key FROM llm_sim_context WHERE context_key=%s', (context,))
        if not cur.fetchone() and count >= settings['Conversation.MaxContexts']:
            return finish(transport, event['id'], 'skipped')
        cur.execute('INSERT IGNORE INTO llm_sim_context(context_key) VALUES(%s)', (context,))
        cur.execute('UPDATE llm_sim_context SET event_id=%s,lease_until=UTC_TIMESTAMP()+INTERVAL %s SECOND WHERE context_key=%s AND (lease_until IS NULL OR lease_until<UTC_TIMESTAMP()) AND (next_visible_at IS NULL OR next_visible_at<=UTC_TIMESTAMP())', (event['id'], int(settings['Conversation.LeaseSeconds']), context))
        reserved = cur.rowcount == 1
        transport.commit()
        if not reserved:
            # Queue the newer event instead of spawning concurrent replies or losing the player's turn.
            cur.execute("UPDATE llm_chatter_events SET status='pending',react_after=UTC_TIMESTAMP()+INTERVAL 2 SECOND WHERE id=%s", (event['id'],))
            transport.commit()
            return
        cur.execute('SELECT last_speaker FROM llm_sim_context WHERE context_key=%s', (context,))
        previous = cur.fetchone()['last_speaker']
    sim = None
    queued = False
    bot = None
    start = time.monotonic()
    try:
        sim = connect(settings)
        store = Store(sim, transport, settings)
        candidates = payload['candidates'][:int(settings['Conversation.MaxCandidates'])]
        identities = {c['guid']: store.identity(c['guid']) for c in candidates}
        relations = {c['guid']: store.relationship(c['guid'], payload['player_guid']) for c in candidates}
        chosen = select_speaker(candidates, payload.get('player_message', ''), previous, identities, relations, settings, rng, payload.get('direct_guid', 0))
        store.player_turn(context, event, payload)
        if not chosen:
            record('decision', event=event['id'], summary='No speaker passed the reaction policy; stay silent.')
            return finish(transport, event['id'], 'skipped')
        bot = chosen['guid']
        from simulation.domain import fold
        import re
        addressed = bool(payload.get('direct_guid')) or bool(re.search(
            r'(?<!\w)' + re.escape(fold(chosen['name'])) + r'(?!\w)',
            fold(payload.get('player_message', ''))))
        with transport.cursor() as cur:
            cur.execute('INSERT IGNORE INTO llm_sim_speaker(bot_guid) VALUES(%s)', (bot,))
            cur.execute('UPDATE llm_sim_speaker SET event_id=%s,lease_until=UTC_TIMESTAMP()+INTERVAL %s SECOND WHERE bot_guid=%s AND (lease_until IS NULL OR lease_until<UTC_TIMESTAMP()) AND (%s OR last_visible_at IS NULL OR last_visible_at<UTC_TIMESTAMP()-INTERVAL %s SECOND)',
                        (event['id'], int(settings['Conversation.LeaseSeconds']), bot, addressed or previous == bot,
                         int(settings['Conversation.BotGlobalCooldown'])))
            claimed = cur.rowcount == 1
            transport.commit()
            if not claimed:
                cur.execute("UPDATE llm_chatter_events SET status='pending',react_after=UTC_TIMESTAMP()+INTERVAL 2 SECOND WHERE id=%s", (event['id'],))
                transport.commit()
                return
        memories = store.memories(bot, payload['player_guid'])
        recent = store.recent(context)
        tier = route(payload.get('player_message', ''), memories, payload['channel'], chosen.get('combat', False))
        length = length_class(settings, rng, payload['channel'], chosen.get('combat', False))
        actions = {'none'}
        if settings.enabled('Behavior.Enable'):
            actions.update(chosen.get('actions', []))
        prompt = build_prompt(identities[bot], chosen, payload, recent, memories,
                              relationship_label(relations[bot], datetime.now(timezone.utc), settings),
                              length, actions, settings, store.results(bot, payload['player_guid']))
        record('decision', event=event['id'], bot=chosen['name'], profile=tier,
               model=str(settings.raw.get('LLMChatter.Simulation.Model.' + tier + '.Model', 'default')).strip('"'),
               summary=('Directly addressed' if addressed else 'Selected by conversation and reaction policy'),
               memories=len(memories), recent_turns=len(recent), length=length, allowed_actions=sorted(actions))
        raw = llm(None, prompt, settings.raw, max_tokens_override=220, profile=tier, label='simulation')
        # One model call in the first milestone. Malformed outputs fail closed without a second slow call.
        response = parse_response(raw, actions, length, identities[bot], settings, rng)
        if not response['respond']:
            record('decision', event=event['id'], bot=chosen['name'], summary='Model chose silence.')
            return finish(transport, event['id'], 'skipped')
        if any(t['speaker'] == chosen['name'] and t['message'] == response['message'] for t in recent[-4:]):
            return finish(transport, event['id'], 'skipped')
        elapsed = time.monotonic() - start
        created = event['created_at']
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        event_age = max(elapsed, (datetime.now(timezone.utc) - created).total_seconds())
        delay = max(0, rng.uniform(settings['Conversation.MinVisibleLineGap'], settings['Conversation.MaxVisibleLineGap']) - event_age)
        with transport.cursor() as cur:
            # Reservation may have expired/replaced during a slow call. Never insert stale work.
            cur.execute('SELECT event_id FROM llm_sim_context WHERE context_key=%s AND lease_until>UTC_TIMESTAMP() FOR UPDATE', (context,))
            row = cur.fetchone()
            if not row or row[0] != event['id']:
                transport.rollback()
                return finish(transport, event['id'], 'skipped')
            cur.execute('INSERT INTO llm_chatter_messages(event_id,bot_guid,bot_name,message,channel,player_guid,group_id,owner_subsystem,deliver_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP()+INTERVAL %s MICROSECOND)', (event['id'], bot, chosen['name'], response['message'], payload['channel'], payload['player_guid'], payload.get('group_id', 0), 'simulation', int(delay * 1e6)))
            mid = cur.lastrowid
            cur.execute('INSERT INTO llm_sim_outbox(message_id,event_id,context_key,bot_guid,player_guid,map_id,instance_id,group_id,guild_id,channel_id,intent,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP()+INTERVAL %s SECOND)', (mid, event['id'], context, bot, payload['player_guid'], payload['map_id'], payload['instance_id'], payload.get('group_id', 0), payload.get('guild_id', 0), payload.get('channel_id', 0), response['intent'], int(settings['Conversation.LeaseSeconds'])))
            cur.execute('UPDATE llm_sim_context SET lease_until=UTC_TIMESTAMP()+INTERVAL %s SECOND WHERE context_key=%s AND event_id=%s', (int(settings['Conversation.LeaseSeconds']), context, event['id']))
            cur.execute('UPDATE llm_sim_speaker SET lease_until=UTC_TIMESTAMP()+INTERVAL %s SECOND WHERE bot_guid=%s AND event_id=%s', (int(settings['Conversation.LeaseSeconds']), bot, event['id']))
        transport.commit()
        queued = True
        record('reply', event=event['id'], message_id=mid, bot=chosen['name'], player=payload.get('player_name'),
               channel=payload['channel'], message=response['message'], intent=response['intent'],
               profile=tier, generation_ms=int(elapsed * 1000), status='queued')
        finish(transport, event['id'], 'completed')
        log.info('simulation profile=%s generation_ms=%d channel=%s speaker=%d', tier, int(elapsed * 1000), payload['channel'], bot)
    except Exception as exc:
        transport.rollback()
        record('error', event=event['id'], summary='Response or event rejected', error=type(exc).__name__)
        log.warning('simulation event rejected: %s', type(exc).__name__)
        finish(transport, event['id'], 'skipped')
    finally:
        if sim:
            sim.close()
        if not queued:
            with transport.cursor() as cur:
                cur.execute('UPDATE llm_sim_context SET lease_until=NULL,event_id=NULL WHERE context_key=%s AND event_id=%s', (context, event['id']))
                if bot is not None:
                    cur.execute('UPDATE llm_sim_speaker SET lease_until=NULL,event_id=NULL WHERE bot_guid=%s AND event_id=%s', (bot, event['id']))
            transport.commit()


def finish(db, event_id, status):
    with db.cursor() as cur:
        cur.execute('UPDATE llm_chatter_events SET status=%s,processed_at=UTC_TIMESTAMP() WHERE id=%s', (status, event_id))
    db.commit()
