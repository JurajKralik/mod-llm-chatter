import json
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simulation.config import Settings
from simulation.domain import *


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings({})
        self.identity = make_identity(3, self.s)

    def test_language_persistent_and_ratio(self):
        identities = [make_identity(n, self.s) for n in range(2500)]
        self.assertEqual(identities[3], self.identity)
        self.assertTrue(.77 < sum(i['language'] == 'cs' for i in identities) / 2500 < .83)

    def test_direct_and_stickiness(self):
        cs = [{'guid': 1, 'name': 'Kelmar'}, {'guid': 3, 'name': 'Morwen'}]
        ids = {c['guid']: make_identity(c['guid'], self.s) for c in cs}
        self.assertEqual(select_speaker(cs, 'Morwen pojd se mnou', 1, ids, {}, self.s, random.Random(1))['guid'], 3)
        self.assertEqual(select_speaker(cs, 'follow', 1, ids, {}, self.s, random.Random(1), 3)['guid'], 3)

    def test_stranger_gate(self):
        rng = random.Random(6)
        c = [{'guid': 3, 'name': 'Morwen'}]
        count = sum(select_speaker(c, 'cau', 0, {3: self.identity}, {}, self.s, rng) is not None for _ in range(10000))
        self.assertTrue(2800 < count < 3200)

    def test_length_distribution(self):
        rng = random.Random(2)
        counts = {k: 0 for k in LENGTHS}
        for _ in range(10000):
            counts[length_class(self.s, rng, 'say')] += 1
        self.assertTrue(5700 < counts['tiny'] < 6300)
        self.assertTrue(70 < counts['long'] < 130)

    def test_decay_and_old_context(self):
        now = datetime.now(timezone.utc)
        m = {'occurred_at': now-timedelta(days=45), 'salience': 1, 'decay_class': 'weak'}
        self.assertLess(memory_score(m, now, self.s), .02)
        self.assertEqual(age_text(m['occurred_at'], now), '45 days ago')

    def test_model_route(self):
        self.assertEqual(route('inv pls', [], 'say'), 'Fast')
        self.assertEqual(route('probereme taktiku na raid', [], 'party'), 'Strong')
        self.assertEqual(route('taktiku', [], 'party', True), 'Fast')

    def test_invalid_actions_and_leak(self):
        for intent, text in [('rm -rf /', 'jo'), ('travel_to', 'jo'), ('none', 'jsem AI'), ('none', '|Hitem:1|h'), ('none', 'ok\nhello')]:
            with self.assertRaises(ValueError):
                parse_response(json.dumps({'respond': True, 'message': text, 'intent': intent}), ACTIONS, 'tiny', self.identity, self.s, random.Random(1))
        for raw in ['[]', '{"respond":true,"respond":false}', '{"respond":false,"intent":"follow_player"}', '```json {} ```']:
            with self.assertRaises(ValueError):
                parse_response(raw, ACTIONS, 'tiny', self.identity, self.s, random.Random(1))

    def test_follow_and_resume(self):
        for intent in ('follow_player', 'resume_autonomous'):
            result = parse_response(json.dumps({'respond': True, 'message': 'jo', 'intent': intent}), ACTIONS, 'tiny', self.identity, self.s, random.Random(2))
            self.assertEqual(result['intent'], intent)

    def test_custom_profanity_single_words(self):
        settings = Settings({'LLMChatter.Simulation.Profanity.Enable': 1,
                             'LLMChatter.Simulation.Profanity.Words': 'sakra'})
        identity = make_identity(3, settings)
        identity['personality']['toxicity'] = 1
        response = parse_response(json.dumps({'respond': True, 'message': '__SWEAR_MILD__ jo',
                                             'intent': 'none'}), {'none'}, 'tiny', identity,
                                  settings, random.Random(1))
        self.assertEqual(response['message'], 'sakra jo')
        disabled = Settings({'LLMChatter.Simulation.Profanity.Words': 'sakra'})
        response = parse_response(json.dumps({'respond': True, 'message': '__SWEAR_MILD__ jo',
                                             'intent': 'none'}), {'none'}, 'tiny', identity,
                                  disabled, random.Random(1))
        self.assertEqual(response['message'], 'jo')
        for invalid in ('two words', 'word;command', '<markup>', 'word\nnext'):
            with self.assertRaises(ValueError):
                Settings({'LLMChatter.Simulation.Profanity.Words': invalid})

    def test_no_candidates_no_response(self):
        self.assertIsNone(select_speaker([], 'cau', 0, {}, {}, self.s, random.Random(1)))


if __name__ == '__main__':
    unittest.main()
