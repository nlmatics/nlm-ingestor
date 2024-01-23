import logging
import os
import string

from symspellpy.symspellpy import SymSpell
from symspellpy.symspellpy import Verbosity

import nlm_ingestor.ingestor as ingestor
from nlm_ingestor.ingestor import patterns

logger = logging.getLogger(__name__)


class SpellUtil:
    def __init__(self):
        self.sym_spell = SymSpell(2, 7)

        dictionary_path = os.path.join(
            os.path.dirname(os.path.abspath(ingestor.__file__)),
            "../ingestor_models/symspell/frequency_dictionary_en_82_765.txt",
        )
        bigram_path = os.path.join(
            os.path.dirname(os.path.abspath(ingestor.__file__)),
            "../ingestor_models/symspell/frequency_dictionary_en_82_765.txt",
        )

        if not self.sym_spell.load_dictionary(
            dictionary_path, term_index=0, count_index=1,
        ):
            logging.error(f"Dictionary file not found: {dictionary_path}")
            return
        if not self.sym_spell.load_bigram_dictionary(
            bigram_path, term_index=0, count_index=2,
        ):
            logger.error(f"Bigram dictionary file not found: {bigram_path}")
            return

    def lookup_word(self, input_term):
        max_edit_distance_lookup = 2
        suggestion_verbosity = Verbosity.CLOSEST
        # ignore_token = None
        ignore_token = "|".join(patterns.spell_check)
        suggestions = self.sym_spell.lookup(
            input_term,
            suggestion_verbosity,
            max_edit_distance_lookup,
            transfer_casing=False,
            ignore_token=ignore_token,
        )
        # print(suggestions)
        # for suggestion in suggestions:
        #     print("{}, {}, {}".format(suggestion.term, suggestion.distance,
        #                               suggestion.count))

        if len(suggestions) > 0:
            return suggestions[0].term
        else:
            return input_term

    # def lookup_sentence(self, input_term):

    def lookup_compound(self, input_term):
        max_edit_distance_lookup = 2
        suggestions = self.sym_spell.lookup_compound(
            input_term,
            max_edit_distance_lookup,
            transfer_casing=True,
            ignore_non_words=True,
        )
        # for suggestion in suggestions:
        #     print("{}, {}, {}".format(suggestion.term, suggestion.distance,
        #                               suggestion.count))

        if len(suggestions) > 0:
            return suggestions[0].term
        else:
            return input_term

    def segment(self, input_term):
        is_mixed_case_term = not input_term.islower()
        if is_mixed_case_term:
            input_term = input_term.lower()
        suggestion = self.sym_spell.word_segmentation(input_term)
        corrected_string = suggestion.corrected_string
        if is_mixed_case_term:
            corrected_string = string.capwords(corrected_string)
        return corrected_string
