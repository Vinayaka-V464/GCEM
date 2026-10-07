import os
import tempfile
import fitz
from app import app


def make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['user'] = {'role': 'hod', 'name': 'HOD User', 'email': 'hod@example.com'}

    dirp = tempfile.mkdtemp()
    internal_path = os.path.join(dirp, 'internal.pdf')
    external_path = os.path.join(dirp, 'external.pdf')
    make_pdf(internal_path, 'Q1. What is object-oriented programming?\nQ2. Explain the concept of classes and objects.')
    make_pdf(external_path, 'Q1. What is object-oriented programming?\nQ2. Describe polymorphism in Python.')

    with open(internal_path, 'rb') as internal_file, open(external_path, 'rb') as external_file:
        resp = client.post(
            '/hod/question-paper-comparison',
            data={
                'internal_papers': [(internal_file, 'internal.pdf')],
                'external_papers': [(external_file, 'external.pdf')],
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        print('status:', resp.status_code)
        print('location:', resp.headers.get('Location'))
        print('set-cookie:', bool(resp.headers.get('Set-Cookie')))
