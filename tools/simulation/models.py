"""Isolated profile clients; never mutate the upstream shared config/client."""
import os
import threading

_lock = threading.Lock()
_clients = {}


def profile_config(config, profile):
    if profile not in ('Fast', 'Strong'):
        raise ValueError('Unknown model profile')
    prefix = 'LLMChatter.Simulation.Model.' + profile + '.'
    result = dict(config)
    provider = str(config.get(prefix + 'Provider', config.get('LLMChatter.Provider', 'openai'))).strip('"').lower()
    model = str(config.get(prefix + 'Model', config.get('LLMChatter.Model', ''))).strip('"')
    if not model:
        raise ValueError('Missing model for ' + profile)
    result['LLMChatter.Provider'] = provider
    result['LLMChatter.Model'] = model
    result['_simulation_profile'] = profile
    return result


def client_for_profile(config, profile):
    result = profile_config(config, profile)
    prefix = 'LLMChatter.Simulation.Model.' + profile + '.'
    provider = result['LLMChatter.Provider']
    names = {'openai': 'OpenAI', 'anthropic': 'Anthropic', 'google': 'Google', 'openrouter': 'OpenRouter', 'ollama': 'Ollama'}
    if provider not in names:
        raise ValueError('Unsupported simulation provider')
    name = names[provider]
    env_name = str(config.get(prefix + 'ApiKeyEnv', '')).strip('"')
    key = os.environ.get(env_name, '') if env_name else str(config.get('LLMChatter.' + name + '.ApiKey', '')).strip('"')
    defaults = {'openai': os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1'), 'google': 'https://generativelanguage.googleapis.com/v1beta/openai/', 'openrouter': 'https://openrouter.ai/api/v1', 'ollama': 'http://localhost:11434/v1', 'anthropic': 'https://api.anthropic.com'}
    url = str(config.get(prefix + 'BaseUrl', defaults[provider])).strip('"')
    timeout = float(config.get(prefix + 'Timeout', 25 if profile == 'Fast' else 60))
    fingerprint = (provider, url, key, timeout)
    with _lock:
        if fingerprint not in _clients:
            if len(_clients) >= 8:
                raise ValueError('Too many model client configurations; restart bridge')
            if provider == 'anthropic':
                import anthropic
                client = anthropic.Anthropic(api_key=key, base_url=url, timeout=timeout, max_retries=0)
            else:
                import openai
                client = openai.OpenAI(api_key=key or 'local-no-key', base_url=url, timeout=timeout, max_retries=0)
            _clients[fingerprint] = client
        return _clients[fingerprint], result
