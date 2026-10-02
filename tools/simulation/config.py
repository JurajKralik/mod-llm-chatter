"""Validated Python-owned tuning. No credentials are logged."""
import json
import os
from pathlib import Path

PREFIX = 'LLMChatter.Simulation.'
DEFAULTS = {
    'Enable': 0, 'Behavior.Enable': 0, 'ProximityRadius': 40,
    'Language.CzechPercent': 80, 'Language.SlovakPercent': 20,
    'Reaction.UnknownPlayerChance': 30, 'Reaction.KnownPlayerChance': 65,
    'Reaction.DirectAddressChance': 100,
    'Conversation.SpeakerStickiness': 0.35,
    'Conversation.MinVisibleLineGap': 3, 'Conversation.MaxVisibleLineGap': 7,
    'Conversation.BotGlobalCooldown': 8, 'Conversation.MaxCandidates': 24,
    'Conversation.LeaseSeconds': 120, 'Conversation.MaxContexts': 512,
    'Conversation.IdleRetentionSeconds': 3600, 'Conversation.RecentTurns': 12,
    'Conversation.EventMaxAgeSeconds': 90, 'Conversation.Workers': 4,
    'MessageLength.TinyWeight': 60, 'MessageLength.ShortWeight': 30,
    'MessageLength.MediumWeight': 9, 'MessageLength.LongWeight': 1,
    'Memory.HalfLife.ephemeral': 0.5, 'Memory.HalfLife.weak': 7,
    'Memory.HalfLife.normal': 45, 'Memory.HalfLife.strong': 180,
    'Memory.HalfLife.landmark': 3650, 'Memory.RecallLimit': 4,
    'Memory.CleanupThreshold': 0.02,
    'Relationship.DecayDays': 90, 'Profanity.Enable': 0,
    'Model.Fast.Timeout': 25, 'Model.Strong.Timeout': 60,
}


class Settings:
    def __init__(self, raw):
        self.raw = dict(raw)
        self.values = {}
        for key, default in DEFAULTS.items():
            value = float(str(raw.get(PREFIX + key, default)).strip('"'))
            if not 0 <= value <= 1000000:
                raise ValueError('Invalid simulation setting: ' + key)
            self.values[key] = value
        for key in ('Conversation.Workers', 'Conversation.MaxCandidates',
                    'Conversation.MaxContexts', 'Conversation.RecentTurns'):
            if self[key] < 1:
                raise ValueError(key + ' must be positive')
        if self['Language.CzechPercent'] + self['Language.SlovakPercent'] <= 0:
            raise ValueError('Language weights cannot both be zero')
        if self['Conversation.MaxVisibleLineGap'] < self['Conversation.MinVisibleLineGap']:
            raise ValueError('Invalid visible gap range')
        if self['Conversation.LeaseSeconds'] < max(self['Model.Fast.Timeout'], self['Model.Strong.Timeout']) + 15:
            raise ValueError('Lease must exceed model timeout by at least 15 seconds')
        name = str(raw.get(PREFIX + 'Profile', 'twinstar_wotlk')).strip('"')
        if name != Path(name).name:
            raise ValueError('Profile must be a file name without a path')
        path = Path(__file__).resolve().parents[1] / 'simulation_profiles' / (name + '.json')
        self.profile = json.loads(path.read_text())
        self.database = os.getenv('LLM_SIM_DATABASE', str(raw.get(PREFIX + 'Database.Name', 'acore_llm_sim')).strip('"'))
        self.competence_weights = json.loads(str(raw.get(PREFIX + 'Competence.Weights', '[8,20,40,22,8,2]')))
        if len(self.competence_weights) != 6 or min(self.competence_weights) < 0 or not sum(self.competence_weights):
            raise ValueError('Competence.Weights must contain six nonnegative weights')

    def __getitem__(self, key):
        return self.values[key]

    def enabled(self, key='Enable'):
        return self[key] == 1
