#!/usr/bin/env python3
"""Owner-authorized physical eSCL encoder acceptance; images stay private.

Development-only readers: Pillow and pypdf. Never runs concurrently with another
scanner acceptance harness. This writes no persistent configuration.
"""
import hashlib, importlib.util, io, json, pathlib, time, urllib.request, urllib.error
from PIL import Image
from pypdf import PdfReader

spec = importlib.util.spec_from_file_location('escl', pathlib.Path(__file__).with_name('accept-escl.py'))
escl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(escl)

if __name__ == '__main__':
    results = []
    for fmt, modes in [('image/jpeg', ['RGB24', 'Grayscale8']),
                       ('application/pdf', ['RGB24', 'Grayscale8', 'BlackAndWhite1'])]:
        for mode in modes:
            start = time.monotonic()
            url = escl.create(mode, 150, (400, 400, 1200, 1500), fmt)
            try:
                with urllib.request.urlopen(url + '/NextDocument', timeout=150) as response:
                    content_type = response.headers.get('Content-Type')
                    data = response.read()
                assert content_type.split(';', 1)[0] == fmt
                extension = 'jpg' if fmt == 'image/jpeg' else 'pdf'
                path = escl.OUT / 'scans' / ('final-format-' + mode + '.' + extension)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.write_bytes(data)
                if extension == 'jpg':
                    im = Image.open(io.BytesIO(data))
                    extra = {}
                else:
                    pdf = PdfReader(io.BytesIO(data))
                    assert len(pdf.pages) == 1
                    images = list(pdf.pages[0].images)
                    assert len(images) == 1
                    im = images[0].image
                    extra = {'pages': 1, 'media_box': list(pdf.pages[0].mediabox)}
                im.load()
                assert im.size == (600, 750), im.size
                assert im.mode == {'RGB24': 'RGB', 'Grayscale8': 'L', 'BlackAndWhite1': '1'}[mode], im.mode
                result = {'file': str(path), 'format': fmt, 'mode': mode,
                          'content_type': content_type, 'bytes': len(data),
                          'sha256': hashlib.sha256(data).hexdigest(), 'passed': True,
                          'seconds': round(time.monotonic() - start, 3),
                          'pixel_mode': im.mode, 'size': list(im.size),
                          'extrema': im.getextrema(), **extra}
                results.append(result)
                print(json.dumps(result), flush=True)
            finally:
                try:
                    urllib.request.urlopen(urllib.request.Request(url, method='DELETE'), timeout=30).close()
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
    (escl.OUT / 'final-format-acceptance.json').write_text(json.dumps(results, indent=2) + '\n')
