import json
import re

from string import punctuation
from typing import List, Dict
from unidecode import unidecode

STOPWORDS_GENE = [
    'a',
    'about',
    'again',
    'all',
    'almost',
    'also',
    'although',
    'always',
    'among',
    'an',
    'and',
    'another',
    'any',
    'are',
    'as',
    'at',
    'be',
    'because',
    'been',
    'before',
    'being',
    'between',
    'both',
    'but',
    'by',
    'can',
    'could',
    'did',
    'do',
    'does',
    'done',
    'due',
    'during',
    'each',
    'either',
    'enough',
    'especially',
    'etc',
    'for',
    'found',
    'from',
    'further',
    'gene',
    'had',
    'has',
    'have',
    'having',
    'here',
    'how',
    'however',
    'i',
    'if',
    'in',
    'into',
    'is',
    'it',
    'its',
    'itself',
    'just',
    'kg',
    'km',
    'made',
    'mainly',
    'make',
    'may',
    'mg',
    'might',
    'ml',
    'mm',
    'most',
    'mostly',
    'must',
    'nearly',
    'neither',
    'no',
    'nor',
    'obtained',
    'of',
    'often',
    'on',
    'our',
    'overall',
    'perhaps',
    'protein',
    'quite',
    'rather',
    'really',
    'regarding',
    'seem',
    'seen',
    'sequence',
    'several',
    'should',
    'show',
    'showed',
    'shown',
    'shows',
    'significantly',
    'since',
    'so',
    'some',
    'such',
    'than',
    'that',
    'the',
    'their',
    'theirs',
    'them',
    'then',
    'there',
    'therefore',
    'these',
    'they',
    'this',
    'those',
    'through',
    'thus',
    'to',
    'upon',
    'use',
    'used',
    'using',
    'various',
    'very',
    'was',
    'we',
    'were',
    'what',
    'when',
    'which',
    'while',
    'with',
    'within',
    'without',
    'would',
]
special_char_regex = re.compile('[^0-9a-zA-Z]+')


class NERDict:
    def __init__(
            self,
    ):
        self.ner_dict = dict()

    def create_ner_dict(self, input_dict: Dict):
        """
        Sample Input Data
        {
            'Abdominal Neoplasms': {
                'type': 'disease',
                'metadata': {
                    'uuid': 'D000008',
                    'derived_from': 'mesh',
                    'tree_numbers': ['C04.588.033']
                }
            },
            'Abdominal Neoplasm': {
                'type': 'disease',
                'metadata': {
                    'uuid': 'D000008',
                    'derived_from': 'mesh',
                    'tree_numbers': ['C04.588.033']
                }
            },
        }
        """
        for input_str, meta_values in input_dict.items():
            if input_str.strip():
                NERDict.insert_tokens(input_str, input_str.split(), None, self.ner_dict, self.ner_dict, meta_values)

    def get_ner_dict(self):
        return self.ner_dict

    def load_ner_dict_from_json(self, json_file: str):
        with open(json_file) as read_file:
            self.ner_dict = json.load(read_file)

    def save_ner_dict_to_json(self, json_file: str):
        with open(json_file, 'w') as write_file:
            json.dump(self.ner_dict, write_file, indent=2)

    def find_keys_in_text(self, text: str, stop_words: List[str]):
        list_of_keys = []
        if text:
            input_list = [i for i in text.split() if i[0].lower() + i[1:] not in stop_words]
            list_of_keys = self.lookup_keys_in_dict(input_list, self.ner_dict, [], list_of_keys)
            # Special case for Pathways
            '''
            # Commenting out the pathway detection as there is a division by Zero in 
            # "len(new_list_keys)/len(input_list) >= 0.5"
            identified_result = [item for sublist in [d['result'].split() for d in list_of_keys] for item in sublist]
            special_words = []
            for word in input_list:
                if ("-" in word or "/" in word) and word not in identified_result:
                    special_words.append(word)
            for word in special_words:
                split_char = '/'
                if "-" in word:
                    split_char = '-'
                new_list_keys = []
                input_list = [i for i in word.split(split_char) if i and i[0].lower() + i[1:] not in stop_words]
                new_list_keys = self.lookup_keys_in_dict(input_list, self.ner_dict, [], new_list_keys)
                if len(new_list_keys)/len(input_list) >= 0.5 and \
                        any([meta['type'].lower() == 'gene' for res in new_list_keys for meta in res['meta']]):
                    derived_dict = {
                        'result': word,
                        'meta': [{
                            'type': 'pathways',
                            'metadata': {
                                'uuid': 'NA',
                                'derived_from': 'derived',
                            }
                        }]
                    }
                    list_of_keys.append(derived_dict)
            '''
        return list_of_keys

    def lookup_keys_in_dict(
            self,
            token_list: List[str],
            lookup_dict: Dict,
            token_cache: List[str],
            list_of_keys: List[Dict]
    ):
        if not list_of_keys:
            list_of_keys = []

        if not token_list:  # Nothing more to check for.
            if token_cache:
                if not lookup_dict.get("synonyms", True) and not lookup_dict.get("ner_dict", True):
                    list_of_keys += [
                        {
                            'result': " ".join(token_cache),
                            'meta': lookup_dict.get("meta", {}),
                        }
                    ]
                token_cache = []
            return list_of_keys
        else:  # There are tokens in the list worth our Attention.
            # Retrieve the first token
            token = NERDict.preprocess_token(token_list[0])
            token_struct = lookup_dict.get(token, None)
            if token_struct:  # We have a match in the dictionary lookup
                if token in token_struct["synonyms"]:  #token_list[0] in token_struct["synonyms"]:  # We have a match in the synonyms
                    token_cache.append(token_list[0].rstrip(punctuation))
                    lookup_dict = token_struct["ner_dict"]
                token_list = token_list[1:]
            else:  # Not Present in the dictionary
                if token_cache:
                    if not lookup_dict.get("synonyms", True) and not lookup_dict.get("ner_dict", True):
                        list_of_keys += [
                            {
                                'result': " ".join(token_cache),
                                'meta': lookup_dict.get("meta", {}),
                            }
                        ]
                    token_cache = []
                lookup_dict = self.ner_dict
                if not lookup_dict.get(token, None):
                    token_list = token_list[1:]
            return self.lookup_keys_in_dict(token_list, lookup_dict, token_cache, list_of_keys)

    @staticmethod
    def insert_tokens(
            input_str: str,
            token_list: List[str],
            parent_token_dict,
            ner_token_dict,
            ner_dict: Dict,
            meta_values: Dict
    ):
        if not token_list:
            existing_meta = None
            if parent_token_dict['ner_dict'].get('meta', None):
                existing_meta = parent_token_dict['ner_dict']['meta']
                if meta_values not in existing_meta:
                    existing_meta.append(meta_values)
            if not parent_token_dict['ner_dict']:
                parent_token_dict['ner_dict'] = {
                    "synonyms": [],
                    "ner_dict": {},
                    "meta": [meta_values] if not existing_meta else existing_meta,
                }
            else:
                parent_token_dict['ner_dict']['synonyms'] = []
                parent_token_dict['ner_dict']['ner_dict'] = {}
                parent_token_dict['ner_dict']['meta'] = [meta_values] if not existing_meta else existing_meta

            return ner_dict
        else:
            token = NERDict.preprocess_token(token_list[0])
            if len(NERDict.tokenize(input_str)) <= 1:
                if not NERDict.is_valid_token(token):
                    return
            token_struct = ner_token_dict.get(token, None)
            if token_struct:
                for t in [token_list[0], token]:
                    if t not in token_struct["synonyms"]:
                        token_struct["synonyms"].append(t)
            else:  # Not Present in the dictionary
                # Create a new dictionary struct
                ner_token_dict[token] = {
                    "synonyms": [token_list[0], token] if token != token_list[0] else [token],
                    "ner_dict": {
                    },
                }

            return NERDict.insert_tokens(input_str, token_list[1:], ner_token_dict[token],
                                         ner_token_dict[token]["ner_dict"], ner_dict,
                                         meta_values)

    @staticmethod
    def preprocess_token(token: str):
        if token:
            token = token.strip()
            if not token:
                return token

            token = unidecode(token)  # Unidecode the token to use the unaccented words
            if special_char_regex.search(token):
                # Contains special characters.
                return token

            if NERDict.contains_letter_and_number(token):
                # Contains letters and numbers.
                return token

            if token.istitle():
                token = token.lower().strip()  # Strip all whitespaces
                token = token.strip(punctuation)  # Strip all punctuations

        return token

    @staticmethod
    def is_valid_token(token: str, stop_words=None):
        ret = False
        if token:
            alnum_chars = sum(char.isalnum() for char in token)
            if alnum_chars > 1:
                ret = True
        return ret

    @staticmethod
    def tokenize(text: str):
        tokens = []
        if text:
            # Right now tokenize on spaces
            tokens = text.split()
        return tokens

    @staticmethod
    def contains_letter_and_number(text: str):
        return text.isalnum() and not text.isalpha() and not text.isdigit()

