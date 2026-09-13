#!/usr/bin/env python3
"""Real eSCL cancellation at pending, warmup and image-transfer stages."""
import concurrent.futures, importlib.util, json, time, urllib.request, urllib.error
spec=importlib.util.spec_from_file_location('accept_escl',__file__.replace('accept-cancel.py','accept-escl.py'))
escl=importlib.util.module_from_spec(spec);spec.loader.exec_module(escl)

def fetch(url, started):
    try:
        with urllib.request.urlopen(url+'/NextDocument',timeout=150) as response:
            first=response.read(4096);started.set()
            total=len(first)
            while True:
                chunk=response.read(32768)
                if not chunk:break
                total+=len(chunk)
            return {'bytes':total}
    except Exception as e:
        return {'transfer_interrupted':str(e)}

if __name__=='__main__':
    import threading
    results=[]
    for stage in ('pending','warmup','transfer'):
        url=escl.create('RGB24',600)
        started=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=None
            if stage!='pending':
                future=pool.submit(fetch,url,started)
                if stage=='transfer':
                    if not started.wait(100):raise RuntimeError('No image transfer started')
                else:time.sleep(0.25)
            start=time.monotonic()
            with urllib.request.urlopen(urllib.request.Request(url,method='DELETE'),timeout=40) as response:
                result={'stage':stage,'delete_status':response.status,'cancel_seconds':round(time.monotonic()-start,3)}
            if future:result['transfer']=future.result(timeout=40)
        assert result['cancel_seconds']<30,result
        result['retry']=escl.acquire('cancel-retry-'+stage,'RGB24',75)
        assert result['retry']['passed']
        results.append(result)
        print(json.dumps(result),flush=True)
    (escl.OUT/'cancel-acceptance.json').write_text(json.dumps(results,indent=2)+'\n')
