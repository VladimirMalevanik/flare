"""Check the standalone CLI without an installed app, key or live network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / 'scripts/smoke_groq_text_analysis.py'


@pytest.mark.parametrize('key_source', ['environment', 'dotenv'])
def test_direct_smoke_without_editable_install_or_pythonpath(tmp_path, key_source):
    # -I -S omits cwd, PYTHONPATH and editable-install .pth hooks. Add dependencies
    # only, proving the script itself makes this checkout's app importable.
    harness = r'''
import importlib.util, json, os, runpy, sys
sys.path.append(os.environ['FLARE_TEST_PURELIB'])
assert importlib.util.find_spec('app') is None
import httpx
calls = []
def handler(request):
    calls.append(request)
    assert request.headers['authorization'] == 'Bearer synthetic-smoke-test-key'
    body = json.loads(request.content)
    assert body['model'] == 'openai/gpt-oss-20b'
    assert body['response_format']['json_schema']['strict'] is True
    analysis = {'observations': [{'category': 'decision', 'text': 'Use PostgreSQL.',
        'evidence': [{'source_id': 'smoke-note-1', 'quote': 'We decided to use PostgreSQL for the MVP database.'}]}]}
    return httpx.Response(200, headers={'x-request-id': 'req-smoke-test'}, json={
        'id': 'completion-smoke-test', 'object': 'chat.completion', 'created': 0,
        'model': body['model'], 'choices': [{'index': 0, 'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps(analysis)}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}})
original = httpx.AsyncClient.__init__
def patched(self, *args, **kwargs):
    kwargs['transport'] = httpx.MockTransport(handler)
    original(self, *args, **kwargs)
httpx.AsyncClient.__init__ = patched
sys.argv = ['scripts/smoke_groq_text_analysis.py', '--live']
runpy.run_path(sys.argv[0], run_name='__main__')
assert len(calls) == 1
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GROQ_', 'LLM_'))}
    # ``-S`` deliberately hides a virtual environment's site-packages and can
    # make sysconfig resolve the base interpreter instead. Pass the dependency
    # directory chosen by the test runner explicitly, while still excluding the
    # checkout and editable-install hooks from the isolated child process.
    env['FLARE_TEST_PURELIB'] = sysconfig.get_paths()['purelib']
    working = tmp_path / 'backend'
    (working / 'scripts').mkdir(parents=True)
    (working / 'scripts' / SCRIPT.name).write_text(SCRIPT.read_text())
    (working / 'app').symlink_to(BACKEND / 'app', target_is_directory=True)
    if key_source == 'environment':
        env['GROQ_API_KEY'] = 'synthetic-smoke-test-key'
        (working / '.env').write_text('GROQ_API_KEY=must-not-override-environment\n')
    else:
        (working / '.env').write_text('GROQ_API_KEY=synthetic-smoke-test-key\n')
    completed = subprocess.run([sys.executable, '-I', '-S', '-c', harness],
                               cwd=working, env=env, text=True, capture_output=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report['validation_outcome'] == 'valid'
    assert report['analysis']['observations'][0]['evidence'][0]['source_id'] == 'smoke-note-1'
    assert 'synthetic-smoke-test-key' not in completed.stdout + completed.stderr


def test_smoke_requires_explicit_opt_in():
    completed = subprocess.run([sys.executable, '-I', str(SCRIPT)], cwd=BACKEND,
                               text=True, capture_output=True, timeout=15)
    assert completed.returncode == 2
    assert 'Pass --live' in completed.stderr
