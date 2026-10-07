import os
import tempfile
import unittest

import fitz

from app import build_internal_external_similarity_summary, extract_questions_from_pdf


class InternalExternalSimilarityTest(unittest.TestCase):
    def _create_pdf_with_questions(self, text):
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_pdf.close()
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(temp_pdf.name)
        doc.close()
        self.addCleanup(lambda: os.path.exists(temp_pdf.name) and os.unlink(temp_pdf.name))
        return temp_pdf.name

    def test_extract_questions_from_pdf_extracts_question_text_from_real_pdf(self):
        pdf_path = self._create_pdf_with_questions(
            "Q1. What is object-oriented programming?\n\n"
            "Q2. Explain the difference between classes and objects.\n\n"
            "Q3. State the advantages of Python."
        )

        extracted = extract_questions_from_pdf(pdf_path)

        self.assertGreaterEqual(len(extracted), 3)
        self.assertTrue(any('object' in q.lower() for q in extracted))
        self.assertTrue(any('python' in q.lower() for q in extracted))

    def test_build_internal_external_similarity_summary_detects_overlap(self):
        internal_questions = [
            {'question': 'What is object-oriented programming?'},
            {'question': 'Explain the difference between classes and objects.'},
            {'question': 'Write a short note on inheritance.'},
        ]
        external_questions = [
            {'question': 'What is object-oriented programming?'},
            {'question': 'Explain the difference between classes and objects.'},
            {'question': 'Describe polymorphism in Python.'},
        ]

        summary = build_internal_external_similarity_summary(internal_questions, external_questions)

        self.assertGreaterEqual(summary['similarity_score'], 30.0)
        self.assertGreaterEqual(summary['common_questions'], 2)
        self.assertIn('object', [topic['topic'] for topic in summary['similar_topics']])
        self.assertTrue(any(q and q[0].isupper() for q in summary['shared_question_labels']))

    def test_extract_questions_from_pdf_ignores_exam_metadata(self):
        pdf_path = self._create_pdf_with_questions(
            "VISVESVARAYA TECHNOLOGICAL UNIVERSITY\n"
            "Semester End Examination\n"
            "Principal Signature\n"
            "Q1. What is object-oriented programming?\n\n"
            "Q2. Explain the difference between classes and objects."
        )

        extracted = extract_questions_from_pdf(pdf_path)

        self.assertTrue(any('object' in q.lower() for q in extracted))
        self.assertFalse(any('visvesvaraya' in q.lower() for q in extracted))
        self.assertFalse(any('principal signature' in q.lower() for q in extracted))
        self.assertFalse(any('semester end examination' in q.lower() for q in extracted))

    def test_clean_question_text_ignores_exam_headers_and_subitems(self):
        sample = (
            "Year / Sem/ Sec III/6 Duration 1.30hr Course Code.\n"
            "Name CLOUD COMPUTING Max. Marks 50 Q. No. Questions Marks COs* RBT** Level\n"
            "1. a. Define Cloud Security. What are top 5 security concerns faced by\n"
            "cloud users?\n"
            "5. Analyze the security risks posed by shared virtual machine images and management operating systems.\n"
            "1. Model Question Paper USN Sixth.\n"
            "Discuss in detail about distributed system models. L2 10 b.\n"
            "Explain the basic Cluster Architecture with a neat diagram. L2 10 OR\n"
            "Write short notes on Peer-to-Peer network families. L2 10 b."
        )

        cleaned = clean_question_text(sample)

        self.assertIn('Define Cloud Security', cleaned)
        self.assertIn('What are top 5 security concerns faced by', cleaned)
        self.assertIn('Analyze the security risks posed by shared virtual machine images', cleaned)
        self.assertIn('Discuss in detail about distributed system models', cleaned)
        self.assertIn('Explain the basic Cluster Architecture', cleaned)
        self.assertIn('Write short notes on Peer-to-Peer network families', cleaned)
        self.assertNotIn('Year / Sem', cleaned)
        self.assertNotIn('Q. No.', cleaned)
        self.assertNotIn('Model Question Paper', cleaned)
        self.assertNotIn('USN Sixth', cleaned)

    def test_clean_question_text_removes_rbt_level_headers(self):
        sample = (
            "AM to 11:00 AM Course. unwanted1. Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5."
            "1. Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5."
        )

        cleaned = clean_question_text(sample)

        self.assertNotIn('RBT Levels', cleaned)
        self.assertNotIn('L1 L2 L3 L4 L5', cleaned)
        self.assertEqual(cleaned, "")


if __name__ == '__main__':
    unittest.main()
