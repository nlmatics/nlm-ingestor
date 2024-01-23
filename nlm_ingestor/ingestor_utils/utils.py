import json
import re

import numpy as np
from nltk import load
from nltk import PunktSentenceTokenizer


nltk_abbs = load("tokenizers/punkt/{}.pickle".format("english"))._params.abbrev_types


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)


nlm_abbs = {
    "u.s",
    "u.s.a",
    "n.w",
    "p.o",
    "po",
    "st",
    "ave",
    "blvd",
    "ctr",
    "cir",
    "ct",
    "dr",
    "mtn",
    "apt",
    "hwy",
    "esq",
    "fig",
    "no",
    "sec",
    "n.a",
    "s.a.b",
    "non-u.s",
    "cap",
    'u.s.c',
    "ste",
}

nlm_special_abbs = {
    "inc",
}

abbs = nltk_abbs | nlm_abbs

nltk_tokenzier = PunktSentenceTokenizer()

rules = []

for abb in abbs:
    # match start of the sentence
    pattern = fr"^{abb}.\s"
    replaced = f"{abb}_ "

    # case insensitive replacement for synonyms
    rule = re.compile(pattern, re.IGNORECASE)
    rules.append((rule, replaced))

    # match token in sentence
    pattern = fr"\s{abb}.\s"
    replaced = f" {abb}_ "

    # case insensitive replacement for synonyms
    rule = re.compile(pattern, re.IGNORECASE)
    rules.append((rule, replaced))

for abb in nlm_special_abbs:
    pattern = fr"{abb}\."
    replaced = f"{abb}_"
    rule = re.compile(pattern, re.IGNORECASE)
    rules.append((rule, replaced))

# match content inside brackets
# (?<=\() ==> starts with "("
# ([^)]+) ==> repeat not ")"
# (?=\))") ==> ends with ")"
bracket_rule = re.compile(r"(?<=\()([^)]+)(?=\))")
space_rule = re.compile(r"\s([.'](?:\s|$|\D))", re.IGNORECASE)  # Remove any space between punctuations (.')
quotation_pattern = re.compile(r'[”“"‘’\']')


def sent_tokenize(org_texts):
    if not org_texts:
        return org_texts

    sents = []

    # in case org_texts has \n, break it into multiple paragraph
    # edge case for html and markdown
    for org_text in org_texts.split("\n"):
        org_text = space_rule.sub(r'\1', org_text)
        modified_text = re.sub(r'^([.,?!]\s+)+', "", org_text)  # To handle bug https://github.com/nltk/nltk/issues/2925
        orig_offset = abs(len(org_text) - len(modified_text))

        # do not break bracket
        for span_group in bracket_rule.finditer(modified_text):
            start_byte, end_byte = span_group.span()
            span = modified_text[start_byte:end_byte]
            # skip this logic when span is too big? disabled for now
            # if len(span.split()) >= 10:
            #     continue
            modified_text = modified_text.replace(
                f"({span})", f"_{span.replace('.','_')}_",
            )

        for rule, replaced in rules:
            modified_text = rule.sub(replaced, modified_text)
        # Normalize all the quotation.
        modified_text = quotation_pattern.sub("\"", modified_text)

        modified_sents = nltk_tokenzier.tokenize(modified_text)

        offset = orig_offset
        sent_idx = 0
        while offset < len(modified_text) and sent_idx < len(modified_sents):
            if modified_text[offset] == " ":
                offset += 1
                continue

            # cut org_text based on lengths of modified_sent
            modified_sent = modified_sents[sent_idx]
            sents.append(org_text[offset: offset + len(modified_sent)])

            offset += len(modified_sent)
            sent_idx += 1
    if len(sents) >= 2 and re.match(r"^.\.$", sents[0]):
        sents[1] = sents[0] + " " + sents[1]
        sents = sents[1:]

    return sents


def divide_list_into_chunks(lst, n):
    # looping till length l
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def normalize(X):
    norms = np.einsum("ij,ij->i", X, X)
    np.sqrt(norms, norms)

    X /= norms[:, np.newaxis]
    return X


def detect_block_center_aligned(block, page_width):
    center_location = block["box_style"][1] + block["box_style"][3] / 2
    center_aligned = abs(center_location - page_width / 2) < page_width * 0.01
    width_check = block["box_style"][3] * 2 < page_width
    return center_aligned and width_check


def detect_block_center_of_page(block, page_height):
    bottom = block["box_style"][0] + block["box_style"][4]
    center_of_page = (page_height / 3) <= bottom <= ((2 * page_height) / 3)
    return center_of_page


def check_char_is_word_boundary(c):
    if c.isalnum():
        return False
    if c in ['-', '_']:
        return False
    return True

def blocks_to_sents(blocks, flatten_merged_table=False, debug=False):
    block_texts = []
    block_info = []
    header_block_idx = -1
    header_match_idx = -1
    header_match_idx_offset = -1
    header_block_text = ""
    is_rendering_table = False
    is_rendering_merged_cells = False
    table_idx = 0
    levels = []
    prev_header = None
    block_idx = 0
    for block_idx, block in enumerate(blocks):
        block_type = block["block_type"]
        if block_type == "header":
            if debug:
                print("---", block["level"], block["block_text"])
            header_block_text = block["block_text"]
            header_block_idx = block["block_idx"]
            header_match_idx = header_match_idx_offset + 1
            if prev_header and block["level"] <= prev_header['level'] and len(levels) > 0:
                while len(levels) > 0 and levels[-1]["level"] >= block["level"]:
                    if debug:
                        print("<<", levels[-1]["level"], levels[-1]["block_text"])
                    levels.pop(-1)
            if debug:
                print(">>", block["block_text"])
            levels.append(block)
            prev_header = block
            if debug:
                print("-", [str(level['level']) + "-" + level['block_text'] for level in levels])
        block["header_text"] = header_block_text
        block["header_block_idx"] = header_block_idx
        block["header_match_idx"] = header_match_idx
        block["block_idx"] = block_idx

        level_chain = []
        for level in levels:
            level_chain.append({"block_idx": level["block_idx"], "block_text": level["block_text"]})
        # remove a level for header
        if block_type == "header":
            level_chain = level_chain[:-1]
        level_chain.reverse()
        block["level_chain"] = level_chain

        # if block_type == "header" or block_type == "table_row":
        if (
                block_type == "header"
                and not is_rendering_table and 'is_table_start' not in block
        ):
            block_texts.append(block["block_text"])
            # append text from next block to header block
            # TODO: something happened here, it messed up the match_text
            # if block_type == "header" and block_idx + 1 < len(blocks):
            #     block[
            #         "block_text"
            #     ] += blocks[block_idx+1]['block_text']

            block_info.append(block)
            header_match_idx_offset += 1
        elif (
                block_type == "list_item" or block_type == "para" or block_type == "numbered_list_item"
        ) and not is_rendering_table:
            block_sents = block["block_sents"]
            header_match_idx_offset += len(block_sents)
            for sent in block_sents:
                block_texts.append(sent)
                block_info.append(block)
        elif 'is_table_start' in block:
            is_rendering_table = True
            if 'has_merged_cells' in block:
                is_rendering_merged_cells = True
        elif 'is_table_start' not in block and not is_rendering_table and block_type == "table_row":
            block_info.append(block)
            block_texts.append(block["block_text"])
            header_match_idx_offset += 1

        if is_rendering_table:
            if is_rendering_merged_cells and "effective_para" in block and flatten_merged_table:
                eff_header_block = block["effective_header"]
                eff_para_block = block["effective_para"]

                eff_header_block["header_text"] = block["header_text"]
                eff_header_block["header_block_idx"] = block["block_idx"]
                eff_header_block["header_match_idx"] = header_match_idx_offset + 1
                eff_header_block["level"] = block["level"] + 1
                eff_header_block["level_chain"] = block["level_chain"]

                eff_para_block["header_block_idx"] = block["block_idx"]
                eff_para_block["header_match_idx"] = header_match_idx_offset + 1
                eff_para_block["level"] = block["level"] + 2
                eff_para_block["level_chain"] = [
                                {
                                    "block_idx": eff_header_block["block_idx"],
                                    "block_text": eff_header_block["block_text"],
                                },
                ] + eff_header_block["level_chain"]
                header_match_idx_offset += 1
                block_info.append(block["effective_header"])
                block_texts.append(block["effective_header"]["block_text"])
                for sent in block["effective_para"]["block_sents"]:
                    block_texts.append(sent)
                    block_info.append(block["effective_para"])
                header_match_idx_offset += len(block["effective_para"]["block_sents"])
            else:
                block["table_idx"] = table_idx
                block_info.append(block)
                block_texts.append(block["block_text"])
                header_match_idx_offset += 1

        if 'is_table_end' in block:
            is_rendering_table = False
            table_idx += 1

    return block_texts, block_info


def get_block_texts(blocks):
    block_texts = []
    block_info = []
    for block in blocks:
        block_type = block["block_type"]
        if (
            block_type == "list_item"
            or block_type == "para"
            or block_type == "numbered_list_item"
            or block_type == "header"
        ):
            block_texts.append(block["block_text"])
            block_info.append(block)
    return block_texts, block_info