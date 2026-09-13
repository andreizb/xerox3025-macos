#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Original three-workflow core probe on copied synthetic fixtures.

Workflows remain in private evidence. No Open action, UI automation, workflow
registration, print command, scanner operation or user file is used.
The later date/direct-output extension uses retained action specifications;
verify-apple-actions.py verifies the full six-execution historical evidence.
This probe refuses to overwrite its existing execution evidence.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from PIL import Image, ImageDraw
from pypdf import PdfReader

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'evidence/2026-09-09/unattended-print/apple-action-execution'
OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
TMP=HERE/'action-test-build'
TMP.mkdir(exist_ok=True,mode=0o700)
os.umask(0o077)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def record(name,value): (OUT/name).write_text(json.dumps(value,indent=2)+'\n')


def execute(name,actions,inputs):
    config=OUT/(name+'.actions.json');config.write_text(json.dumps(actions,indent=2)+'\n')
    workflow=OUT/(name+'.workflow')
    subprocess.run([str(TMP/'workflow-builder'),str(config),str(workflow)],check=True,timeout=20)
    started=time.monotonic()
    # Apple's documented stdin contract treats each newline as one input item.
    command=['/usr/bin/automator','-i','-',str(workflow)]
    env=os.environ.copy();temp=TMP/(name+'-temp');temp.mkdir(exist_ok=True)
    env['TMPDIR']=str(temp)+'/'
    try:
        done=subprocess.run(command,input=''.join(str(p)+'\n' for p in inputs),
                            text=True,capture_output=True,timeout=40,env=env)
        result={'argv':command,'exit_code':done.returncode,'stdout':done.stdout,
                'stderr':done.stderr,'elapsed_seconds':round(time.monotonic()-started,3)}
    except subprocess.TimeoutExpired as failure:
        result={'argv':command,'timeout_seconds':40,'stdout':str(failure.stdout),
                'stderr':str(failure.stderr),'blocker':'headless action did not finish; no UI or retry attempted'}
    record(name+'.execution.json',result)
    return result


def main():
    if (OUT/'engine-run.json').exists() or (OUT/'watermark.execution.json').exists():
        raise SystemExit('Historical evidence already exists. Use a separately scoped output area; do not overwrite it.')
    subprocess.run(['swiftc','-parse-as-library','-target','arm64-apple-macos14.0','-O',
                    str(HERE/'AppleActionWorkflow.swift'),'-o',str(TMP/'workflow-builder')],
                   check=True,timeout=60)
    original=HERE/'fixtures/labels-4.pdf'; original_hash=sha(original)
    before=PdfReader(original)
    image=Image.new('RGBA',(120,60),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rectangle((4,4,115,55),fill=(230,20,20,255))
    draw.rectangle((16,16,35,43),fill=(255,255,255,255))
    draw.rectangle((50,16,100,24),fill=(255,255,255,255))
    stamp=OUT/'synthetic-stamp.png';image.save(stamp)
    copies=OUT/'watermark-input-copies';copies.mkdir(exist_ok=True)
    dest=OUT/'watermark-output';dest.mkdir(exist_ok=True)
    wm=execute('watermark',[
        {'action':'Copy Finder Items','parameters':{'toDirectory':str(copies),'replaceExisting':False}},
        {'action':'Watermark PDF Documents','parameters':{'fileNames':[str(stamp)],'onePDF':False,
                  'angle':0,'opacity':0.6,'scale':1,'xOffset':80,'yOffset':180,'overUnder':1}},
        {'action':'Move Finder Items','parameters':{'toDirectory':str(dest),'replaceExisting':False}},
    ],[original])
    if wm.get('exit_code')!=0:
        record('acceptance.json',{'completed':False,'blocker':'watermark headless action failed',
                                 'original_unchanged':sha(original)==original_hash,'execution':wm});return
    outputs=list(dest.glob('*.pdf'))
    if len(outputs)!=1:
        record('acceptance.json',{'completed':False,'blocker':'watermark action returned no unique PDF',
                                 'original_unchanged':sha(original)==original_hash,'output_files':[str(p) for p in outputs]});return
    marked=outputs[0];after=PdfReader(marked)
    watermark={'input_sha256':original_hash,'output_sha256':sha(marked),
               'input_unchanged':sha(original)==original_hash,
               'source_copy_matches':sha(copies/original.name)==original_hash,
               'page_count':[len(before.pages),len(after.pages)],
               'text_unchanged':[a.extract_text()==b.extract_text() for a,b in zip(before.pages,after.pages)],
               'output':str(marked.relative_to(ROOT))}
    record('watermark-result.json',watermark)
    fixture_names=['geometry-a4.pdf','geometry-custom.pdf','geometry-wide.pdf']
    source_hashes={n:sha(HERE/'fixtures'/n) for n in fixture_names}
    rename_sources=OUT/'rename-source-copies';rename_sources.mkdir(exist_ok=True)
    files=[]
    for label,source in zip(('alpha','beta','gamma'),fixture_names):
        p=rename_sources/(label+'.pdf');shutil.copyfile(HERE/'fixtures'/source,p);files.append(p)
    seq=execute('sequence',[{'action':'Rename Finder Items','parameters':{
        'renameType':3,'renameItems':1,'defaultName':'Scan','numberLocation':1,
        'numberSeparator':1,'startingNumber':7,'useLeadingZeros':True,'minimumCount':'3'}}],files)
    named=sorted(rename_sources.glob('*.pdf'))
    sequence={'execution_ok':seq.get('exit_code')==0,'names':[p.name for p in named],
              'file_hashes':{p.name:sha(p) for p in named},'input_hashes':source_hashes,
              'original_fixture_hashes_unchanged':all(sha(HERE/'fixtures'/n)==h for n,h in source_hashes.items())}
    record('sequence-result.json',sequence)
    date_before=datetime.datetime.now().astimezone().isoformat()
    date=execute('date',[{'action':'Rename Finder Items','parameters':{
        'renameType':0,'dateToUse':0,'dateFormat':3,'dateSeparator':1,
        'datePlacement':0,'nameDateSeparator':1}}],named)
    dated=sorted(rename_sources.glob('*.pdf'))
    record('date-result.json',{'execution_ok':date.get('exit_code')==0,
              'date_before':date_before,'date_after':datetime.datetime.now().astimezone().isoformat(),
              'names':[p.name for p in dated],'file_hashes':{p.name:sha(p) for p in dated},
              'original_fixture_hashes_unchanged':all(sha(HERE/'fixtures'/n)==h for n,h in source_hashes.items())})
    record('engine-run.json',{'completed':True,'watermark':watermark,
                             'sequence_execution_ok':seq.get('exit_code')==0,'date_execution_ok':date.get('exit_code')==0,
                             'workflow_installed':False,'physical_prints':0,'user_documents_touched':0,
                             'pixel_verification_pending':True})


if __name__=='__main__':main()
