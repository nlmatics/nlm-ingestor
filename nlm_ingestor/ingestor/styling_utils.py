import re
import unicodedata
from collections import Counter
from collections import defaultdict
from statistics import median

from nlm_ingestor.ingestor import formatter
from nlm_ingestor.ingestor import line_parser
from nlm_ingestor.ingestor_utils.word_splitter import WordSplitter

ws = WordSplitter()

WORDS = set(ws._word2cost.keys())

SPACES = [
    "\t",
    "\n",
    " ",
    "\u000a",
    "\u000b",
    "\u000c",
    "\u000d",
    "\x85",
    "\xa0",
    "\u180e",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200a",
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2028",
    "\u2029",
    "\u202f",
    "\u205f",
    "\u2060",
    "\u3000",
    "\ufeff",
]

"""
HELPER FUNCTIONS
"""


def font_weight_is_float(s):
    return s.split(".")[0].isnumeric()


def get_p_styling_dict(style_str: str) -> dict:
    """
    Outputs a dictionary of {style:val} given a string representation of the bs4 tag
    """
    style_dict = {}
    start_fs_list = []
    start_x_list = []
    end_x_list = []
    for styling in style_str.split(";"):
        style_and_val = styling.split(":")
        if len(style_and_val) == 2:
            style, val = style_and_val
            if style == "word-start-positions":
                list_of_tuples = re.findall(r"\((.*?,.*?,.*?,.*?)\)", val)
                for word_tuple in list_of_tuples:
                    # (x, y, fs, fw)
                    val = word_tuple.split(",")
                    start_fs_list.append(float(val[2]))
                    start_x_list.append(float(val[0]))
                val = list_of_tuples[0].split(",")
                style_dict["start_x"] = float(val[0])
                style_dict["start_y"] = float(val[1])
                style_dict["start_fs"] = float(val[2])
                if font_weight_is_float(val[3]):
                    style_dict["start_fw"] = float(val[3])
                elif val[3] == "bold":
                    style_dict["start_fw"] = 600.0
                else:
                    style_dict["start_fw"] = 0.0
            elif style == "word-end-positions":
                list_of_tuples = re.findall(r"\((.*?,.*?,.*?,.*?)\)", val)
                for word_tuple in list_of_tuples:
                    # (x, y, fs, fw)
                    val = word_tuple.split(",")
                    end_x_list.append(float(val[0]))
                val = list_of_tuples[-1].split(",")
                style_dict["end_x"] = float(val[0])
                style_dict["end_y"] = float(val[1])
                style_dict["end_fs"] = float(val[2])
                if font_weight_is_float(val[3]):
                    style_dict["end_fw"] = float(val[3])
                elif val[3] == "bold":
                    style_dict["end_fw"] = 600.0
                else:
                    style_dict["end_fw"] = 0.0
            elif style in ["font-style", "font-family"]:
                style = style.replace("-", "_")
                style_dict[style] = val

            if "end_x" in style_dict and "start_x" in style_dict:
                style_dict["x_range"] = style_dict["end_x"] - style_dict["start_x"]
            else:
                style_dict["x_range"] = -1

        style_dict["start_x_list"] = start_x_list
        style_dict["start_fs_list"] = start_fs_list
        style_dict["end_x_list"] = end_x_list
    return style_dict


def join_single_letters(prev_text_list: list) -> bool:
    word_lengths = [len(re.sub(r"\s+", "", word)) for word in prev_text_list]
    if word_lengths and (int(sum(word_lengths) / len(word_lengths)) <= 2):
        return True
    else:
        return False


def join_sub_words(line_info):
    end_x_list = sum(line_info["style"]["end_x_list"], [])
    start_x_list = sum(line_info["style"]["start_x_list"], [])
    min_fs = min(sum(line_info["style"]["start_fs_list"], []))
    overlap_count = 0
    for start_x in start_x_list:
        for end_x in end_x_list:
            diff_x = abs(start_x + min_fs - end_x)
            if diff_x < 1.5:
                overlap_count += 1
    n_segments = len(line_info["text_list"])
    space_count = 0
    for word in line_info["text_list"]:
        if word.startswith(" "):
            space_count += 1
        if word.endswith(" "):
            space_count += 1
    overlap_count += space_count
    if n_segments >= 4 and overlap_count >= 2 and n_segments // overlap_count <= 2:
        return True
    else:
        return False


def join_words(prev_text_list: list) -> bool:
    if len(prev_text_list) == 1:
        return False
    else:
        joined_text = " ".join(prev_text_list)
        line_type = line_parser.Line(joined_text).line_type
        if line_type == "para" or line_type == "list_item":
            return True
        else:
            return False


def mode_of_list(fonts: list):
    cnts = Counter()
    cnts.update(fonts)
    item_and_count = cnts.most_common(1)[0]
    return item_and_count[0]


def no_style_p_to_lines(p_item):
    lines = []
    p_text = unicodedata.normalize("NFKD", p_item.text)
    if len(p_text) > 0 and not p_text.strip().isnumeric():
        text_lines = p_text.split("\n")
        for text in text_lines:
            line = ""
            for word in text.split():
                line += formatter.fix_mixedcase_words(word) + " "
            text = line.strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                line_info = {
                    "text": text,
                    "text_list": [],
                    "style": {},
                }
                lines.append(line_info)
    return lines


def compute_overlap(
    start_x0: float, end_x0: float, start_x1: float, end_x1: float, divide_by_min=True,
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


def tops_2_dict(p_items):
    tops_2_info = defaultdict(list)
    idx_2_top = {}
    for p_idx, p_item in enumerate(p_items):
        if not p_item.text.strip():
            continue
        style_str = p_item.attrs.get("style", "")
        if not style_str:
            continue
        # do not strip text as trailing white-space is used as a features
        text = unicodedata.normalize("NFKD", p_item.text)

        style = get_p_styling_dict(style_str)
        start_y = style["start_y"]
        tops_2_info[round(start_y, 0)].append((p_idx, text, style))
        idx_2_top[p_idx] = round(start_y, 0)
    # print(tops_2_info)
    return tops_2_info, idx_2_top


def sort_p_tags(p_items):
    tops_2_info, idx_2_top = tops_2_dict(p_items)
    sorted_p_idx = []
    for p_idx, p_item in enumerate(p_items):
        if not p_item.text.strip():
            continue
        if p_idx not in sorted_p_idx:
            sorted_p_idx.append(p_idx)
        last_added_idx = sorted_p_idx[-1]
        last_added_top = idx_2_top[last_added_idx]
        list_of_tops = [
            info for info in tops_2_info[last_added_top] if info[0] >= last_added_idx
        ]
        curr_idx, curr_text, curr_style = list_of_tops[0]
        end_x = curr_style["end_x"]
        end_fs = curr_style["end_fs"]
        end_fw = curr_style["end_fw"]
        for info in list_of_tops[1:]:
            next_idx, next_text, next_style = info
            start_x = next_style["start_x"]
            start_fs = next_style["start_fs"]
            start_fw = next_style["start_fw"]
            max_font_size = max(start_fs, end_fs)
            if (start_x - end_x < 0) or (
                start_x - end_x < max_font_size
                and (end_fs == start_fs or end_fw == start_fw)
            ):
                sorted_p_idx.append(next_idx)
            else:
                break
            end_x = next_style["end_x"]
            end_fs = next_style["end_fs"]
            end_fw = next_style["end_fw"]
    sorted_p_items = []
    for idx in sorted_p_idx:
        # text = unicodedata.normalize("NFKD", p_items[idx].text)
        sorted_p_items.append(p_items[idx])
    return sorted_p_items


def calc_page_info_and_line_stats(lines):
    page_stats = {}
    page_info_dict = defaultdict(list)
    for prev_line, curr_line, next_line in zip(
        [None] + lines[:-1], lines, lines[1:] + [None],
    ):
        # calculate statistics within a line
        font_sizes = []
        font_weights = []
        word_spaces = []
        for i in range(len(curr_line["style"]["start_fs"])):
            fs = max(curr_line["style"]["start_fs"][i], curr_line["style"]["end_fs"][i])
            fw = max(curr_line["style"]["start_fw"][i], curr_line["style"]["end_fw"][i])
            word_space = round(
                curr_line["style"]["end_x"][i] - curr_line["style"]["start_x"][i], 1,
            )

            font_sizes.append(fs)
            font_weights.append(fw)
            word_spaces.append(int(10 * int(word_space / 10)))
        # calculate statistic of entire line
        line_length = curr_line["style"]["end_x"][-1] - curr_line["style"]["start_x"][0]
        # calculate statistics between lines
        diff_next_y = -1.0
        if next_line is not None:
            diff_next_y = round(
                next_line["style"]["start_y"][0] - curr_line["style"]["start_y"][0], 0,
            )

        diff_prev_y = -1.0
        if prev_line is not None:
            diff_prev_y = round(
                curr_line["style"]["start_y"][0] - prev_line["style"]["start_y"][0], 0,
            )

        # add diff_y properties to current line
        curr_line["style"]["diff_prev_y"] += [diff_prev_y]
        curr_line["style"]["diff_next_y"] += [diff_next_y]
        curr_line["style"]["line_fs"] += [mode_of_list(font_sizes)]
        curr_line["style"]["line_fw"] += [mode_of_list(font_weights)]

        page_info_dict["font_sizes"] += font_sizes
        page_info_dict["font_weights"] += font_weights
        page_info_dict["word_spaces"] += word_spaces

        # round line_length to a strictly smaller nearest multiple of 10
        page_info_dict["line_length"].append(int(10 * int(line_length / 10)))
        page_info_dict["diff_next_y"].append(diff_next_y)
        page_info_dict["diff_prev_y"].append(diff_prev_y)
        page_info_dict["fs_and_diff_next_y"].append(
            (round(min(font_sizes), 1), round(diff_next_y)),
        )
        page_info_dict["fs_and_diff_prev_y"].append(
            (round(min(font_sizes), 1), round(diff_prev_y)),
        )
    if page_info_dict:
        page_stats["mode_fs"] = mode_of_list(page_info_dict["font_sizes"])
        page_stats["mode_fw"] = mode_of_list(page_info_dict["font_weights"])
        page_stats["mode_length"] = mode_of_list(page_info_dict["line_length"])
        page_stats["fs_and_diff_prev_y"] = Counter(page_info_dict["fs_and_diff_prev_y"])
        page_stats["fs_and_diff_next_y"] = Counter(page_info_dict["fs_and_diff_next_y"])
        page_stats["n_lines"] = len(page_info_dict["fs_and_diff_next_y"])
        page_stats["fs_list"] = page_info_dict["font_sizes"]
        page_stats["median_fs"] = median(page_stats["fs_list"])
    return lines, page_stats, page_info_dict


def check_key_value(prev_line, curr_line):
    # for key value the current line can't be below the previous line
    # check for edge cases
    prev_text, prev_start_x, prev_start_y, prev_fs = prev_line
    curr_text, curr_start_x, curr_start_y, curr_fs = curr_line
    if prev_start_y < curr_start_y:
        return False
    if prev_start_x > curr_start_x:
        return False
    prev_y_range = prev_start_y - prev_fs  # fuzzy check for prev y proximity
    curr_y_range = curr_start_y + curr_fs  # fuzzy check for curr y proximity
    # print(prev_y_range, "prev_line", prev_start_x, prev_start_y, prev_text)
    # print(curr_y_range, "curr_line", curr_start_x, curr_start_y, curr_text)
    if prev_y_range < curr_y_range:
        # print()
        # print("CHECK KEY VALUE")
        # print("prev", prev_text, prev_start_x, prev_start_y)
        # print("curr", curr_text, curr_start_x, curr_start_y)
        return True
    return False


def has_same_words(words0, words1):
    words0 = [re.sub("[^a-zA-Z0-9]", "", word) for word in words0]
    words0 = [word for word in words0 if word]

    words1 = [re.sub("[^a-zA-Z0-9]", "", word) for word in words1]
    words1 = [word for word in words1 if word]

    c_words0 = Counter(words0)
    n_words0 = sum(c_words0.values())

    c_words1 = Counter(words1)
    n_words1 = sum(c_words1.values())

    common = c_words0 & c_words1

    num_same = sum(common.values())
    if len(words0) == 0 or len(words1) == 0:
        return words0 == words1
    if num_same == 0:
        return False
    if 1.0 * num_same / max(n_words0, n_words1) >= 0.8:
        return True
    else:
        return False


def p_to_lines(p_items: list) -> list:
    """
    INPUT:
    p_items: List[<bs4 p_tags>]

    OUTPUT:
    lines: Dict("text": str, "text_list": List[str], "style": Dict[str, Any])
    has_style_dict: Bool

    Given a BeautifulSoup p_item it will determine the relationship between this p_item and the previous p_item.
    If two consecutive p_items are part of the same line, they will be part of the same text_list
    If two consecutive p_items are part of the same textual string i.e. split headers, they will be part of the same text
    """
    has_style_dict = True
    # vertical_stack_count keeps track of how many split lines are merged together
    vertical_stack_count = 1
    # p_items = sort_p_tags(p_items)
    line_info = {
        "text": "",
        "text_list": [],
        "style": defaultdict(list),
    }
    lines = []
    for p_item in p_items:
        # this is necessary to avoid bugs replated to special space characters
        if not p_item.text.translate(str.maketrans({k: "" for k in SPACES})):
            continue

        style_str = p_item.attrs.get("style", "")
        if not style_str:
            has_style_dict = False
            lines += no_style_p_to_lines(p_item)
            continue
        # do not strip text as trailing white-space is used as a features
        text = unicodedata.normalize("NFKD", p_item.text)

        # print(f"\nCONSIDERING TEXT: '{text}'\n", "=" * 50)

        # extract visual features of current p-tag
        style = get_p_styling_dict(style_str)
        start_x = style["start_x"]
        start_y = style["start_y"]
        end_x = style["end_x"]
        start_fw = style["start_fw"]
        end_fw = style["end_fw"]
        start_fs = style["start_fs"]
        end_fs = style["end_fs"]

        single_item = len(p_items) == 1

        if line_info["text_list"] == []:
            line_info["text_list"].append(text)
            # update style_dict with new information
            for key, value in style.items():
                line_info["style"][key].append(value)
            if single_item:
                line_info["text"] = " ".join(line_info["text_list"])
                lines.append(line_info)
            continue

        # print("-" * 50)
        # print()
        # print(f"Text list at start: {line_info['text_list']}")

        # extract visual features from the entire line seen thus far
        prev_style = line_info["style"]
        prev_text = line_info["text_list"][-1]
        # print(line_info)

        # start params are used from the beginning of the prev line
        prev_start_x = prev_style["start_x"][0]
        prev_start_y = prev_style["start_y"][0]
        prev_start_fw = prev_style["start_fw"][0]
        prev_start_fs = prev_style["start_fs"][0]

        # end params are used from the end of the prev line
        prev_end_x = prev_style["end_x"][-1]
        prev_end_fw = prev_style["end_fw"][-1]

        # these are introduced for robustness against subscripts and superscripts
        # and to smooth variations in noisy tika output
        min_font_size = min(start_fs, end_fs)

        # if the line has headers which have been stacked, then we expand the region in which
        # we consider two lines to be in the same y-coordinate range

        diff_prev_y = min(
            abs(start_y - y) for y in prev_style["end_y"][-vertical_stack_count:]
        )
        diff_prev_y = min(diff_prev_y, abs(start_y - prev_style["end_y"][0]))
        # print(
        #    f"Y_DIFF_FROM_BEGINNING: {abs(start_y - prev_start_y)}, Y_DIFF_REL_TO_STACK: {diff_prev_y}, FONT SIZE: {max_font_size}"
        # )
        # print("JOIN CHECK")
        # print("diff_prev_y < (4 / 3) * min_font_size")
        # print(diff_prev_y, (4 / 3) * min_font_size, diff_prev_y < (4 / 3) * min_font_size)
        key_value_check = check_key_value(
            (prev_text, prev_start_x, prev_start_y, prev_start_fs),
            (text, start_x, start_y, start_fs),
        )
        if diff_prev_y < (8 / 5) * min_font_size or key_value_check:
            # print("appending textlist")
            # previous p_tag and current p_tag are on the same line with small error window
            # print(
            #    f"This text is part of the previous line, {diff_x} units apart on x-axis!\nText: {text},\nHistory: {line_info['text_list']}"
            # )
            # if diff_x < min(max_font_size, prev_max_font_size):
            #     # if the space between tags is smaller than font-size, it is likely a subword split
            #     line_info["text_list"][-1] += text
            #     for k, v in style.items():
            #         line_info["style"][k].append(v)
            line_info["text_list"].append(text)
            for k, v in style.items():
                line_info["style"][k].append(v)
            vertical_stack_count = 1
        else:
            # print("Line analysis")
            line_type = line_parser.Line(text).line_type
            if join_single_letters(line_info["text_list"]):
                # if spaced characters, join to more accurately asses line type
                prev_line_type = line_parser.Line(
                    "".join(line_info["text_list"]),
                ).line_type
            else:
                prev_line_type = line_parser.Line(prev_text).line_type

            # print(
            #    f"This text might be part of a different line...\nType of current line '{text}': {line_type},\nType of previous line {prev_text}: {prev_line_type}"
            # )
            # print(f"The overlap between the two texts is: {compute_overlap(prev_start_x, prev_end_x, start_x, end_x)}")
            # overlap_divided_by_min = intersection(line_1, line_2)/min(line_1, line_2)

            overlap_divided_by_min = compute_overlap(
                prev_start_x, prev_end_x, start_x, end_x,
            )
            overlap_divided_by_max = compute_overlap(
                prev_start_x, prev_end_x, start_x, end_x, divide_by_min=False,
            )

            # overlap check
            if overlap_divided_by_min > 0.75 and overlap_divided_by_max > 0.5:
                # print(f"Joined single letters: {line_info['text_list']}")
                line_info["text"] = "".join(line_info["text_list"])
                # p_tags occupy roughly the same reigon on the x-axis
                is_both_header = line_type == "header" and prev_line_type == "header"
                is_neither_table_row = (
                    line_type != "table_row" and prev_line_type != "table_row"
                )
                is_both_bold = (
                    max(start_fw, end_fw) >= 600.0
                    and max(prev_start_fw, prev_end_fw) >= 600.0
                )

                is_close_y = diff_prev_y < 2.5 * min_font_size
                is_semi_close_y = diff_prev_y < 4 * min_font_size
                is_prev_ends_with_space = prev_text.endswith(" ")

                is_one_bold_other_not = (
                    min(prev_start_fw, prev_end_fw) >= 600.0
                    and max(start_fw, end_fw) <= 400.0
                ) or (
                    min(start_fw, end_fw) >= 600.0
                    and max(prev_start_fw, prev_end_fw) <= 400.0
                )

                # print(f"is_same_font: {is_same_font}")
                # print(f"is_both_header: {is_both_header}")
                # print(f"is_both_bold: {is_both_bold}")
                # print(f"is_one_bold_other_not: {is_one_bold_other_not}")
                # print(f"is_neither_table_row: {is_neither_table_row}")
                # print(f"is_close_y: {is_close_y}")
                # print(f"is_semi_close_y: {is_semi_close_y}")
                # print(f"is_prev_ends_with_space: {is_prev_ends_with_space}")
                is_not_list_char = not (
                    line_type == "list_item" or prev_line_type == "list_item"
                )
                if (
                    is_not_list_char
                    and (
                        (is_both_header and not is_one_bold_other_not)
                        or (is_both_bold and is_neither_table_row)
                    )
                    and (is_close_y or (is_prev_ends_with_space and is_semi_close_y))
                ):
                    # this mergs split headers
                    # i.e. executive
                    #      summary
                    # into executive summary and stores the original visual params.
                    vertical_stack_count += 1
                    line_info["text_list"][-1] = (
                        line_info["text_list"][-1].rstrip() + " " + text.lstrip()
                    )
                    # print(prev_text, prev_end_fw, prev_end_fs)
                    # print(text, start_fw, max_font_size)
                    # print(line_info["text_list"][-1])
                    for k, v in style.items():
                        line_info["style"][k].append(v)
                    continue
            vertical_stack_count = 1
            # previous p_tag and current p_tag are likely on different lines
            has_many_numbers = (
                sum(
                    [
                        1 if re.sub(r"[\$\%\,\.\-\']", "", word).isdigit() else 0
                        for word in line_info["text_list"]
                    ],
                )
                / len(line_info["text_list"])
            ) > 0.4
            if join_single_letters(line_info["text_list"]) or (
                join_sub_words(line_info) and not has_many_numbers
            ):
                # print(f"Joined single letters: {line_info['text_list']}")

                new_text_list = []
                word_list = []
                text_list_text = " ".join(line_info["text_list"])
                for text_list_str in text_list_text.split(". "):
                    # remove all spaces
                    text_list_str = re.sub(r"[\s+]", "", text_list_str).translate(
                        str.maketrans({k: "" for k in SPACES}),
                    )
                    if text_list_str:
                        text_list = ws.split(text_list_str)
                        word_list += text_list
                        new_text_list.append(" ".join(text_list))
                # if line ends in space, add it back
                if (
                    line_info["text_list"]
                    and line_info["text_list"][-1]
                    and line_info["text_list"][-1][-1] == " "
                ):
                    new_text_list.append(" ")
                # if line is correctly identified as having split word problem
                # easy join is the correct solution
                easy_join_words = (
                    "".join(line_info["text_list"]).replace(". ", " ").split()
                )
                if (
                    has_same_words(easy_join_words, word_list)
                    or new_text_list == [""]
                    or new_text_list == []
                ):
                    line_info["text"] = "".join(line_info["text_list"])
                else:
                    line_info["text"] = ". ".join(new_text_list)

            elif join_words(line_info["text_list"]):
                # print(f"Joined words: {line_info['text_list']}")
                line_info["text"] = " ".join(line_info["text_list"])
            else:
                # this case usually occurs for table rows
                line_info["text"] = "  ".join(line_info["text_list"])
                # print(line_info["text"])
            # print(f"Line text added: {line_info['text']}")
            # print(f"Line text list added: {line_info['text_list']}")
            # print("\n", line_info["style"], "\n")
            # print("NEWLINE")
            # print(line_info["text"])
            # print()
            lines.append(line_info.copy())

            line_info["text"] = text
            line_info["text_list"] = [text]
            line_info["style"] = defaultdict(list)
            for k, v in style.items():
                line_info["style"][k].append(v)

    # line append
    if lines and line_info["text"] != lines[-1]["text"]:

        if line_info["text_list"] and join_single_letters(line_info["text_list"]):
            # print("")
            # line_history["text_list"] = line_history["text"].copy()
            line_info["text"] = "".join(line_info["text_list"])
        elif line_info["text_list"] and join_words(line_info["text_list"]):
            # line_history["text_list"] = line_history["text"].copy()
            line_info["text"] = " ".join(line_info["text_list"])
        else:
            line_info["text"] = " ".join(line_info["text_list"])
        # print(f"Line added: {line_info['text']}\n")
        if len(line_info["text"].strip()):
            # print(line_info["text"])
            # print()
            lines.append(line_info)

    return lines, has_style_dict
