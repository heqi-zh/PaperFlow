"""Manually start the local workbench and open it in the user's browser."""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8766/'


def service_ready():
    try:
        with urllib.request.urlopen(URL + 'api/health', timeout=1) as response:
            health = json.load(response)
        return health.get('ok') and bool(health.get('project_root')) and Path(health['project_root']).resolve() == ROOT
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_workbench():
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/open', '-a', 'Google Chrome', URL], check=True)
    else:
        webbrowser.open(URL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if service_ready():
        print('PaperFlow 已在运行，直接打开工作台。', flush=True)
        if not args.no_browser:
            open_workbench()
        return 0
    print('正在启动 PaperFlow，请保留此终端窗口。', flush=True)
    # Preserve configured proxies when launched from Finder instead of a shell.
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    environment = os.environ.copy()
    for scheme, proxy in urllib.request.getproxies().items():
        if scheme in {'http', 'https', 'all', 'no'}:
            environment.setdefault(scheme.upper() + '_PROXY', proxy)
    process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'deployments/desktop/server.py'),
                                '--host', '127.0.0.1', '--port', '8766', '--no-browser'], cwd=ROOT, env=environment)
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return process.returncode
            if service_ready():
                break
            time.sleep(.25)
        else:
            print('服务启动较慢，请查看上方日志；就绪后可手动打开 ' + URL, flush=True)
            return process.wait()
        if not args.no_browser:
            open_workbench()
        print('工作台：' + URL + ' ；在此窗口按 Ctrl+C 停止。', flush=True)
        return process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        process.wait()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
