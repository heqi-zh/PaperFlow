"""Direct ChatGPT-plan inference through the official local SIWC SDK.

The child process is an OAuth/inference transport, not Codex CLI or an agent.
No API key or Codex credential file is read by this adapter.
"""
from __future__ import annotations

import atexit
import json
import os
import select
import shutil
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_lock = threading.RLock()
_process = None


def _stop():
    global _process
    if _process is not None and _process.poll() is None:
        _process.terminate()
    _process = None


atexit.register(_stop)


def rpc(op: str, **args):
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            node = os.environ.get('PAPERFLOW_NODE') or shutil.which('node')
            if not node:
                raise RuntimeError('Configure PAPERFLOW_NODE to a Node.js 22+ executable.')
            child_env = os.environ.copy()
            # Node 24+ fetch otherwise ignores the user's existing HTTP(S)_PROXY.
            child_env.setdefault('NODE_USE_ENV_PROXY', '1')
            _process = subprocess.Popen(
                [node, str(ROOT / 'scripts/chatgpt-bridge.mjs')], cwd=ROOT,
                env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        _process.stdin.write(json.dumps({'id':1, 'op':op, 'args':args})+'\n')
        _process.stdin.flush()
        ready, _, _ = select.select([_process.stdout], [], [], 240)
        if not ready:
            _stop()
            raise RuntimeError('ChatGPT transport timed out; please retry.')
        line = _process.stdout.readline()
        if not line:
            _stop()
            raise RuntimeError('ChatGPT transport stopped. Check the local SIWC SDK installation.')
        response = json.loads(line)
        if 'error' in response:
            error=response['error']
            raise RuntimeError(f"{error['code']}: {error['message']}")
        return response['result']


class ChatGPTLLM:
    name = 'chatgpt'

    def __init__(self, model='auto'):
        self.model=model

    def generate(self, prompt, *, system=None, temperature=0.0, max_tokens=1024):
        from .llm import LLMResponse
        # Plan-usage endpoint does not accept temperature or max_output_tokens.
        result=rpc('generate', model=self.model, prompt=prompt, system=system)
        return LLMResponse(text=result['text'], model=result['model'], provider=self.name)

    def stream_generate(self, prompt, *, system=None, temperature=0.0, max_tokens=1024):
        # Collect only a fully completed response before exposing it to the caller.
        yield self.generate(prompt, system=system).text
