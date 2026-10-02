#!/usr/bin/env python3
"""Bounded simulation utilities. No arbitrary SQL or game commands."""
import argparse
import json
import re
import time
from pathlib import Path
from chatter_shared import parse_config, PromptParts
from chatter_db import get_db_connection
from simulation.config import Settings
from simulation.models import client_for_profile
from simulation.store import Store, connect, transport_connect


def migrate(settings):
    from chatter_db import get_db_connection
    # CREATE DATABASE is explicit, optional, and uses a validated identifier.
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', settings.database):
        raise ValueError('Invalid database name')
    db = get_db_connection(settings.raw)
    try:
        with db.cursor() as cur:
            cur.execute('CREATE DATABASE IF NOT EXISTS `' + settings.database + '` CHARACTER SET utf8mb4')
        sim = connect(settings)
        try:
            root = Path(__file__).resolve().parents[1] / 'data/sql/simulation'
            for connection, filename in ((sim, '001_state.sql'), (db, '001_transport.sql')):
                sql = '\n'.join(line for line in (root / filename).read_text().splitlines() if not line.startswith('--'))
                with connection.cursor() as cur:
                    for statement in sql.split(';'):
                        if statement.strip():
                            cur.execute(statement)
                connection.commit()
            print('Schema version 1 applied; upstream rows preserved')
        finally:
            sim.close()
    finally:
        db.close()


def benchmark(settings, profiles, stream=False):
    from chatter_llm import call_llm
    for profile in profiles:
        client, config = client_for_profile(settings.raw, profile)
        prompt = PromptParts('Morwen pojd se mnou', 'Reply only JSON: {"respond":true,"message":"jo","intent":"follow_player"}. Ordinary Czech WotLK player, maximum five words in message.')
        start = time.monotonic()
        ttft = None
        if stream and config['LLMChatter.Provider'] in ('openai', 'google', 'openrouter', 'ollama'):
            parts = []
            with client.chat.completions.create(model=config['LLMChatter.Model'], max_tokens=160,
                    messages=[{'role':'system','content':prompt.system_prompt},
                              {'role':'user','content':prompt.user_prompt}], stream=True) as chunks:
                for chunk in chunks:
                    content = chunk.choices[0].delta.content if chunk.choices else None
                    if content:
                        if ttft is None:
                            ttft = round(time.monotonic()-start, 3)
                        parts.append(content)
            text = ''.join(parts)
        else:
            text = call_llm(client, prompt, settings.raw, max_tokens_override=160, profile=profile, label='simulation-benchmark')
        print(json.dumps({'profile': profile, 'model': config['LLMChatter.Model'], 'total_seconds': round(time.monotonic()-start, 3), 'ttft_seconds': ttft, 'response': text}, ensure_ascii=False))



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    b = sub.add_parser('benchmark'); b.add_argument('--profile', choices=['Fast', 'Strong', 'both'], default='both'); b.add_argument('--stream', action='store_true')
    for cmd in ('identity', 'relationship', 'memories'):
        s = sub.add_parser(cmd); s.add_argument('--bot', type=int, required=True)
        if cmd != 'identity':
            s.add_argument('--player', type=int, required=True)
    sub.add_parser('contexts')
    args = p.parse_args()
    settings = Settings(parse_config(args.config))
    if args.command == 'migrate':
        return migrate(settings)
    if args.command == 'benchmark':
        return benchmark(settings, ('Fast', 'Strong') if args.profile == 'both' else (args.profile,), args.stream)
    db, sim = transport_connect(settings.raw), connect(settings)
    try:
        store = Store(sim, db, settings)
        if args.command == 'identity':
            result = store.identity(args.bot)
        elif args.command == 'relationship':
            result = store.relationship(args.bot, args.player)
        elif args.command == 'memories':
            result = store.memories(args.bot, args.player)
        else:
            with db.cursor(dictionary=True) as cur:
                cur.execute('SELECT * FROM llm_sim_context ORDER BY updated_at DESC LIMIT 100')
                result = cur.fetchall()
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        db.close(); sim.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print connection strings, request headers or provider error bodies.
        raise SystemExit('Simulation utility failed: ' + type(exc).__name__ + '; check service availability and database grants')
