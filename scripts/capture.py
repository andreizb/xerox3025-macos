#!/usr/bin/env python3
"""Physical scan harness; call only after the owner loads the test sheet."""
import argparse,hashlib,json,os,pathlib,signal,subprocess,time
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--printer-uuid',required=True);p.add_argument('--output',type=pathlib.Path,default=pathlib.Path('evidence/acquisition'));p.add_argument('--mode',default='Color');p.add_argument('--resolution',type=int,default=75);p.add_argument('--stock',action='store_true');p.add_argument('--crop',nargs=4);p.add_argument('--jpeg',choices=['yes','no'],default='yes');p.add_argument('--debug',type=int,choices=range(6),default=3);p.add_argument('--timeout',type=float,default=150);a=p.parse_args()
if a.timeout<=0:p.error('--timeout must be positive')
root=pathlib.Path(__file__).resolve().parents[1];out=a.output.resolve();scans=out/'scans';scans.mkdir(parents=True,exist_ok=True,mode=0o700)
if pathlib.Path(a.name).name != a.name or a.name in ('.','..'):p.error('name must be a filename stem')
sane_config=root/'build/runtime/sane.d';sane_config.mkdir(parents=True,exist_ok=True)
(sane_config/'dll.conf').write_text('xerox_mfp\n')
identity=json.loads(subprocess.check_output([str(root/'build/discover'),a.printer_uuid],text=True));device=f"xerox_mfp:tcp {identity['hostname']} 9400"
env=os.environ.copy();env.update(SANE_CONFIG_DIR=str(root/'build/runtime/sane.d'),SANE_DEBUG_XEROX_MFP=str(a.debug),SANE_DEBUG_DLL='3')
if a.stock:env['LD_LIBRARY_PATH']=str(root/'build/stock-backend')
args=[str(root/'prefix/bin/scanimage'),'-d',device,'--source','Flatbed','--mode',a.mode,'--resolution',str(a.resolution),'--jpeg='+a.jpeg,'--format=png']
if a.crop:
 for option,value in zip(['-l','-t','-x','-y'],a.crop):args += [option,value]
result={'name':a.name,'backend':'stock' if a.stock else 'patched','mode':a.mode,'resolution':a.resolution,'crop_mm':a.crop,'jpeg_transport':a.jpeg};t=time.monotonic();image=scans/(a.name+'.png')
with image.open('wb') as f:
 proc=subprocess.Popen(args,env=env,stdout=f,stderr=subprocess.PIPE)
 try:
  _,log=proc.communicate(timeout=a.timeout)
 except subprocess.TimeoutExpired:
  result['timeout']=True
  # Let scanimage call sane_cancel and release its reservation before killing.
  proc.send_signal(signal.SIGINT)
  try:_,log=proc.communicate(timeout=20)
  except subprocess.TimeoutExpired:
   result['forced_termination']=True;proc.kill();_,log=proc.communicate()
 result['exit_code']=proc.returncode
result['elapsed_seconds']=round(time.monotonic()-t,3);result['bytes']=image.stat().st_size;result['sha256']=hashlib.sha256(image.read_bytes()).hexdigest()
(out/(a.name+'.log')).write_bytes(log);(out/(a.name+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));print(log.decode(errors='replace')[-2500:])
raise SystemExit(0 if result.get('exit_code')==0 else 1)
