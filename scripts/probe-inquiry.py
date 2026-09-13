#!/usr/bin/env python3
"""Only upstream xerox_mfp INQUIRY; no scan, firmware or settings command."""
import argparse,json,pathlib,socket,subprocess,time
p=argparse.ArgumentParser(description=__doc__);p.add_argument("--printer-uuid",required=True);p.add_argument("--output",type=pathlib.Path,default=pathlib.Path("evidence/inquiry.json"));a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
identity=json.loads(subprocess.check_output([str(root/'build/discover'),a.printer_uuid],text=True))
r={'identity':identity,'command_hex':'1ba81200','timeout_seconds':12,'description':'Exact upstream INQUIRY with longer receive deadline'}
t=time.monotonic()
try:
 with socket.create_connection((identity['hostname'],9400),timeout=5) as s:
  r['connected']=True;s.settimeout(12);s.sendall(bytes.fromhex(r['command_hex']));reply=s.recv(1024)
  r.update(response_bytes=len(reply),response_hex=reply.hex())
except Exception as e:r.update(error=type(e).__name__+': '+str(e))
r['elapsed_seconds']=round(time.monotonic()-t,3)
a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
