#!/usr/bin/env python3
"""Offline functional qualification; uses no printer, scanner or native application UI."""
import hashlib, json, math, os, shutil, subprocess, tempfile
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.annotations import Text

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BIN = HERE / 'build/xerox-pdf-deskew'
(HERE / 'tmp').mkdir(exist_ok=True)
passed = []
reports = []
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok, name):
    assert ok, name
    passed.append(name)
def fixture(path, angle=0, lines=18, mixed=False):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=True)
    c.translate(A4[0]/2, A4[1]/2)
    c.setFont('Helvetica', 12)
    for i in range(lines):
        c.saveState(); c.rotate((-angle if i % 2 else angle) if mixed else angle)
        c.drawString(-235, 330-i*32, f'Line {i+1:02d}: Document alignment preserves original text and page content.')
        c.restoreState()
    c.showPage(); c.save()
def invoke(src, dst, fail=False):
    before = sha(src)
    p = subprocess.run([BIN, src, dst], capture_output=True, text=True, timeout=60)
    check(sha(src)==before, f'{src.stem}: source unchanged')
    if fail:
        check(p.returncode != 0, f'{src.stem}: rejected')
        return p
    check(p.returncode == 0, f'{src.stem}: succeeded {p.stderr}')
    r = json.loads(p.stdout)
    check(r['inputSHA256']==before and r['outputSHA256']==sha(dst), f'{src.stem}: hashes')
    check(r['ocrLayerAdded'] is False, f'{src.stem}: no OCR added')
    reports.append({'fixture': src.name, 'report': r})
    return r

with tempfile.TemporaryDirectory(prefix='qualification-', dir=HERE/'tmp') as d:
    d = Path(d)
    for angle in (-3, -1, 0, 2, 7, 12):
        src, out = d/f'angle-{angle}.pdf', d/f'out-{angle}.pdf'
        fixture(src, angle)
        r = invoke(src, out); p = r['pages'][0]
        if angle in (-3,-1,2,7):
            check(p['status']=='corrected', f'{angle}: corrected')
            check(abs(p['detectedDegrees']-angle)<0.4, f'{angle}: measured angle within0.4deg: {p}')
            check(p['outputWidth']>=A4[0]-0.1 and p['outputHeight']>=A4[1]-0.1, f'{angle}: no clipping canvas')
            before = ''.join(PdfReader(src).pages[0].extract_text().split())
            after = ''.join(PdfReader(out).pages[0].extract_text().split())
            check(before==after, f'{angle}: independent pypdf text preservation')
            again = invoke(out, d/f'recheck-{angle}.pdf')
            check(abs(again['pages'][0]['detectedDegrees'] or 0) < 0.4, f'{angle}: corrected image nearly horizontal')
        else:
            check(p['status'].startswith('skipped'), f'{angle}: conservative skip')
            check(src.read_bytes()==out.read_bytes(), f'{angle}: skip is byte-identical')
    for name, kwargs in [('blank',{'lines':0}),('one-line',{'angle':3,'lines':1}),('mixed',{'angle':5,'mixed':True})]:
        src, out = d/f'{name}.pdf', d/f'{name}-out.pdf'
        fixture(src, **kwargs); r = invoke(src,out)
        check(r['pages'][0]['status'].startswith('skipped'), f'{name}: uncertain skip')
        check(src.read_bytes()==out.read_bytes(), f'{name}: unchanged derivative')
    base = d/'angle-2.pdf'
    # Existing paths and aliases must not be overwritten.
    out = d/'existing.pdf'; out.write_bytes(b'KEEP')
    invoke(base, out, fail=True); check(out.read_bytes()==b'KEEP','existing output retained')
    invoke(base, base, fail=True)
    link = d/'symlink.pdf'; link.symlink_to(out)
    invoke(base,link,fail=True); check(out.read_bytes()==b'KEEP','symlink target retained')
    # Explicit rejection instead of silently losing interactive/encrypted/cropped structure.
    w=PdfWriter(); w.append(base); w.encrypt('test-only'); enc=d/'encrypted.pdf'; w.write(enc)
    invoke(enc,d/'encrypted-out.pdf',fail=True)
    w=PdfWriter(); w.append(base); w.add_annotation(0,Text(rect=(10,10,30,30),text='keep')); ann=d/'annotated.pdf'; w.write(ann)
    invoke(ann,d/'annotated-out.pdf',fail=True)
    w=PdfWriter(); w.add_page(PdfReader(base).pages[0]); w.pages[0].cropbox.lower_left=(10,10); crop=d/'cropped.pdf'; w.write(crop)
    invoke(crop,d/'cropped-out.pdf',fail=True)
    bad=d/'malformed.pdf'; bad.write_bytes(b'not a PDF')
    invoke(bad,d/'malformed-out.pdf',fail=True)
    # Physical scan evidence, without requesting another scan. This page is already essentially straight.
    saved=ROOT/'evidence/2026-09-09/post-firmware-native/PrintCenter.pdf'
    private_available=saved.is_file() and os.environ.get('XEROX_SKIP_PRIVATE') != '1'
    if private_available:
        r=invoke(saved,d/'saved-out.pdf')
        check(r['pages'][0]['status']=='skipped-already-straight','saved physical scan already straight')
        check(saved.read_bytes()==(d/'saved-out.pdf').read_bytes(),'saved OCR scan remains byte-identical')
    # Image-only PDF: force an actual correction and verify that no OCR layer is added.
    poppler=os.environ.get('PDFTOPPM') or shutil.which('pdftoppm') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm')
    subprocess.run([poppler,'-r','150','-singlefile','-png',d/'angle-0.pdf',d/'raster-source'],check=True,capture_output=True)
    c=canvas.Canvas(str(d/'raster.pdf'),pagesize=A4)
    c.translate(A4[0]/2,A4[1]/2); c.rotate(2)
    c.drawImage(str(d/'raster-source.png'),-A4[0]*.45,-A4[1]*.45,width=A4[0]*.9,height=A4[1]*.9)
    c.showPage(); c.save()
    r=invoke(d/'raster.pdf',d/'raster-out.pdf')
    check(r['pages'][0]['status']=='corrected','image-only PDF actually corrected')
    check(not PdfReader(d/'raster-out.pdf').pages[0].extract_text().strip(),'image-only input has no output OCR')
    # Existing native OCR must survive an actual correction too (no fresh acquisition).
    if private_available:
        w=PdfWriter(); page=PdfReader(saved).pages[0]
        page.add_transformation(Transformation().translate(-A4[0]/2,-A4[1]/2).rotate(2).translate(A4[0]/2+20,A4[1]/2+20))
        page.mediabox.upper_right=(A4[0]+40,A4[1]+40); page.cropbox=page.mediabox
        w.add_page(page); w.write(d/'native-ocr-tilted.pdf')
        r=invoke(d/'native-ocr-tilted.pdf',d/'native-ocr-straight.pdf')
        check(r['pages'][0]['status'] in ('corrected','skipped-insufficient-text','skipped-inconsistent-lines'),'native OCR derivative either confidently corrected or refused')
        check(''.join(PdfReader(d/'native-ocr-tilted.pdf').pages[0].extract_text().split())==''.join(PdfReader(d/'native-ocr-straight.pdf').pages[0].extract_text().split()),'native OCR text preserved in retained derivative')
    # A deterministic image plus invisible text layer proves retained OCR on a changed page.
    c=canvas.Canvas(str(d/'invisible-ocr.pdf'),pagesize=A4)
    c.translate(A4[0]/2,A4[1]/2); c.rotate(2)
    c.drawImage(str(d/'raster-source.png'),-A4[0]*.45,-A4[1]*.45,width=A4[0]*.9,height=A4[1]*.9)
    t=c.beginText(); t.setTextRenderMode(3); t.setFont('Helvetica',12)
    t.setTextOrigin(-200,250); t.textLine('EXISTING INVISIBLE OCR LAYER'); c.drawText(t)
    c.showPage(); c.save()
    r=invoke(d/'invisible-ocr.pdf',d/'invisible-ocr-out.pdf')
    check(r['pages'][0]['status']=='corrected','invisible OCR PDF actually corrected')
    check('EXISTING INVISIBLE OCR LAYER' in PdfReader(d/'invisible-ocr-out.pdf').pages[0].extract_text(),'invisible OCR text remains selectable')
    # Multipage handling and intrinsic 90-degree page rotation.
    w=PdfWriter(); w.add_page(PdfReader(d/'angle-2.pdf').pages[0]); w.add_page(PdfReader(d/'angle-0.pdf').pages[0]); w.write(d/'multi.pdf')
    r=invoke(d/'multi.pdf',d/'multi-out.pdf')
    check(len(r['pages'])==2 and r['pages'][0]['status']=='corrected' and r['pages'][1]['status']=='skipped-already-straight','multipage decisions independent')
    check(len(PdfReader(d/'multi-out.pdf').pages)==2,'multipage output count')
    w=PdfWriter(); w.add_page(PdfReader(d/'angle-2.pdf').pages[0]); w.pages[0].rotate(90); w.write(d/'quarter-turn.pdf')
    r=invoke(d/'quarter-turn.pdf',d/'quarter-turn-out.pdf')
    check(r['pages'][0]['status'].startswith('skipped'),'sideways page conservatively skipped')
    check((d/'quarter-turn.pdf').read_bytes()==(d/'quarter-turn-out.pdf').read_bytes(),'intrinsic rotation preserved when skipped')
    # Retain a single synthetic before/after pair for visual QA; not user Documents.
    ev=HERE/'evidence'; ev.mkdir(exist_ok=True)
    shutil.copy2(d/'angle-2.pdf',ev/'synthetic-before.pdf')
    shutil.copy2(d/'out-2.pdf',ev/'synthetic-after.pdf')
    result_name='acceptance.json' if private_available else 'acceptance-portable.json'
    (ev/result_name).write_text(json.dumps({'assertions_passed':len(passed),'checks':passed,'reports':reports,'private_cases_run':private_available,'scope':'offline PDF engine, no application UI or scanner acquisition'},indent=2)+'\n')
    print(json.dumps({'assertions_passed':len(passed),'scope':'offline only'}))
