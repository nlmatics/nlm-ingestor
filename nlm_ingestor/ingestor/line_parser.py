import datetime
import logging
import math
import re
import string

from nltk.corpus import stopwords

from .patterns import abbreviations
from .patterns import states
from .patterns import states_abbreviations
from .styling_utils import mode_of_list

try:
    stop_words = set(stopwords.words("english"))
except Exception as e:
    logging.error(e)
    import nltk

    stopwords = nltk.download("stopwords")
    stop_words = set(stopwords.words("english"))

stop_words.add("per")
continuing_chars = "!\"&'+,./:;<=?@\\]^_`|}~"
list_chars = [
    "•",
    "➢",
    "*",
    "ƒ",
    "",
    "",
    "",
    "",
    "»",
    "☐",
    "·",
    "�",
    "▪",
    "▪",
    "○",
    "􀁸",
    "–",
]
list_types = {
    "•": "circle",
    "➢": "wide_symbol_arrow",
    "*": "star",
    "ƒ": "f",
    "": "clock",
    "": "small_square",
    "": "narrow_symbol_arrow",
    "": "large_square",
    "»": "double_arrow",
    "☐": "hollow_square",
    "·": "circle",
    "�": "special_char",
    "▪": "very_small_square",
    "▪": "very_small_square",
    "○": "hollow_circle",
    "􀁸": "hollow_squere",
    "–": "dash",
    "‒": "another-dash",
    "̶": "underscore",
}
unicode_list_types = {
    "\\uf0b7": "•",
    "\\uf0fc": "",
}
footnote_types = {
    "©"
}
ambiguous_list_chars = ["+", "-"]
units = ["acres", "miles", "-"]  # - could represent a null value in a row
punctuations = string.punctuation + "“"
start_quotations = ["'", '"', "“"]
end_quotations = ["'", '"', "”"]
"""
Quote Pattern details:
    \\W ==> Match non-alphanumeric characters. Helps in mitigating words like O'Reilly.
    ["“\'] ==> Quote patterns
    (?!\\D\\s) ==> Negative Lookahead for single character following the quote.
                        Helps in removing words like Macy's, don't ...
    (?!\\d+) ==> Negative Lookahead for one or more digits following the pattern.
                        Helps in removing words like '19, '2019
    (.*?)[,;.]?[”"\'] ==> Match all other data.
"""
# Add / Modify Quotation pattern in ingestor_utils/utils.py also.
quote_pattern = re.compile(
    r'(?:(?<=\W)|(?<=^))["“‘’\']+(?!\D\s)(?!\d+)(.*?)[,;.]?[”"‘’\']+',
)  # (r'["“\'](.*?)[,;.]?[”"\']')
single_char_pattern = re.compile(r'[a-zA-Z]')
multi_char_pattern = re.compile(r'[a-zA-Z]+')
roman_number_pattern = re.compile(r'[ixvIXV]+$')
ends_with_sentence_delimiter_pattern = re.compile(r"(?<![.;:][a-zA-Z0-9])(?<!INC|inc|Inc)[.;:]+(?![\w])[\"“‘’”\'\s]*$")
conjunction_list = ["for", "and", "not", "but", "or", "yet", "so", "between"]


class Word:
    def __init__(self, token):
        self.text = token
        self.is_percent = False
        self.is_number = False
        self.is_year = False  # year does not count as a number
        self.is_dollar = False
        self.is_million = False
        self.is_billion = False
        self.is_thousand = False
        self.is_date_entry = False
        self.is_negative = False
        self.length = len(self.text)
        self.is_stop_word = self.text.lower() in stop_words
        self.is_number_range = False
        self.parts = []
        text_without_punct = self.text

        while (
                len(text_without_punct) > 1 and
                (text_without_punct[-1] in string.punctuation or text_without_punct[-1] in end_quotations)
        ):
            text_without_punct = text_without_punct[0:-1]
        # remove leading unbalancced punctuations
        while (
                len(text_without_punct) > 1 and
                (text_without_punct[0] in string.punctuation or text_without_punct[0] in start_quotations)
        ):
            text_without_punct = text_without_punct[1:]

        self.text_without_punct = text_without_punct
        self.is_noun = self.text_without_punct[0].isupper()

        n = self.check_numeric()
        self.check_date()
        try:
            if n:
                n = round(float(n))
                if n > 0:
                    digits = int(math.log10(n)) + 1
                elif n == 0:
                    digits = 1
                else:
                    digits = int(math.log10(-n)) + 2
                self.num_digits = digits
                if digits == 4 and self.text.replace(",", "") == self.text:
                    self.is_year = True
                    self.is_number = False
            else:
                self.num_digits = 0
        except Exception as e:
            logging.error(e)
            self.num_digits = 0

    def check_date(self):
        if "/" in self.text or "-" in self.text:
            text = self.text.replace("/", "-")
            date_patterns = [
                "%b-%d",
                "%B-%d",
                "%B-%d-%y",
                "%B-%d-%Y",
                "%b-%d-%Y",
                "%b-%d-%y",
                "%m-%d",
                "%m-%d-%y",
                "%m-%d-%Y",
            ]
            for pat in date_patterns:
                try:
                    datetime.datetime.strptime(text, pat)
                    self.is_date_entry = True
                    return
                except ValueError:
                    pass
        else:
            self.is_date_entry = False

    def check_numeric(self):
        word = self.text.lower()
        if not word.isalpha():
            if word.isprintable():
                if not word.isnumeric():
                    if word.startswith("(") and word.endswith(")"):
                        word = word[1:-1]
                    if word.startswith("-"):
                        self.is_negative = True
                        word = word[1:]
                    if word.startswith("$"):
                        self.is_dollar = True
                        word = word[1:]
                    elif word.endswith("$"):
                        self.is_dollar = True
                        word = word[0:-1]
                    elif word.endswith("%"):
                        self.is_percent = True
                        word = word[0:-1]
                    elif word.endswith("m"):
                        self.is_million = True
                    elif word.endswith("bn"):
                        self.is_billion = True
                    if word.startswith("(") and word.endswith(")"):
                        word = word[1:-1]
                    word = word.replace(",", "")
                    if word.isnumeric() or word.replace(".", "", 1).isnumeric():
                        self.is_number = True
                    parts = word.split("-")
                    if (
                        len(parts) == 2
                        and parts[0].isnumeric()
                        and parts[1].isnumeric()
                    ):
                        self.is_number_range = True
                        self.parts = parts
                else:
                    self.is_number = True
        if self.is_number:
            numeric_part = word
            return numeric_part


class Line:
    def __init__(
        self,
        line_str,
        text_list=[],
        style_dict={},
        page_details={},
        noun_chunk_ending_tokens=[],
    ):
        self.text = line_str.strip()
        self.visual_line = VisualLine(text_list, style_dict, page_details)
        self.words = []
        self.is_independent = False
        self.is_header = False
        self.is_header_without_comma = False
        self.noun_chunks = []
        self.quoted_words = quote_pattern.findall(self.text)
        self.noun_chunk_ending_tokens = {x.lower() for x in noun_chunk_ending_tokens}
        self.parse_line()

    def check_header(self):

        # Section X, Article Y, Note 1 etc.
        first_word_header = self.first_word.lower() in ["section", "article", "note"]

        # If there are a certain percentage of title words (first letter capitalize)
        title_ratio = (
            self.title_word_count / self.eff_word_count
            if self.eff_word_count > 0
            else 1.0
        )
        # print(self.title_word_count, self.eff_word_count, title_ratio)

        # Section 1 is a header but Section 1: Hello 3 is not

        has_enough_titles = title_ratio > 0.9 and self.eff_word_count < 10

        has_header_structure = (
            (first_word_header or has_enough_titles) and self.number_count == 1
        ) or self.numbered_line or self.text.isupper()
        # has_header_structure = has_header_structure and self.eff_word_count <

        last_word_number = (
            self.last_word.lower() in units
            or self.last_word_number
            and not has_header_structure
        )
        last_word_date = self.last_word_date and not has_header_structure
        # Find lines ending with sentence delimiter. But exclude text like "L.P."
        ends_with_delim = ends_with_sentence_delimiter_pattern.search(self.text) is not None
        sentence_structure = self.ends_with_period and not (
            has_header_structure and title_ratio > 0.9
        ) and ends_with_delim

        last_letter_is_punctuation = (
            self.last_word[-1] in punctuations and self.last_word[-1] not in ":?.)]%" and
            ends_with_delim
        )

        self.is_header_without_comma = (
                not sentence_structure
                and not self.has_list_char
                and not self.first_char in footnote_types
                and has_enough_titles
                and not last_word_number
                and (
                        self.number_count == 0
                        or (has_header_structure and self.number_count <= 1)
                )
                and not self.has_continuing_chars
                and not last_word_date
                and self.first_word_title
                and not self.last_word_is_stop_word
                and not self.is_zipcode_or_po
                and not last_letter_is_punctuation
                and not "://" in self.text  # url pattern
        )
        self.is_header = self.is_header_without_comma and \
                         ((not self.text.count(',') > 1) if not self.text.lower().startswith('section') else True)

    def check_ends_with_period(self):
        # punct_rule = self.last_char in string.punctuation and self.last_char not in [':', '.']
        last_word_is_title = self.last_word in ["Mr.", "Dr.", "Mrs."]
        self.ends_with_period = self.last_char in ["."] and not last_word_is_title

    def check_table_row(self):
        if not self.is_header:
            value_count = (
                self.number_count
                + self.dollar_count
                + self.pct_count
                + self.text.count(" - ")
            )
            word_symbols = self.word_count - self.dollar_sign_count
            if word_symbols == 0:
                word_symbols = 1
            word_ratio = (
                value_count + self.title_word_count + self.date_entry_count
            ) / word_symbols
            self.is_table_row = (
                (
                    (value_count > 0 or self.date_entry_count > 0)
                    and word_ratio > 0.7
                    and not self.ends_with_period
                    and not self.is_zipcode_or_po
                )
                and not self.last_word_is_stop_word
                or ("...." in self.text)
            )
        else:
            self.is_table_row = False

    def check_list_item(self):
        text = self.text.strip()
        self.has_list_char = text[0] in list_types.keys()
        # if not self.has_list_char and text[0] in ambiguous_list_chars:
        #     self.has_list_char = text[1:].strip()[0].isalpha()
        self.is_list_item = self.has_list_char and self.first_word[-1] not in ":?.)]%$"
        if self.is_list_item:
            self.list_type = list_types[text[0]]

    # matches 1.1 1.2.1 1 etc.
    def check_numbered_line(self, word):
        trunc_word = word
        ends_with_parens = word.endswith(")")
        number_end_char = word.endswith(".") or ends_with_parens
        number_start_char = word.startswith("(")
        if number_start_char and not ends_with_parens:
            return False
        if word[-1] in ["%", "$", ","]:
            return False
        if number_end_char:
            trunc_word = word[:-1]
        if number_start_char:
            trunc_word = trunc_word[1:]
        # To handle scenarios like (ii)(A)
        if ")(" in trunc_word:
            trunc_word = trunc_word.split(")(")[0]

        parts = trunc_word.split(".")
        self.integer_numbered_line = False
        self.roman_numbered_line = False
        self.letter_numbered_line = False
        self.dot_numbered_line = False
        mixed_list_items = False
        max_digits = 2
        max_roman = 6

        for idx, part in enumerate(parts):
            # print(">part: ", part, re.sub(r"[a-zA-Z]+", "", part).isdigit() or idx > 0)
            if len(part) <= max_digits:
                # (1), (2), (3)
                self.integer_numbered_line = part.isdigit() and (
                    len(parts) > 1 or word.endswith(")")
                )
                # 1. 2. 3.
                self.dot_numbered_line = part.isdigit() and (
                    len(parts) > 1 or word.endswith(".")
                )
                # a. b. c. or a) b) c)
                # idx > 0 for patterns like 10.a
                # a1 b1 c1 etc.
                self.letter_numbered_line = (
                    True
                    if single_char_pattern.match(part)
                    and (
                        (number_end_char and len(part) == 1 and len(parts) == 1)
                        or multi_char_pattern.sub("", part).isdigit()
                        or idx > 0
                    )
                    else False
                )
            if len(part) <= max_roman:
                # xi, i, iv
                self.roman_numbered_line = (
                    True if roman_number_pattern.match(part) and idx == 0 else False
                )
            if part.endswith(")") and part[0].isalnum() and "(" in part:
                mixed_list_items = True
            # else:
            #     self.integer_numbered_line = False
            # A-1
            # self.letter_numbered_line = (
            #     True if re.match("[a-zA-Z]+-?[0-9]+$", part) else False
            # )
            self.numbered_line = (
                self.integer_numbered_line
                or self.roman_numbered_line
                or self.letter_numbered_line
                or self.dot_numbered_line
            ) and not mixed_list_items
            if not self.numbered_line:
                break
        if self.numbered_line:
            self.start_number = trunc_word
            self.line_without_number = self.text[len(word) + 1 :]
            self.full_number = self.text[:len(word)]

    # check if line is part of address
    def check_zipcode_or_pobox(self):
        # check if line matches format P.O. box xxxxx
        pobox = (
            self.word_count == 3
            and self.last_word_number
            and self.first_word.lower() in ["po", "p.o", "p.o."]
        )
        # check if line is last part of address, matching format "city, state zipcode"
        zipcode = (
            self.word_count
            < 7  # ensure line is standalone address, not part of larger sentence
            and (
                self.contains_state  # line contains comma followed by state name or abbreviation
                # line ends in zipcode, with format xxxxx or xxxxx-xxxx
                and (
                    (self.last_word_number or self.last_word[-4:].isdigit())
                    and (
                        (len(self.last_word) == 10 and self.last_word[-5] == "-")
                        or len(self.last_word) == 5
                    )
                )
                and not self.ends_with_period
            )
        )
        self.is_zipcode_or_po = pobox or zipcode

    def set_line_type(self):
        line_type = "para"
        if self.is_table_row:
            line_type = "table_row"
        elif self.is_header:
            line_type = "header"
        elif self.is_list_item or self.numbered_line:
            line_type = "list_item"
        else:
            line_type = "para"
        self.line_type = line_type

    def parse_line(self):
        self.words = []
        self.title_word_count = 0
        self.alpha_count = 0
        self.list_type = ""
        self.integer_numbered_line = False
        self.roman_numbered_line = False
        self.dot_numbered_line = False
        self.numbered_line = False
        self.stop_word_count = 0
        self.dollar_count = 0
        self.pct_count = 0
        self.number_count = 0
        self.last_word_number = False
        self.first_word_title = False
        self.letter_numbered_line = False
        self.ends_with_hyphen = False
        self.last_word_date = False
        self.is_reference_author_name = False
        self.date_entry_count = 0
        self.last_word_is_stop_word = False  # self.last_word in self.stopwords
        self.hit_colon = False
        self.is_zipcode_or_po = False
        self.contains_state = False
        self.addresses = []
        # todo - this is a stopgap solution, need to make it more efficient
        tokens = self.text.split()
        self.length = len(self.text)

        self.word_count = len(tokens)
        self.dollar_sign_count = tokens.count("$")
        last_idx = self.word_count - 1
        first_alpha_found = False
        prev_token_comma = False

        self.eff_length = 0
        single_letter_word_count = 0
        noun_chunk_buf = []
        if self.length == 0:
            return
        for idx, token in enumerate(tokens):
            if token in unicode_list_types.keys():
                token = unicode_list_types[token]
            if token.__contains__(":"):
                self.hit_colon = True

            # remove punctuation unless (word) or unless it is the first token or if it has colon
            last_char = token[-1]
            # remove punctuation unless (word) or unless it is the first token
            if (
                (token[-1] in string.punctuation or token[-1] in end_quotations)
                and not (token[0] in string.punctuation or token[0] in start_quotations)
                and (not idx == 0 or token[-1] == ":")
            ):
                token = token[0:-1]

            if len(token) == 0:
                continue
            # if prev token contained comma, check if current token is state name
            if prev_token_comma and (
                token.lower() in states or token.lower() in states_abbreviations
            ):
                self.contains_state = True
                prev_token_comma = False
            if prev_token_comma:
                prev_token_comma = False
            if last_char == ",":
                prev_token_comma = True
            if idx == 0 and not token.lower() == "i" and not token.lower() == "a":
                self.check_numbered_line(token)

            if token.istitle() or token.isupper():  # and not self.hit_colon:
                self.title_word_count = self.title_word_count + 1

            if token.isalpha():
                # if not self.hit_colon:
                self.alpha_count = self.alpha_count + 1
                if not first_alpha_found:
                    first_alpha_found = True
            if idx == 0:
                self.first_word_title = token[0].isupper()

            word = Word(token)
            if word.is_number:
                self.number_count = self.number_count + 1
                if idx == last_idx:
                    self.last_word_number = True
            if word.is_date_entry:
                self.date_entry_count += 1
                if idx == last_idx:
                    self.last_word_date = True
            if word.is_dollar:
                self.dollar_count = self.dollar_count + 1
                if idx == last_idx:
                    self.last_word_number = True
            if word.is_percent:
                self.pct_count = self.pct_count + 1
                if idx == last_idx:
                    self.last_word_number = True
            self.eff_length += word.length

            if word.length == 1:
                single_letter_word_count += 1

            if word.is_stop_word:
                if not self.hit_colon:
                    self.stop_word_count = self.stop_word_count + 1
                if idx == last_idx and len(token) != 1 and not token.isupper():
                    self.last_word_is_stop_word = True
            if word.is_noun or word.text == "&":
                noun = word.text_without_punct
                prev_word = self.words[-1] if len(self.words) > 0 else None
                if prev_word and (prev_word.is_number or prev_word.is_number_range) and not noun_chunk_buf:
                    noun_chunk_buf.append(prev_word.text_without_punct)  # get stuff like 150 Broadway
                if noun.endswith("'s"):
                    noun = noun[0:-2]
                    noun_chunk_buf.append(noun)
                    self.noun_chunks.append(" ".join(noun_chunk_buf))
                    noun_chunk_buf = []
                elif (
                    "".join([x.lower() for x in noun if x not in {".", ","}])
                    in self.noun_chunk_ending_tokens
                ):
                    noun_chunk_buf.append(noun)
                    self.noun_chunks.append(" ".join(noun_chunk_buf))
                    noun_chunk_buf = []
                else:
                    noun_chunk_buf.append(noun)
            elif len(noun_chunk_buf) and word.is_number and word.text[0] not in ["$"]:
                noun_chunk_buf.append(word.text_without_punct)
            elif len(noun_chunk_buf):
                self.noun_chunks.append(" ".join(noun_chunk_buf))
                noun_chunk_buf = []

            self.words.append(word)

        if len(noun_chunk_buf) > 0:
            self.noun_chunks.append(" ".join(noun_chunk_buf))

        self.noun_chunks = sorted(list(set(filter(lambda x: x.lower() not in stop_words, self.noun_chunks))))
        self.first_word = tokens[0]
        self.last_word = tokens[-1]
        self.last_char = self.text[-1]
        self.ends_with_period = self.last_char == "."
        self.ends_with_comma = self.last_char == ","
        self.end_with_period_single_char = len(self.text) > 2 and self.text[-2] == "."

        self.eff_word_count = self.alpha_count - self.stop_word_count
        self.check_ends_with_period()
        self.first_char = self.text[0]
        self.has_continuing_chars = not self.numbered_line and (
            self.first_char.islower() or self.first_char in continuing_chars
        )
        self.last_continuing_char = self.last_char in continuing_chars

        self.check_zipcode_or_pobox()
        self.check_list_item()
        self.check_header()
        self.check_table_row()

        self.separate_line = (
            self.is_header
            or self.is_table_row
            or self.is_list_item
            or self.is_zipcode_or_po
        )

        self.is_list_or_row = self.is_table_row or self.is_list_item

        self.is_header_or_row = (
            self.is_header or self.is_table_row or self.is_zipcode_or_po
        )

        self.ends_with_abbreviation = self.ends_with_period and (
            (self.last_word.find(".") != len(self.last_word) - 1)
            or self.last_word.lower() in abbreviations
            or len(self.last_word) <= 3
        )

        self.incomplete_line = not self.is_header_or_row and (
            not self.ends_with_period
            or self.ends_with_abbreviation
            or self.end_with_period_single_char
        )

        self.continuing_line = self.has_continuing_chars and not self.separate_line

        self.has_spaced_characters = single_letter_word_count / self.word_count > 0.8

        self.set_line_type()

        if self.is_header or self.is_header_without_comma:
            if "," in self.text or self.last_word.isupper() and len(self.last_word) <= 2:
                self.is_reference_author_name = True

        self.last_word_is_co_ordinate_conjunction = self.ends_with_comma or self.last_word in conjunction_list
        # print(self.separate_line)
        # self.continuing_line = not self.separate_line and

    def to_json(self):
        json_lp = dict(self.__dict__)
        del json_lp["visual_line"]
        words = []
        for word in self.words:
            words.append(word.__dict__)
        json_lp["words"] = words
        return json_lp


class VisualLine:
    def __init__(self, text_list=[], style_dict={}, page_stats={}):
        self.text_list = text_list
        self.start_x = None
        self.start_y = None
        self.end_x = None
        self.end_y = None
        self.fs = None
        self.fw = None
        self.start_fs = None
        self.end_fs = None
        self.diff_prev_y = None
        self.diff_next_y = None
        self.is_comparably_sized = False
        self.is_comparably_bolded = False
        self.is_prev_space_smallest = False
        self.is_next_space_smallest = False
        self.wrapped_page = False
        self.text = " ".join(self.text_list)

        if style_dict:
            self.start_x = style_dict["start_x"][0]
            self.start_y = style_dict["start_y"][0]
            self.end_x = style_dict["end_x"][-1]
            self.end_y = style_dict["end_y"][-1]
            self.fs = style_dict["line_fs"][0]
            self.fw = style_dict["line_fw"][0]
            self.diff_prev_y = style_dict["diff_prev_y"][0]
            self.diff_next_y = style_dict["diff_next_y"][0]

            self.font_family = (
                style_dict["font_family"][0] if len(style_dict["font_family"]) else None
            )

            self.font_style = (
                style_dict["font_style"][0] if len(style_dict["font_style"]) else None
            )
            self.min_x = (
                self.start_x
            )  # these variables are adjustable during line joins for line width
            self.max_x = self.end_x
            self.start_x_list = style_dict["start_x"]  # joined ents
            self.end_x_list = style_dict["end_x"]  # joined ents

            self.start_x_list_single_ent = style_dict["start_x_list"][0]
            self.end_x_list_single_ent = style_dict["end_x_list"][0]

            self.mode_fs = mode_of_list(style_dict["line_fs"])
            self.tab_count = 0

            # calculates tabs for when tika misses word split
            if len(self.start_x_list_single_ent) == len(self.end_x_list_single_ent):
                self.start_end_list = list(
                    zip(self.start_x_list_single_ent, self.end_x_list_single_ent),
                )
                for word_x, next_word_x in zip(
                    self.start_end_list[:-1],
                    self.start_end_list[1:],
                ):
                    word_start_x, word_end_x = word_x
                    next_word_start_x, next_word_end_x = next_word_x
                    word_distance = next_word_start_x - word_end_x
                    if word_distance > 20:
                        self.tab_count += 1
            else:
                self.start_end_list = []

            self.tab_count_join = 0  # tab count after join in ptolines

            # calculates tabs for when tika misses word split
            if len(self.start_x_list) == len(self.end_x_list):
                self.start_end_list_join = list(
                    zip(self.start_x_list, self.end_x_list),
                )
                for word_x, next_word_x in zip(
                    self.start_end_list_join[:-1],
                    self.start_end_list_join[1:],
                ):
                    word_start_x, word_end_x = word_x
                    next_word_start_x, next_word_end_x = next_word_x
                    word_distance = next_word_start_x - word_end_x
                    if word_distance > 20:
                        self.tab_count_join += 1
            else:
                self.start_end_list_join = []

            if len(self.text.split()) == 2 and self.tab_count == 1:
                self.text_list = self.text.split()
            # Count tabs in text list, Eventually make it a function of font size

            self.start_fs = round(style_dict["start_fs"][0], 1)
            self.end_fs = round(style_dict["end_fs"][-1], 1)

            self.compute_visual_features(page_stats)

    def compute_visual_features(self, page_stats):
        # compute font size relative to most common font
        font_sizes_mode = page_stats["mode_fs"]
        if self.fs > (4 / 3) * font_sizes_mode:
            self.is_comparably_sized = True
        else:
            self.is_comparably_sized = False

        # compute font weight relative to 600.0 which has generally
        # been observed to correspond to bolding of some sort
        font_weights_mode = page_stats["mode_fw"]
        if font_weights_mode >= 600.0:
            self.is_comparably_bolded = False
        elif self.fw > 600.0:
            self.is_comparably_bolded = True

        # compare line height for similar type (same font) lines
        if page_stats["fs_and_diff_prev_y"].get((self.fs, self.diff_prev_y), 0) > 2:
            for k, v in page_stats["fs_and_diff_prev_y"].items():
                if k == self.fs and 0 <= v < self.diff_prev_y:
                    break
            else:
                self.is_prev_space_smallest = True

        if page_stats["fs_and_diff_next_y"].get((self.fs, self.diff_next_y), 0) > 2:
            for k, v in page_stats["fs_and_diff_next_y"].items():
                if k == self.fs and 0 <= v < self.diff_next_y:
                    break
            else:
                self.is_next_space_smallest = True

    def should_join_table(self, next_line):
        """
        Check if next line should be joined as a tr. This makes no assumption if the current line is a table
        """
        # check list of spaced words
        curr_line_ents = len(self.text_list)
        next_line_ents = len(next_line.text_list)
        ent_match = (
            curr_line_ents == next_line_ents and curr_line_ents >= 2
        )  # tr should have at least two elements

        # compare alignment of elements in both lists
        if ent_match:
            return
        return False

    def should_join_para(self):
        return False

    def should_join_header(self):
        return False

    def __str__(self):
        output_str = f"\ntext_list = {self.text_list},\nstart_x = {self.start_x}, \nstart_y = {self.start_y}\nend_x = {self.end_x},\nend_y = {self.end_y},\nfs = {self.fs},\nfw = {self.fw},\nstart_fs = {self.start_fs},\nend_fs = {self.end_fs},\ndiff_prev_y = {self.diff_prev_y},\ndiff_next_y = {self.diff_next_y},\nis_comparably_sized = {self.is_comparably_sized},\nis_comparably_bolded = {self.is_comparably_bolded},\nis_prev_space_small = {self.is_prev_space_smallest}\nis_next_space_small = {self.is_next_space_smallest},"
        output_str += f"\nfont_style = {self.font_style}"
        return output_str
