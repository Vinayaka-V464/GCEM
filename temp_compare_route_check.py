import tempfile, os, fitz
from app import app

app.config['TESTING'] = True

with app.test_client() as c:
    with c.session_transaction() as s:
        s['user'] = {'id': 'hod1', 'role': 'hod', 'department': 'Computer Science', 'name': 'HOD'}

    pdf1 = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    pdf2 = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    pdf1.close(); pdf2.close()

    d1 = fitz.open()
    p1 = d1.new_page()
    p1.insert_text((72, 72), 'Q1. What is object-oriented programming?\nQ2. Explain the difference between classes and objects.')
    d1.save(pdf1.name)
    d1.close()

    d2 = fitz.open()
    p2 = d2.new_page()
    p2.insert_text((72, 72), 'Q1. What is object-oriented programming?\nQ2. Describe polymorphism in Python.')
    d2.save(pdf2.name)
    d2.close()

    with open(pdf1.name, 'rb') as f1, open(pdf2.name, 'rb') as f2:
        resp = c.post(
            '/hod/question-paper-comparison',
            data={'internal_papers': [(f1, 'internal.pdf')], 'external_papers': [(f2, 'external.pdf')]},
            content_type='multipart/form-data',
        )
        print('status', resp.status_code)
        print('location', resp.headers.get('Location'))
        print(resp.data.decode('utf-8', 'ignore')[:1200])

    os.unlink(pdf1.name)
    os.unlink(pdf2.name)
