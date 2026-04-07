import json
from pathlib import Path
from utils.pdf_loader import process_pdf_file

base = Path('.')
pdfs = ['MERGED_PUBLIC_PDF_FILES.pdf']
documents = []
chunks = []
for name in pdfs:
    p = base / name
    if not p.exists():
        continue
    c = process_pdf_file(p, name)
    if c:
        documents.append(name)
        chunks.extend(c)

store = {'documents': documents, 'chunks': chunks}
(base / 'data' / 'chunks.json').write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding='utf-8')
print('DOCS', documents)
print('CHUNK_COUNT', len(chunks))
print('HAS_PAGE_META', all(('page_start' in x and 'chunk_id' in x) for x in chunks[:50]))
