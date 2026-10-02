"""Simulation event lane reusing upstream transport; no legacy LLM workers."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from simulation.config import Settings
from simulation.coordinator import handle
from simulation.store import Store, connect, transport_connect

log = logging.getLogger(__name__)


def worker(event, settings):
    db = transport_connect(settings.raw)
    try:
        handle(event, db, settings)
    finally:
        db.close()


def run(config):
    settings = Settings(config)
    log.info('Simulation lane started; legacy generators disabled')
    futures = []
    last_cleanup = 0
    with ThreadPoolExecutor(max_workers=int(settings['Conversation.Workers'])) as pool:
        while True:
            db = sim = None
            try:
                remaining = []
                for f in futures:
                    if f.done():
                        try:
                            f.result()
                        except Exception as exc:
                            log.warning('Simulation worker unavailable: %s', type(exc).__name__)
                    else:
                        remaining.append(f)
                futures = remaining
                db = transport_connect(config)
                sim = connect(settings)  # fail closed before spending LLM tokens
                store = Store(sim, db, settings)
                store.reconcile()
                with db.cursor(dictionary=True) as cur:
                    cur.execute("UPDATE llm_chatter_events SET status='expired' WHERE status='pending' AND cooldown_key LIKE 'sim:%%' AND expires_at<UTC_TIMESTAMP() LIMIT 100")
                    cur.execute("SELECT * FROM llm_chatter_events WHERE status='pending' AND cooldown_key LIKE 'sim:%%' AND react_after<=UTC_TIMESTAMP() AND expires_at>UTC_TIMESTAMP() AND NOT EXISTS (SELECT 1 FROM llm_sim_context c WHERE c.context_key=llm_chatter_events.cooldown_key AND (c.lease_until>UTC_TIMESTAMP() OR c.next_visible_at>UTC_TIMESTAMP())) ORDER BY priority DESC,created_at ASC LIMIT %s", (max(0, int(settings['Conversation.Workers']) - len(futures)),))
                    events = cur.fetchall()
                    for event in events:
                        cur.execute("UPDATE llm_chatter_events SET status='processing',processed_at=UTC_TIMESTAMP() WHERE id=%s AND status='pending'", (event['id'],))
                        claimed = cur.rowcount == 1
                        db.commit()
                        if claimed:
                            futures.append(pool.submit(worker, event, settings))
                    if time.monotonic() - last_cleanup > 60:
                        cur.execute("UPDATE llm_chatter_events SET status='expired' WHERE status='processing' AND cooldown_key LIKE 'sim:%%' AND processed_at<UTC_TIMESTAMP()-INTERVAL %s SECOND LIMIT 100", (int(settings['Conversation.LeaseSeconds']) * 2,))
                        cur.execute('DELETE FROM llm_sim_context WHERE updated_at<UTC_TIMESTAMP()-INTERVAL %s SECOND AND (lease_until IS NULL OR lease_until<UTC_TIMESTAMP()) LIMIT 100', (int(settings['Conversation.IdleRetentionSeconds']),))
                        cur.execute("UPDATE llm_sim_outbox SET status='expired',reason='delivery_timeout',completed_at=UTC_TIMESTAMP() WHERE status='pending' AND expires_at<UTC_TIMESTAMP() LIMIT 100")
                        cur.execute("DELETE FROM llm_sim_outbox WHERE feedback_recorded=1 AND completed_at<UTC_TIMESTAMP()-INTERVAL 7 DAY LIMIT 100")
                        cur.execute("DELETE FROM llm_sim_speaker WHERE (lease_until IS NULL OR lease_until<UTC_TIMESTAMP()) AND (last_visible_at IS NULL OR last_visible_at<UTC_TIMESTAMP()-INTERVAL 1 DAY) LIMIT 100")
                        cur.execute("DELETE FROM llm_chatter_messages WHERE owner_subsystem='simulation' AND delivered=1 AND deliver_at<UTC_TIMESTAMP()-INTERVAL 7 DAY LIMIT 100")
                        cur.execute("DELETE FROM llm_chatter_events WHERE cooldown_key LIKE 'sim:%%' AND status IN ('completed','skipped','expired') AND created_at<UTC_TIMESTAMP()-INTERVAL 7 DAY LIMIT 100")
                        store.cleanup()
                        last_cleanup = time.monotonic()
                db.commit()
            except KeyboardInterrupt:
                break
            except Exception as exc:
                log.warning('Simulation unavailable; retrying: %s', type(exc).__name__)
                time.sleep(4)
            finally:
                if sim:
                    sim.close()
                if db:
                    db.close()
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                break
