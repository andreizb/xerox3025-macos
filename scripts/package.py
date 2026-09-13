#!/usr/bin/env python3
"""Create a relocatable, reviewable per-user ARM64 package; never install it."""
import argparse, hashlib, json, os, pathlib, plistlib, re, shutil, subprocess, tarfile, io
from source_archive import add_project_sources
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=pathlib.Path,default=ROOT/'dist/Xerox3025Bridge-candidate')
parser.add_argument('--identity-config',type=pathlib.Path,default=ROOT/'packaging/device.json',help='explicit stable printer identity; contains no IP address')
args=parser.parse_args()
DIST=args.output.resolve()
PREFIX=ROOT/'prefix'
def run(args): return subprocess.check_output(list(map(str,args)),text=True)
if not args.identity_config.is_file():
 parser.error('Missing private identity configuration. Copy packaging/device.example.json to packaging/device.json and supply your printer identity, or use --identity-config.')
identity=json.loads(args.identity_config.read_text())
if set(identity)!={'printer_uuid','published_name','serial_number'}:raise RuntimeError('Unexpected identity configuration fields')
if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',identity['printer_uuid']):raise RuntimeError('Invalid printer UUID')
for key,value in identity.items():
 if not isinstance(value,str) or len(value)>255 or any(ord(c)<32 or ord(c)==127 for c in value):raise RuntimeError('Invalid identity value: '+key)
identity['printer_uuid']=identity['printer_uuid'].lower()
if not identity['published_name']:raise RuntimeError('The published name must not be empty')
if DIST.exists():
 if not (DIST/'payload.sha256').is_file():raise RuntimeError('Refusing to replace a directory that is not a bridge package: '+str(DIST))
 shutil.rmtree(DIST)
PAYLOAD=DIST/'payload'
for d in ('bin','lib/sane','etc','licenses'): (PAYLOAD/d).mkdir(parents=True,exist_ok=True)
for name,src in {'airsaned':PREFIX/'sbin/airsaned','scanimage':PREFIX/'bin/scanimage','discover':ROOT/'build/discover','service-lock':ROOT/'build/service-lock'}.items():shutil.copy2(src,PAYLOAD/'bin'/name)
for name in ('libsane.1.dylib','libjpeg.62.dylib','libpng16.16.dylib','libusb-1.0.0.dylib'):shutil.copy2(PREFIX/'lib'/name,PAYLOAD/'lib'/name)
shutil.copy2(PREFIX/'lib/sane/libsane-xerox_mfp.1.so',PAYLOAD/'lib/sane/libsane-xerox_mfp.1.so')
for name in ('install','uninstall','uninstall-all'): shutil.copy2(ROOT/'packaging'/name,DIST/name);(DIST/name).chmod(0o755)
shutil.copy2(ROOT/'packaging/bridge-run',PAYLOAD/'bin/bridge-run');(PAYLOAD/'bin/bridge-run').chmod(0o755)
shutil.copy2(ROOT/'packaging/diagnostics',PAYLOAD/'bin/diagnostics');(PAYLOAD/'bin/diagnostics').chmod(0o755)
(PAYLOAD/'etc/options.conf').write_text('device xerox_mfp:.*\n'+'device-uuid '+identity['printer_uuid']+'\npublished-name '+identity['published_name']+'\nlocation This Mac\n'+('serial-number '+identity['serial_number']+'\n' if identity['serial_number'] else ''))
(PAYLOAD/'etc/access.conf').write_text('allow 127.0.0.1/32\nallow ::1/128\n')
(PAYLOAD/'etc/ignore.conf').write_text('')
(PAYLOAD/'etc/device.plist').write_bytes(plistlib.dumps(identity))
report=[]
for file in sorted(PAYLOAD.rglob('*')):
 if not file.is_file() or 'Mach-O' not in run(['/usr/bin/file','-b',file]):continue
 arch=run(['/usr/bin/lipo','-archs',file]).strip()
 if arch!='arm64':raise RuntimeError(f'Non-native dependency: {file}: {arch}')
 deps=[line.strip().split(' (compatibility')[0] for line in run(['/usr/bin/otool','-L',file]).splitlines()[1:]]
 for dep in deps:
  if dep.startswith(('/usr/lib/','/System/Library/')):continue
  if not dep.startswith((str(PREFIX)+'/', '@rpath/')):raise RuntimeError('Unexpected dependency: '+dep)
  target=PAYLOAD/'lib'/pathlib.Path(dep).name
  if not target.exists():raise RuntimeError('Unbundled dependency: '+dep)
  relative='@loader_path/'+os.path.relpath(target,file.parent)
  run(['/usr/bin/install_name_tool','-change',dep,relative,file])
 if file.suffix=='.dylib':run(['/usr/bin/install_name_tool','-id','@loader_path/'+file.name,file])
 # Drop absolute build rpaths, even if all imports were already relocated.
 lines=run(['/usr/bin/otool','-l',file]).splitlines()
 for i,line in enumerate(lines):
  if line.strip()=='cmd LC_RPATH':
   rpath=lines[i+2].strip().split(' (offset')[0].removeprefix('path ')
   if rpath.startswith('/'):run(['/usr/bin/install_name_tool','-delete_rpath',rpath,file])
 run(['/usr/bin/codesign','--force','--sign','-',file])
 run(['/usr/bin/codesign','--verify','--strict',file])
 finaldeps=run(['/usr/bin/otool','-L',file])
 if any(x in '\n'.join(finaldeps.splitlines()[1:]) for x in ('/opt/homebrew','/usr/local',str(ROOT))):raise RuntimeError('Unrelocated library')
 report.append({'file':str(file.relative_to(PAYLOAD)),'architectures':arch,'dependencies':finaldeps.splitlines()[1:],'signature':'ad-hoc verified'})
licenses={'AirSane-GPL3.txt':'AirSane/LICENSE','SANE-LICENSE.txt':'sane-backends/LICENSE','SANE-COPYING.txt':'sane-backends/COPYING','libusb-LGPL.txt':'libusb-1.0.30/COPYING','libpng-LICENSE.txt':'libpng-1.6.58/LICENSE','libjpeg-turbo-LICENSE.md':'libjpeg-turbo-3.2.0/LICENSE.md','libjpeg-IJG.txt':'libjpeg-turbo-3.2.0/README.ijg'}
for dest,source in licenses.items():shutil.copy2(ROOT/'upstream'/source,PAYLOAD/'licenses'/dest)
for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','sources.lock.json','capabilities.json'):
 shutil.copy2(ROOT/name,DIST/name)
shutil.copytree(ROOT/'docs',DIST/'docs')
if (ROOT/'scripts/associate-queue.py').is_file():
 (DIST/'maintenance').mkdir()
 shutil.copy2(ROOT/'scripts/associate-queue.py',DIST/'maintenance/associate-queue.py')
 for name in ('association-maintenance.py','select-python'):
  shutil.copy2(ROOT/'packaging'/name,DIST/'maintenance'/name)
 (DIST/'maintenance.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted((DIST/'maintenance').iterdir()) if p.is_file()))
(DIST/'architecture.json').write_text(json.dumps(report,indent=2)+'\n')
# Provide the full preferred source form of bundled copyleft components, plus
# untouched dependency release tarballs, local patches, and the build scripts.
with tarfile.open(DIST/'corresponding-source.tar.gz','w:gz') as output:
 add_project_sources(output, ROOT)
 lock=json.loads((ROOT/'sources.lock.json').read_text())
 manifests={}
 for key,entry in lock.items():
  if 'commit' in entry:
   export=ROOT/'pristine'/entry['directory']
   if export.is_dir():
    manifest=json.loads((ROOT/'pristine/manifest.json').read_text())[key]
    hashes={str(p.relative_to(export)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(export.rglob('*')) if p.is_file()}
    if manifest!={'commit':entry['commit'],'sha256':hashes}:raise RuntimeError('Pristine export changed: '+key)
    manifests[key]=manifest
    output.add(export,arcname='printer-modernization/pristine/'+entry['directory'])
   else:
    archive=subprocess.check_output(['git','-C',str(ROOT/'upstream'/entry['directory']),'archive',entry['commit']])
    hashes={}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
     for member in source:
      data=source.extractfile(member).read() if member.isfile() else None
      if data is not None:hashes[member.name]=hashlib.sha256(data).hexdigest()
      member.name='printer-modernization/pristine/'+entry['directory']+'/'+member.name
      output.addfile(member,io.BytesIO(data) if data is not None else None)
    manifests[key]={'commit':entry['commit'],'sha256':hashes}
  else:
   archive=ROOT/'downloads'/entry['url'].rsplit('/',1)[1]
   assert hashlib.sha256(archive.read_bytes()).hexdigest()==entry['sha256']
   output.add(archive,arcname='printer-modernization/downloads/'+archive.name)
 manifestdata=(json.dumps(manifests,indent=2)+'\n').encode()
 member=tarfile.TarInfo('printer-modernization/pristine/manifest.json');member.size=len(manifestdata)
 output.addfile(member,io.BytesIO(manifestdata))
hashes=[]
for file in sorted(PAYLOAD.rglob('*')):
 if file.is_file():hashes.append(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+str(file.relative_to(PAYLOAD)))
(DIST/'payload.sha256').write_text('\n'.join(hashes)+'\n')
print(DIST)
