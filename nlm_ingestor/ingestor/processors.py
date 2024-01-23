import logging
import re
from collections import Counter
from collections import defaultdict

from . import formatter
from . import line_parser
from . import patterns
from nlm_ingestor.ingestor_utils import spell_utils
from nlm_ingestor.ingestor_utils.utils import sent_tokenize

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

su = spell_utils.SpellUtil()


def stem(line):
    line = line.replace("'s", "")
    line = line.replace("’s", "")
    return line


def check_parentheses(text):
    count = 0
    for i in text:
        if i == "(":
            count += 1
        elif i == ")":
            count -= 1
    return count == 0


def nlm_tokenize(line):
    # print(line)
    tokens = []
    if not line:
        line = ""
    line = line.lower()
    trans_table = line.maketrans("-/", "  ")
    line = line.translate(trans_table)
    line = line.translate(str.maketrans("", "", "�\\(*,.?•\\➢ƒ–\\)'\"—"))
    # line = patterns.num_unit.sub(r"100 \1", line)
    line = patterns.num_unit.sub(r"", line)
    line = stem(line)
    words = line.split()

    for word in words:
        if (
            not word.isdigit()
            and not word.endswith("%")
            and not word.startswith("$")
            and not word.endswith("$")
        ):
            tokens.append(word)
    if len(tokens) == 0:
        tokens.append("unknown")
    return tokens


# make sure that there is at least one word which is greater than two characters
def find_floating_chars(line):
    words = line.split(" ")
    for word in words:
        if len(word) > 2:
            return False
    return True


def is_table_row(line):
    line = line_parser.Line(line)
    return line.is_table_row


def should_skip(line, xml=False):
    return len(line) <= 2 if not xml else len(line) == 0


def clean_lines(lines, xml=False):
    result = []
    running_line = ""
    line_buffer = []
    line_type = "para"
    header_block_idx = -1
    block_idx = 0
    line_set = set()
    for line_str in lines:
        # print(line_str)
        line_str = clean_line(line_str)

        if should_skip(line_str, xml=xml):
            continue
        line_without_numbers = re.sub(r"\d+", "", line_str)
        if line_without_numbers in line_set:
            continue
        else:
            line_set.add(line_without_numbers)

        curr_line = line_parser.Line(line_str)

        # this converst strings like 'e x e c u t i v e summary' to 'executive summary'
        if not xml and curr_line.has_spaced_characters:
            line_str = fix_spaced_characters(line_str)
            curr_line = line_parser.Line(line_str)

        if len(line_buffer) > 0:

            # find out if previous line was a discontinous line
            prev_line = line_buffer[-1]

            logger.debug("========")
            logger.debug(f"{prev_line.incomplete_line} >> {prev_line.text} \n")
            logger.debug(f"{curr_line.continuing_line} >> {curr_line.text} \n")
            # keep connecting lines as long as they seem incomplete
            is_incomplete = prev_line.incomplete_line or (
                len(line_buffer) > 1 and not prev_line.ends_with_period
            )
            logger.debug(
                f"incomplete: {is_incomplete}, is_list_or_row: {curr_line.is_list_or_row}, continuing_line: {curr_line.continuing_line}",
            )
            if (
                is_incomplete
                and not (curr_line.is_list_or_row or curr_line.line_type == "list_item")
            ) or curr_line.continuing_line:
                logger.debug("connecting..")
                running_line = formatter.connect(running_line, curr_line.text)
                line_buffer.append(curr_line)
                # if we are connecting lines, then this has to be a para unless it is a list_item, basically no headers
                if not line_type == "list_item":
                    line_type = "para"
            else:  # commit the line and start a new line
                # remove different types of bulletted list (for better formatting) but do not touch numbered line
                logger.debug("starting new line..")
                # if line_type == "list_item":
                #     running_line = running_line[1:].lstrip()

                if line_type == "header":
                    header_block_idx = block_idx

                block = {
                    "block_idx": block_idx,
                    "block_text": running_line,
                    "block_type": line_type,
                    "text_group_start_idx": -1,
                    "block_list": [],
                    "header_block_idx": header_block_idx,
                    "level": 0,
                }

                result.append(block)

                block_idx = block_idx + 1

                running_line = curr_line.text
                line_buffer = [curr_line]
                line_type = curr_line.line_type
            logger.debug("========")
        else:
            running_line = curr_line.text
            line_type = curr_line.line_type
            line_buffer = [curr_line]

    if line_type == "list_item" and running_line[0] in "�\\*,.?•\\➢ƒ–\\'\"—":
        running_line = running_line[1:].lstrip()

    block = {
        "block_idx": block_idx,
        "block_text": running_line,
        "block_type": line_type,
        "text_group_start_idx": -1,
        "block_list": [],
        "header_block_idx": header_block_idx,
        "level": 0,
    }

    result.append(block)
    return result


def line_list_check(prev_line, curr_line, list_char):
    # if prev_line is list_item and list_char matches curr_line
    if list_char == curr_line.text[0] and list_char not in ["”", "'", '"', "("]:
        return True
    # same char is alpha
    if prev_line.text[0] == curr_line.text[0] and prev_line.text[0].isalpha():
        if len(prev_line.text) >= 2 and prev_line.text[1].isupper():
            # spell check first word
            first_word = prev_line.text.split(" ")[0]
            first_word = first_word.replace("'", "")
            correct_word = su.segment(first_word)
            if first_word[1:] == correct_word:
                return True
    # same char is not alpha but not digit
    if prev_line.text[0] == curr_line.text[0] and not (
        prev_line.text[0].isalpha()
        or prev_line.text[0].isdigit()
        or list_char not in ["”", "'", '"', "("]
    ):
        return True
    return False


def should_join_table(prev_line, curr_line, ents_aligned):
    """
    Check if next line should be joined as a tr. This makes no assumption if the current line is a table
    """
    # print()
    # print("Checking to join tr", prev_line.visual_line.text_list, "\n", curr_line.visual_line.text_list)
    # check list of spaced words
    curr_line_ents = len(prev_line.visual_line.text_list)
    next_line_ents = len(curr_line.visual_line.text_list)
    ent_match = (
        curr_line_ents == next_line_ents and curr_line_ents >= 2
    )  # tr should have at least two elements

    # print("tab check", prev_line.visual_line.tab_count, curr_line.visual_line.tab_count)
    tab_match = (
        prev_line.visual_line.tab_count == curr_line.visual_line.tab_count
        and curr_line.visual_line.tab_count > 0
    )
    # casing should also be the same
    same_case = (
        prev_line.text[0].islower() == curr_line.text[0].islower()
        or prev_line.text[0].isupper() == curr_line.text[0].isupper()
    )
    colon_check = (
        prev_line.hit_colon
        and curr_line.hit_colon
        and prev_line
        and same_case
        and not prev_line.incomplete_line
    )

    # if prev_line.hit_colon and curr_line.hit_colon:
    # print()
    # print("colon check")
    # print(prev_line.visual_line.text_list)
    # print(curr_line.visual_line.text_list)
    # col_check
    # print(tab_match, ent_match, colon_check)
    tab_check = prev_line.visual_line.tab_count or curr_line.visual_line.tab_count
    return (
        (tab_match and ent_match)
        or colon_check
        or (ents_aligned and ent_match and tab_check)
    )


def check_page_spacing(prev_line, curr_line, spacing_dict):
    #     print("^"*50)
    #     print("checking page stats")
    #     print(prev_line.visual_line.start_fs, prev_line.visual_line.end_fs, prev_line.text)
    #     print(curr_line.visual_line.start_fs, curr_line.visual_line.end_fs, curr_line.text)
    #     print()

    diff_top = round(curr_line.visual_line.start_y - prev_line.visual_line.end_y)
    # find best fs reference
    prev_line_fs = {prev_line.visual_line.start_fs, prev_line.visual_line.end_fs}
    curr_line_fs = {curr_line.visual_line.start_fs, curr_line.visual_line.end_fs}

    same_fs = prev_line_fs.intersection(curr_line_fs)
    fs = min(same_fs) if same_fs else curr_line.visual_line.start_fs

    min_check = (
        spacing_dict[(fs, diff_top - 1)] if (fs, diff_top - 1) in spacing_dict else None
    )
    max_check = (
        spacing_dict[(fs, diff_top + 1)] if (fs, diff_top + 1) in spacing_dict else None
    )
    normal_check = (fs, diff_top) in spacing_dict and spacing_dict[(fs, diff_top)] > 3

    if min_check or normal_check or max_check:
        # get all fs in spacing dict
        # see if the diff top is a min
        # print("checking space dict")
        distance_list = []
        for val in spacing_dict:
            if val[0] == fs and val[1] > 0 and spacing_dict[val] > 2:
                distance_list.append((val, val[1]))
        # print(distance_list)
        val = min(distance_list) if len(distance_list) else []
        if len(val):
            join_fs, join_top = val[0]
        if len(val):
            join_fs, join_top = val[0]

            if val[0] == (fs, diff_top):  # or close
                # print("SHOULDJOIN")
                return True
            elif (
                join_fs == fs
                and ((diff_top - 1) == join_top)
                or ((diff_top + 1) == join_top)
            ):
                return True
    return False


def compute_overlap(
    start_x0: float,
    end_x0: float,
    start_x1: float,
    end_x1: float,
    divide_by_min=True,
) -> float:
    """
    Computes the % of intersection (overlap) of two lines w.r.t. the shortest line
    """
    width_x0 = abs(end_x0 - start_x0)
    width_x1 = abs(end_x1 - start_x1)
    if start_x0 <= start_x1 <= end_x0:
        intersect = min(abs(end_x0 - start_x1), width_x1)
    elif start_x0 <= end_x1 <= end_x0:
        intersect = min(abs(end_x1 - start_x0), width_x1)
    elif start_x1 <= start_x0 <= end_x0 <= end_x1:
        intersect = abs(end_x0 - start_x0)
    else:
        intersect = 0.0
    if divide_by_min:
        intersect /= min(width_x0, width_x1) + 1e-5
    else:
        intersect /= max(width_x0, width_x1) + 1e-5
    return intersect


def compute_overlap_top_bottom(
    start_x0: float,
    end_x0: float,
    start_x1: float,
    end_x1: float,
) -> float:
    """
    This is different from the above function.
    Finds percentage overlap of top to bottom.
    Score of 100% is possible doesn't reference the shortest line
    """
    width_x1 = abs(end_x1 - start_x1)
    if width_x1 == 0:
        return 0.0

    if start_x0 <= start_x1:
        # measure from left to right
        if end_x1 <= end_x0:
            # if start and end both less, full in subset
            return 1.0
        return (end_x1 - start_x0) / width_x1
    else:
        # measure from bottom start
        if end_x1 <= start_x0:
            return 0.0
        return (end_x1 - start_x0) / width_x1


def compute_bottom_top_overlap(start_x0, end_x0, start_x1, end_x1):
    """
    This is different from the above function.
    Finds percentage overlap of top to bottom.
    Score of 100% is possible doesn't reference the shortest line
    """
    # print(start_x0, end_x0)
    # print(start_x1, end_x1)

    if start_x0 == start_x1 and end_x0 != start_x0:  # aligned with bottom line
        # print()
        # print("bottom overlap", (end_x1 - start_x1) / (end_x0 - start_x0))
        return (end_x1 - start_x1) / (end_x0 - start_x0)
    # other conditions
    # elif start_x0 < start_x1 and end_x0 > end_x1: # to the left of bottom line
    #    return
    # else: #to the right of bottom line
    return 1.0


# header check for lines with similar font
# header check for lines with similar font
def visual_header_check(prev_line, curr_line, same_font):
    # check top overlap (small) if the font size is bigger
    # print()
    # print("visual_header check:")
    # print("prev", prev_line.text)
    # print("checking", curr_line.text)
    # top also has to be higher
    # print("prev_line.visual_line.start_y, prev_line.visual_line.end_y")
    # print(prev_line.visual_line.start_y, prev_line.visual_line.end_y)
    # print(prev_line.visual_line.start_y, curr_line.visual_line.start_y)
    if prev_line.visual_line.wrapped_page:
        return False

    if prev_line.visual_line.start_y < curr_line.visual_line.start_y:
        prev_line_width = prev_line.visual_line.max_x - prev_line.visual_line.min_x
        curr_line_width = curr_line.visual_line.max_x - curr_line.visual_line.min_x
        # print("prev_line.visual_line.min_x, prev_line.visual_line.max_x, prev_line.visual_line.end_x")
        # print(prev_line.visual_line.min_x, prev_line.visual_line.max_x, prev_line.visual_line.end_x)
        # print("curr_line.visual_line.min_x, curr_line.visual_line.max_x")
        # print(curr_line.visual_line.min_x, curr_line.visual_line.max_x)
        # print("prev_line_width / curr_line_width")
        # print(prev_line_width / curr_line_width)
        # print("prev_line_width, curr_line_width")
        # print(prev_line_width, curr_line_width)
        if curr_line_width == 0:
            return False
        # print(round(prev_line.visual_line.min_x), round(curr_line.visual_line.min_x))
        if round(prev_line.visual_line.min_x) == round(curr_line.visual_line.min_x):
            if round(prev_line_width) == round(curr_line_width):
                # print()
                # print("NOT A HEADER1")
                return False
        offset = 0
        # print(prev_line.visual_line.min_x, curr_line.visual_line.min_x)
        # print(prev_line.visual_line.min_x <= curr_line.visual_line.min_x)
        if prev_line.visual_line.min_x <= curr_line.visual_line.min_x:
            offset = curr_line.visual_line.min_x - prev_line.visual_line.min_x  # offset

        # print("(prev_line_width - offset) / curr_line_width")
        # print((prev_line_width - offset) / curr_line_width)
        overlap_percentage = (prev_line_width - offset) / curr_line_width
        different_font_style = (
            prev_line.visual_line.fw != curr_line.visual_line.fw
            or prev_line.visual_line[1] != curr_line.visual_line[1]
            or prev_line.visual_line.fs > curr_line.visual_line.fs
        )

        if (
            overlap_percentage < 0.3
            or (different_font_style and overlap_percentage < 0.6)
            or (prev_line.line_type == "header" and different_font_style)
            # or (prev_line.is_header and different_font_style)
        ):
            # print("HEADER INDENT", prev_line.is_header)
            # print("overlap rule::", (prev_line_width - offset) / curr_line_width)
            # print(True)
            return True
        # print(False)
    # print()
    # print("NOT A HEADER")
    return False


def visual_header_from_stats(prev_line, curr_line, page_stats):
    prev_fs = prev_line.visual_line.fs
    curr_fs = curr_line.visual_line.fs

    median_val = round(page_stats["median_fs"])
    max_val = round(max(page_stats["fs_list"]))

    max_val_diff = ((max_val - prev_fs) / max_val) < 0.2 if max_val != 0 else True

    prev_fs_diff = round(prev_fs - median_val)
    curr_fs_diff = (
        round(curr_fs - median_val) if round(curr_fs - median_val) else 0.8
    )  # curr_fs is the median
    varied_set = len(set(page_stats["fs_list"])) >= 4
    rounded_fs_count = Counter([round(x, 3) for x in page_stats["fs_list"]])
    unique_text = rounded_fs_count[round(prev_fs, 3)] / len(page_stats["fs_list"])
    prev_curr_ratio_from_median = prev_fs_diff / curr_fs_diff

    #     print("prev_fs, curr_fs", prev_fs, curr_fs)
    #     print("unique text")
    #     print(rounded_fs_count[round(prev_fs, 3)], len(page_stats["fs_list"]) )
    #     print("visual_header check", len(set(page_stats["fs_list"])))
    #     print("varied_set", varied_set, "unique_text", unique_text)
    #     print(rounded_fs_count)
    #     print()

    # close from max or far enough from median
    bigger_text = max_val_diff or (
        prev_curr_ratio_from_median > 2
    )  # TODO text must also be relatively uncommon

    if varied_set and (unique_text <= 0.08):
        if bigger_text and (prev_fs_diff > 1) and (prev_fs_diff - curr_fs_diff) > 0.3:
            # print(max_val_diff)
            # print(prev_fs, prev_line.text)
            # print(curr_fs, curr_line.text)
            # print()
            return True

        # header join
        if bigger_text and curr_fs == prev_fs and (prev_fs_diff > 1):
            # print(max_val_diff)
            # print(prev_fs, prev_line.text)
            # print(curr_fs, curr_line.text)
            # print()
            return True

    return False


# def visual_clean_lines(lines, page_stats={}, page_info_dict={}):
# def visual_clean_lines(lines, page_stats={}, page_info_dict={}):
# def visual_clean_lines(lines, page_stats={}, page_info_dict={}):
def check_tr_alignment(prev_line, curr_line):
    #     print("-=" * 50)
    #     print("check_tr_alignment!")
    #     print(prev_line.text)
    #     print(curr_line.text)
    #     print()
    prev_ents = len(prev_line.visual_line.text_list)
    curr_ents = len(curr_line.visual_line.text_list)
    prev_positions = prev_line.visual_line.start_x_list
    curr_positions = curr_line.visual_line.start_x_list

    prev_line_start_ents = prev_line.visual_line.start_x_list_single_ent
    curr_line_start_ents = curr_line.visual_line.start_x_list_single_ent

    #     print(prev_line_start_ents)
    #     print(curr_line_start_ents)

    same_ents = prev_ents > 1 and abs(prev_ents - curr_ents) <= 1

    if len(prev_line_start_ents) == len(curr_line_start_ents):
        prev_positions = prev_line_start_ents
        curr_positions = curr_line_start_ents

    if len(prev_line_start_ents) == len(curr_positions) and len(
        prev_line_start_ents,
    ) != len(
        prev_positions,
    ):  # joined p_tags
        prev_positions = prev_line_start_ents

    if not same_ents:
        #         print("check_tr_alignment False1")
        #         print(prev_ents, curr_ents)
        return False

    #     print("CHECKING POSITIONS")
    #     print(prev_positions)
    #     print(curr_positions)
    for p_x, c_x in zip(prev_positions, curr_positions):
        p_x = round(p_x)
        c_x = round(c_x)
        if abs(p_x - c_x) > 100:
            #             print("False")
            #             print("check_tr_alignment False3")
            return False
    #     print("check_tr_alignment True")
    return True


def check_layout(prev_line, curr_line, prev_above_curr):
    prev_line_width = range(
        int(prev_line.visual_line.min_x),
        int(prev_line.visual_line.max_x),
    )

    # weird edge case
    if not prev_line_width:
        prev_line_width = range(
            int(prev_line.visual_line.max_x),
            int(prev_line.visual_line.min_x),
        )

    curr_line_width = range(
        int(curr_line.visual_line.min_x),
        int(curr_line.visual_line.max_x),
    )

    prev_line_width = set(prev_line_width)
    prev_curr_overlap = prev_line_width.intersection(curr_line_width)

    if prev_curr_overlap and not prev_above_curr:
        # print(prev_line.text)
        # print(curr_line.text)
        # print("misplaced text group")
        # print()
        return True
    return False


def order_blocks(blocks):
    block_group_dict = defaultdict(list)
    for idx, block in enumerate(blocks):
        # print(idx, "block-group", block["group_id"], block["block_type"], block['block_text'])
        group_id = block["group_id"]
        block_group_dict[group_id].append(block)

    block_group_list = []  # list that holds tuples (group_id, y_pos)
    for block_group_id in block_group_dict:
        block_group_list.append(
            (block_group_id, block_group_dict[block_group_id][0]["y"]),
        )  # append starting y position of group

    block_group_list = sorted(
        block_group_list,
        key=lambda x: x[1],
    )  # sort block groups by y position

    # get list of ordered block group keys
    ordered_blocks = []
    for block_group_id, y in block_group_list:
        ordered_blocks += block_group_dict[block_group_id]

    # for b in original_blocks:
    # re-index blocks and headers based off of new ordering
    header_idx = 0
    for idx, block in enumerate(ordered_blocks):
        block["block_idx"] = idx
        if block["block_type"] == "header":
            header_idx = idx
        ordered_blocks[idx]["header_block_idx"] = header_idx
    return ordered_blocks


def visual_clean_lines(
    lines,
    page_stats={},
    page_info_dict={},
    page_idx=0,
    line_set={},
):
    page_blocks = []
    header_block_idx = -1
    block_idx = 0
    # block_idx = page_idx
    style_dict = {}
    join_font_spacing = False
    prev_line = None
    text_list = []
    prev_ents = 0
    curr_ents = 0
    is_incomplete = False
    colon_rule = False
    text_group_start = True
    text_group_start_idx = 0

    prev_line = None
    next_line = None
    # for idx, line in enumerate(lines[12:14]):
    sentence_visual_end = False
    group_id = 0

    for idx, line in enumerate(lines):
        # print(idx)
        line_str, style_dict, text_list = (
            line["text"],
            line["style"],
            line["text_list"],
        )

        line_str = " ".join(line_str.split())
        if should_skip(line_str):
            continue

        if line_str in line_set:
            continue

        if len(line_str.split()) > 8:
            line_set.add(line_str)

        curr_line = line_parser.Line(
            line_str=line_str,
            style_dict=style_dict,
            text_list=text_list,
            page_details=page_stats,
        )

        if prev_line is None:
            # initialize memory of previous line.
            # this will update with join decisions
            list_char = ""
            if curr_line.line_type == "list_item":
                list_char = curr_line.text[0]
                curr_line.text = curr_line.text[1:].lstrip()

            if curr_line.line_type == "header":
                header_block_idx = block_idx

            block = {
                "block_idx": block_idx,
                "block_text": curr_line.text,
                "block_type": curr_line.line_type,
                "header_block_idx": header_block_idx,
                "block_group": [curr_line.visual_line.text_list],
                "list_char": list_char,
                "fs": curr_line.visual_line.start_fs,
                "text_group_start_idx": text_group_start_idx,
                "block_list": curr_line.visual_line.text_list,
                "line": curr_line,
                "y": curr_line.visual_line.start_y,
                "group_id": group_id,
            }

            prev_line = curr_line
            block_idx += 1
            # if (idx <= 3) or (idx >= len(lines) - 3):
            #     line_without_numbers = re.sub(r"[^a-zA-Z]+", "", line_str).strip()
            #     if line_without_numbers:
            #         # track block_idx for de-duplication
            #         line_set[line_without_numbers].append((page_idx, block_idx))

            page_blocks.append(block)
            continue

        # print("--" * 50)
        # print(prev_line.line_type, "\n", prev_line.text)
        # print(prev_ents)
        #         print(prev_line.visual_line.fw_list)
        # print(prev_line.visual_line.font_family)
        # print(prev_line.visual_line.fs, prev_line.visual_line.fw, "prev_line:", prev_line.line_type, prev_line.text)
        # print(prev_line.visual_line.mode_fs)
        # print(curr_line.line_type, "\n", curr_line.text)
        # print(curr_ents)
        # print()
        # print(curr_line.visual_line.font_family)
        # print(curr_line.visual_line.mode_fs)
        # print(curr_line.visual_line.fs, curr_line.visual_line.fw, "curr_line:", curr_line.line_type, curr_line.text)

        if (
            len(prev_line.text) > 1
            and len(curr_line.text) > 1
            and prev_line.text[:2] == curr_line.text[:2]
            and prev_line.text[1] == " "
            and not (prev_line.text[0].isdigit() or curr_line.text[0].isdigit())
            and not (prev_line.text[0].isalpha() or curr_line.text[0].isalpha())
        ):
            curr_line.line_type = "list_item"
            curr_line.is_list_item = True
            curr_line.is_list_or_row = True

            if page_blocks[-1]["block_type"] != "list_item":
                page_blocks[-1]["block_type"] = "list_item"
                page_blocks[-1]["list_char"] = page_blocks[-1]["block_text"][0]
                page_blocks[-1]["block_text"] = page_blocks[-1]["block_text"][
                    1:
                ].lstrip()

        same_start_fs = (
            abs(prev_line.visual_line.start_fs - curr_line.visual_line.start_fs) < 0.5
        )
        same_end_fs = (
            abs(prev_line.visual_line.end_fs - curr_line.visual_line.end_fs) < 0.5
        )

        same_end_start_fs = (
            abs(prev_line.visual_line.end_fs - curr_line.visual_line.start_fs) < 0.5
        )

        prev_above_curr = (
            True
            if prev_line.visual_line.end_y < curr_line.visual_line.start_y
            else False
        )

        y_diff = curr_line.visual_line.start_y - prev_line.visual_line.start_y

        top_overlap = compute_overlap_top_bottom(
            start_x0=prev_line.visual_line.start_x,
            end_x0=prev_line.visual_line.end_x,
            start_x1=curr_line.visual_line.start_x,
            end_x1=curr_line.visual_line.end_x,
        )

        bottom_overlap = compute_bottom_top_overlap(
            start_x0=prev_line.visual_line.start_x,
            end_x0=prev_line.visual_line.end_x,
            start_x1=curr_line.visual_line.start_x,
            end_x1=curr_line.visual_line.end_x,
        )

        prev_overlap_curr = True if bottom_overlap or top_overlap else False
        use_visual_join = True if prev_above_curr and prev_overlap_curr else False
        if not use_visual_join and prev_line.incomplete_line:
            join_font_spacing = True

        if not (prev_line.is_table_row or curr_line.is_table_row):

            if page_stats["n_lines"] <= 3:
                join_font_spacing = True
            else:
                join_font_spacing = check_page_spacing(
                    prev_line,
                    curr_line,
                    page_stats["fs_and_diff_next_y"],
                )

        # if the font is different and font-family is different
        different_font_family = (
            curr_line.visual_line.font_family != prev_line.visual_line.font_family
        )
        different_common_fs = (
            prev_line.visual_line.mode_fs != curr_line.visual_line.mode_fs
            and prev_line.visual_line.start_fs != curr_line.visual_line.start_fs
        )
        different_font = (
            different_font_family and different_common_fs and not join_font_spacing
        )

        # start and end characters are same font or the mode of fonts of both lines is the same
        same_font = (
            (prev_line.visual_line.fs == curr_line.visual_line.fs)
            or (same_start_fs and same_end_fs)
            or same_end_start_fs
            or prev_line.visual_line.mode_fs == curr_line.visual_line.mode_fs
        ) and not different_font

        prev_ents = (
            len(prev_line.visual_line.text_list)
            if not prev_line.line_type == "list_item"
            else 0
        )
        curr_ents = (
            len(curr_line.visual_line.text_list) if not curr_line.is_list_item else 0
        )

        ents_aligned = check_tr_alignment(prev_line, curr_line)

        is_incomplete_sent = (
            prev_line.incomplete_line
            and not prev_line.ends_with_period
            or prev_line.ends_with_comma
        )

        # logic using line after curr
        if idx + 1 < len(lines):
            # this is inefficent as line_parser is called twice,
            # once for next_line and once for curr_line.
            next_line = lines[idx + 1]
            # print("NEXT LINE\n", next_line['text'])
            next_line_str, next_style_dict, next_text_list = (
                next_line["text"],
                next_line["style"],
                next_line["text_list"],
            )
            next_line = line_parser.Line(
                line_str=next_line_str,
                style_dict=next_style_dict,
                text_list=next_text_list,
                page_details=page_stats,
            )
            # if the last line was not a table, check if the next line is a table to avoid single tr
            if prev_line.line_type != "table_row" and not ents_aligned:
                # check if the next line is a table and matches curr_line
                next_line_tr = next_line.line_type == "table_row" or should_join_table(
                    curr_line,
                    next_line,
                    False,
                )
                if not next_line_tr and curr_line.line_type == "table_row":
                    curr_line.line_type = "para"

        # if the next line is joinable by visual stats but prev and curr are not
        # don't join the line (only true by x-span check and y is below for prev cur)
        # if this is not true ignore the rule
        prev_not_above_next = (
            next_line and prev_line.visual_line.start_y > next_line.visual_line.start_y
        )
        next_line_join = False
        if next_line and check_layout(prev_line, next_line, prev_not_above_next):
            next_line_join = check_page_spacing(
                curr_line,
                next_line,
                page_stats["fs_and_diff_next_y"],
            )

        # if the prev line is not visually joinable and the curr_next is
        # make sure the prev_line doesn't join the curr_line
        curr_next_visual_join = not join_font_spacing and next_line_join

        # print()
        # print("is_incomplete_sent, (join_font_spacing and not sentence_visual_end), curr_line.continuing_line")
        # print(is_incomplete_sent, (join_font_spacing and not sentence_visual_end), curr_line.continuing_line)
        # print("join_font_spacing:,", join_font_spacing)

        is_incomplete = (
            is_incomplete_sent
            or (join_font_spacing and not sentence_visual_end)
            or curr_line.continuing_line
        )
        # print("is_incomplete", is_incomplete)
        has_overlap_with_min = (
            compute_overlap(
                curr_line.visual_line.start_x,
                curr_line.visual_line.end_x,
                prev_line.visual_line.start_x,
                prev_line.visual_line.end_x,
                divide_by_min=True,
            )
            > 0.7
        )

        is_below = curr_line.visual_line.start_y - prev_line.visual_line.start_y > 0
        is_visually_apart = (has_overlap_with_min and not is_below) or (
            not has_overlap_with_min and is_below
        )

        above_bold_below_not = (
            prev_line.visual_line.fw >= 600.0 and curr_line.visual_line.fw <= 400.0
        )
        has_overlap_with_max = (
            compute_overlap(
                curr_line.visual_line.start_x,
                curr_line.visual_line.end_x,
                prev_line.visual_line.start_x,
                prev_line.visual_line.end_x,
                divide_by_min=False,
            )
            > 0.3
        )

        is_not_header_over_para = True
        if (
            above_bold_below_not
            and not has_overlap_with_max
            and prev_line.line_type == "header"
            and not prev_line.incomplete_line
        ):
            is_not_header_over_para = False

        #         print("header over para check")
        #         print("""above_bold_below_not
        #             and not has_overlap_with_max
        #             and prev_line.line_type == "header"
        #         """)
        #         print(above_bold_below_not)
        #         print(has_overlap_with_max, j)
        #         print(prev_line.line_type == "header")
        #         print()
        #         print(is_not_header_over_para)

        ###########
        # List item

        if line_list_check(prev_line, curr_line, page_blocks[-1]["list_char"]):
            prev_line.line_type = "list_item"
            curr_line.line_type = "list_item"
            curr_line.is_list_item = True
            # change prev_line to list item
            if page_blocks[-1]["block_type"] != "list_item":
                page_blocks[-1]["list_char"] = page_blocks[-1]["block_text"][0]
                page_blocks[-1]["block_text"] = page_blocks[-1]["block_text"][
                    1:
                ].lstrip()
            page_blocks[-1]["block_type"] = "list_item"

        close_text_y = (
            curr_line.visual_line.start_y
            - curr_line.visual_line.mode_fs
            - prev_line.visual_line.start_y
            - prev_line.visual_line.mode_fs
        ) <= 0
        aligned_text = curr_line.visual_line.start_x == prev_line.visual_line.start_x

        title_text = False
        if len(lines) < 10:
            title_text = top_overlap == 1.0 and close_text_y and aligned_text

        visual_header = visual_header_check(prev_line, curr_line, same_font)

        list_item_rule = curr_line.has_list_char or (
            curr_line.numbered_line
            and not (
                (prev_line.incomplete_line and curr_line.continuing_line)
                or join_font_spacing
            )
        )
        last_2_block_tr = False
        if len(page_blocks) >= 2:
            last_block_tr = (
                page_blocks[-1]["block_type"] == "table_row"
                and page_blocks[-2]["block_type"] == "table_row"
            )
            if not last_block_tr and curr_line.line_type == "para":
                # check to join
                if prev_line.incomplete_line and curr_line.continuing_line:
                    last_2_block_tr = True

        no_space_join = prev_line.ends_with_period and curr_line.text[0] != " "
        visual_header_by_stats = visual_header_from_stats(
            prev_line,
            curr_line,
            page_stats,
        )
        header_join = False
        common_list = curr_line.has_list_char or prev_line.has_list_char
        if (
            visual_header_by_stats
            and curr_line.incomplete_line
            and same_font
            and not (prev_line.is_table_row or curr_line.is_table_row or common_list)
        ):
            header_join = True

        #         print("LINEJOIN CHECK")
        #         print("positive\n", "*" * 10)
        #         print(f"\nsame_font:{same_font}",
        #               f"\nis_incomplete:{is_incomplete}",
        #               f"\nis_not_header_over_para:{is_not_header_over_para}")
        #         print("join_font_spacing", join_font_spacing)
        #         print("header join", header_join)

        #         print()
        #         print("negative\n", "*" * 10)

        #         print(f"\nis_visually_apart:{is_visually_apart}",
        #               f"\nshould_join_table(prev_line, curr_line): {should_join_table(prev_line, curr_line, ents_aligned)}",
        #               f"\ncurr_line.is_list_or_row:{curr_line.is_list_or_row}",
        #               f"\ncurr_line table {curr_line.line_type == 'table_row'}",
        #               f"\ncurr_line list {curr_line.is_list_item}",
        #               f"\nvisual_header {visual_header}",
        #               f'\nprev_line.line_type == "table_row", {prev_line.line_type == "table_row"}')

        if (
            same_font
            and not should_join_table(prev_line, curr_line, ents_aligned)
            and not (curr_line.line_type == "table_row" or list_item_rule)
            and not (prev_line.line_type == "table_row" and not last_2_block_tr)
            and is_incomplete
            and not curr_next_visual_join  # is_visually_apart
            and not visual_header
            or not check_parentheses(prev_line.text)
            and is_not_header_over_para
            and not no_space_join
            or title_text
            or header_join
        ):

            # print("JOIN")

            if not is_visually_apart and bottom_overlap < 0.5:
                # this would signify end of paragraph
                sentence_visual_end = True
            else:
                sentence_visual_end = False
            if page_stats["n_lines"] <= 3:
                page_blocks[-1]["block_type"] = "header"
            elif (
                not prev_line.line_type == "list_item"
            ):  # and not curr_line.visual_line.is_header:
                page_blocks[-1]["block_type"] = "para"
            new_text = formatter.connect(
                prev_line.text.rstrip(),
                curr_line.text.lstrip(),
            )
            new_text_list = (
                prev_line.visual_line.text_list + curr_line.visual_line.text_list
            )

            # print("Max ex min ex assignment")
            max_x = max(prev_line.visual_line.max_x, prev_line.visual_line.max_x)
            min_x = min(prev_line.visual_line.min_x, curr_line.visual_line.min_x)

            prev_line_type = prev_line.line_type

            page_blocks[-1]["block_text"] = new_text
            prev_start_y = prev_line.visual_line.start_y

            curr_start_y = curr_line.visual_line.start_y
            prev_end_y = prev_line.visual_line.end_y
            wrapped_page = prev_line.visual_line.wrapped_page

            # pass the line parser attributes
            prev_line = curr_line

            # add appended text and text_list, preserve the line type
            prev_line.text = new_text
            prev_line.visual_line.start_y = prev_start_y
            prev_line.visual_line.text_list = new_text_list
            prev_line.line_type = prev_line_type
            prev_line.visual_line.min_x = min_x
            prev_line.visual_line.max_x = max_x
            prev_line.visual_line.wrapped_page = wrapped_page

            if curr_start_y < prev_end_y:
                prev_line.visual_line.wrapped_page = True
        #             print(prev_start_y)
        #             print("Join")
        #             print()
        #             print("-" * 50)
        #            print()
        # new block
        else:
            # print("NEW block")
            # print("*" * 50)

            if not is_visually_apart and bottom_overlap < 0.5:
                # this would signify end of paragraph
                sentence_visual_end = True
            else:
                sentence_visual_end = False

            # print("-"*50)
            colon_rule = (
                prev_line.hit_colon and curr_line.hit_colon and prev_ents == curr_ents
            )
            # normal case
            tab_check_join = {
                prev_line.visual_line.tab_count_join,
                prev_line.visual_line.tab_count,
            } & {curr_line.visual_line.tab_count_join, curr_line.visual_line.tab_count}
            tab_check = sum(tab_check_join) > 0
            # print("-+" * 50)
            # print("TAB POSITIONS")
            # print(prev_line.text)
            # print(prev_line.visual_line.start_x_list)
            # print(prev_line.visual_line.start_x_list_single_ent)
            # print(prev_line.visual_line.tab_count)
            # print(prev_line.visual_line.tab_count_join)
            #
            # print(curr_line.text)
            # print(curr_line.visual_line.start_x_list)
            # print(curr_line.visual_line.start_x_list_single_ent)
            # print(curr_line.visual_line.tab_count)
            # print(curr_line.visual_line.tab_count_join)
            # print("tabcheck", tab_check)
            # print("ents_aligned", ents_aligned)
            # print(prev_ents, curr_ents)
            # print(curr_line.visual_line.text_list)
            # print("-+" * 50)

            if visual_header_by_stats and prev_line.line_type != "table_row":
                page_blocks[-1]["block_type"] = "header"

            elif (
                colon_rule
                and prev_ents == 1
                and prev_line.line_type != "list_item"
                and not (prev_line.incomplete_line and curr_line.continuing_line)
            ):
                # print("Table Conversion")
                # print()
                # print("colon check")
                # print(prev_line.text.split(":"))
                # print(curr_line.text.split(":"))
                # print("TR1")
                new_text_list = prev_line.text.split(":")
                new_text_list = [new_text_list[0] + ":", new_text_list[1:]]
                page_blocks[-1]["block_type"] = "table_row"
                page_blocks[-1]["block_list"]: new_text_list
                if text_group_start:
                    text_group_start = False
                    text_group_start_idx = page_blocks[-1]["block_idx"]
                    page_blocks[-1]["text_group_start_idx"] = text_group_start_idx
                curr_line.line_type = "table_row"
                curr_line.is_list_or_row = True
            #                 print("Table Conversion!")
            #                 print(prev_ents, curr_ents)
            #                 print(page_blocks[-1]["block_text"])
            #                 print("TR3")

            elif (
                tab_check and ents_aligned and prev_line.line_type != "list_item"
            ) or (colon_rule and not prev_line.incomplete_line):
                #                 print("Table Conversion")
                #                 print(prev_ents, curr_ents)
                #                 print(page_blocks[-1]["block_text"])
                #                 print("TR2")
                page_blocks[-1]["block_type"] = "table_row"
                if text_group_start:
                    text_group_start = False
                    text_group_start_idx = page_blocks[-1]["block_idx"]
                    page_blocks[-1]["text_group_start_idx"] = text_group_start_idx
                curr_line.line_type = "table_row"
            else:
                text_group_start = True
                text_group_start_idx = -1

            list_char = ""
            if curr_line.line_type == "list_item":
                list_char = curr_line.text[0]
                curr_line.text = curr_line.text[1:].lstrip()

            if curr_line.line_type == "header":
                header_block_idx = block_idx

            if (visual_header or visual_header_by_stats) and not (
                prev_line.line_type == "list_item"
                or prev_line.line_type == "numbered_list_item"
            ):
                page_blocks[-1]["block_type"] = "header"
            #             print()
            #             print("*" * 40)
            #             print("NEW BLOCK")
            # print()
            # print("*" * 40)
            # print(curr_line.line_type, curr_line.text)
            # group attribute
            if check_layout(prev_line, curr_line, prev_above_curr) or y_diff < 0:
                group_id += 1
            block = {
                "block_idx": block_idx,
                "block_text": curr_line.text,
                "block_type": curr_line.line_type,
                "header_block_idx": header_block_idx,
                "block_group": [curr_line.visual_line.text_list],
                "text_group_start_idx": text_group_start_idx,
                "list_char": list_char,
                "group_id": group_id,
                "fs": curr_line.visual_line.start_fs,
                "x": curr_line.visual_line.start_x,
                "y": curr_line.visual_line.start_y,
                "line": curr_line,
                "block_list": curr_line.visual_line.text_list,
            }
            # This is to account for when the headers get false positive #TODO improve header code
            prev_text = page_blocks[-1]["block_text"]

            if page_blocks[-1]["block_type"] == "header" and (
                len(sent_tokenize(prev_text)) >= 2 or len(prev_text.split()) > 16
            ):
                page_blocks[-1]["block_type"] = "para"

            prev_line = curr_line
            block_idx += 1
            page_blocks.append(block)

    # not too many blocks there may be title text missed
    if len(page_blocks) <= 2:
        for idx, block in enumerate(page_blocks):
            if "." not in block["block_text"] and len(block["block_text"].split()) < 10:
                page_blocks[idx]["block_type"] = "header"

    page_blocks = order_blocks(page_blocks)

    return page_blocks, line_set


def clean_line(line):
    line = line.replace("\n", " ")
    line = line.replace("\t", " ")
    line = line.strip()
    return line


def fix_spaced_characters(line_text):
    line_text = re.sub(r"\s+", "", line_text)
    return su.segment(line_text)


def connect(prev, curr):
    has_space = prev.endswith(" ")
    result = prev + ("" if has_space else " ") + curr
    return result


def get_numbers(line):
    # test = re.compile(r"[0-9]+\.?[0-9]?")
    regex = re.compile(r"\$?(\d*(\d\.?|\.\d{1,2}))$")
    return regex.search(line)


def check_block_join(prev_block, block):
    prev_text = prev_block["block_text"]
    curr_text = block["block_text"]
    blocks_are_paras = (
        prev_block["block_type"] == "para" and block["block_type"] == "para"
    )
    if len(prev_text.strip()) and len(curr_text.strip()) and blocks_are_paras:
        prev_line = line_parser.Line(prev_block["block_text"])
        curr_line = line_parser.Line(block["block_text"])
        if prev_line.incomplete_line or curr_line.continuing_line:
            return True
    return False


def join_blocks(page_blocks, blocks):
    prev_last_block = page_blocks[-1][-1]
    # update page blocks and blocks
    # prev_blocks = page_blocks[-1]
    # last_prev_block = prev_blocks[-1]
    # check to join last_prev_block with first blocks[0]
    # if it's a join, pop the block and join, subtract block indexes
    prev_last_block["block_text"] = (
        prev_last_block["block_text"].rstrip() + " " + blocks[0]["block_text"].lstrip()
    )
    prev_last_block["block_list"].append(blocks[0]["block_list"])
    # print(prev_block)
    page_blocks[-1][-1] = prev_last_block
    for block in blocks[1:]:
        block["block_idx"] -= 1
    return page_blocks, blocks[1:]
