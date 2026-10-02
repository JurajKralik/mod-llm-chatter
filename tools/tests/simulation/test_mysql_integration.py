"""Opt-in integration against session-local TEMPORARY tables, never live game rows.
Run: LLM_SIM_TEST_CONFIG=/path/to/conf python -m unittest discover -s tools/tests/simulation -v
"""
import json
import os
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS))


@unittest.skipUnless(os.getenv('LLM_SIM_TEST_CONFIG'), 'MySQL config not provided')
class MySQLIntegration(unittest.TestCase):
    def setUp(self):
        from chatter_shared import parse_config
        from chatter_db import get_db_connection
        from simulation.config import Settings
        self.config = parse_config(os.environ['LLM_SIM_TEST_CONFIG'])
        self.config['LLMChatter.Simulation.Behavior.Enable'] = '1'
        self.settings = Settings(self.config)
        self.db = get_db_connection(self.config)
        self.addCleanup(self.db.close)
        with self.db.cursor() as c:
            c.execute("SET time_zone='+00:00'")
            c.execute('CREATE TEMPORARY TABLE characters(guid INT PRIMARY KEY, account INT, name VARCHAR(64), online TINYINT)')
            for table in ('llm_bot_identities', 'llm_bot_memories', 'llm_chatter_events', 'llm_chatter_messages'):
                c.execute(f'SHOW CREATE TABLE {table}')
                ddl = c.fetchone()[1]
                c.execute(ddl.replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1))
            root = TOOLS.parent / 'data/sql/simulation'
            for name in ('001_state.sql', '001_transport.sql'):
                sql = '\n'.join(l for l in (root / name).read_text().splitlines() if not l.startswith('--'))
                for statement in sql.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE').split(';'):
                    if statement.strip():
                        c.execute(statement)
            c.execute("INSERT INTO characters(guid,account,name,online) VALUES(900001,1,'TestObserver',1)")
        self.db.commit()
        class SharedConnection:
            def __init__(self, db): self.db = db
            def __getattr__(self, key): return getattr(self.db, key)
            def close(self): pass
        self.connection = patch('simulation.coordinator.connect', return_value=SharedConnection(self.db))
        self.connection.start()
        self.calls = 0

    def tearDown(self):
        self.connection.stop()
        self.db.close()  # All test tables disappear automatically.

    def event(self, text='Morwen pojd se mnou', context='sim:local:0:0:1', bot=900002):
        payload = {'simulation_version': 1, 'context_key': context, 'channel': 'say',
                   'player_guid': 900001, 'player_name': 'TestObserver', 'player_message': text,
                   'map_id': 0, 'instance_id': 0, 'candidates': [{'guid': bot, 'name': 'Morwen', 'level': 20,
                   'class': 'Druid', 'combat': False, 'actions': ['follow_player', 'resume_autonomous']}]}
        with self.db.cursor(dictionary=True) as c:
            c.execute("INSERT INTO llm_chatter_events(event_type,extra_data,cooldown_key,status,created_at) VALUES('proximity_player_say',%s,%s,'processing',UTC_TIMESTAMP()-INTERVAL 10 SECOND)", (json.dumps(payload), context))
            event_id = c.lastrowid
            self.db.commit()
            c.execute('SELECT * FROM llm_chatter_events WHERE id=%s', (event_id,))
            return c.fetchone()

    def model(self, *a, **kw):
        self.calls += 1
        self.assertEqual(kw['profile'], 'Fast')
        return '{"respond":true,"message":"jo","intent":"follow_player"}'

    def run_event(self, event, model=None):
        from simulation.coordinator import handle
        handle(event, self.db, self.settings, random.Random(1), model or self.model)

    def test_follow_transport_and_replay_feedback(self):
        from simulation.store import Store
        event = self.event()
        self.run_event(event)
        with self.db.cursor(dictionary=True) as c:
            c.execute('SELECT * FROM llm_sim_outbox')
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['intent'], 'follow_player')
            c.execute('SELECT deliver_at<=UTC_TIMESTAMP() AS ready FROM llm_chatter_messages')
            self.assertEqual(c.fetchone()['ready'], 1, '10-second generation must not add full typing delay')
            c.execute("UPDATE llm_sim_outbox SET status='succeeded',completed_at=UTC_TIMESTAMP()")
            c.execute('UPDATE llm_chatter_messages SET delivered=1,delivered_at=UTC_TIMESTAMP()')
            self.db.commit()
        store = Store(self.db, self.db, self.settings)
        store.reconcile()
        with self.db.cursor() as c:
            c.execute('UPDATE llm_sim_outbox SET feedback_recorded=0')
            self.db.commit()
        store.reconcile()
        self.assertEqual(store.relationship(900002, 900001)['interaction_count'], 1)

    def test_context_busy_no_fanout(self):
        self.run_event(self.event())
        second = self.event()
        self.run_event(second)
        self.assertEqual(self.calls, 1)
        with self.db.cursor() as c:
            c.execute('SELECT status FROM llm_chatter_events WHERE id=%s', (second['id'],))
            self.assertEqual(c.fetchone()[0], 'pending')

    def test_overlapping_bot_is_serialized(self):
        self.run_event(self.event())
        self.run_event(self.event(context='sim:whisper:900001:900002'))
        self.assertEqual(self.calls, 1)

    def test_independent_contexts(self):
        self.run_event(self.event())
        self.run_event(self.event(context='sim:local:571:0:2', bot=900003))
        self.assertEqual(self.calls, 2)

    def test_no_observer_no_llm(self):
        with self.db.cursor() as c:
            c.execute('UPDATE characters SET online=0'); self.db.commit()
        self.run_event(self.event())
        self.assertEqual(self.calls, 0)

    def test_malformed_no_outbox(self):
        self.run_event(self.event(), lambda *a, **k: '{"respond":true,"message":"jo","intent":"rm -rf"}')
        with self.db.cursor() as c:
            c.execute('SELECT COUNT(*) FROM llm_sim_outbox')
            self.assertEqual(c.fetchone()[0], 0)

    def test_identity_is_database_authoritative(self):
        from simulation.store import Store
        first = Store(self.db, self.db, self.settings).identity(900002)
        self.settings.values['Language.CzechPercent'] = 0
        self.settings.values['Language.SlovakPercent'] = 100
        self.assertEqual(Store(self.db, self.db, self.settings).identity(900002), first)

    def test_resume_after_follow_feedback(self):
        first = self.event()
        self.run_event(first)
        with self.db.cursor() as c:
            c.execute("UPDATE llm_sim_outbox SET status='succeeded',completed_at=UTC_TIMESTAMP()")
            c.execute('UPDATE llm_sim_context SET event_id=NULL,lease_until=NULL,next_visible_at=NULL,last_speaker=900002')
            c.execute('UPDATE llm_sim_speaker SET event_id=NULL,lease_until=NULL,last_visible_at=UTC_TIMESTAMP()')
            self.db.commit()
        self.run_event(self.event('Morwen uz bez'), lambda *a, **k: '{"respond":true,"message":"ok","intent":"resume_autonomous"}')
        with self.db.cursor() as c:
            c.execute('SELECT intent FROM llm_sim_outbox ORDER BY message_id DESC LIMIT 1')
            self.assertEqual(c.fetchone()[0], 'resume_autonomous')

    def test_2500_realm_bots_only_shortlist_processed(self):
        import time
        with self.db.cursor() as c:
            c.executemany('INSERT INTO characters(guid,account,name,online) VALUES(%s,2,%s,1)', [(i, 'Bot'+str(i)) for i in range(1,2501)])
            self.db.commit()
        event = self.event()
        payload = json.loads(event['extra_data'])
        payload['candidates'].extend({'guid': i, 'name': 'Bot'+str(i), 'level':20, 'combat':False, 'actions':[]} for i in range(1,24))
        event['extra_data'] = payload
        start = time.monotonic()
        self.run_event(event)
        elapsed = time.monotonic()-start
        self.assertEqual(self.calls, 1)
        with self.db.cursor() as c:
            c.execute('SELECT COUNT(*) FROM sim_bot_identity')
            self.assertEqual(c.fetchone()[0], 24)
            c.execute('SELECT COUNT(*) FROM llm_chatter_messages')
            self.assertEqual(c.fetchone()[0], 1)
        print(f'LOAD: realm_bots=2500 candidates=24 identities=24 llm_calls=1 messages=1 seconds={elapsed:.4f}')

    def test_local_core_timestamp_is_ready_in_utc_worker(self):
        from datetime import datetime, timezone
        with self.db.cursor() as c:
            c.execute("SET time_zone='+02:00'")
            c.execute("INSERT INTO llm_chatter_events(event_type,cooldown_key,created_at,react_after,expires_at) VALUES('proximity_player_say','sim:timezone',NOW(),NOW(),NOW()+INTERVAL 90 SECOND)")
            event_id = c.lastrowid
            self.db.commit()
            c.execute("SET time_zone='+00:00'")
            c.execute('SELECT created_at,react_after<=UTC_TIMESTAMP(),expires_at>UTC_TIMESTAMP() FROM llm_chatter_events WHERE id=%s', (event_id,))
            created, ready, live = c.fetchone()
            self.assertEqual((ready,live),(1,1))
            self.assertLess(abs((datetime.now(timezone.utc)-created.replace(tzinfo=timezone.utc)).total_seconds()), 3)
            # Python writes UTC; C++ local-time polling must see it immediately.
            c.execute("INSERT INTO llm_chatter_messages(bot_guid,bot_name,message,deliver_at) VALUES(900002,'Morwen','jo',UTC_TIMESTAMP())")
            self.db.commit()
            c.execute("SET time_zone='+02:00'")
            c.execute('SELECT deliver_at<=NOW() FROM llm_chatter_messages')
            self.assertEqual(c.fetchone()[0],1)
            c.execute("SET time_zone='+00:00'")

    def test_query_indexes(self):
        queries = [
            ('identity', 'SELECT * FROM sim_bot_identity WHERE bot_guid=900002'),
            ('relationship', 'SELECT * FROM sim_bot_player_relationship WHERE bot_guid=900002 AND player_guid=900001'),
            ('memory', 'SELECT * FROM sim_bot_memory WHERE bot_guid=900002 AND player_guid=900001 ORDER BY occurred_at DESC LIMIT 64'),
            ('dialogue', "SELECT * FROM sim_recent_dialogue WHERE context_key='sim:local:0:0:1' ORDER BY id DESC LIMIT 12"),
            ('pending', "SELECT * FROM llm_sim_outbox WHERE status='pending' AND expires_at<UTC_TIMESTAMP() LIMIT 100"),
        ]
        self.run_event(self.event())
        with self.db.cursor(dictionary=True) as c:
            c.execute('INSERT INTO sim_bot_player_relationship(bot_guid,player_guid,last_seen_at) VALUES(900002,900001,UTC_TIMESTAMP())')
            c.execute("INSERT INTO sim_bot_memory(bot_guid,player_guid,source_reference,memory_type,summary,occurred_at) VALUES(900002,900001,'fixture','dungeon','shared dungeon',UTC_TIMESTAMP())")
            self.db.commit()
            for label, query in queries:
                c.execute('EXPLAIN ' + query)
                plan = c.fetchone()
                print('EXPLAIN:', label, 'type='+str(plan['type']), 'key='+str(plan['key']), 'possible='+str(plan['possible_keys']))
                self.assertIsNotNone(plan['possible_keys'])


if __name__ == '__main__':
    unittest.main()
