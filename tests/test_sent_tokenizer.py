import unittest

from ingestor_utils.utils import sent_tokenize


class PreProcessingTests(unittest.TestCase):
    def test_sentence_tokenizer(self):
        """
        sentence tokenization tests
        """
        samples = [
            "Effective September 1, 2017, John Smith (“Advisor”) and XYZ, Inc. (“Company”) agree as follows:",
            "Fig. 2 shows a U.S.A. map.",
            "The item at issue is no. 3553.",
            "Computershare Trust Company, N.A. (“Computershare”) is the transfer agent and registrar for our common stock.",
            "valid any day after january 1. not valid on federal holidays, including february 14, or with other in-house events, specials, or happy hour.",
            "LSTM networks, which we preview in Sec. 2, have been successfully",
        ]
        for text in samples:
            sentences = sent_tokenize(text)
            expected = [text]
            self.assertEquals(sentences, expected)
