import app
app._rebuild_preloaded_documents_store()
s = app.load_store()
print('DOCS', s.get('documents'))
print('COUNT', len(s.get('chunks', [])))
print('HAS_PAGE', all(('page_start' in c and 'chunk_id' in c) for c in s.get('chunks', [])[:50]))
