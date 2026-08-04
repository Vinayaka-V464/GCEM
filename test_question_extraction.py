import unittest

from app import clean_question_text, infer_paper_context


class QuestionExtractionTests(unittest.TestCase):
    def test_strips_exam_metadata_prefix(self):
        sample = "M : Marks, L : Bloom's level, C : Course outcomes. M L C Module – 1 Q.1 a. What is recursion?"
        self.assertEqual(clean_question_text(sample), "What is recursion?")

    def test_strips_module_and_question_numbering(self):
        sample = "Module 2 Q2 b. Explain the concept of inheritance."
        self.assertEqual(clean_question_text(sample), "Explain the concept of inheritance.")

    def test_strips_full_metadata_prefix_sample(self):
        sample = "M : Marks, L: Bloom's level, C: Course outcomes. M L C Module – 1 Q.1 a. still same"
        self.assertEqual(clean_question_text(sample), "")

    def test_drops_generic_fragments(self):
        sample = "10 L2 CO1 b. remove this no need"
        self.assertEqual(clean_question_text(sample), "")

    def test_strips_trailing_exam_suffix(self):
        sample = "Explain python functions and modules with an example. 10 L3 CO3 1 of 2 BCS701 Module – 4 Q.7 a."
        self.assertEqual(clean_question_text(sample), "Explain python functions and modules with an example.")

    def test_infers_paper_context_from_filename_and_text(self):
        context = infer_paper_context("iot_june_july_2026.pdf", "Seventh Semester B.E. Degree Examination June-July 2026")
        self.assertEqual(context['paper_name'], "iot_june_july_2026.pdf")
        self.assertEqual(context['year'], "June-July 2026")


if __name__ == '__main__':
    unittest.main()
