import os, tempfile, fitz
import app

text = 'Q1. What is object-oriented programming?\n\nQ2. Explain the difference between classes and objects.'
f = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
f.close()
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), text)
doc.save(f.name)
doc.close()
extracted = app.extract_questions_from_pdf(f.name)
print('COUNT', len(extracted))
print('RESULTS', extracted[:3])
os.unlink(f.name)
