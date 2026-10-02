"""Parameterized persistence and lazy non-destructive upstream compatibility."""
import json
import os
from datetime import datetime, timezone

from simulation.domain import make_identity, memory_score, age_text
from simulation.telemetry import record


def transport_connect(config):
    """TIMESTAMP transport columns must be read/written in UTC by this worker.

    Core connections may use local time: MySQL converts TIMESTAMP at the boundary.
    Simulation-owned DATETIME columns always contain UTC by contract.
    """
    from chatter_db import get_db_connection
    db = get_db_connection(config)
    with db.cursor() as cur:
        cur.execute("SET time_zone='+00:00'")
    return db


def connect(settings):
    from chatter_db import get_db_connection
    raw = dict(settings.raw)
    for field in ('Host', 'Port', 'User', 'Password'):
        value = os.getenv('LLM_SIM_DB_' + field.upper(), raw.get('LLMChatter.Simulation.Database.' + field))
        if value is not None:
            raw['LLMChatter.Database.' + field] = value
    db = get_db_connection(raw, settings.database)
    with db.cursor() as cur:
        cur.execute("SET time_zone='+00:00'")
    return db


class Store:
    def __init__(self, db, transport, settings):
        self.db, self.transport, self.settings = db, transport, settings

    def identity(self, guid):
        with self.db.cursor(dictionary=True) as cur:
            cur.execute('SELECT identity_json FROM sim_bot_identity WHERE bot_guid=%s', (guid,))
            row = cur.fetchone()
            if row:
                return json.loads(row['identity_json'])
            with self.transport.cursor(dictionary=True) as upstream:
                upstream.execute('SELECT trait1,trait2,trait3 FROM llm_bot_identities WHERE bot_guid=%s', (guid,))
                legacy = upstream.fetchone()
            identity = make_identity(guid, self.settings, legacy)
            cur.execute('INSERT IGNORE INTO sim_bot_identity(bot_guid,native_language,identity_json) VALUES(%s,%s,%s)', (guid, identity['language'], json.dumps(identity)))
            self.db.commit()
            # Database wins even when another context created the identity concurrently.
            cur.execute('SELECT identity_json FROM sim_bot_identity WHERE bot_guid=%s', (guid,))
            return json.loads(cur.fetchone()['identity_json'])

    def relationship(self, bot, player):
        with self.db.cursor(dictionary=True) as cur:
            cur.execute('SELECT * FROM sim_bot_player_relationship WHERE bot_guid=%s AND player_guid=%s', (bot, player))
            return cur.fetchone() or {}

    def memories(self, bot, player):
        now = datetime.now(timezone.utc)
        # Read only bounded, indexed active legacy memories, retaining original timestamps.
        with self.transport.cursor(dictionary=True) as cur:
            cur.execute('SELECT id,memory_type,memory,created_at FROM llm_bot_memories WHERE bot_guid=%s AND player_guid=%s AND active=1 ORDER BY id DESC LIMIT 32', (bot, player))
            legacy = cur.fetchall()
        with self.db.cursor(dictionary=True) as cur:
            for row in legacy:
                cur.execute('INSERT IGNORE INTO sim_bot_memory(bot_guid,player_guid,source_reference,memory_type,summary,occurred_at) VALUES(%s,%s,%s,%s,%s,%s)', (bot, player, 'upstream:' + str(row['id']), row['memory_type'], row['memory'][:1024], row['created_at']))
            self.db.commit()
            cur.execute('SELECT * FROM sim_bot_memory WHERE bot_guid=%s AND player_guid=%s AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP()) ORDER BY occurred_at DESC LIMIT 64', (bot, player))
            rows = cur.fetchall()
        ranked = sorted(rows, key=lambda r: memory_score(r, now, self.settings), reverse=True)
        return [{'age': age_text(r['occurred_at'], now), 'summary': r['summary'],
                 'strength': 'weak/uncertain' if memory_score(r, now, self.settings) < .2 else 'remembered'}
                for r in ranked[:int(self.settings['Memory.RecallLimit'])] if memory_score(r, now, self.settings) > self.settings['Memory.CleanupThreshold']]

    def recent(self, context):
        with self.db.cursor(dictionary=True) as cur:
            cur.execute('SELECT speaker,message FROM sim_recent_dialogue WHERE context_key=%s ORDER BY id DESC LIMIT %s', (context, int(self.settings['Conversation.RecentTurns'])))
            return list(reversed(cur.fetchall()))

    def player_turn(self, context, event, payload):
        if not payload.get('player_message'):
            return
        with self.db.cursor() as cur:
            cur.execute('INSERT IGNORE INTO sim_recent_dialogue(context_key,source_reference,speaker,message,created_at) VALUES(%s,%s,%s,%s,UTC_TIMESTAMP())', (context, 'player:' + str(event['id']), payload['player_name'], payload['player_message'][:1024]))
        self.db.commit()

    def results(self, bot, player):
        with self.transport.cursor(dictionary=True) as cur:
            cur.execute("SELECT intent,status,reason FROM llm_sim_outbox WHERE bot_guid=%s AND player_guid=%s AND completed_at IS NOT NULL ORDER BY message_id DESC LIMIT 3", (bot, player))
            return cur.fetchall()

    def reconcile(self):
        with self.transport.cursor(dictionary=True) as cur:
            cur.execute('SELECT o.*,m.bot_name,m.message,m.delivered_at FROM llm_sim_outbox o JOIN llm_chatter_messages m ON m.id=o.message_id WHERE o.feedback_recorded=0 AND o.completed_at IS NOT NULL LIMIT 64')
            rows = cur.fetchall()
        for row in rows:
            record('result', event=row['event_id'], message_id=row['message_id'], bot=row['bot_name'],
                   message=row['message'], intent=row['intent'], status=row['status'], reason=row['reason'])
            # Cross-database replay-safe: unique source + relationship update in one transaction.
            if row['status'] == 'succeeded' and row['delivered_at']:
                with self.db.cursor() as cur:
                    cur.execute('INSERT IGNORE INTO sim_recent_dialogue(context_key,source_reference,speaker,message,created_at) VALUES(%s,%s,%s,%s,%s)', (row['context_key'], 'message:' + str(row['message_id']), row['bot_name'], row['message'], row['delivered_at']))
                    if cur.rowcount:
                        cur.execute('INSERT INTO sim_bot_player_relationship(bot_guid,player_guid,familiarity,interaction_count,last_seen_at) VALUES(%s,%s,0.5,1,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE familiarity=LEAST(100,familiarity+IF(last_seen_at<UTC_TIMESTAMP()-INTERVAL 5 MINUTE,0.5,0)),interaction_count=interaction_count+1,last_seen_at=UTC_TIMESTAMP()', (row['bot_guid'], row['player_guid']))
                self.db.commit()
            with self.transport.cursor() as cur:
                cur.execute('UPDATE llm_sim_outbox SET feedback_recorded=1 WHERE message_id=%s', (row['message_id'],))
            self.transport.commit()

    def cleanup(self):
        with self.db.cursor() as cur:
            cur.execute('DELETE FROM sim_bot_memory WHERE expires_at<UTC_TIMESTAMP() LIMIT 500')
            cur.execute('DELETE FROM sim_recent_dialogue WHERE created_at<UTC_TIMESTAMP()-INTERVAL 1 DAY LIMIT 500')
        self.db.commit()
