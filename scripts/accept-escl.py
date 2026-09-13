#!/usr/bin/env python3
"""Real-device acceptance. The owner must first place a test target on the glass.

Images remain in the ignored private evidence folder. No printer settings change.
Development dependency: Pillow (not installed or shipped by the bridge).
"""
import argparse, datetime, hashlib, io, json, pathlib, time, urllib.request, urllib.error
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence' / datetime.date.today().isoformat()
BASE = 'http://127.0.0.1:18325/eSCL'

def ticket(mode, dpi, region=(0, 0, 2551, 3509), fmt='image/png'):
    x, y, w, h = region
    return f'''<?xml version="1.0"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
<pwg:Version>2.0</pwg:Version><scan:Intent>Document</scan:Intent>
<pwg:ScanRegions><pwg:ScanRegion><pwg:Height>{h}</pwg:Height><pwg:Width>{w}</pwg:Width><pwg:XOffset>{x}</pwg:XOffset><pwg:YOffset>{y}</pwg:YOffset><pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits></pwg:ScanRegion></pwg:ScanRegions>
<scan:InputSource>Platen</scan:InputSource><scan:ColorMode>{mode}</scan:ColorMode>
<scan:XResolution>{dpi}</scan:XResolution><scan:YResolution>{dpi}</scan:YResolution>
<pwg:DocumentFormat>{fmt}</pwg:DocumentFormat></scan:ScanSettings>'''.encode()

def create(mode, dpi, region=(0, 0, 2551, 3509), fmt='image/png'):
    req = urllib.request.Request(BASE+'/ScanJobs', ticket(mode, dpi, region, fmt), {'Content-Type':'text/xml'}, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        assert response.status == 201, response.status
        location = response.headers['Location']
    # The service is local, and the harness never follows a remote image URL.
    from urllib.parse import urljoin, urlsplit
    url = urljoin(BASE+'/', location)
    parsed = urlsplit(url)
    assert parsed.hostname in ('127.0.0.1', 'localhost', '::1') and parsed.port == 18325
    return url

def acquire(name, mode, dpi, region=(0, 0, 2551, 3509)):
    start = time.monotonic()
    record = dict(name=name, mode=mode, dpi=dpi, region_300dpi=region)
    url = create(mode, dpi, region)
    try:
        with urllib.request.urlopen(url+'/NextDocument', timeout=150) as response:
            data = response.read()
            record['content_type'] = response.headers.get('Content-Type')
        dest = OUT/'scans'/(name+'.png')
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest.write_bytes(data)
        with Image.open(io.BytesIO(data)) as im:
            im.load()  # Complete decompression, not merely an IHDR check.
            record.update(size=list(im.size), pixel_mode=im.mode, extrema=im.getextrema())
            # AirSane crops the overscanned hardware window to the exact eSCL
            # region, independent of SANE's coarser acquisition coordinates.
            expected = [max(1, v*dpi//300) for v in region[2:]]
            assert list(im.size) == expected, (im.size,expected)
            assert im.mode == {'RGB24':'RGB','Grayscale8':'L','BlackAndWhite1':'1'}[mode], im.mode
        record.update(passed=True, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    finally:
        try: urllib.request.urlopen(urllib.request.Request(url, method='DELETE'), timeout=30).close()
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
    record['seconds'] = round(time.monotonic()-start, 3)
    return record

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    cases_group=parser.add_mutually_exclusive_group()
    cases_group.add_argument('--matrix',action='store_true')
    cases_group.add_argument('--repeat',type=int,default=0,help='Sequential mixed-mode/corner-crop regression jobs')
    parser.add_argument('--name',default='escl-check')
    parser.add_argument('--output',type=pathlib.Path,default=OUT)
    args=parser.parse_args()
    OUT=args.output
    OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
    if args.repeat < 0: parser.error('--repeat must be nonnegative')
    deadline=time.monotonic()+60
    while True:
        try:
            with urllib.request.urlopen(BASE+'/ScannerCapabilities',timeout=3) as response: response.read()
            break
        except (OSError,urllib.error.HTTPError):
            if time.monotonic()>deadline: raise
            time.sleep(1)
    cases=[(m,d,(0,0,2551,3509)) for m in ('RGB24','Grayscale8','BlackAndWhite1') for d in (75,100,150,200,300,600)] if args.matrix else [('BlackAndWhite1',75,(0,0,2551,3509))]
    if args.matrix: cases += [('RGB24',150,(0,0,1200,1500)),('RGB24',150,(1350,2000,1200,1500))]
    if args.repeat:
        cycle=[('RGB24',150,(0,0,1200,1500)),('RGB24',150,(1350,2000,1200,1500)),
               ('Grayscale8',75,(0,0,2551,3509)),('BlackAndWhite1',75,(0,0,2551,3509))]
        cases=[cycle[i % len(cycle)] for i in range(args.repeat)]
    with (OUT/(args.name+'.jsonl')).open('a') as log:
        for i,(mode,dpi,region) in enumerate(cases):
            name=f'{args.name}-{i+1:02d}-{mode}-{dpi}'
            try: record=acquire(name,mode,dpi,region)
            except Exception as e:
                record=dict(name=name,passed=False,error=str(e)); log.write(json.dumps(record)+'\n');log.flush();print(json.dumps(record),flush=True);raise
            log.write(json.dumps(record)+'\n');log.flush();print(json.dumps(record),flush=True)
