"""Deterministic identity, social selection, decay and strict output contract."""
import json
import math
import random
import re
import unicodedata
from datetime import datetime, timezone

ACTIONS = frozenset(('none', 'follow_player', 'stay_here', 'resume_autonomous'))
COMPETENCE = ('newbie', 'casual', 'average', 'experienced', 'very experienced', 'leader')
LENGTHS = {'tiny': (5, 60), 'short': (16, 110), 'medium': (30, 180), 'long': (45, 240)}
LEAK = re.compile(r'\b(ai|llm|bot|bots|playerbot\w*|openclaw|python|mysql|azerothcore|chatgpt|system prompt|language model|jazykov[yý] model|um[eě]l[aá] inteligence|simulace|simul[aá]cia|skript|script|automated|generated|datab[aá]ze)\b|c\+\+', re.I)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def make_identity(guid, settings, legacy=None):
    rng = random.Random(f'twinstar:v1:{guid}')
    language = rng.choices(('cs', 'sk'), weights=(settings['Language.CzechPercent'], settings['Language.SlovakPercent']))[0]
    personality = {k: round(rng.betavariate(2, 2), 2) for k in ('friendliness', 'talkativeness', 'patience', 'confidence', 'sarcasm', 'helpfulness', 'leadership', 'toxicity', 'humor')}
    personality['toxicity'] *= 0.3
    competence = rng.choices(COMPETENCE, weights=settings.competence_weights)[0]
    if competence in COMPETENCE[:2]:
        personality['leadership'] *= 0.4
    return {'language': language, 'version': 1, 'competence': competence,
            'personality': personality,
            'interests': {k: round(rng.random(), 2) for k in ('dungeons', 'raids', 'pvp', 'professions', 'exploration')},
            'style': {'diacritics': rng.choices(('never', 'rare', 'often'), (50, 35, 15))[0],
                      'lowercase': rng.random() < .75, 'punctuation': rng.random() < .3,
                      'emoticon': rng.choice(('', '', '', ':D', 'xd', ':)', '^^'))},
            'legacy_traits': [legacy.get(k, '') for k in ('trait1', 'trait2', 'trait3')] if legacy else []}


def age_days(then, now):
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, (now - then).total_seconds() / 86400)


def memory_score(memory, now, settings):
    age = age_days(memory['occurred_at'], now)
    half = max(.01, settings['Memory.HalfLife.' + memory['decay_class']])
    return float(memory['salience']) * math.exp2(-age / half) / (1 + .05 * memory.get('recall_count', 0))


def age_text(then, now):
    days = age_days(then, now)
    if days < 1 / 24:
        return f'{int(days * 1440)} minutes ago'
    if days < 1:
        return f'{int(days * 24)} hours ago'
    if days < 2:
        return 'yesterday'
    if days < 60:
        return f'{int(days)} days ago'
    return f'about {int(days / 30)} months ago'


def relationship_label(row, now, settings):
    if not row or not row.get('interaction_count'):
        return 'stranger'
    familiarity = float(row['familiarity'])
    familiarity *= .4 + .6 * math.exp2(-age_days(row['last_seen_at'], now) / max(1, settings['Relationship.DecayDays']))
    if row.get('annoyance', 0) > 50:
        return 'annoyed'
    return 'friend' if familiarity > 75 else 'friendly' if familiarity > 45 else 'familiar' if familiarity > 20 else 'recognized'


def select_speaker(candidates, message, previous, identities, relations, settings, rng, direct=0):
    named = [c for c in candidates if re.search(r'(?<!\w)' + re.escape(fold(c['name'])) + r'(?!\w)', fold(message))]
    if direct:
        named = [c for c in candidates if c['guid'] == direct]
    if named:
        return named[0] if rng.random() * 100 < settings['Reaction.DirectAddressChance'] else None
    if not candidates:
        return None
    chance = settings['Reaction.KnownPlayerChance'] if any(relations.get(c['guid'], {}).get('interaction_count', 0) for c in candidates) else settings['Reaction.UnknownPlayerChance']
    if rng.random() * 100 >= chance:
        return None
    def score(c):
        p = identities[c['guid']]['personality']
        return p['talkativeness'] + p['helpfulness'] * .2 + rng.random() * .3 + (settings['Conversation.SpeakerStickiness'] if c['guid'] == previous else 0)
    return max(candidates, key=score)


def route(message, memories, channel, combat=False):
    if combat:
        return 'Fast'
    text = fold(message)
    complex_topic = any(w in text for w in ('taktik', 'strategy', 'naplan', 'organiz', 'proc jsi', 'pamatu', 'remember'))
    return 'Strong' if complex_topic or len(message.split()) > 25 or len(memories) >= 3 else 'Fast'


def length_class(settings, rng, channel, combat=False):
    if combat or channel in ('battleground', 'trade', 'lfg'):
        return rng.choices(('tiny', 'short'), (85, 15))[0]
    return rng.choices(tuple(LENGTHS), [settings['MessageLength.' + k.title() + 'Weight'] for k in LENGTHS])[0]


def parse_response(raw, available_actions, length, identity, settings, rng):
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError('Duplicate JSON key')
            obj[k] = v
        return obj
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('Missing or oversized response')
    obj = json.loads(raw, object_pairs_hook=unique)
    if type(obj) is not dict or type(obj.get('respond')) is not bool:
        raise ValueError('Invalid decision')
    if not obj['respond']:
        if set(obj) != {'respond'}:
            raise ValueError('Silence must not carry side effects')
        return obj
    if set(obj) != {'respond', 'message', 'intent'}:
        raise ValueError('Unexpected structured fields')
    intent = obj['intent']
    if type(intent) is not str or intent not in ACTIONS or intent not in available_actions:
        raise ValueError('Unsupported action')
    text = obj['message']
    if type(text) is not str or not text.strip() or any(unicodedata.category(c).startswith('C') for c in text):
        raise ValueError('Invalid chat text')
    if LEAK.search(text) or re.search(r'https?://|www\.|[|<>]|\n|\r', text):
        raise ValueError('Implementation disclosure, link or markup')
    for severity in ('mild', 'medium', 'strong'):
        token = '__SWEAR_' + severity.upper() + '__'
        if token in text:
            replacements = settings.profile['profanity'][identity['language']][severity]
            allow = settings.enabled('Profanity.Enable') and rng.random() < identity['personality']['toxicity']
            text = text.replace(token, rng.choice(replacements) if allow else '')
    if '__' in text:
        raise ValueError('Unknown placeholder')
    if identity['style']['diacritics'] == 'never':
        text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    if identity['style']['lowercase']:
        text = text.lower()
    text = ' '.join(text.split())
    words, limit = LENGTHS[length]
    # Reject instead of truncating: truncation could reverse consent or an action promise.
    if not text or len(text.split()) > words or len(text.encode('utf-8')) > limit:
        raise ValueError('Length class exceeded')
    obj['message'] = text
    return obj
