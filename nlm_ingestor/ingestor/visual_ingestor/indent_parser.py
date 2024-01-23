from nlm_ingestor.ingestor.visual_ingestor import table_parser
from nlm_ingestor.ingestor_utils.utils import detect_block_center_aligned
from nlm_ingestor.ingestor import line_parser
import copy
import operator

LEVEL_DEBUG = False
NO_INDENT = False

roman_tallies = {
    'I': 1,
    'V': 5,
    'X': 10,
    'L': 50,
    'C': 100,
    'D': 500,
    'M': 1000,
}


def roman_numeral_to_decimal(roman_str):
    roman_str = roman_str.split(".")[0]
    roman_sum = 0
    for i in range(len(roman_str) - 1):
        left = roman_str[i]
        right = roman_str[i + 1]
        if not (roman_tallies.get(left, 0) or roman_tallies.get(left, 0)):
            return 0
        if roman_tallies[left] < roman_tallies[right]:
            roman_sum -= roman_tallies[left]
        else:
            roman_sum += roman_tallies[left]
    roman_sum += roman_tallies[roman_str[-1]]
    return roman_sum


def get_list_item_sum(number, list_type):
    if list_type == "roman":
        return roman_numeral_to_decimal(number.upper())
    elif list_type == "integer" or list_type == "integer-dot":
        new_number = ""
        for c in number.split("."):
            if len(c) == 1:
                new_number += "0"
            if c.isdigit():
                new_number += c
        return int(new_number)
    elif list_type == "letter":
        return sum(ord(c) for c in number)
    else:
        return sum(ord(c) for c in number)


class IndentParser:
    def __init__(self, doc):
        self.doc = doc
        self.blocks = doc.blocks

    def indent_blocks(self):
        # {"class": cls1, "upper": True, "list_type": "number"}
        level_stack = []
        is_table = False
        prev_block = None
        prev_line_style = None
        prev_class_name = None
        indent = 0
        header_block_idx = -1
        header_block_text = ""
        table_header_text = ""
        table_header_idx = 0
        level_freq = {}
        list_indents = {}
        list_indents_stack = {}
        # page_width = self.doc.page_width

        for block_idx, block in enumerate(self.blocks):
            # if prev_block:
            #     print(f"block text: {block['block_text']}")
            #     print(f"block box: {block['box_style']}")
            #     print(f"block type: {block['block_type']}")
            #     print(f"block type: {block['list_type']}") if block['block_type'] == "list_item" else None
            #     print(f"prec text: {prev_block['block_text']}")
            def get_level(new_class_name):
                new_class = {
                    "name": new_class_name, 
                    "upper": False, 
                    "header": False,
                    "special_header": "",
                    "list_type": "", 
                    "center_italic": False,
                    "block_type": block["block_type"],
                    "left": block["visual_lines"][0]["box_style"][1],
                    "top": block["visual_lines"][0]["box_style"][0],
                }
                header_numbers_limit = sum(c.isdigit() for c in block['block_text']) < 10
                not_symbol_start = block["block_text"][0].isalnum()

                line = line_parser.Line(block["block_text"])
                if block['block_text'].isupper() and header_numbers_limit and not_symbol_start:
                    new_class["upper"] = True
                if block['block_type'] == "header":
                    if block['block_text'].split(" ")[0] in ["Section", "SECTION", "ARTICLE"]:
                        new_class["special_header"] = block['block_text'].split(" ")[0]
                    elif block['block_text'].lower().startswith("table of content"):
                        new_class["special_header"] = "TOC"
                if block['block_type'] == "list_item" or (block['block_type'] == "header" and "list_type" in block):
                    new_class["list_type"] = block["list_type"]
                    if line.numbered_line:
                        start_number = line.start_number
                        full_number = line.full_number
                        if start_number.isupper():
                            new_class["list_type"] += "u"
                        if full_number.endswith(")"):
                            new_class["list_type"] += ")"
                        if full_number.endswith("."):
                            new_class["list_type"] += "."
                        new_class["list_type"] += "." * (full_number.count(".") - 1)
                        
                        # check for case i
                        replaced = new_class["list_type"].replace("roman", "letter")
                        if "roman" in new_class["list_type"] and \
                                ((start_number.lower() == "i" and replaced in list_indents and
                                  list_indents[replaced]["text"].lower() == "h") or
                                 (start_number.lower() == "x" and new_class["list_type"] in list_indents and
                                  list_indents[new_class["list_type"]]["text"].lower() != "ix") or
                                 (start_number.lower() == "v" and new_class["list_type"] in list_indents and
                                  list_indents[new_class["list_type"]]["text"].lower() != "iv")):
                            new_class["list_type"] = replaced
                            block["list_type"] = "letter"
                        
                if block['block_type'] in ['header', 'inline_header']:
                    new_class["header"] = True
                    # print(f"block text: {block['block_text']}")
                
                # if block['block_type'] == "header" and "list_type" in block:
                #     new_class["list_type"] = block["list_type"]
                if detect_block_center_aligned(block, self.doc.page_width):
                    new_class["center_aligned"] = True
                    if len(block["visual_lines"]) == 1 and block["visual_lines"][0]["line_style"][1] == "italic":
                        new_class["center_italic"] = True
                
                new_stack = []
                level = 0
                indent_reason = "none"
                if LEVEL_DEBUG:
                    print("==========================================")
                    print(block["block_text"])
                    print("Block Type: ", block["block_type"])
                    print(f"level_stack before:{level_stack}")
                    print(f"new block: {new_class_name}")
                    print(f"List indents: {list_indents}")
                    print(f"List indents stack: {list_indents_stack}")
                    print(f"New Class: {new_class}")

                prev_existing_class = None
                center_aligned_header_same_class = None
                probable_prev_existing_class = None
                header_same_indent_upper_diff_cnt = 0
                has_smaller_or_lighter_header_font = False

                if prev_block and prev_block["block_type"] == "header" and block["block_type"] == "header":
                    has_smaller_or_lighter_header_font = self.doc.has_smaller_or_lighter_header_font(prev_class_name,
                                                                                                     new_class_name)
                if not new_class["list_type"]:
                    for c_idx, c in enumerate(level_stack[::-1]):
                        same_list_item_type = new_class["list_type"] != "" and new_class["list_type"] == c["list_type"]
                        # same_header_list_type = new_class["header_list"] != "" and new_class["header_list"] == c["header_list"]
                        ignore_keys = ["left", "center_aligned", "top"]
                        if same_list_item_type:
                            ignore_keys.append("name")
                        same_attr = {k: v for k, v in new_class.items() if k not in ignore_keys} == \
                            {k: v for k, v in c.items() if k not in ignore_keys}
                        # < 30 is para indent or they have same top (multi column)
                        page_style = list(self.doc.page_styles[block["visual_lines"][0]["page_idx"]])
                        indent_match = True
                        if not page_style[3].get("probable_multi_column", False):
                            indent_match = abs(new_class["left"] - c["left"]) < 30 or\
                                           abs(new_class["top"] - c["top"]) < 3 or \
                                           (new_class.get("center_aligned", False) and c.get("center_aligned", False))
                        same_indent = same_attr and indent_match
                        # print(same_indent, same_list_item_type)
                        # print({k: v for k,v in new_class.items() if k not in ignore_keys})
                        # print({k: v for k,v in c.items() if k not in ignore_keys})
                        cond = prev_block["block_type"] != "header"
                        header_same_indent_upper_diff = False
                        if block["block_type"] == "header" and not cond and not has_smaller_or_lighter_header_font:
                            # Here we are dealing with header and does not have a smaller or lighter header font.
                            # No need to check block_type in that case
                            cond = True
                        if block["block_type"] == "header" and not same_indent and c['block_type'] == "header":
                            # Dealing with headers.
                            header_ignore_keys = {"top", "block_type"}
                            diff = []
                            # Find missing keys
                            missing = list(new_class.keys() - c - header_ignore_keys)
                            if missing:
                                diff.extend(missing)
                            missing = list(c.keys() - new_class - header_ignore_keys)
                            if missing:
                                diff.extend(missing)
                            # Find keys with different values
                            [diff.append(key) for key in (new_class.keys() & c) - header_ignore_keys
                             if new_class[key] != c[key] and key not in diff]

                            if len(diff) == 0:
                                # Do we need this? Can't think why we need it.
                                same_indent = True
                            elif len(diff) == 1:
                                if diff[0] == 'upper' and c_idx != 0:
                                    # All matched except upper and its not the immediate parent in the stack.
                                    # same_indent = True
                                    header_same_indent_upper_diff = True
                            #     elif diff[0] != 'upper':
                            #         has_same_or_bigger_font = self.doc.has_same_or_bigger_font(c['name'],
                            #                                                                    new_class_name)
                            #         if has_same_or_bigger_font:
                            #             same_indent = True
                            elif len(diff) == 2 and 'left' in diff:
                                if 'center_aligned' in diff:
                                    center_aligned_header_same_class = c
                                    break
                                if new_class['special_header'] and \
                                        'special_header' not in diff and abs(new_class['left'] - c['left']) <= 1:
                                    same_indent = True
                        if (same_indent or same_list_item_type) and cond:
                            prev_existing_class = c
                            break
                        if header_same_indent_upper_diff:
                            if not header_same_indent_upper_diff_cnt:
                                probable_prev_existing_class = c
                            header_same_indent_upper_diff_cnt += 1

                if not prev_existing_class and \
                        probable_prev_existing_class and \
                        header_same_indent_upper_diff_cnt == 1:
                    prev_existing_class = probable_prev_existing_class

                prev_diff_class = None
                for c in reversed(level_stack):
                    if not c["name"] == new_class_name:
                        prev_diff_class = c
                        break
                all_caps_largest_font = True
                if len(level_stack) > 0:
                    top_level_class = self.doc.class_line_styles[level_stack[0]["name"]]
                    new_class_style = self.doc.class_line_styles[new_class_name]
                    if new_class_style[2] < top_level_class[2]:
                        all_caps_largest_font = False

                if line.numbered_line and new_class["list_type"] in list_indents:
                    prev_ch = list_indents[new_class["list_type"]]["last_sum"]
                    prev_level = list_indents[new_class["list_type"]]["level"]
                    current_sum = get_list_item_sum(line.start_number, block["list_type"]) if "list_type" in block \
                                    else get_list_item_sum(line.start_number, "")
                    if not 0 < current_sum - prev_ch <= 2 and len(list_indents_stack[new_class["list_type"]]) > 1:
                        stack_list = list_indents_stack[new_class["list_type"]]
                        for item_idx, item in enumerate(stack_list):
                            if item["last_sum"] + 1 == current_sum:
                                prev_ch = item["last_sum"]
                                prev_level = item["level"]
                                list_indents[new_class["list_type"]] = item
                                break
                    if 0 < current_sum - prev_ch <= 2:
                        stack_list = list_indents_stack[new_class["list_type"]]
                        idx = None
                        for item_idx, item in enumerate(stack_list):
                            if item == list_indents[new_class["list_type"]]:
                                idx = item_idx
                                break
                        list_indents[new_class["list_type"]]["last_sum"] = current_sum
                        last_text = list_indents[new_class["list_type"]]["text"]
                        list_indents[new_class["list_type"]]["text"] = line.start_number
                        new_stack = level_stack[:prev_level+1]
                        if idx is not None:
                            list_indents_stack[new_class["list_type"]][idx] = list_indents[new_class["list_type"]]
                            for key, value in list_indents_stack.items():
                                if key == new_class["list_type"]:
                                    op_func = operator.le
                                else:
                                    op_func = operator.lt
                                new_value_list = []
                                for v in value:
                                    if op_func(v["level"], prev_level):
                                        new_value_list.append(v)
                                list_indents_stack[key] = new_value_list

                        parent_list_idx = list_indents[new_class["list_type"]]["parent_list_idx"]
                        block["parent_list_idx"] = parent_list_idx

                        indent_reason = f"matching previous list {last_text}"
                        for l_idx, l in enumerate(level_stack):
                            if l["list_type"] == new_class["list_type"]:
                                if l_idx > prev_level:
                                    new_stack.append(new_class)
                                elif l_idx == prev_level:
                                    # Replace with the new class
                                    new_stack.pop()
                                    new_stack.append(new_class)
                                return prev_level, new_stack, indent_reason
                        
                        new_stack.append(new_class)
                        return prev_level, new_stack, indent_reason

                is_underwriter_block = False
                if prev_block and (
                        prev_block.get("underwriter_block", False) and block.get("underwriter_block", False)):
                    is_underwriter_block = True
                if len(level_stack) == 0:
                    new_stack = [new_class]
                    # print(f"new level {level}")
                    indent_reason = "first level"
                    return 0, new_stack, indent_reason
                elif block["block_type"] == "para" and block["block_text"].startswith("(0 "):
                    block["block_type"] = "list_item"
                    # try to find an matching left
                    for l in level_stack:
                        if l["left"] == new_class["left"]:
                            block["list_type"] = new_class["list_type"]
                            level = level_stack.index(l)
                            new_stack = level_stack[:level+1]
                            parent_list_idx = list_indents[l["list_type"]]["parent_list_idx"]
                            block["parent_list_idx"] = parent_list_idx
                            indent_reason = "special keep indent"
                            return level, new_stack, indent_reason
                    # didn't find the previous indent, start new indent
                    block["list_type"] = ""
                    block["parent_list_idx"] = block["block_idx"] - 1
                    level = len(level_stack)
                    new_stack = level_stack
                    # print(f"found level {level}")
                    indent_reason = "special new indent"
                    return level, new_stack, indent_reason
                elif block['block_text'].isupper() and block["block_type"] == "header" and \
                     (all_caps_largest_font or detect_block_center_aligned(block, self.doc.page_width)):
                    if prev_existing_class:
                        level = level_stack.index(prev_existing_class)
                        # If we indent on a match with the previous header of the same class, it might lead to a train.
                        level_stack[level] = new_class
                        new_stack = level_stack[:level+1]
                        indent_reason = "matching header previous level"
                        return level, new_stack, indent_reason
                    elif center_aligned_header_same_class:
                        # Found a center aligned header in the level stack with the same class which is all Upper case.
                        # Need to add a level
                        level = level_stack.index(center_aligned_header_same_class)
                        level += 1
                        level_stack.append(new_class)
                        new_stack = level_stack
                        indent_reason = "center aligned header previous level - adding another level"
                        return level, new_stack, indent_reason
                    new_stack = [new_class]
                    indent_reason = "all caps reset"
                    return 0, new_stack, indent_reason
                elif prev_existing_class:
                    level = level_stack.index(prev_existing_class)
                    # Replace the existing class with the new one.
                    level_stack[level] = new_class
                    new_stack = level_stack[:level+1]
                    indent_reason = "matching previous level"
                    return level, new_stack, indent_reason
                elif is_underwriter_block:
                    level = len(level_stack) - 1
                    new_stack = level_stack
                    indent_reason = "underwriter - matching previous level"
                    return level, new_stack, indent_reason
                elif block["block_type"] == "table_row" and (is_table or is_table_end) and \
                        level_stack and level_stack[-1]["block_type"] == "table_row":
                    level = len(level_stack) - 1
                    new_stack = level_stack
                    indent_reason = "table - matching previous level"
                    return level, new_stack, indent_reason
                else:
                    new_stack = copy.deepcopy(level_stack)
                    new_line_style = self.doc.class_line_styles[new_class["name"]]
                    all_caps = prev_block["block_text"].isupper() and not block['block_text'].isupper()
                    if prev_block["block_type"] == block["block_type"] == "header" and \
                            all_caps and \
                            self.doc.has_smaller_or_lighter_header_font(new_class_name, prev_class_name):
                        all_caps = False
                    # header_para = prev_block["block_type"] == "header" # and block['block_type'] == "para"
                    parenthesis_indent = "header_type" in prev_block and \
                                         prev_block["header_type"] == "parenthesized_hdr"
                    
                    for (level_idx, level_class_name) in enumerate(reversed(level_stack)):
                        same_class_name = level_class_name["name"] == new_class["name"]
                        level_line_style = self.doc.class_line_styles[level_class_name["name"]]
                        has_smaller_font = new_line_style[2] < level_line_style[2]
                        has_lighter_font = ((new_line_style[2] == level_line_style[2]) and
                                            new_line_style[3] < level_line_style[3])
                        cap_no_cap = (new_line_style[2] == level_line_style[2]) \
                            and (new_line_style[3] == level_line_style[3])  \
                                and (level_class_name["upper"] and not new_class["upper"])

                        is_list_item = new_class["block_type"] == "list_item" and \
                                       level_class_name["list_type"] != new_class["list_type"]

                        header_not_smaller_font = level_line_style[2] >= new_line_style[2]
                        prev_block_toc = False
                        curr_hblock_larger_font_but_aligned = False
                        larger_font_left_aligned = False
                        larger_font_left_level_down = False
                        smaller_font_left_aligned = False
                        center_aligned_header_found = False
                        left_aligned_same_class_list_header = False

                        if prev_block and prev_block["block_type"] == "header":
                            if prev_block['block_text'].lower().startswith("table of content"):
                                prev_block_toc = True
                            if new_class['block_type'] != "header" and level_idx == 0 and \
                                    level_line_style[0] != new_line_style[0] and \
                                    level_line_style[3] > new_line_style[3]:
                                # If we are dealing with different font family, and the previous block was a header,
                                # then preference to font-weight
                                has_lighter_font = True

                        if new_class['block_type'] == "header" and \
                                new_line_style[0] == level_line_style[0] and \
                                new_line_style[3] == level_line_style[3] and \
                                0 <= new_line_style[2] - level_line_style[2] < 0.75 and \
                                level_class_name['left'] < new_class['left'] < self.doc.page_width / 0.4:
                            # If both the continuous blocks are headers and are of the same
                            # font-family, font_weight and new header block is slightly higher font < 0.75 and
                            # if the new block is left-intended consider it a constituent of new header para
                            curr_hblock_larger_font_but_aligned = True
                        elif level_idx == 0 and \
                                same_class_name and \
                                level_class_name['left'] == new_class['left'] and \
                                level_class_name["list_type"] and new_class['list_type'] and \
                                level_class_name["list_type"] == new_class['list_type']:
                            # Same class, left aligned and basically a list item changed to a header.
                            # Respect the order in the PDF File.
                            left_aligned_same_class_list_header = True
                        elif level_idx == 0 and \
                                0 <= new_line_style[2] - level_line_style[2] < 0.75:
                            if level_class_name['left'] == new_class['left']:
                                larger_font_left_aligned = True
                            elif level_class_name['left'] < new_class['left'] < self.doc.page_width / 0.4:
                                larger_font_left_level_down = True
                        elif level_idx == 0 and \
                                has_smaller_font and \
                                level_class_name['left'] == new_class['left'] and \
                                level_class_name['block_type'] == new_class['block_type'] and \
                                new_class['block_type'] != "header":
                            smaller_font_left_aligned = True
                            has_smaller_font = False
                        elif 0 <= new_line_style[2] - level_line_style[2] < 0.75 and \
                                level_class_name['block_type'] == "header" and \
                                new_class['block_type'] in ["para"] and \
                                level_class_name['left'] <= new_class['left']:
                            larger_font_left_level_down = True
                        elif 0 <= new_line_style[2] - level_line_style[2] < 0.75 and \
                                level_class_name['block_type'] == "header" and \
                                new_class['block_type'] == "header" and \
                                level_class_name['left'] == new_class['left']:
                            larger_font_left_aligned = True
                        # No two para blocks of the same type can be in different level
                        if larger_font_left_level_down and \
                                level_class_name['block_type'] == new_class['block_type'] and \
                                new_class['block_type'] == "para":
                            larger_font_left_level_down = False

                        if level_class_name["header"] and \
                                level_class_name.get('center_aligned', False) and \
                                (has_smaller_font or has_lighter_font or same_class_name):
                            center_aligned_header_found = True
                        header_para = level_class_name["header"] and (has_smaller_font
                                                                      or has_lighter_font
                                                                      or prev_block_toc
                                                                      or curr_hblock_larger_font_but_aligned)    # header_not_smaller_font
                        # Check if header_para and of different font sizes and weight
                        if header_para and level_idx < len(level_stack) - 2 and \
                                new_line_style[2] != level_line_style[2] and new_line_style[3] != level_line_style[3]:
                            # Reset header_para if the previous level in the stack is of the same font_weight.
                            # Give more preference to font_weight. (Bold)
                            prev_level_in_stack = level_stack[-(level_idx + 2)]
                            prev_level_line_style = self.doc.class_line_styles[prev_level_in_stack["name"]]
                            has_smaller_font_prev = new_line_style[2] < prev_level_line_style[2]
                            has_lighter_font_prev = ((new_line_style[2] == prev_level_line_style[2])
                                                     and new_line_style[3] < prev_level_line_style[3])
                            has_same_font_prev = new_line_style[3] == prev_level_line_style[3]
                            if prev_level_in_stack["header"] and \
                                    sum([has_smaller_font_prev, has_lighter_font_prev, has_same_font_prev]) >= 2:
                                header_para = False
                                has_smaller_font = False

                        # center_italic = level_line_style.font_style == "italic" and level_class_name["center_aligned"]
                        center_italic = prev_diff_class and prev_diff_class["center_italic"]
                        not_table = not level_class_name["block_type"] == "table_row"
                        indent_same_class_name_header = False
                        if same_class_name and level_class_name["block_type"] == new_class["block_type"] == "header":
                            # Dealing with headers.
                            header_ignore_keys = ["top", "block_type", "name", "header"]
                            set1 = set([(k, v) for k, v in new_class.items() if k not in header_ignore_keys])
                            set2 = set([(k, v) for k, v in level_class_name.items() if k not in header_ignore_keys])
                            diff = list(set1 - set2)
                            if len(diff) == 1:
                                if diff[0][0] == 'left' and new_class['left'] >= level_class_name['left']:
                                    indent_same_class_name_header = True
                            elif len(diff) >= 1:
                                indent_same_class_name_header = True

                        if (header_para or is_list_item) and new_class["list_type"] \
                                and level_class_name["list_type"] != new_class["list_type"]:
                            if line.numbered_line:
                                curr_list_item_sum = get_list_item_sum(line.start_number, block["list_type"]) \
                                    if "list_type" in block else get_list_item_sum(line.start_number, "")
                                list_stack_items = list_indents_stack.get(new_class["list_type"], [])
                                found_prev_item_level = None
                                for item in list_stack_items[::-1]:
                                    if 0 < curr_list_item_sum - item['last_sum'] <= 2:
                                        found_prev_item_level = item['level']
                                        break
                                if found_prev_item_level is not None:
                                    new_stack = new_stack[:found_prev_item_level]
                        disjoint_same_list_type = False
                        if new_class["block_type"] == "list_item" and \
                                level_class_name["list_type"] == new_class["list_type"]:
                            if line.numbered_line:
                                curr_list_item_sum = get_list_item_sum(line.start_number, block["list_type"]) \
                                    if "list_type" in block else get_list_item_sum(line.start_number, "")
                                list_stack_items = list_indents_stack.get(new_class["list_type"], [])
                                found_prev_item_level = None
                                for item in list_stack_items[::-1]:
                                    if 0 < curr_list_item_sum - item['last_sum'] <= 2:
                                        found_prev_item_level = item['level']
                                        break
                                if found_prev_item_level is None:
                                    disjoint_same_list_type = True

                        # print(has_smaller_font, has_lighter_font, all_caps, header_para, cap_no_cap)
                        if not_table and ((has_smaller_font or has_lighter_font or all_caps or
                                          header_para or cap_no_cap or is_list_item or center_italic or
                                          parenthesis_indent) or disjoint_same_list_type or
                                          (same_class_name and level_class_name["header"] and
                                           new_class["block_type"] in ["para"]) or indent_same_class_name_header or
                                          larger_font_left_aligned or larger_font_left_level_down or
                                          smaller_font_left_aligned or center_aligned_header_found or
                                          left_aligned_same_class_list_header):
                            level = len(new_stack)
                            new_class_added = False
                            if smaller_font_left_aligned or left_aligned_same_class_list_header:
                                # Remove from the stack and replace it with the new class below.
                                new_stack.pop()
                            if not larger_font_left_aligned or \
                                    (larger_font_left_aligned and level_class_name["block_type"] in ["header"]):
                                # Add a level when the left aligned block has a header parent.
                                new_stack.append(new_class)
                                new_class_added = True
                            if (larger_font_left_aligned and not level_class_name["block_type"] in ["header"]) or \
                                    smaller_font_left_aligned:
                                # Keep the level same if we encounter a slightly larger font but left aligned.
                                level = level - 1
                            if left_aligned_same_class_list_header:
                                # Remove from the stack and replace it with the new class below.
                                if not new_class_added:
                                    new_stack.append(new_class)
                                level = level - 1

                            # print(f"new indent: {level}")
                            s = f"not_table: {not_table} has_smaller_font: {has_smaller_font}, " \
                                f"has_lighter_font: {has_lighter_font}, all_caps: {all_caps}, " \
                                f"header_para: {header_para}, cap_no_cap: {cap_no_cap}, is_list_item: {is_list_item} \
                                center_italic: {center_italic}, parenthesis_indent: {parenthesis_indent}, " \
                                f"disjoint_same_list_type: {disjoint_same_list_type}, " \
                                f"indent_same_class_name_header: {indent_same_class_name_header}, " \
                                f"larger_font_left_aligned: {larger_font_left_aligned}, " \
                                f"larger_font_left_level_down: {larger_font_left_level_down}, " \
                                f"smaller_font_left_aligned: {smaller_font_left_aligned}, " \
                                f"center_aligned_header_found: {center_aligned_header_found}, " \
                                f"left_aligned_same_class_list_header: {left_aligned_same_class_list_header}"
                            indent_reason = f"added level {level} of indent because {s}"
                            if parenthesis_indent:
                                return level, new_stack[:-2], indent_reason

                            if line.numbered_line:
                                ch_sum = get_list_item_sum(line.start_number, block["list_type"]) \
                                    if "list_type" in block else get_list_item_sum(line.start_number, "")
                                list_indent_item = {
                                    "last_sum": ch_sum,
                                    "level": level,
                                    "text": line.start_number,
                                    "parent_list_idx": block["block_idx"] - 1,
                                }
                                list_indents[new_class["list_type"]] = list_indent_item
                                if list_indents_stack.get(new_class["list_type"], None) is None:
                                    list_indents_stack[new_class["list_type"]] = []
                                idx = None
                                for v_idx, v in enumerate(list_indents_stack[new_class["list_type"]]):
                                    if v['level'] == level:
                                        idx = v_idx
                                        break
                                if idx:
                                    list_indents_stack[new_class["list_type"]][idx] = list_indent_item
                                else:
                                    list_indents_stack[new_class["list_type"]].append(list_indent_item)

                                for key, value in list_indents_stack.items():
                                    new_value_list = []
                                    if key == new_class["list_type"]:
                                        op_func = operator.le
                                    else:
                                        op_func = operator.lt
                                    for v in value:
                                        if op_func(v["level"], level):
                                            new_value_list.append(v)
                                    list_indents_stack[key] = new_value_list

                                block["parent_list_idx"] = block["block_idx"] - 1
                            return level, new_stack, indent_reason
                        else:
                            # new_stack.append(level_class_name)
                            new_stack.pop()
                    if not new_stack:
                        new_stack = [new_class]
                        indent_reason = "most outer level indent (0)"
                    return level, new_stack, indent_reason           

            class_name = block["block_class"]

            line_style = self.doc.class_line_styles[class_name]
            is_para = class_name in self.doc.para_classes
            is_inline_header = block['block_type'] == 'inline_header'
            is_header = block['block_type'] == 'header'

            is_table_start = 'is_table_start' in block
            is_table_end = 'is_table_end' in block

            if is_table_start:
                if LEVEL_DEBUG:
                    print("table started...")
                is_table = True
                if prev_block:
                    table_header_text = header_block_text
                    table_header_idx = header_block_idx
                    # prev_block["block_type"] = "header"

            # is_child_block = is_table_start or ((is_para or is_inline_header) and not is_table)

            # prev_block_is_header = (prev_block and prev_block['block_type'] in ['header', 'inline_header']
            #                         or prev_line_style in self.doc.header_styles)

            indent_reason = "none"

            if is_table and table_parser.row_group_key in block:
                table_header_text = block['block_text']
                table_header_idx = block_idx

            if not is_table and is_header:
                header_block_idx = block["block_idx"]
                header_block_text = block["block_text"]
                block["block_type"] = "header"

            if is_table:
                block["header_text"] = table_header_text
                block["header_block_idx"] = table_header_idx
            else:
                block["header_text"] = header_block_text
                block["header_block_idx"] = header_block_idx

            if is_table_end:
                is_table = False

            # if prev_class_name: # and not class_name == prev_class_name and prev_block_is_header:
            # need to add center alignment detection here
            if LEVEL_DEBUG:
                print(f'\n====', block['block_text'][0:80], '=====\n')
            # if is_child_block:
            #     indent = 0 if NO_INDENT else indent + 1
            #     if is_table_start:
            #         indent_reason = "table_start"
            #     elif is_para:
            #         indent_reason = "para"
            #     elif is_inline_header:
            #         indent_reason = "inline_header"
            #     if LEVEL_DEBUG:
            #         print(f'child block level set to {indent}')
            # else:
            if NO_INDENT:
                indent = 0
                indent_reason = "no indent"
            else:
                indent, level_stack, indent_reason = get_level(class_name)
                if indent in level_freq:
                    level_freq[indent] += 1
                else:
                    level_freq[indent] = 1
            if LEVEL_DEBUG:
                print(f'{class_name} level set to {indent}')
                print(indent_reason)

            # if prev_block and indent != prev_block["level"]:
            if prev_block and False:
                prefix = "\t" * indent
                print(prefix + ">>", indent_reason)
                print(
                    prefix + block["block_type"],
                    block["page_idx"],
                    indent,
                    class_name,
                    # box_style.left,
                    line_style[2],
                    line_style[3],
                    ">", block["block_text"][0:60]
                )
                print(prefix + "***")
            prev_block = block
            prev_class_name = class_name
            prev_line_style = line_style
            block['level'] = indent

            # if there's only 1 header indent under header, make header para
            if block_idx - 2 >= 0 and self.blocks[block_idx - 1]["block_type"] == "header" and \
                    self.blocks[block_idx - 1]["level"] - self.blocks[block_idx - 2]["level"] == 1 and \
                    block["level"] < self.blocks[block_idx - 1]["level"]:
                self.blocks[block_idx - 1]["block_type"] = "para"

        # unindent everything if there is only 1 item in the first level
        i = 0
        while i < len(level_freq) and level_freq[i] == 1:
            for block in self.blocks:
                if block['level'] >= 1:
                    block['level'] -= 1
            i += 1

        # if len(level_freq) > 0 and level_freq[0] == 1:
        #     for block in self.blocks:
        #         if block['level'] >= 1:
        #             block['level'] -= 1