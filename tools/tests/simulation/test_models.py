"""Real OpenAI SDK against a local mock HTTP endpoint; no external API calls."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ModelTests(unittest.TestCase):
    def test_profile_routing_and_plain_upstream_call(self):
        from chatter_llm import call_llm
        from chatter_shared import PromptParts
        from simulation.models import client_for_profile
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                result = json.dumps({'id':'mock', 'object':'chat.completion', 'created':1,
                    'model':body['model'], 'choices':[{'index':0,'message':{'role':'assistant',
                    'content':'{"respond":true,"message":"jo","intent":"follow_player"}'},'finish_reason':'stop'}]}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(result))); self.end_headers(); self.wfile.write(result)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        config = {'LLMChatter.Provider':'openai', 'LLMChatter.Model':'legacy'}
        for tier in ('Fast','Strong'):
            config['LLMChatter.Simulation.Model.'+tier+'.BaseUrl'] = f'http://127.0.0.1:{server.server_port}/v1'
            config['LLMChatter.Simulation.Model.'+tier+'.Model'] = 'test-'+tier.lower()
        original = dict(config)
        try:
            for tier in ('Fast','Strong'):
                response = call_llm(None, PromptParts('Morwen pojd', 'Return JSON'), config, profile=tier)
                self.assertEqual(json.loads(response)['intent'], 'follow_player')
            client, _ = client_for_profile(config, 'Fast')
            self.assertIsNotNone(call_llm(client, 'hello', config))
            self.assertEqual([r['model'] for r in requests], ['test-fast','test-strong','legacy'])
            self.assertEqual(requests[0]['messages'][0]['role'], 'system')
            self.assertTrue(all('tools' not in r for r in requests))
            self.assertEqual(config, original)
        finally:
            server.shutdown(); server.server_close(); thread.join()
