from nlm_ingestor.ingestor_utils.utils import detect_block_center_aligned
import re
from collections import namedtuple
from collections import Counter
import functools

LEVEL_DEBUG = False

HeaderStyle = namedtuple('HeaderStyle',
                         'is_numbered_header, prefix, center_aligned, all_caps, line_style, left_indent')
HeaderInfo = namedtuple('HeaderInfo',
                        'block, clazz, number_part, text_after_number_part, header_style')
style_rank = {'bold': 3, 'normal': 2, 'italic': 1}
prefix_rank = {'has_prefix': 2, 'no_prefix': 1}


# is h1 > h2
def inner_level_compare(h1, h2, debug=False):
    reason = "center"
    h2_prefix = 'no_prefix' if h2.prefix == 'no_prefix' else 'has_prefix'
    h1_prefix = 'no_prefix' if h1.prefix == 'no_prefix' else 'has_prefix'
    # if something is in the center and capitalized and has a number convention
    result = (h1.center_aligned and h1.all_caps and h1_prefix == 'has_prefix') - \
             (h2.center_aligned and h2.all_caps and h2_prefix == 'has_prefix')
    if result == 0:
        result = h1.line_style.font_size - h2.line_style.font_size
        reason = "font_size"
    if result == 0:
        result = h1.line_style.font_weight - h2.line_style.font_weight
        reason = "font_weight"
    if result == 0:
        result = style_rank[h1.line_style.font_style] - style_rank[h2.line_style.font_style]
        reason = "font_style"
    if result == 0:
        reason = "prefix"
        result = prefix_rank[h1_prefix] - prefix_rank[h2_prefix]
        if result == 0:
            result = h1.prefix.isupper() - h2.prefix.isupper()
    if result == 0:
        reason = "all caps"
        result = h1.all_caps - h2.all_caps
    if result == 0:
        result = h2.center_aligned - h1.center_aligned
        reason = "same font center aligned"
    if result == 0:
        reason = "left indent"
        result = h2.left_indent - h1.left_indent
    if debug:
        print(reason)
    return result


def print_and_compare(h1, h2, debug=True):
    print(h1)
    print(h2)
    return inner_level_compare(h1[1], h2[1])


class NewIndentParser(object):
    def __init__(self, doc, blocks):
        self.doc = doc
        self.blocks = doc.blocks
        self.header_by_class_and_prefix = {}
        self.header_key_to_style = {}
        self.style_key_to_info = {}
        self.block_infos = []

    def build_header_by_class_map(self):
        header_by_class = {}
        for block in self.blocks:
            if block['block_type'] == 'header':
                if block['block_class'] not in header_by_class:
                    header_by_class[block['block_class']] = []
                header_by_class[block['block_class']].append(block)

        regex = r'^(\w*) ?(\b[0-9IVX]{1,3}[A-Z]?\b)\.?(.*$)'
        # text = "Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF RESULTS OF OPERATIONS AND FINANCIAL"
        # create a mapping of headers by their class and prefix. For Item 7. prefix is Item
        for clazz, blocks in header_by_class.items():
            header_infos = []
            for block in blocks:
                header_text = block['block_text']
                matches = re.findall(regex, header_text)
                center_aligned = detect_block_center_aligned(block, self.doc.page_width)
                line_style = self.doc.class_line_styles[clazz]
                left_indent = 0 if center_aligned else block['visual_lines'][0]['box_style'].left
                if len(matches) > 0:  # header has prefix or numbers
                    prefix = matches[0][0].strip()
                    number_part = matches[0][1].strip()
                    text_after_number_part = matches[0][2].strip()
                    all_caps = False
                    if text_after_number_part != '':
                        all_caps = text_after_number_part.isupper()
                    else:
                        all_caps = prefix.isupper()
                    header_style = HeaderStyle(
                        is_numbered_header=True,
                        prefix=prefix,
                        line_style=line_style,
                        left_indent=left_indent,
                        center_aligned=center_aligned,
                        all_caps=all_caps)

                    header_info = HeaderInfo(
                        clazz=clazz,
                        block=block,
                        number_part=number_part,
                        header_style=header_style,
                        text_after_number_part=text_after_number_part)

                    header_infos.append(header_info)
                else:   # header doesn't have prefix or numbers
                    header_style = HeaderStyle(
                        is_numbered_header=False,
                        prefix="no_prefix",
                        left_indent=left_indent,
                        line_style=line_style,
                        center_aligned=center_aligned,
                        all_caps=header_text.isupper())

                    header_info = HeaderInfo(
                        clazz=clazz,
                        block=block,
                        number_part=None,
                        header_style=header_style,
                        text_after_number_part=None)

                    header_infos.append(header_info)
            header_info_by_prefix = {}
            for info in header_infos:
                #   print(info.block['header_text'], info.header_style.prefix, info.clazz)
                if info.header_style.prefix:
                    if info.header_style.prefix not in header_info_by_prefix:
                        header_info_by_prefix[info.header_style.prefix] = []
                    header_info_by_prefix[info.header_style.prefix].append(info)

            self.header_by_class_and_prefix[clazz] = header_info_by_prefix

    def build_header_key_to_style_map(self):
        for clazz, header_info_by_prefix in self.header_by_class_and_prefix.items():
            if len(header_info_by_prefix.items()):
                for key, infos in header_info_by_prefix.items():
                    if key != 'no_prefix':
                        # get the most frequently used style for something with a certain numbering system
                        info_set = set()
                        self.style_key_to_info[key] = []
                        for info in infos:
                            info_set.add(info.header_style)
                            self.style_key_to_info[key].append(info)
                        self.header_key_to_style[key] = Counter(info_set).most_common(1)[0][0]
                    else:
                        # get the most frequently used style for something with no numbering system
                        no_prefix_items_by_style = dict()
                        for info in infos:
                            if info.header_style not in no_prefix_items_by_style:
                                no_prefix_items_by_style[info.header_style] = []
                            no_prefix_items_by_style[info.header_style].append(info)
                        for key in no_prefix_items_by_style.keys():
                            self.header_key_to_style[key] = key
                            self.style_key_to_info[key] = []
                            for info in no_prefix_items_by_style[key]:
                                self.style_key_to_info[key] .append(info)

    def assign_levels(self):
        def header_level_compare(item1, item2):
            h1 = item1[1]
            h2 = item2[1]
            return inner_level_compare(h1, h2)

        # sort the items by comparing their levels
        # level is the relative preference of a particular header style e.g. bold is higher level than regular text
        sorted_items = sorted(list(self.header_key_to_style.items()),
                              key=functools.cmp_to_key(header_level_compare), reverse=True)
        # this block of file goes through the entire list of headers to figure out relative level of every style
        if len(sorted_items) > 0:
            level = 0
            prev_style = sorted_items[0][1]
            # assign a level to every style
            for idx, (style_key, style) in enumerate(sorted_items):
                level_difference = inner_level_compare(style, prev_style)
                # if there is level change between previous style and new one
                if level_difference < 0:
                    level = level + 1 
        #             print("change in level -----", style, prev_style)
                infos = self.style_key_to_info[style_key]
                if LEVEL_DEBUG:
                    print(f"--------{idx}, {level}--------")
                for info in infos:
                    info.block['level'] = level
                    if LEVEL_DEBUG:
                        print(info.block['block_text'])
                    self.block_infos.append(info)
                prev_style = style

    # def combine_and_remove_duplicates(self):
    #     for (style_key, style) in self.header_key_to_style.items():
    #         print(style_key, style)
    def assign_indents(self):
        sorted_by_idx = sorted(self.block_infos, key=lambda x: x.block['block_idx'])
        indent = 0  # indent is how this particular level should be indented
        level_to_indents = {}   # the previous indent of this level
        level_stack = []
        prev_level = 0
        for idx, info in enumerate(sorted_by_idx):
            level = info.block['level']
            if len(level_stack) == 0:
                level_stack.append(level)
        #     elif level in level_to_indents: # if this level was previously used
        #         print("found level...", level)
        #         indent = level_to_indents[level]
            else:   # if this is a new level
                prev_level = level_stack[-1]
                if level > prev_level:  # keep increasing indent if level > prev_level
                    # print("adding level...", level)
                    level_stack.append(level)
                elif level < prev_level: # if level is less than prev level
                    while level < prev_level and len(level_stack) > 0: # keep going back left until the right level
                        level_stack.pop()
                        if len(level_stack) > 0:
                            prev_level = level_stack[-1]
                    if level > prev_level or len(level_stack) == 0:
                        level_stack.append(level)
                        prev_level = 0
                indent = len(level_stack) - 1
            level_to_indents[level] = indent
            if indent == 0:
                level_to_indents = {}
            if LEVEL_DEBUG:
                print(str(idx) + "\t"*indent + str(indent)
                      + "--" + info.block['block_text'] + "--" + str(info.block['level']), level_stack)
            info.block['level'] = level

    def indent_leafs(self):
        curr_header = None
        prev_block = None
        for block in self.blocks:
            if block['block_type'] == 'header':
                curr_header = block
            if curr_header and block['block_type'] in ['para', 'table', 'list', 'table_row']:
                block['level'] = curr_header['level'] + 1
            if block['block_type'] in ['list_item']:
                if prev_block and prev_block['block_type'] in ['para', 'list_item'] and \
                        prev_block['block_text'].endswith(':'):
                    block['level'] = curr_header['level'] + 1
                elif prev_block and prev_block['block_type'] in ['list_item']:
                    block['level'] = prev_block['level']
            prev_block = block

    def indent(self):
        self.build_header_by_class_map()
        self.build_header_key_to_style_map()
        self.assign_levels()
        self.assign_indents()
        self.indent_leafs()
