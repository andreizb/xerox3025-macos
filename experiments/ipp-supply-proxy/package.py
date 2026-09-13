#!/usr/bin/env python3
"""Package the optional ARM64 supply proxy without installing or changing queues."""
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT / 'build/package-candidate')
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    raise RuntimeError('Refusing to replace an existing output directory: ' + str(output))
(output / 'runtime').mkdir(parents=True)
(output / 'maintenance').mkdir()
(output / 'licenses').mkdir()
architecture = []
for name in ('ipp-supply-proxy', 'discover'):
    target = output / 'runtime' / name
    shutil.copy2(ROOT / 'build' / name, target)
    arch = subprocess.check_output(['/usr/bin/lipo', '-archs', target], text=True).strip()
    if arch != 'arm64':
        raise RuntimeError('Non-native runtime: ' + name)
    dependencies = subprocess.check_output(['/usr/bin/otool', '-L', target], text=True).splitlines()[1:]
    if any(not line.strip().startswith(('/usr/lib/', '/System/Library/')) for line in dependencies):
        raise RuntimeError('Unbundled dependency in ' + name)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', target], check=True)
    architecture.append({'file': 'runtime/' + name, 'architectures': arch,
                         'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                         'dependencies': dependencies, 'signature': 'ad-hoc verified'})
for destination, source in {
    'proxy-maintenance.py': ROOT / 'proxy-maintenance.py',
    'associate-queue.py': PROJECT / 'scripts/associate-queue.py',
    'select-python': PROJECT / 'packaging/select-python',
}.items():
    shutil.copy2(source, output / 'maintenance' / destination)
for name in ('install', 'uninstall'):
    shutil.copy2(ROOT / name, output / name)
    (output / name).chmod(0o755)
for name in ('REVIEW.md', 'INSTALLER-DESIGN.md', 'INSTALLATION.md', 'sources.json'):
    shutil.copy2(ROOT / name, output / name)
for source in (ROOT / 'licenses').iterdir():
    if source.is_file():
        shutil.copy2(source, output / 'licenses' / source.name)
for part in ('runtime', 'maintenance', 'licenses'):
    hashes = {str(p.relative_to(output / part)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((output / part).rglob('*')) if p.is_file()}
    (output / (part + '.json')).write_text(json.dumps(hashes, indent=2, sort_keys=True) + '\n')
    (output / (part + '.sha256')).write_text(''.join(value + '  ' + name + '\n' for name, value in hashes.items()))
(output / 'architecture.json').write_text(json.dumps(architecture, indent=2) + '\n')
# No private evidence, review snapshots, scanned pages, caches or process logs.
with tarfile.open(output / 'corresponding-source.tar.gz', 'w:gz') as archive:
    for name in ('main.go', 'main_test.go', 'go.mod', 'go.sum', 'sources.json', 'build.py',
                 'package.py', 'proxy-maintenance.py', 'test_maintenance.py', 'install', 'uninstall',
                 'REVIEW.md', 'INSTALLER-DESIGN.md', 'INSTALLATION.md', 'licenses', 'vendor',
                 'vendor.sha256.json'):
        path = ROOT / name
        archive.add(path, arcname='printer-modernization/' + str(path.relative_to(PROJECT)))
    for name in ('src/discover.c', 'scripts/associate-queue.py', 'packaging/select-python', 'LICENSE'):
        archive.add(PROJECT / name, arcname='printer-modernization/' + name)
    toolchain = ROOT / 'build' / json.loads((ROOT / 'sources.json').read_text())['go']['url'].rsplit('/', 1)[1]
    archive.add(toolchain, arcname='printer-modernization/experiments/ipp-supply-proxy/build/' + toolchain.name)
(output / 'package.sha256').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' +
    str(path.relative_to(output)) + '\n' for path in sorted(output.rglob('*')) if path.is_file()))
print(output)
