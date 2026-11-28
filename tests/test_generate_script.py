import json
import unittest
from pathlib import Path

from generate_script import _split_narration


class NarrationSplitterTests(unittest.TestCase):
    def assert_words_preserved(self, original, chunks):
        expected = original.lower().split()
        actual = " ".join(chunks).lower().split()
        self.assertEqual(actual, expected)

    def test_splits_long_sentence_without_punctuation(self):
        fact = "People often rely on an initial number when making a later estimate even when that number is random and unrelated to the answer."
        chunks = _split_narration(fact, max_words=10)
        self.assertTrue(all(len(chunk.split()) <= 10 for chunk in chunks))
        self.assert_words_preserved(fact, chunks)

    def test_splits_long_clauses_after_commas(self):
        fact = "Researchers presented an initial number, participants considered the question, and their final estimates shifted toward that starting point."
        chunks = _split_narration(fact, max_words=8)
        self.assertTrue(all(3 <= len(chunk.split()) <= 8 for chunk in chunks))
        self.assert_words_preserved(fact, chunks)

    def test_keeps_short_sentences_readable(self):
        fact = "The result was surprising. The groups gave different estimates."
        chunks = _split_narration(fact, max_words=18)
        self.assertEqual(chunks, ["The result was surprising.", "The groups gave different estimates."])

    def test_handles_anchoring_bank_fact(self):
        fact = "In a classic experiment, people spun a wheel rigged to land on 10 or 65. They then estimated the percentage of African countries in the United Nations. The median estimate was about 25 after seeing 10. It was about 45 after seeing 65."
        chunks = _split_narration(fact)
        self.assertTrue(all(len(chunk.split()) <= 18 for chunk in chunks))
        self.assert_words_preserved(fact, chunks)

    def test_every_vetted_topic_fits_scene_limits(self):
        bank_path = Path(__file__).resolve().parents[1] / "topics_bank.json"
        topics = json.loads(bank_path.read_text(encoding="utf-8"))["topics"]
        for topic in topics:
            with self.subTest(topic=topic["id"]):
                chunks = _split_narration(topic["fact"])
                self.assertTrue(all(len(chunk.split()) <= 18 for chunk in chunks))
                self.assertLessEqual(len(chunks) + 2, 10)


if __name__ == "__main__":
    unittest.main()
