"""Install the pinned official ChatGPT DevKit into ignored local storage."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / '.local' / 'siwc-devkit'
REVISION = '0a36fefeb913055c8c7a1a29b63d82b96b2e841a'
REPOSITORY = 'https://github.com/openai/sign-in-with-chatgpt-devkit.git'


def run(*args):
    subprocess.run(args, cwd=SDK, check=True)


def main():
    node = os.environ.get('PAPERFLOW_NODE') or shutil.which('node')
    if not node:
        raise SystemExit('Install Node.js 24.5+ and add it to PATH first.')
    version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
    if tuple(map(int, version.split('.')[:2])) < (24, 5):
        raise SystemExit('Node.js 24.5+ is required for environment proxy support.')
    package_manager = shutil.which('pnpm') or shutil.which('npm')
    if not package_manager:
        raise SystemExit('Install pnpm or npm first.')
    if not shutil.which('git'):
        raise SystemExit('Install Git first.')
    if not SDK.exists():
        SDK.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', REPOSITORY, str(SDK)], check=True)
        run('git', 'checkout', '--detach', REVISION)
    else:
        origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=SDK, text=True).strip()
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SDK, text=True).strip()
        if origin.removesuffix('.git') != REPOSITORY.removesuffix('.git') or revision != REVISION:
            raise SystemExit('Existing SDK does not match the pinned official source; it has been left unchanged.')
    if Path(package_manager).name == 'pnpm':
        (SDK / 'pnpm-workspace.yaml').write_text('packages:\n  - packages/local\n')
        run(package_manager, 'install', '--ignore-scripts')
        run(package_manager, 'exec', 'tsc', '-p', 'packages/local/tsconfig.json')
    else:
        run(package_manager, 'install', '--ignore-scripts', '--workspace', '@siwc/local', '--include-workspace-root')
        run(package_manager, 'exec', '--', 'tsc', '-p', 'packages/local/tsconfig.json')
    print('ChatGPT SDK ready. Start PaperFlow and authorize your own account in the login page.')


if __name__ == '__main__':
    main()
