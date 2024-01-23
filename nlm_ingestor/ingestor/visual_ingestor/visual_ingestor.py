# parse style

import copy
import re
import string
from collections import OrderedDict, namedtuple
import operator
import sys
import numpy as np
import pprint
from typing import List, Dict
from itertools import groupby
from bs4 import BeautifulSoup
from timeit import default_timer

from nlm_ingestor.ingestor_utils.utils import sent_tokenize
from nlm_ingestor.ingestor_utils.ing_named_tuples import BoxStyle, LineStyle, LocationKey
from nlm_ingestor.ingestor.visual_ingestor import style_utils, table_parser, indent_parser, block_renderer, order_fixer
from nlm_ingestor.ingestor import line_parser
from nlm_ingestor.ingestor_utils.parsing_utils import *
from nlm_ingestor.ingestor.visual_ingestor import vi_helper_utils as vhu

base_font_size = 3
header_margin = 0.18            # don't touch this!
footer_margin = 0.1
line_height_threshold = 1.4     # used to be 1.8 - use statistics
table_col_threshold = 2.8       # 3.35# used to be 4.0 - use statistics
table_end_space_threshold = 2.2
JUSTIFIED_NORMAL_GAP_MULTIPLIER = 4.0
CURRENCY_TOKENS = ['$', '€', '£']

LINE_DEBUG = False
LEVEL_DEBUG = False
MIXED_FONT_DEBUG = False
NO_INDENT = False
HF_DEBUG = False
REORDER_DEBUG = False
BLOCK_DEBUG = False
MERGE_DEBUG = False
PERFORMANCE_DEBUG = False
PROGRESS_DEBUG = True

pp = pprint.PrettyPrinter(indent=4, compact=True)

# List of items / p_tags which when returned need to be raised a flag
filter_out_pattern_list = [
    ".", "_", "�"  # example --->  "start string . . . . . . . . .some other string"
    ]
PARENTHESIZED_HDR = r'^\s*\(([^\)]+)\)\s*$'
PAGE_NUM_HEADER = r'\s*[pP]age\s*\d+\s*'            # Identify patterns like "Page 1" / "Page 1 of n"

filter_out_pattern = re.compile(r"[" + "".join(filter_out_pattern_list) + "]{2,}")  # 2 or more occurrences
filter_ls_pattern = re.compile(r"^[" + "".join(filter_out_pattern_list) + "]{2,}")  # Left side pattern
text_only_pattern = re.compile(r"[^a-zA-Z]+")
only_text_pattern = re.compile(r"^[^a-zA-Z$%]+$")
roman_only_pattern = re.compile(r"^[ixvIXV]+$")
not_a_number_pattern = re.compile(r"[^0-9]+")
single_char_pattern = re.compile(r"^[a-zA-Z]$")
non_alphanumeric_pattern = re.compile(r"[^A-Za-z0-9]+")
year_pattern = re.compile(r"^(1|2)\d{3}$")
number_in_braces_pattern = re.compile(r"(\(\d+\))")
page_num_pattern = re.compile(PAGE_NUM_HEADER, re.IGNORECASE)
parenthesized_hdr_pattern = re.compile(PARENTHESIZED_HDR)
ends_with_sentence_delimiter_pattern = re.compile(r"(?<![.;:][a-zA-Z0-9])(?<!INC|inc|Inc)[.;:]+(?![\w])[\"“‘’”\'\s]*$")
section_num_pattern = re.compile(r"^\d+([.]?\d+[.]?)*$")
floating_number_pattern = re.compile(r"\d+([.]?\d+[.]?)*")
section_generic_pattern = re.compile(r"section(?!\s+\d+\.*\d*\.*[(])(\s+\d+\.*\d*\.*[,\-;\w\s]+\.\s*)", re.MULTILINE)
integer_pattern = re.compile(r"(?<![\d.])[0-9]+(?![\d.])")
start_punct_pattern = re.compile(r"^[.,;:\"“‘’”\']")
email_pattern = re.compile(r'([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+')


def get_block_type(group_is_list, group_is_table_row, group_text):
    block_type = "para"
    line_props = line_parser.Line(group_text)
    if group_is_list:
        block_type = "list_item"
    elif group_is_table_row:
        block_type = "table_row"
    elif line_props.is_header:
        block_type = "header"
    return block_type, line_props


class Doc:
    def __init__(self, pages, ignore_blocks, render_format: str = "all", audited_bbox = None):
        self.pages = pages
        self.line_style_classes = dict()
        self.class_line_styles = dict()
        self.class_stats = dict()
        self.render_format = render_format
        self.html_str = ""
        self.json_dict = None
        self.blocks = []
        self.header_styles = []
        self.normal_styles = []
        self.footnote_styles = []
        self.blocks_by_page = []
        self.ignore_blocks = ignore_blocks
        self.class_levels = OrderedDict()
        self.file_stats = {}
        self.para_classes = set()
        self.class_freq_order = {}
        self.page_width = 0
        self.page_height = 0
        self.line_style_space_stats = {}
        self.line_style_word_space_stats = {}
        self.line_style_word_stats = {}
        self.visual_line_word_stats = {}
        self.is_justified = False
        self.page_styles = []           # Style specific to a page. Height, width, space stats etc.
        self.audited_bbox = audited_bbox
        self.audited_table_bbox = {}
        self.page_svg_tags = []
        if PERFORMANCE_DEBUG:
            self.wall_time = default_timer()
        self.parse(pages)

    def parse(self, pages):
        pages = pages
        group_buf = []
        grouped_body_str = "<body>"
        class_name = "none"
        group_is_list = False
        group_is_table_row = False
        blocks = []
        block_idx = 0
        class_blocks = []
        group_reason = ""
        page_headers = dict()
        page_footers = dict()
        last_line_counts = {}
        page_p_styles = []
        page_idx = 0
        blocks_by_page = []
        page_blocks = []
        vl_word_counts = []
        soup = BeautifulSoup()
        if self.audited_bbox:
            # Group by page_idx for later usage.
            table_query = {'block_type': 'table'}
            for page_id, bboxes in groupby(audited_bbox, key=lambda bbox: bbox.page_idx):
                list_of_bbox = list(bboxes)
                self.audited_bbox[page_id] = list_of_bbox
                self.audited_table_bbox[page_id] = list(self.filter_list_of_bbox(list_of_bbox, **table_query))
        if BLOCK_DEBUG:
            print('Audited Table Boxes: ', self.audited_table_bbox)
        for page_idx, page in enumerate(pages):
            all_p = page.find_all("p")
            svg_children = page.find('svg') or []
            lines_tag_list, rect_tag_list = Doc.remove_duplicate_svg_tags(soup, svg_children)

            self.page_svg_tags.append([lines_tag_list, rect_tag_list])
            # page_style = pages[0].attrs["style"]
            page_style = pages[page_idx].attrs.get("style", None) or pages[0].attrs["style"]
            page_style_kv = style_utils.get_style_kv(page_style)
            page_width = style_utils.parse_px(page_style_kv["width"])
            self.page_width = self.page_width or page_width
            page_height = style_utils.parse_px(page_style_kv["height"])
            self.page_height = self.page_height or page_height
            header_cutoff = header_margin * page_height
            footer_cutoff = self.page_height - footer_margin * self.page_height
            # print("page_dims: ", page_width, page_height)
            # print("margins: ", header_margin*page_height, footer_margin*page_height)
            p_styles = []
            prev_box_style = None
            prev_line_style = None
            page_line_stats = {}
            prev_p_tag = None
            for line_idx, orig_p in enumerate(all_p):
                # Reformat p if the text contains items to be replaced.
                new_p = None
                changed = False
                if filter_out_pattern.search(orig_p.text) is not None:
                    new_p, changed = style_utils.format_p_tag(orig_p, filter_out_pattern,
                                                              filter_ls_pattern, soup)
                if orig_p.text.strip() == '':
                    orig_p.decompose()
                    line_idx += 1
                    continue
                p_list = [orig_p]
                if new_p:
                    if prev_p_tag:
                        prev_p_tag.insert_after(new_p)
                    else:
                        page.insert(0, new_p)
                    p_list = [new_p, orig_p]
                for p in p_list:
                    if line_idx > len(all_p) - 3:
                        text_only = text_only_pattern.sub("", p.text).strip()
                        if not (text_only == '' and year_pattern.search(p.text) is None):
                            # Possible year?
                            if text_only not in last_line_counts:
                                last_line_counts[text_only] = 1
                            else:
                                last_line_counts[text_only] = last_line_counts[text_only] + 1
                    box_style, line_style, word_line_styles = style_utils.parse_tika_style(
                        p["style"], p.text, page_width
                    )
                    is_page_header = box_style[0] < header_cutoff  # Check box_style.top
                    is_page_footer = box_style[0] > footer_cutoff  # Check box_style.top

                    loc_key = "N/A"
                    if is_page_header or is_page_footer:
                        loc_key = Doc.get_location_key(box_style, p.text)
                        if is_page_header:
                            if loc_key in page_headers:
                                page_headers[loc_key].append(page_idx)
                            else:
                                page_headers[loc_key] = [page_idx]
                        else:
                            if loc_key in page_footers:
                                page_footers[loc_key].append(page_idx)
                            else:
                                page_footers[loc_key] = [page_idx]

                    p_styles.append(
                        (
                            box_style,
                            line_style,
                            word_line_styles,
                            loc_key,
                            is_page_header,
                            is_page_footer,
                            changed
                        ),
                    )
                    if len(p.text) > 0:
                        word_count = len(p.text.split())
                        vl_word_counts.append(word_count)
                        if line_style not in self.line_style_word_stats:
                            self.line_style_word_stats[line_style] = []
                        self.line_style_word_stats[line_style].append(word_count)

                    if prev_line_style == line_style:
                        same_top = prev_box_style[0] == box_style[0]
                        if not same_top:
                            space = round(box_style[0] - prev_box_style[0], 1)
                            if space > 0:
                                if line_style not in self.line_style_space_stats:
                                    self.line_style_space_stats[line_style] = []
                                self.line_style_space_stats[line_style].append(space)
                                # Add to page_line_stats.
                                if line_style not in page_line_stats:
                                    page_line_stats[line_style] = {'lines': 0, 'space_counts': {}}
                                page_line_stats[line_style]['lines'] += 1
                                if space not in page_line_stats[line_style]['space_counts']:
                                    page_line_stats[line_style]['space_counts'][space] = 0
                                page_line_stats[line_style]['space_counts'][space] += 1
                        else:
                            word_space = round(box_style[1] - prev_box_style[2], 1)
                            if word_space > 0:
                                if line_style not in self.line_style_word_space_stats:
                                    self.line_style_word_space_stats[line_style] = []
                                self.line_style_word_space_stats[line_style].append(word_space)

                    prev_box_style = box_style
                    prev_line_style = line_style
                    prev_p_tag = p
                    changed = False  # Reset the change here. Change is meant for only the first p_tag
            page_p_styles.append(p_styles)
            # Calculate the page stats.
            # Max number of lines and most frequent space gaps between lines etc
            max_lines = 0
            most_freq_spaces = {}
            for line_style in page_line_stats:
                max_lines = max(max_lines, page_line_stats[line_style]['lines'])
                max_count = 0
                ls_most_freq_space = -1
                for space, space_count in page_line_stats[line_style]['space_counts'].items():
                    if space_count > max_count:
                        max_count = space_count
                        ls_most_freq_space = space
                most_freq_spaces[ls_most_freq_space] = most_freq_spaces.get(ls_most_freq_space, 0) + max_count
            most_freq_space = 0
            if most_freq_spaces:
                most_freq_space = max(most_freq_spaces.items(), key=operator.itemgetter(1))[0]
            page_stats = {'lines': max_lines, 'most_frequent_space': most_freq_space}
            self.page_styles.append((page_style_kv, page_width, page_height, page_stats))
        if PERFORMANCE_DEBUG:
            new_wall_time = default_timer()
            print(f"Checkpoint 1 Finished. Wall time: {((new_wall_time - self.wall_time) * 1000):.2f}ms")
            self.wall_time = new_wall_time
        for line_style in self.line_style_space_stats:
            spaces = self.line_style_space_stats[line_style]
            space_counts = {}
            for space in spaces:
                if space not in space_counts:
                    space_counts[space] = 0
                space_counts[space] = space_counts[space] + 1
            max_count = 0
            most_frequent_space = -1
            for space, space_count in space_counts.items():
                if space_count > max_count:
                    max_count = space_count
                    most_frequent_space = space
            self.line_style_space_stats[line_style] = {"avg": np.mean(spaces)/line_style[2],
                                                       "median": np.median(spaces)/line_style[2],
                                                       "std": np.std(spaces),
                                                       "count": len(spaces),
                                                       "most_frequent_space": most_frequent_space,
                                                       "space_counts": space_counts}
        for line_style in self.line_style_word_space_stats:
            line_style_vl_word_spaces = self.line_style_word_space_stats[line_style]

            self.line_style_word_space_stats[line_style] = {
                "avg": np.mean(line_style_vl_word_spaces),
                "median": np.median(line_style_vl_word_spaces),
                "count": len(line_style_vl_word_spaces),
                "std": np.std(line_style_vl_word_spaces),
            }
        for line_style in self.line_style_word_stats:
            line_style_vl_word_counts = self.line_style_word_stats[line_style]
            # print(line_style_vl_word_counts)
            line_style_vl_word_stats_median = np.median(line_style_vl_word_counts)
            self.line_style_word_stats[line_style] = {
                "avg": np.mean(line_style_vl_word_counts),
                "median": line_style_vl_word_stats_median,
                "std": np.std(line_style_vl_word_counts),
                "is_justified": line_style_vl_word_stats_median < 2,
                "count": np.sum(line_style_vl_word_counts),
            }
        self.visual_line_word_stats = {
            "avg": np.mean(vl_word_counts),
            "median": np.median(vl_word_counts),
            "std": np.std(vl_word_counts),
            "count": np.sum(vl_word_counts),
        }

        self.is_justified = self.visual_line_word_stats["avg"] < 1.1
        page_headers = Doc.find_true_header_footers(page_headers, len(pages))
        page_footers = Doc.find_true_header_footers(page_footers, len(pages), is_footer=True)
        if PERFORMANCE_DEBUG:
            new_wall_time = default_timer()
            print(f"Checkpoint 2 Finished. Wall time: {((new_wall_time - self.wall_time) * 1000):.2f}ms")
            self.wall_time = new_wall_time
        for page_idx, page in enumerate(pages):
            if not page_p_styles or not page_p_styles[page_idx]:
                continue
            # figure out page
            all_p = page.find_all("p")
            if PROGRESS_DEBUG:
                print('processing page: ', page_idx, " Number of p_tags.... ", len(all_p))
            line_idx = 0
            oo_present = False
            prev_filter_ignore = False
            filter_pattern_ignored = False
            has_lines_from_previous_page = len(group_buf) > 0
            page_visual_lines = []
            while line_idx < len(all_p):
                if line_idx >= len(page_p_styles[page_idx]):
                    break
                p = all_p[line_idx]
                p_text = p.text
                for word, replacement in line_parser.unicode_list_types.items():
                    p_text = p_text.replace(word, replacement)
                lp_line = line_parser.Line(p_text)
                (
                    box_style,
                    line_style,
                    word_line_styles,
                    loc_key,
                    is_page_header,
                    is_page_footer,
                    changed
                ) = page_p_styles[page_idx][line_idx]

                # this section removes any unwanted lines e.g. line numbers, footers, ignore blocks etc.
                should_ignore, filter_ignore = self.should_ignore_line(all_p, is_page_footer, is_page_header,
                                                                       last_line_counts, line_idx, loc_key, lp_line, p,
                                                                       page_footers, page_headers, page_idx, box_style,
                                                                       page_visual_lines)
                # Items to be filtered out.
                if prev_filter_ignore and len(page_visual_lines) > 0:
                    prev_filter_ignore = filter_ignore
                    # Check if the previous line is the same as the current one and both had to be filtered out.
                    if filter_ignore:
                        line_idx = line_idx + 1
                        filter_pattern_ignored = True
                        continue
                    elif filter_pattern_ignored:
                        # Flush out the last one remaining (the first one added to the list)
                        page_visual_lines = page_visual_lines[:-1]
                        if len(page_visual_lines) > 0:
                            last_vl = page_visual_lines[-1]
                            last_vl["changed"] = True
                            page_visual_lines[-1] = last_vl
                            filter_pattern_ignored = False
                else:
                    prev_filter_ignore = filter_ignore

                def check_ignore_line_within_retained(psv, bs):
                    if not len(psv):
                        return False
                    if abs(psv[-1]["box_style"][0] - bs[0]) <= bs[4] and \
                            abs(psv[-1]["box_style"][2] - bs[1]) <= 20:
                        return True
                    elif len(psv) > 1:
                        # Check for table cell elements
                        if abs(psv[-2]["box_style"][0] - psv[-1]["box_style"][0]) <= psv[-1]["box_style"][4]:
                            if psv[-2]["box_style"][2] < psv[-1]["box_style"][1]:
                                gap = psv[-1]["box_style"][1] - psv[-2]["box_style"][2]
                                if abs(psv[-1]["box_style"][0] - bs[0]) <= bs[4] and \
                                        abs(psv[-1]["box_style"][2] - bs[1]) <= gap + 20:
                                    return True
                    return False
                if should_ignore and check_ignore_line_within_retained(page_visual_lines, box_style) and \
                        p_text not in string.punctuation:
                    should_ignore = False
                if should_ignore:
                    if LINE_DEBUG:
                        print("Skipping curr line: ",  p_text)
                    # Check we have some business to be taken care before we sign off the page.
                    if not (len(page_visual_lines) > 0 and line_idx == len(all_p) - 1):
                        line_idx = line_idx + 1
                        continue
                # print(p.text, line_style)
                line_info = {
                    "box_style": box_style,
                    "line_style": line_style,
                    "text": p_text,
                    "page_idx": page_idx,
                    "lp_line": lp_line,
                    "line_parser": lp_line.to_json(),
                    "should_ignore": should_ignore,
                    "changed": changed,
                    "ptag_idx": line_idx
                }
                if LINE_DEBUG:
                    print("\n")
                    print("-"*80)
                    print("curr line: ",  line_info['text'])

                # assign a style name to the font/line style (only font characteristics)
                word_classes = []
                prev_word_class = None
                for word_idx, word_line_style in enumerate(word_line_styles):
                    word_class = self.get_class(word_line_style)
                    word_classes.append(word_class)
                line_info["word_classes"] = word_classes

                class_name = self.get_class(line_style)
                line_info["class"] = class_name
                page_visual_lines.append(line_info)
                line_idx = line_idx + 1
            page_blocks, group_buf, block_idx, group_is_list, vl_from_prev_page_discarded = \
                self.visual_lines_to_blocks(page_visual_lines, group_buf, block_idx, group_is_list)
            # a page has ended
            order_offset = 0
            if has_lines_from_previous_page:
                order_offset = 1
                # Handle case with sections.
                # header_modified & para
                if len(page_blocks) > 1 and page_blocks[0]["page_idx"] == page_blocks[1]["page_idx"]:
                    order_offset = 2
            oo_fixer = order_fixer.OrderFixer(self, page_blocks, offset=order_offset)
            page_blocks, is_reordered = oo_fixer.reorder()
            for i in range(2):
                if len(page_blocks) > 0 and Doc.has_page_number(page_blocks[-1]["block_text"], last_line_counts):
                    # print("---removing", page_blocks[-1]["block_text"])
                    page_blocks.pop()
            # Last block in the previous page might get attached to the current page.
            # Due to TIKA placing of p-tags, we might receive the first Visual Line as the last one,
            # so try to correctly place them. Right now check only for top co-ordinate
            page_block_start_block_num = 0
            if has_lines_from_previous_page and len(blocks_by_page[-1]) and len(page_blocks) and \
                    not vl_from_prev_page_discarded:
                page_block_start_block_num = order_offset
                last_page_blocks_len = len(blocks_by_page[-1])
                t_blocks = []
                page_block_added = False
                block_top = page_blocks[0]["visual_lines"][0]["box_style"][0]
                if order_offset == 1:
                    for count, b in enumerate(blocks[-last_page_blocks_len:]):
                        curr_box = b["visual_lines"][0]["box_style"]
                        curr_top = curr_box[0]
                        curr_bottom = curr_box[0] + curr_box[4]
                        if not page_block_added and (abs(block_top - curr_top) <= 15 or
                                                     block_top < curr_top) and block_top < curr_bottom:
                            page_blocks[0]["block_reordered"] = True
                            t_blocks.append(page_blocks[0])
                            t_blocks.append(b)
                            page_block_added = True
                        else:
                            t_blocks.append(b)
                elif order_offset == 2:
                    t_blocks = blocks[-last_page_blocks_len:]
                if not page_block_added:
                    t_blocks.extend(page_blocks[:page_block_start_block_num])
                blocks = blocks[:-last_page_blocks_len] + t_blocks
            blocks_by_page.append(page_blocks[page_block_start_block_num:])
            # print(">>>>>>>>>>>>>>>last block: ", page_blocks[-1]['block_text'], group_buf[0]['page_idx'])
            for pb in page_blocks[page_block_start_block_num:]:
                blocks.append(pb)
            page_blocks = []

        if len(group_buf) > 0:
            print("group buf still has: ", len(group_buf), group_buf[0]["text"])
            group_text, group_props, page_idxs = self.collapse_group(group_buf, class_name)
            block_type, line_props = get_block_type(
                group_is_list, group_is_table_row, group_text,
            )
            if block_type == "para" and group_buf[0]['text'].lower().startswith("section"):
                result_list = [group_buf]
                buf_texts = block_types = []
                result_list, buf_texts, block_types = \
                    self.create_new_vl_group_for_sections(result_list, buf_texts, block_types)
                for i, grp_buf in enumerate(result_list):
                    block_type = block_types[i]
                    block_modified = False
                    block_class = class_name
                    if block_types[i] == "header_modified":
                        block_type = "header"
                        block_modified = True
                        block_class = grp_buf[0]['class']
                    block = {
                        "block_idx": block_idx,
                        "page_idx": page_idx,
                        "block_type": block_type,
                        "block_text": str(buf_texts[i]),
                        "visual_lines": grp_buf,
                        "block_class": block_class,
                        "block_modified": block_modified
                    }
                    block['box_style'] = Doc.calc_block_span(block)
                    blocks.append(block)
                    page_blocks.append(block)
            else:
                block = {
                    "block_idx": block_idx,
                    "page_idx": page_idx,
                    "block_type": block_type,
                    "block_text": group_text,
                    "visual_lines": group_buf,
                    "block_class": class_name,
                }
                block['box_style'] = Doc.calc_block_span(block)
                blocks.append(block)
                page_blocks.append(block)
            oo_fixer = order_fixer.OrderFixer(self, page_blocks, offset=0)
            page_blocks, is_reordered = oo_fixer.reorder()
            blocks_by_page.append(page_blocks)

        if PERFORMANCE_DEBUG:
            new_wall_time = default_timer()
            print(f"Checkpoint 3 Finished. Wall time: {((new_wall_time - self.wall_time) * 1000):.2f}ms")
            self.wall_time = new_wall_time
        self.blocks = blocks
        self.blocks_by_page = blocks_by_page
        self.save_file_stats()
        self.organize_and_indent_blocks()
        if PERFORMANCE_DEBUG:
            new_wall_time = default_timer()
            print(f"Checkpoint 4 Finished. Wall time: {((new_wall_time - self.wall_time) * 1000):.2f}ms")
            self.wall_time = new_wall_time
        self.label_table_of_content()
        if self.render_format == "json":
            self.json_dict = block_renderer.BlockRenderer(self).render_json()
        elif self.render_format == "html":
            self.html_str = block_renderer.BlockRenderer(self).render_html()
        else:
            self.json_dict = block_renderer.BlockRenderer(self).render_json()
            self.html_str = block_renderer.BlockRenderer(self).render_html()

    def visual_lines_to_blocks(self, visual_lines, group_buf=[], block_idx=0, group_is_list=False):
        prev_line_info = group_buf[-1] if len(group_buf) > 0 else None
        has_vl_from_prev_page = True if prev_line_info else False
        vl_from_prev_page_discarded = False
        is_list_start = False
        is_list_start_separate_line = False
        is_list_start_same_line = False
        group_is_fake_row = False
        group_is_table_row = False
        page_blocks = []
        line_idx = 0
        prev_block_footer_discarded = False
        page_height = None
        prev_discarded_block = None
        while line_idx < len(visual_lines):
            if not page_height:
                _, page_width, page_height, _ = self.page_styles[visual_lines[0]["page_idx"]]
            line_info = visual_lines[line_idx]
            should_ignore = "should_ignore" in line_info and line_info["should_ignore"]
            if "lp_line" not in line_info:
                lp_line = line_parser.Line(line_info["text"])
                line_info["lp_line"] = lp_line
                line_info["line_parser"] = lp_line.to_json()

            # is_multi_class_line = len(word_class) > 1
            is_list_start, is_list_start_separate_line, \
            is_mixed_font, group_is_table_row, \
            is_new_group, line_idx, prev_line_info, line_info = self.detect_new_group(
                line_idx,
                line_info,
                prev_line_info,
                group_buf,
                line_info["lp_line"],
                group_is_table_row,
                is_list_start,
                page_blocks,
            )
            is_mixed_font = False  # turn it off until fixed
            if is_new_group or is_mixed_font or line_idx == len(visual_lines) - 1:
            # if ((is_new_group or (is_new_group and (line_idx == len(visual_lines) - 1))) and not should_ignore) \
            #         or is_mixed_font:
                if line_idx == len(visual_lines) - 1 and not is_new_group and not should_ignore:
                    group_buf.append(line_info)
                # group only has everything until previous line
                group_class_name = ( 
                    Counter(prev_line_info["word_classes"]).most_common()[0][0]
                    if prev_line_info
                    else line_info["class"]
                )  # prev_line_info['word_classes'][-1] if prev_line_info else class_name

                inline_header_line_info = None
                # process mixed font only
                if is_mixed_font and not group_is_table_row:
                    header_line_info, normal_line_info = self.split_line(line_info)
                    is_continuing_header = (
                            group_class_name == header_line_info["class"]
                    )
                    line_info = normal_line_info
                    if is_continuing_header:
                        group_buf.append(header_line_info)
                    else:
                        # this will be written after closing the current group
                        inline_header_line_info = header_line_info
                block_type = None

                # merging stuff a table, remove merge vls when needed
                if group_is_table_row and not group_is_fake_row:  # good place to fix justified text
                    group_text, group_props, page_idxs = self.collapse_group(
                        group_buf, group_class_name,
                    )
                    prev_count = len(group_buf)
                    group_buf, row_count, check_fake_row = self.merge_vls_if_needed(group_buf, group_is_table_row)
                    new_count = len(group_buf)
                    if new_count == row_count and check_fake_row and prev_count > 1:
                        print("removing fake table row: ", group_text, line_info['text'], prev_count, row_count,
                              group_is_table_row)
                        if table_parser.TABLE_DEBUG:
                            print("removing fake table row: ", group_text)
                        block_type, _ = get_block_type(False, False, group_text)
                        group_is_table_row = False
                        group_is_fake_row = True
                        line_idx = line_idx + 1
                        continue
                else:
                    group_text, group_props, page_idxs = self.collapse_group(
                        group_buf, group_class_name,
                    )

                group_page_idx = page_idxs[0]
                if group_text.strip() == "":
                    prev_line_info = line_info
                    group_buf.append(line_info)
                    line_idx = line_idx + 1
                    continue
                if not block_type:
                    if group_is_list and len(page_blocks) > 0 and not group_is_table_row and \
                            page_blocks[-1]["block_type"] == "table_row" and len(group_buf) > 2:
                        prev_vl = group_buf[0]
                        num_table_cells = 0
                        for vl in group_buf[1:]:
                            gap, normal_gap, act_normal_gap, _ = self.get_gaps_from_vls(vl, prev_vl)
                            if gap > normal_gap:
                                num_table_cells += 1
                            prev_vl = vl
                        if num_table_cells > 0.6 * len(group_buf):
                            group_is_list = False
                            group_is_table_row = True
                    elif group_is_list and group_is_table_row and len(group_buf) >= 2:
                        # find the difference between the last 2 VLs.
                        gap, normal_gap, _, _ = self.get_gaps_from_vls(group_buf[-1], group_buf[-2])
                        if gap > normal_gap:
                            group_is_list = False
                    block_type, line_props = get_block_type(
                        group_is_list, group_is_table_row, group_text,
                    )
                if block_type == "header":
                    cell_count = self.count_possible_cells(group_buf)
                    if cell_count > 2:
                        block_type = "table_row"

                # Here we try to divide any "para" block which might have got created the way Tika output the tags
                # Prepare variables here.
                final_group_bufs = [group_buf]
                block_types = [block_type]
                buf_texts = [group_text]
                last_para_with_delimeter = (line_idx == len(visual_lines) - 1) and \
                                           block_type == "para" and \
                                           not group_buf[-1]["line_parser"].get("incomplete_line", True)
                if block_type != "table_row" and not last_para_with_delimeter:  # Not a table row
                    if line_idx == len(visual_lines) - 1:  # Last line
                        if should_ignore:  # If we have to ignore, don't add to list
                            line_idx = line_idx + 1
                            continue
                        elif not is_new_group and len(group_buf) and \
                                len(page_blocks) > 0 and page_blocks[-1]["box_style"][0] > line_info['box_style'][0]:
                            # Create a block anyways here
                            block = {
                                "block_idx": block_idx,
                                "page_idx": group_page_idx,
                                "block_type": block_type,
                                "block_text": group_text,
                                # 'line_props': line_props,
                                "visual_lines": group_buf,
                                "block_class": group_class_name,
                                "block_modified": False
                            }
                            block['box_style'] = Doc.calc_block_span(block)
                            page_blocks.append(block)
                            if LINE_DEBUG:
                                print(">>> adding block - 1: ", block["block_text"], block_type, block["page_idx"],
                                      len(group_buf), block["block_class"])
                                print("-" * 80)
                            block_idx = block_idx + 1
                            line_idx = line_idx + 1
                            group_buf = []
                            group_is_list = False
                            continue

                # Check the block type
                if block_type == "para" and \
                        (len(group_buf) > 2 or group_buf[0]['text'].lower().startswith("section ")):
                    buf_texts = []
                    block_types = []
                    # Do we have a multi line para which has huge gap, due to the ordering of p_tags from Tika
                    prev_vl = group_buf[0]
                    result_list = [[prev_vl]]
                    buf_text = prev_vl['text']
                    first_line_found = False
                    _, _, _, page_stats = self.page_styles[prev_vl['page_idx']]
                    min_left = prev_vl["box_style"][1]
                    max_right = prev_vl["box_style"][2]
                    for vl in group_buf[1:]:
                        if not vhu.compare_top(vl, prev_vl):
                            gap_bw_lines = round(vl["box_style"][0] -
                                                 (prev_vl["box_style"][0] + prev_vl["box_style"][4]), 1)
                            if vl["box_style"][1] > max_right and gap_bw_lines < 0:
                                min_left = vl["box_style"][1]
                                max_right = vl["box_style"][2]
                            if (not first_line_found) and \
                                    result_list[0][0]['text'].lower().startswith("section"):
                                # Check whether we have a first line starting with "Section " and
                                # if there are more than 1 VL and if the second VL has a mixed font, perform the split
                                result_list, buf_texts, block_types = \
                                    self.create_new_vl_group_for_sections(result_list, buf_texts, block_types)
                                if len(buf_texts) > 0:
                                    buf_text = buf_texts[-1]
                                    buf_texts.pop(-1)
                                first_line_found = True
                            if vl['page_idx'] != prev_vl['page_idx']:
                                _, _, _, page_stats = self.page_styles[vl['page_idx']]

                            def start_a_new_para():
                                prev_vl_ends_with_delim = ends_with_sentence_delimiter_pattern.search(prev_vl["text"])
                                if max_right > 0.3 * page_width and prev_vl["box_style"][2] < max_right and \
                                        min_left < vl["box_style"][1] and prev_vl_ends_with_delim is not None:
                                    return True
                                elif max_right > 0.35 * page_width and prev_vl["box_style"][2] < max_right and \
                                        min_left == vl["box_style"][1] and \
                                        prev_vl_ends_with_delim is not None and \
                                        abs(prev_vl["box_style"][2] - max_right) > (len(vl["text"]) *
                                                                                    vl["line_style"][5]):
                                    return True
                                return False
                            if (page_stats['most_frequent_space'] and
                                gap_bw_lines > -(5 * page_stats['most_frequent_space']) and
                                abs(gap_bw_lines) > 1.2 * page_stats['most_frequent_space'] and
                                prev_vl['page_idx'] == vl['page_idx']) or \
                                    start_a_new_para():
                                # 1.2 multiplier is just a magic number.
                                # Divide them to multiple blocks.
                                block_type, _ = get_block_type(False, False, buf_text)
                                block_types.append(block_type)
                                buf_texts.append(buf_text)
                                result_list.append([vl])
                                buf_text = vl['text']
                            else:
                                buf_text = buf_text + self.check_add_space_btw_texts(buf_text, vl['text']) + vl['text']
                                result_list[-1].append(vl)
                        else:
                            min_left = min(min_left, vl["box_style"][1])
                            max_right = max(max_right, vl["box_style"][2])
                            buf_text = buf_text + self.check_add_space_btw_texts(buf_text, vl['text']) + vl['text']
                            result_list[-1].append(vl)
                        prev_vl = vl
                    if len(group_buf) == 1 and group_buf[0]['text'].lower().startswith("section"):
                        result_list, buf_texts, block_types = \
                            self.create_new_vl_group_for_sections(result_list, buf_texts, block_types)
                    block_type, _ = get_block_type(False, False, buf_text)
                    buf_texts.append(buf_text)
                    block_types.append(block_type)
                    final_group_bufs = result_list

                for i, grp_buf in enumerate(final_group_bufs):
                    word_classes = []
                    for vl in grp_buf:
                        word_classes.extend(vl["word_classes"])
                    group_class_name = Counter(word_classes).most_common()[0][0]
                    block_type = block_types[i]
                    block_modified = False
                    block_class = group_class_name
                    if block_types[i] == "header_modified":
                        block_type = "header"
                        block_modified = True
                        block_class = grp_buf[0]['class']
                    elif block_types[i] == "header" and group_buf[0]['text'].lower().startswith("section"):
                        block_class = grp_buf[0]['class']
                    block = {
                        "block_idx": block_idx,
                        "page_idx": group_page_idx,
                        "block_type": block_type,
                        "block_text": str(buf_texts[i]),
                        # 'line_props': line_props,
                        "visual_lines": grp_buf,
                        "block_class": block_class,
                        "block_modified": block_modified
                    }
                    block_to_discard = False
                    if not prev_block_footer_discarded:
                        if block["block_type"] in ["para", "header"] and \
                                block['visual_lines'][0]['box_style'][0] > page_height - (footer_margin * page_height) \
                                and len(block["visual_lines"]) == 1 and \
                                len(block["visual_lines"][0]["line_parser"]["words"]) == 1:
                            block_to_discard = True
                    elif prev_discarded_block:
                        if block['visual_lines'][0]['box_style'][0] > \
                                prev_discarded_block['visual_lines'][0]['box_style'][0]:
                            block_to_discard = True
                    if block_to_discard:
                        prev_block_footer_discarded = True
                        prev_discarded_block = block
                        if LINE_DEBUG:
                            print("Discarding.....", block['block_text'])
                        if not line_idx and has_vl_from_prev_page:
                            vl_from_prev_page_discarded = True
                        continue
                    else:
                        prev_block_footer_discarded = False
                        prev_discarded_block = None
                    if LINE_DEBUG:
                        print(">>> adding block: ", str(buf_texts[i]), block_types[i], block["page_idx"],
                              len(grp_buf), group_is_table_row, group_is_list, block["block_class"])
                        print("-" * 80)
                    # blocks.append(block)
                    block['box_style'] = Doc.calc_block_span(block)
                    if len(block["visual_lines"]) < 4 and \
                            block["visual_lines"][0]["line_style"][1] == "italic" and \
                            self.detect_block_center_aligned(block):
                        block["block_type"] = "header"
                    if len(page_blocks) and block_types[i] == "table_row" and page_blocks[-1]["block_type"] == "para":
                        # don't attempt this if the block spans multiple lines
                        prev_multi_line = len(
                            set([prev_child_block['box_style'][0] for prev_child_block
                                 in page_blocks[-1]['visual_lines']]))
                        if prev_multi_line == 1:
                            convert_tr, cells, new_visual_lines = check_possible_table(page_blocks[-1], block)
                            if convert_tr:
                                page_blocks[-1]["block_type"] = "table_row"
                                # Don't set is_table_start, let the logic below take care of it.
                                # page_blocks[-1]['is_table_start'] = True
                                page_blocks[-1]['cell_values'] = cells
                                page_blocks[-1]['visual_lines'] = new_visual_lines
                    page_blocks.append(block)
                    block_idx = block_idx + 1

                group_is_list = is_list_start
                # after a group is written, reset table_group_state
                group_is_table_row = False

                #  group_buf = [line_info]
                if line_idx == len(visual_lines) - 1 and (not is_new_group or should_ignore):
                    group_buf = []
                else:
                    group_buf = [line_info]
                # Any mis parsed line from the top of the page.
                if line_idx == len(visual_lines) - 1 and len(group_buf) and \
                        len(page_blocks) > 0 and page_blocks[-1]["box_style"][0] > line_info['box_style'][0]:
                    # Create a block anyways here
                    block_type, _ = get_block_type(False, False, line_info["text"])
                    block = {
                        "block_idx": block_idx,
                        "page_idx": group_page_idx,
                        "block_type": block_type,
                        "block_text": str(line_info["text"]),
                        # 'line_props': line_props,
                        "visual_lines": group_buf,
                        "block_class": Counter(line_info["word_classes"]).most_common()[0][0],
                        "block_modified": False
                    }
                    block['box_style'] = Doc.calc_block_span(block)
                    page_blocks.append(block)
                    if LINE_DEBUG:
                        print(">>> adding block - 1: ", block["block_text"], block_type, block["page_idx"],
                              len(group_buf), block["block_class"])
                        print("-" * 80)
                    block_idx = block_idx + 1
                    group_buf = []
                # if is_list_start_separate_line:
                #     group_buf = []
            else:
                # print("adding to buf", line_info['text'])
                # deal with - at end of line in research papers e.g. implementation
                if len(group_buf) == 1 and group_is_list and group_is_table_row:
                    # We have only a single element in the group_buf, which was detected as a list item and
                    # the current line_info is a table row. Set group_is_list to False
                    group_is_list = False
                if not should_ignore:
                    group_buf.append(line_info)
                # is_table_row_list, group_is_table_row = self.detect_table_or_list(change_in_class, group_buf,
                #                                                                   group_is_list, group_is_table_row,
                #                                                                   is_list_start, line_info,
                #                                                                   prev_line_info, same_top)
            group_is_fake_row = False
            # prev_line_info = None if is_list_start_separate_line else line_info
            if not should_ignore:
                prev_line_info = line_info
            line_idx = line_idx + 1
        if prev_block_footer_discarded and len(page_blocks) > 0 and \
                ends_with_sentence_delimiter_pattern.search(page_blocks[-1]["block_text"]) is None:
            group_buf = page_blocks[-1]["visual_lines"]
            page_blocks = page_blocks[:-1]
        return page_blocks, group_buf, block_idx, group_is_list, vl_from_prev_page_discarded

    def detect_block_center_aligned(self, block, enable_width_check=True):
        center_location = block["box_style"][1] + block["box_style"][3] / 2
        center_aligned = abs(center_location - self.page_width / 2) < self.page_width * 0.015
        width_check = block["box_style"][3] * 2 < self.page_width
        return center_aligned and (width_check if enable_width_check else True)

    def detect_new_group(self,
                         line_idx, line_info, prev_line_info, group_buf, lp_line,
                         group_is_table_row, is_list_start, page_blocks):

        change_in_class, is_new_para, same_top = self.compare_with_previous_line(line_info,
                                                                                 prev_line_info,
                                                                                 group_buf,
                                                                                 group_is_table_row)

        is_table_row_list, is_table_row = self.detect_table_or_list(group_buf, group_is_table_row, line_info,
                                                                    prev_line_info, same_top, page_blocks)
        is_new_group = False
        # print("was group table row: ", group_is_table_row, same_top, is_table_row)
        if not group_is_table_row and is_table_row:
            group_is_table_row = True

            def different_group(vl):
                # vl_same_top = vhu.compare_top(line_info, vl)
                # return (not vhu.compare_top(line_info, vl)
                #         or vl["page_idx"] != line_info["page_idx"])
                return vl["page_idx"] != line_info["page_idx"]
                # return  not vl_same_top
            mismatches = list(filter(different_group, group_buf))
            n_mismatches = len(mismatches)
            if n_mismatches > 0 and len(group_buf) > 1:
                print(mismatches[0]['text'], "->", group_buf[n_mismatches]['text'])
                print("mismatch", n_mismatches, len(group_buf))
                diff = len(group_buf) - n_mismatches
                line_info = group_buf[n_mismatches]
                del group_buf[n_mismatches:]
                line_idx = line_idx - diff
                is_new_group = True
                prev_m = None
                group_is_table_row = False
                for m in mismatches:
                    if prev_m and vhu.compare_top(m, prev_m):
                        group_is_table_row = True
                        break
        elif group_is_table_row:
            # keep adding rows as blocks (same_top), don't bother about anything else
            is_new_group = (
                    not same_top  # a different table row
                    or prev_line_info["page_idx"] != line_info["page_idx"]  # change in page
                    # or not is_table_row # no longer a table row
            )
            if is_new_group and not same_top and not change_in_class:
                prev_line_bottom = prev_line_info["box_style"][0] + prev_line_info["box_style"][4]
                if line_info["box_style"][0] > prev_line_bottom and \
                        (line_info["box_style"][0] - prev_line_bottom <= 1.5 * prev_line_info["box_style"][4]) and \
                        (prev_line_info["box_style"][1] <= line_info["box_style"][1] < prev_line_info["box_style"][2]
                         and prev_line_info["box_style"][1] < line_info["box_style"][2] <=
                         prev_line_info["box_style"][2]):
                    prev_vl_center = prev_line_info["box_style"][1] + prev_line_info["box_style"][3] / 2
                    curr_vl_center = line_info["box_style"][1] + line_info["box_style"][3] / 2
                    if abs(curr_vl_center - prev_vl_center) <= 5 or \
                            prev_line_info["box_style"][1] == line_info["box_style"][1] or \
                            line_info["box_style"][2] == prev_line_info["box_style"][2]:
                        is_new_group = False
        else:
            top_diff = None
            if prev_line_info and prev_line_info["page_idx"] == line_info["page_idx"]:
                top_diff = line_info['box_style'][0] - prev_line_info["box_style"][0]
            is_new_group = (
                    ((not is_list_start) or
                     (is_list_start and top_diff and line_info['box_style'][4] <= top_diff))
                    and not same_top
                    and (not prev_line_info or (is_new_para or change_in_class))
            )
            # Tika Issue;We are on the same Visual Line and we cannot have a right before left.
            if not is_new_group and same_top and is_new_para and \
                    line_info['box_style'][1] < prev_line_info["box_style"][2]:
                is_new_group = True

        # a list is starting with just a bullet point, adjoining text appearing on different line
        is_list_start_separate_line = (
            (lp_line.length == 1 and lp_line.is_list_item and not (group_is_table_row and same_top))
            or ((lp_line.is_list_item or lp_line.numbered_line) and not (group_is_table_row and same_top))
            # or (lp_line.numbered_line and not (group_is_table_row and same_top))
            or (lp_line.length < 6 and lp_line.numbered_line and not same_top)
        ) and not same_top
        # If there are previous VL in the same line as the detected list item,
        # and if its a justified block, may be tika is giving the each word as a tag
        # and thus resulting in getting identified as list item.
        if is_list_start_separate_line and lp_line.length == 1 and same_top and len(group_buf) > 1:
            gap, n_gap, _, is_justified = self.get_gaps_from_vls(line_info, prev_line_info)
            if gap < n_gap and is_justified:
                is_list_start_separate_line = False
        out_of_order_list = False
        if prev_line_info:
            prev_list_start_separate_line = (
                    prev_line_info and ((len(prev_line_info['text']) == 1 and self.is_list_item(prev_line_info)) or
                                        (
                                            is_list_start
                                            and not same_top
                                            and (prev_line_info["lp_line"].is_list_item or
                                                 prev_line_info["lp_line"].numbered_line)
                                        ))
            )
            out_of_order_list = (prev_list_start_separate_line
                                 and line_info['box_style'][0] < prev_line_info['box_style'][0])
            out_of_order_list = out_of_order_list or (prev_list_start_separate_line and
                                                      not number_in_braces_pattern.sub("", line_info["text"]))
        # out_of_order_list = False
        # a list is starting with bullet point appearing before line in the same text block
        is_list_start_same_line = (
            (lp_line.length > 3 and self.is_list_item(line_info))
            or (lp_line.length < 6 and lp_line.numbered_line and not same_top)
        )
        line_start_idx = 0
        if is_list_start_same_line:
            if len(line_info["word_classes"]) > 1:
                line_start_idx = 1
            line_info["text"] = line_info["text"][line_start_idx:]
        is_list_start = is_list_start_same_line or is_list_start_separate_line
        if is_list_start and same_top and len(group_buf) > 1 and not is_new_para:
            gap = (line_info["box_style"][1] - prev_line_info["box_style"][2])
            if gap < line_info['line_style'][5] * 3:
                is_list_start = False
                if LINE_DEBUG:
                    print("Not a list start --->", line_info['text'])
        if out_of_order_list:
            is_list_start = False
        # is_list_end = len(blocks) > 1 and blocks[-1]['block_type'] == 'list_item' and not is_list_start
        is_new_group = ((is_new_group or is_list_start or out_of_order_list)
                        and 'is_superscript' not in line_info
                        and 'follows_superscript' not in line_info
                        )
        if is_new_group:
            if LINE_DEBUG:
                print("new group at--->", line_info['text'])
        is_mixed_font = (
                line_info["word_classes"][line_start_idx]
                != line_info["word_classes"][-1]
        )
        # do mixed font in tika
        if is_mixed_font and MIXED_FONT_DEBUG:
            print(line_info['text'])
            print(line_info['word_classes'])

        if LINE_DEBUG:
            debug_info = {
                'line_idx': line_idx,
                'group_buf': len(group_buf),
                'new_group': is_new_group,
                'new_para': is_new_para,
                'same_top': same_top,
                'class_change': change_in_class,
                'list_start': is_list_start,
                'is_table_row': group_is_table_row,
                'is_mixed_font': is_mixed_font,
                'text': line_info['text']
            }
            if out_of_order_list:
                print("& ool")
            print(", ".join(f"{key}:{value}" for key, value in debug_info.items()))
            print("=" * 80)

        return is_list_start, is_list_start_separate_line, \
               is_mixed_font, group_is_table_row, \
               is_new_group, line_idx, prev_line_info, line_info

    def count_possible_cells(self, group_buf):
        if group_buf[0]['line_parser']['numbered_line'] or group_buf[0]['line_parser']['numbered_line']:
            return 0
        prev_vl = group_buf[0]
        n_cells = 0
        for vl in group_buf[1:]:
            gap, normal_gap, _, _ = self.get_gaps_from_vls(vl, prev_vl)
            if gap > normal_gap:
                n_cells = n_cells + 1
            prev_vl = vl
        return n_cells

    def detect_table_or_list(self, group_buf, group_is_table_row,
                             line_info, prev_line_info, same_top, page_blocks):
        is_list = False
        is_table_row = False
        if same_top:
            # to prevent repeated calculation for each cell in a row
            # if the words (line info with same_top) are spaced apart by more than space of a width
            gap, normal_gap, act_normal_gap, _ = self.get_gaps_from_vls(line_info, prev_line_info)

            if not group_is_table_row:
                if gap > normal_gap or ("changed" in prev_line_info and prev_line_info["changed"]):
                    opt_cond = (gap < 4 * normal_gap)
                    _, page_width, _, _ = self.page_styles[line_info['page_idx']]
                    if line_info["line_style"][2] > 9 or line_info["box_style"][3] > 0.5 * page_width:
                        opt_cond = (gap < 6 * normal_gap)
                    # Make the gap check conditional if we are dealing with numbers.
                    opt_cond = opt_cond and not (line_info['line_parser']["word_count"] == 1 and
                                                 line_info['line_parser']["last_word_number"])
                    if (((group_buf[-1]['line_parser']['numbered_line'] and
                          not group_buf[-1]['line_parser']['is_table_row']) or
                        group_buf[0]['line_parser']['numbered_line'] or self.is_list_item(group_buf[0]))
                            and opt_cond):
                    # if (group_buf[0]['text'].startswith("(")
                    #         and ")" in group_buf[0]['text']
                    #         and group_buf[0]['line_parser']['numbered_line']):
                        is_list = True
                    elif line_info['text'][0] not in line_parser.continuing_chars:
                        # print("table start buf -------")
                        # for idx, gb in enumerate(group_buf):
                        #     print(">>>>", gb['text'], gb['line_parser']['numbered_line'])
                        # print("end buf -------")
                        is_table_row = True
                        if len(group_buf) > 1:
                            if (not vhu.compare_top(group_buf[-1], group_buf[-2])) and \
                                    prev_line_info['text'][-1] in ["."]:
                                # We have a multi line data here. If the previous VL is ending with '.', consider
                                # it not a table row.
                                is_table_row = False
                            if is_table_row and not vhu.compare_top(group_buf[0], line_info):
                                buf0_bstyle = group_buf[0]['box_style']
                                prev_buf_bstyle = group_buf[-1]['box_style']
                                buf_bstyle = line_info['box_style']
                                if len(list(range(max(int(buf0_bstyle[1]), int(buf_bstyle[1])),
                                                  min(int(buf0_bstyle[2]), int(buf_bstyle[2]))+1))) \
                                        >= 0.4 * (int(buf_bstyle[2]) - int(buf_bstyle[1])) and \
                                        list(range(max(int(buf0_bstyle[1]), int(prev_buf_bstyle[1])),
                                                   min(int(buf0_bstyle[2]), int(prev_buf_bstyle[2]))+1)):
                                    # Mark as not a table_row if the first VL is more than
                                    # 40% the length of the current VL
                                    is_table_row = False
                            # If its still a table_row and parser is giving one word @ a time from
                            # TIKA (center-aligned text) and if previous detected block is not a table_row.
                            if is_table_row and \
                                    (len(prev_line_info["line_parser"]["words"]) ==
                                     len(line_info["line_parser"]["words"]) == 1) \
                                    and gap <= line_info["line_style"][5] * 4:
                                do_continue = True
                                if len(page_blocks) and page_blocks[-1]["block_type"] == "table_row":
                                    do_continue = False
                                elif (not line_info["text"].isalnum() and len(line_info["text"]) == 1) or \
                                        (not prev_line_info["text"].isalnum() and len(prev_line_info["text"]) == 1):
                                    do_continue = False
                                if do_continue:
                                    # Prev vl has same top with the current vl, so we can continue with the group_buf
                                    _, spaces = vhu.get_avg_space_bw_multi_line_vls(group_buf)
                                    if len(spaces) > 1 and spaces[-1] <= max(spaces[:-1]):
                                        # Not enough space between vl and other lines in the group buf?
                                        is_table_row = False

                        if is_table_row and (group_buf[0]['text'].lower().startswith("section") or
                                             group_buf[0]['text'].startswith("Item")) and \
                                ((prev_line_info['text'][-1] in line_parser.continuing_chars and
                                  (line_info['text'][-1] in line_parser.continuing_chars or
                                   (prev_line_info['text'].lower().startswith("section") and
                                    prev_line_info['word_classes'][-1] == line_info['word_classes'][0]))) or
                                 (group_buf[0]['word_classes'][0] != line_info['word_classes'][0])):
                            is_table_row = False
                        elif is_table_row and group_buf[0]['text'].lower().startswith("section") and \
                                section_num_pattern.search(prev_line_info["text"].strip().split()[-1]) is not None:
                            # The last part of the text is like 1.1 and
                            # then there is a gap between the number and section heading
                            is_table_row = False
                elif len(page_blocks) > 0 and \
                        page_blocks[-1]["block_type"] == "table_row" and \
                        gap > act_normal_gap and \
                        gap > 0.5 * normal_gap and \
                        len(page_blocks[-1]["visual_lines"]) >= len(group_buf) + 1:
                    # If the previous block is a table_row and if there is a considerable gap between VLs,
                    # consider it a table_row, provided there are no overlaps between the VLs
                    g_buf_vls = group_buf + [line_info] if group_buf else [line_info]
                    do_overlap = False
                    for v_idx, vls in enumerate(page_blocks[-1]["visual_lines"][:len(g_buf_vls)]):
                        if v_idx < len(g_buf_vls) - 1:
                            if g_buf_vls[v_idx]["box_style"][2] > \
                                    page_blocks[-1]["visual_lines"][v_idx + 1]["box_style"][1]:
                                do_overlap = True
                                break
                        else:
                            if g_buf_vls[v_idx]["box_style"][1] < \
                                    page_blocks[-1]["visual_lines"][v_idx - 1]["box_style"][2]:
                                do_overlap = True
                                break
                    if not do_overlap:
                        is_table_row = True
                    if is_table_row and ((group_buf[-1]['line_parser']['numbered_line'] and
                                          not group_buf[-1]['line_parser']['is_table_row']) or
                                         group_buf[0]['line_parser']['numbered_line'] or
                                         self.is_list_item(group_buf[0])):
                        last_blk_bottom = page_blocks[-1]['box_style'][0] + page_blocks[-1]['box_style'][4]
                        if (line_info["box_style"][0] - last_blk_bottom) > 1.5 * page_blocks[-1]['box_style'][4]:
                            is_table_row = False
                            is_list = True
            if LINE_DEBUG:
                print(f"gap: {gap}, normal: {normal_gap}, is_table_cell: {is_table_row} "
                      f"is_list: {is_list} {group_buf[0]['text']} -> {group_buf[0]['line_parser']['numbered_line']}")
                print("\t", "curr:", line_info['text'][0:40], "prev:", prev_line_info['text'][0:40])
        # group_buf.append(line_info)
        return is_list, is_table_row

    def compare_with_previous_line(self, line_info, prev_line_info, block_buf, group_is_table_row):
        line_style = line_info['line_style']
        box_style = line_info['box_style']
        same_top = False
        is_superscript = False
        follows_superscript = False
        top_difference = 0
        prev_line_ends_with_line_delim = False
        _, page_width, page_height, page_stats = self.page_styles[line_info['page_idx']]
        if prev_line_info:
            prev_line_ends_with_line_delim = \
                ends_with_sentence_delimiter_pattern.search(prev_line_info["text"]) is not None
        if (
                prev_line_info
                and prev_line_info["page_idx"] == line_info["page_idx"]
        ):
            line_info["space"] = (
                    round(line_info["box_style"][0] - prev_line_info["box_style"][0], 1)
            )
            # these are table columns
            # if class_name == 'cls_26' and line_info['space'] < 0:
            # print(line_info['box_style'].top, prev_line_info['box_style'], prev_line_info['text'])
            same_top = vhu.compare_top(line_info, prev_line_info)
            same_left_align = abs(line_info['box_style'][1] - prev_line_info['box_style'][1]) < 5
            gap_bw_prev_line = line_info['box_style'][0] - \
                               (prev_line_info['box_style'][0] + prev_line_info['box_style'][4])
            if not same_top and ((line_info["space"] < 0 and
                                  prev_line_info['line_style'] != line_style) or
                                 (group_is_table_row and prev_line_info["lp_line"].word_count < 10)):
                # If we don't have the same top with previous line. check with the other VL from block_buf, if any
                for vl in block_buf[-1::-1]:
                    act_top_diff = line_info['box_style'][0] - vl['box_style'][0]
                    top_diff = abs(act_top_diff)
                    gap_bw_lines = (line_info['box_style'][0] + line_info['box_style'][4]) - vl['box_style'][0]
                    if top_diff <= 2 or (page_stats['most_frequent_space'] and
                                         abs(gap_bw_lines) <= (1.2 * page_stats['most_frequent_space'])) or \
                            (vl['box_style'][0] <= line_info['box_style'][0] <=
                             vl['box_style'][0] + vl['box_style'][4]):
                        # The part after "or" deals with the case when we have a group_is_table_row and
                        # we are dealing with a possible multi-line cell value? Check for intersection points.

                        # If the previous line is above the current line, check for intersection.
                        # Else, check right of the previous line is less than the left of the current line
                        same_top = vhu.compare_top(line_info, vl) or (
                                (vl['box_style'][4] <= line_info['box_style'][4]) and
                                ((line_info["space"] >= 0 and
                                  len(list(range(max(int(vl['box_style'][1]), int(line_info['box_style'][1])),
                                                 min(int(vl['box_style'][2]), int(line_info['box_style'][2]))+1))) > 0)
                                 or
                                 (line_info["space"] < 0 and block_buf[0]['box_style'][2] < line_info['box_style'][1]))
                        )
                        if same_top or top_diff <= 2:
                            if same_top and (group_is_table_row and
                                             block_buf[0]['box_style'][2] > line_info['box_style'][1]):
                                same_top = False
                            break
                    elif group_is_table_row and same_left_align and gap_bw_prev_line > 0:
                        if vl["box_style"][1] - line_info["box_style"][1] < -5 and \
                                line_info["box_style"][0] - (vl["box_style"][0] + vl["box_style"][4]) < \
                                1.5 * gap_bw_prev_line:
                            same_top = True
                            break

            min_top = block_buf[0]["box_style"][0]
            max_top = block_buf[0]["box_style"][0]
            max_top_vl = block_buf[0]
            for vl in block_buf[1:]:
                if vl["box_style"][0] > max_top:
                    max_top = vl["box_style"][0]
                    max_top_vl = vl
                if vl["box_style"][0] < min_top:
                    min_top = vl["box_style"][0]
            
            if not same_top and group_is_table_row and min_top < box_style[0] < max_top:
                same_top = True
            # if not same_top and line_info["space"] < 0 and not group_is_table_row:
            #     first_vl_top = block_buf[0]["box_style"][0]
            #     last_vl_bottom = block_buf[-1]["box_style"][0] + block_buf[-1]["box_style"][4]
            #     if first_vl_top != block_buf[-1]["box_style"][0] and last_vl_bottom > first_vl_top:
            #         if first_vl_top < line_info['box_style'][0] < last_vl_bottom:
            #             same_top = True
            # top_difference = abs(prev_line_info["box_style"].top - line_info['box_style'].top)
            top_difference = prev_line_info["box_style"][0] - line_info['box_style'][0]
            # Consider max_top as a decider only if we are dealing within the same page.
            if max_top > prev_line_info["box_style"][0] and max_top_vl['page_idx'] == prev_line_info['page_idx']:
                top_difference = max_top - line_info['box_style'][0]
            small_gap = (line_info['box_style'][1] - prev_line_info["box_style"][2]) < 10
            super_script_height = 0.10 * prev_line_info["box_style"][4] < top_difference < \
                                  1.0 * prev_line_info["box_style"][4]
            is_superscript = small_gap and super_script_height

            if is_superscript:
                # print("line is superscript: ", line_info["text"], "-->", prev_line_info["text"])
                line_info['is_superscript'] = True
            if "is_superscript" in prev_line_info:
                follows_superscript = 1.0 * prev_line_info["box_style"][4] < top_difference < 1.1 * prev_line_info["box_style"][4]
            if follows_superscript:
                line_info['follows_superscript'] = True

            # same_top = 0 <= line_info["space"] <= 0.01
            # print(line_info['text'], line_info['space'])
        else:
            # todo - determine if the margin is available
            line_info['space'] = 0.0
        # do not do this for the very first line of page
        # space_diff = line_info['space'] - prev_line_info['space']
        is_new_para = False
        change_in_class = False
        new_page_para = False
        if prev_line_info:
            prev_line_style = prev_line_info['line_style']
            change_in_class = (
                    prev_line_info["word_classes"][-1] not in line_info["word_classes"][:3]
                    and not is_superscript
                    and not follows_superscript
            )

            if change_in_class and len(prev_line_info["word_classes"]) == 1 and len(block_buf) > 1:
                grp_buf_word_classes = [wc for li in block_buf for wc in li["word_classes"]]
                group_class_name = block_buf[-2]["word_classes"][-1]
                w_class_to_check = line_info["word_classes"][:3]
                cond_for_single_word_vls = True
                if len(block_buf) == len(grp_buf_word_classes):
                    # We are dealing with individual word Visual lines
                    group_class_name = Counter(grp_buf_word_classes).most_common()[0][0]
                    if len(w_class_to_check) == 1:
                        # Check with the previous visual lines
                        cond_for_single_word_vls = w_class_to_check not in grp_buf_word_classes[-3:]
                change_in_class = (group_class_name not in w_class_to_check) and cond_for_single_word_vls
            if change_in_class and (line_info['page_idx'] != prev_line_info['page_idx'] or not same_top) and \
                    not prev_line_ends_with_line_delim and Doc.soft_line_style_check(line_info, prev_line_info):
                change_in_class = False
            if not change_in_class:
                if line_info['page_idx'] != prev_line_info['page_idx']:
                    if prev_line_ends_with_line_delim or line_info["lp_line"].numbered_line or \
                            (abs(prev_line_info["box_style"][1] - line_info["box_style"][1]) < 10 and
                             prev_line_info["box_style"][2] < 0.4 * page_width) or \
                            (prev_line_info["lp_line"].roman_numbered_line and
                             len(prev_line_info["lp_line"].words) == 1) or \
                            self.detect_block_center_aligned(line_info) or \
                            self.detect_block_center_aligned(prev_line_info):
                        is_new_para = True
                        new_page_para = True
                else:
                    has_more_space = (
                        # line_info['space'] > line_height_threshold * line_style[2]
                        # or
                        line_style not in self.line_style_space_stats
                        or
                        line_info['space'] > 1.1*self.line_style_space_stats[line_style]['most_frequent_space']
                        or
                        (line_info['space'] < 0 and not is_superscript)
                    )
                    if has_more_space and line_style not in self.line_style_space_stats and \
                            prev_line_style in self.line_style_space_stats:
                        # Allow some consideration. If there are no occurrences of line_style in line_style_space_stats,
                        # May be, its that we don't have continuous same line_style
                        has_more_space = False
                    elif has_more_space and line_style not in self.line_style_space_stats and \
                            prev_line_style not in self.line_style_space_stats:
                        act_space_bw_lines = line_info["box_style"][0] - \
                                             (prev_line_info["box_style"][0] + prev_line_info["box_style"][4])
                        if 0 < act_space_bw_lines < line_style[2] and act_space_bw_lines < prev_line_style[2]:
                            has_more_space = False
                        elif same_top:
                            has_more_space = False
                        elif act_space_bw_lines < 1.5 * prev_line_style[2]:
                            has_more_space = False
                    # if has_more_space:
                    #     print("oops ----", line_info['space'],
                    #           1.1*self.line_style_space_stats[line_style]['most_frequent_space']
                    #           if line_style in self.line_style_space_stats else "NA")
                    left_shift_threshold = 200
                    # if both the start line and current line are starting in the first quadrant, reduce the threshold
                    half_page_width = 0.5 * page_width
                    left_to_compare_with = block_buf[0]['box_style'][1]
                    if not same_top:
                        last_top = block_buf[-1]['box_style'][0]
                        for blk in block_buf[::-1]:
                            if last_top != blk['box_style'][0]:
                                break
                            left_to_compare_with = min(left_to_compare_with, blk['box_style'][1])
                    if left_to_compare_with > half_page_width and box_style[1] > half_page_width:
                        left_shift_threshold = 80
                    shifts_left = left_to_compare_with - box_style[1] > left_shift_threshold
                    # Check all the previous Visual Lines are of the same top and is of "name" type

                    top_diff_decider = prev_line_ends_with_line_delim or line_info["lp_line"].numbered_line or \
                                       self.detect_block_center_aligned(prev_line_info) or \
                                       self.detect_block_center_aligned(line_info)
                    font_size = line_info["line_style"][2]
                    if line_info["line_style"][2] > prev_line_info["line_style"][2]:
                        font_size = prev_line_info["line_style"][2]
                    font_size_decider = font_size * (1.8 if top_diff_decider else 2.0)
                    high_top_difference = abs(top_difference) > font_size_decider
                    if high_top_difference and round(abs(top_difference)) == round(font_size_decider) and \
                            abs(top_difference) - font_size_decider <= 0.25:
                        high_top_difference = False
                    if not high_top_difference and line_info["lp_line"].numbered_line and \
                            prev_line_ends_with_line_delim:
                        high_top_difference = abs(top_difference) > line_info["line_style"][2] * 1.5
                    first_vl_numbered_line = False
                    if block_buf[0] and block_buf[0].get("lp_line", None):
                        first_vl_numbered_line = block_buf[0]["lp_line"].numbered_line
                    if shifts_left and first_vl_numbered_line:
                        shifts_left = shifts_left and prev_line_ends_with_line_delim
                    if shifts_left and block_buf[0]:
                        buf_text = block_buf[0]['text']
                        for vl in block_buf[1:]:
                            buf_text = buf_text + self.check_add_space_btw_texts(buf_text, vl["text"]) + vl["text"]
                        if buf_text:
                            lp_json = line_parser.Line(buf_text).to_json()
                            if lp_json['numbered_line'] and not prev_line_ends_with_line_delim\
                                    and not high_top_difference:
                                shifts_left = False
                    is_new_para = has_more_space or shifts_left or high_top_difference or \
                                  (self.detect_block_center_aligned(prev_line_info) and
                                   not self.detect_block_center_aligned(line_info))
                    if is_new_para and has_more_space and high_top_difference and line_info['space'] < 0 and \
                            abs(line_info['space']) > 0.5 * page_height and not prev_line_ends_with_line_delim:
                        # We might be dealing with a new column data
                        is_new_para = False
                    if not is_new_para and first_vl_numbered_line and \
                            line_info["lp_line"].numbered_line \
                            and (abs(top_difference) > (line_info["line_style"].font_size * 1.5)):
                        is_new_para = True
                    # If both the lines are numbered items and are in different lines
                    if not is_new_para and not same_top and line_info["lp_line"].numbered_line and\
                            prev_line_info["lp_line"].numbered_line and prev_line_style == line_info["line_style"]:
                        is_new_para = True
                    if is_new_para and not has_more_space and high_top_difference and \
                            not prev_line_ends_with_line_delim and \
                            abs(prev_line_info["box_style"][1] - line_info["box_style"][1]) < 5 and \
                            line_info["box_style"][0] - (prev_line_info["box_style"][0] +
                                                         prev_line_info["box_style"][4]) < font_size_decider:
                        is_new_para = False
                    # If there is considerable right shift and not of same top, consider a new para.
                    if is_new_para and LINE_DEBUG:
                        print(f'setting new para: space: {has_more_space}, shifts: {shifts_left}, '
                              f'top_difference: {high_top_difference}')
                    if not is_new_para and not group_is_table_row and not same_top and top_difference < 0 \
                            and box_style[1] - prev_line_info['box_style'][1] > left_shift_threshold:
                        is_new_para = True
                    if not is_new_para:
                        # if this is a new line
                        if line_info['box_style'][0] > prev_line_info['box_style'][0] + prev_line_info['box_style'][4]:
                            buf_text_all_caps = all([b["text"].isupper() for b in block_buf])
                            prev_text_all_nouns = all(word["is_noun"] for word in
                                                      prev_line_info.get("line_parser", {'words': []}).get('words', []))
                            # if all of the previous line was all caps and current line is not all caps, then
                            # previous line is a header
                            if buf_text_all_caps and not line_info["text"].isupper() and not prev_text_all_nouns:
                                is_new_para = True

                    # if shifts_left:
                    #     print("---")
                    #     print(prev_line_info['text'], prev_line_info['box_style'].left)
                    #     print(line_info['text'], line_info['box_style'].left)
                    #     print("---")
            else:
                if LINE_DEBUG:
                    print('old class: ', prev_line_info["word_classes"], prev_line_info['line_style'])
                    print('new class: ', line_info["word_classes"], line_info["line_style"])
            if LINE_DEBUG:
                print('space: ', round(line_info['space'], 2),
                      'font size: ', line_style[2],
                      f', new para: {is_new_para}',
                      f', new page para: {new_page_para}',
                      f', change_in_class: {change_in_class}'
                      f', same_top: {same_top}')

            if line_style in self.line_style_word_stats and prev_line_style:
                line_word_stats = self.line_style_word_stats[line_style]
                is_justified = line_word_stats["is_justified"]
                if (is_justified
                        and prev_line_style[2] == line_style[2]
                        and not is_new_para):
                    change_in_class = change_in_class
            # if is_justified and line_style not in self.line_style_space_stats and not change_in_class:
            #     has_more_space = has_more_space  # False
            # else:


    #     print(">>> superscript", line_info['text'], is_superscript, follows_superscript, change_in_class)
    #     merge_vls_if_needed
        return change_in_class, is_new_para, same_top

    def should_ignore_line(self, all_p, is_page_footer, is_page_header, last_line_counts, line_idx, loc_key, lp_line, p,
                           page_footers, page_headers, page_idx, box_style, page_visual_lines):
        if box_style[4] < 1:    # Really small text
            return True, False
        if line_idx > len(all_p) - 2 or line_idx < 2:
            num_only = not_a_number_pattern.sub("", p.text).strip()
            do_ignore = True
            if line_idx < 2:
                remove_whole_numbers = integer_pattern.sub("", p.text).strip()
                if (len(remove_whole_numbers) == len(p.text) or not p.text.lower().startswith("page")) \
                        and lp_line.word_count > 1:
                    do_ignore = False
            if 0 < len(num_only) < 4 and lp_line.alpha_count < 2 and not lp_line.dot_numbered_line and do_ignore:
                return True, False
            else:
                text_only = text_only_pattern.sub("", p.text).strip()
                if text_only in last_line_counts and last_line_counts[text_only] > 2 and \
                        not lp_line.last_word_is_stop_word and line_idx > len(all_p) - 2:
                    return True, False
        if p.text:
            if p.text.startswith("Source:"):
                return True, False
            elif not len(single_char_pattern.sub("", p.text).strip()) and box_style[1] < 5:
                #  Get rid of single letter text, which might be a water mark
                return True, False
        ignore, ignore_all_after = self.should_ignore(
            p.text, "header" if lp_line.is_header else None,
        )
        if ignore:
            return True, False
        if ignore_all_after:
            # fix this
            return True, False
        if is_page_header and loc_key in page_headers:
            do_continue = True
            if len(page_visual_lines) > 0:
                # Sort using top
                sorted_vls = sorted(page_visual_lines, key=lambda vl: vl['box_style'][0])
                if sorted_vls[0]['box_style'][0] < box_style[0]:  # Check top
                    # We have added a VL before this to the group, so don't discard this Header.
                    do_continue = False
            if do_continue:
                page_idxs = page_headers[loc_key]
                if len(page_idxs) > 1 and page_idx > 0 and page_idx in page_idxs and not lp_line.dot_numbered_line:
                    if HF_DEBUG:
                        print(f"skipping header : {p.text}, {loc_key}, {page_idxs}")
                    return True, False
        elif is_page_footer and loc_key in page_footers and not lp_line.dot_numbered_line:
            page_idxs = page_footers[loc_key]
            if len(page_idxs) > 1:
                if HF_DEBUG:
                    print(f"skipping footer : {p.text}, {loc_key}")
                return True, False
        if box_style[4] < 1:  # Check height
            # We are referring to some really small text here.
            if LINE_DEBUG:
                print(f"Ignoring really small line {p.text}.. ", box_style)
            return True, False
        if p.text in filter_out_pattern_list:
            return False, True
        else:
            return False, False

    def is_list_item(self, line_info):
        lp = line_info['line_parser']
        # return lp['is_list_item'] or lp['numbered_line']
        return 'is_list_item' in lp and lp['is_list_item']
        # return ((lp['numbered_line'] and
        #         not line_info['line_style'] in self.header_styles)
        #         or lp['is_list_item'])

    def save_file_stats(self):
        all_font_sizes = []
        header_block_line_styles = []
        for block in self.blocks:
            header_block_type = block["block_type"] == "header"
            first_vl_line_style = block["visual_lines"][0]["line_style"]
            all_font_sizes.append(first_vl_line_style[2])
            for line in block["visual_lines"][1:]:
                all_font_sizes.append(line["line_style"][2])
                if header_block_type and first_vl_line_style == line["line_style"] \
                        and line["line_style"] not in header_block_line_styles:
                    header_block_line_styles.append(line["line_style"])

        keys_by_size = sorted(
            self.line_style_classes.keys(), key=lambda x: x[2], reverse=True,
        )
        font_sizes = []
        new_header_line_styles = []
        total_num_lines = 0
        for line_style in keys_by_size:
            class_name = self.line_style_classes[line_style]
            if class_name in self.class_stats:
                stats = self.class_stats[class_name]
                font_sizes.append(line_style[2])
                total_num_lines += stats.get('n_lines', 0)
                # print(class_name, line_style[2], stats['avg_space'], stats['n_lines'], stats['n_groups'])

            for header_ls in header_block_line_styles:
                if header_ls != line_style and header_ls[1:] == line_style[1:] and \
                        line_style not in new_header_line_styles and \
                        self.class_stats.get(self.line_style_classes[line_style], False):
                    stats = self.class_stats[self.line_style_classes[line_style]]
                    text_with_sentence_delimiter = False
                    for text in stats.get("texts", []):
                        if ends_with_sentence_delimiter_pattern.search(text) is not None:
                            text_with_sentence_delimiter = True
                            break
                    if not text_with_sentence_delimiter:
                        new_header_line_styles.append(line_style)
                        break
        header_block_line_styles.extend(new_header_line_styles)

        avg_font_size = np.mean(font_sizes)
        mode_font_size = max(set(all_font_sizes), key=all_font_sizes.count) if len(all_font_sizes) > 0 else 0
        median_font_size = np.median(font_sizes)
        font_size_sd = np.std(font_sizes)
        self.header_styles = []
        self.normal_styles = []
        self.footnote_styles = []
        cutoff_lower = median_font_size  # avg_font_size - font_size_sd
        cutoff_higher = avg_font_size + 0.25*font_size_sd
        for line_style in keys_by_size:
            # if line_style[2] > cutoff_higher or line_style[3] > 400:
            if (line_style[2] > mode_font_size or line_style[3] > 400) or \
                    (self.line_style_classes[line_style] in self.class_stats and
                     self.class_stats[self.line_style_classes[line_style]].get('n_lines', 0) < 0.75 * total_num_lines
                     and line_style in header_block_line_styles):
                self.header_styles.append(line_style)
            elif line_style[2] < cutoff_lower:
                self.footnote_styles.append(line_style)
            else:
                self.normal_styles.append(line_style)
        self.file_stats = {
            "font_size": {
                "avg": avg_font_size,
                "sd": font_size_sd,
                "median": median_font_size,
                "band": [avg_font_size - font_size_sd, avg_font_size + font_size_sd],
            },
        }

        class_by_freq = sorted(self.class_stats.items(), key=lambda x: len(x[1]['texts']), reverse=True)
        # parsed_doc.class_stats
        class_freq_order = {}
        class_line_counts = []
        for idx, (class_name, stat) in enumerate(class_by_freq):
            class_freq_order[class_name] = idx
            class_line_counts.append(len(stat['texts']))
        para_classes = set()
        lc_mean = np.mean(class_line_counts)
        lc_sd = np.std(class_line_counts)
        for idx, lc in enumerate(class_line_counts):
            if lc > lc_mean + 2 * lc_sd:
                para_classes.add(class_by_freq[idx][0])
        self.para_classes = para_classes
        self.class_freq_order = class_freq_order

    def split_line(self, line_info):
        split_point = 0
        word_classes = line_info["word_classes"]
        first_word_class = word_classes[0]
        normal_word_class = None
        for word_class in word_classes:
            if word_class == first_word_class:
                split_point += 1
            else:
                normal_word_class = word_class
                break
        words = line_info["text"].split()
        header_text = " ".join(words[0:split_point])
        normal_text = " ".join(words[split_point:])
        header_line_info = {
            "box_style": line_info["box_style"],
            "line_style": self.class_line_styles[first_word_class],
            "class": first_word_class,
            "text": header_text,
            "word_classes": word_classes[0:split_point],
            "space": line_info["space"],
            "page_idx": line_info["page_idx"],
            "line_parser": line_parser.Line(header_text).to_json()
        }
        normal_line_info = {
            "box_style": line_info["box_style"],
            "line_style": self.class_line_styles[normal_word_class],
            "class": normal_word_class,
            "word_classes": word_classes[split_point:],
            "space": line_info["space"],
            "text": normal_text,
            "page_idx": line_info["page_idx"],
            "line_parser": line_parser.Line(normal_text).to_json()
        }
        return header_line_info, normal_line_info

    def get_class(self, line_style):

        def cmp_with_keys():
            for key in self.line_style_classes:
                if line_style[0] == key[0] \
                        and line_style[1] == key[1] \
                        and line_style[2] == key[2] \
                        and line_style[3] == key[3] \
                        and line_style[4] == key[4] \
                        and abs(line_style[5] - key[5]) < 1.0 \
                        and line_style[6] == key[6]:
                    return True, key
            return False, None

        style_present, match_line_style = cmp_with_keys()
        if style_present:
            class_name = self.line_style_classes[match_line_style]
            self.line_style_classes[line_style] = class_name
        else:
            class_name = f"cls_{len(self.line_style_classes.keys())}"
            self.line_style_classes[line_style] = class_name
            self.class_line_styles[class_name] = line_style
        return class_name

    def make_header_class(self, line_style):
        if line_style in self.header_styles:
            return self.line_style_classes[line_style]
        else:
            cloned_style = LineStyle(
                line_style[0],
                'italic',
                line_style[2],
                600,
                'none',
                'left'
            )

            if cloned_style in self.header_styles:
                return self.line_style_classes[cloned_style]
            else:
                class_name = f"cls_{len(self.line_style_classes.keys())}"
                self.line_style_classes[cloned_style] = class_name
                self.class_line_styles[class_name] = cloned_style
                self.header_styles.append(cloned_style)
                return self.line_style_classes[cloned_style]

    def merge_vls_if_needed(self, vls, is_table_row=False):
        good_vl = []
        prev_vl = vls[0]
        row_count = 1
        # Check are we spanning multi rows?
        cols_count = vhu.count_cols(vls)
        multi_row = False
        avg_merge_gap = 0
        normal_gap = 0
        # Initialize Maximum merge gap to 5 spaces
        max_merge_gap = prev_vl["line_style"][5] * 5
        gap_bw_vls = []
        if cols_count != len(vls):
            multi_row = True
        prev_vl_merged = False
        # Because of justified TEXT, TIKA might give a single word in a tag and
        # we might be tricked to believe that each is a table cell
        vls_has_single_words = False
        if is_table_row:
            vls_has_single_words = True
            for vl in vls[1:]:
                if "line_parser" in vl:
                    vls_has_single_words = vls_has_single_words and (len(vl["line_parser"]["words"]) == 1)
                    if not vls_has_single_words:
                        break
        for vl_id, vl in enumerate(vls[1:]):
            top_gap = vl['box_style'][0] - prev_vl['box_style'][0]
            # Added Bottom gap to cater to the cases when prev_vl
            # is already a merged one from the previous iteration.
            bottom_gap = (vl['box_style'][0] + vl['box_style'][4]) - (prev_vl['box_style'][0] + prev_vl['box_style'][4])
            same_top = vhu.compare_top(vl, prev_vl)
            if same_top:
                gap_bw_vls.append(vl["box_style"][1] - prev_vl["box_style"][2])
            if not same_top and top_gap > 0:
                row_count = row_count + 1
            should_merge = False
            if prev_vl['text'].strip()[-1] in ['$', '€', '£'] and len(prev_vl['text']) > 1 and \
                    not prev_vl['text'].strip()[-2].isspace():
                vl['text'] = prev_vl['text'].strip()[-1] + vl['text']
                prev_vl['text'] = prev_vl['text'].strip()[:-1]
            if prev_vl['text'].strip() in ['$', '€', '£'] and vl['text'].strip()[0] not in ['$', '€', '£', '%']:
                    # and vl['line_parser']['words'][0]['is_number']):#sometimes it has _ and other stuff
                should_merge = True
            elif vl["word_classes"][0] != prev_vl["word_classes"][-1] and \
                    len(vl['text']) > 1 and len(prev_vl['text']) > 1:
                # Difference in class.
                should_merge = False
            elif "line_parser" in vl and "line_parser" in prev_vl and \
                    len(vl["line_parser"]["words"]) == len(prev_vl["line_parser"]["words"]) == 1 and \
                    vl["line_parser"]["words"][0].get('is_number', False) and \
                    prev_vl["line_parser"]["words"][-1].get('is_number', False):
                # Don't merge 2 numbers in a table row
                should_merge = False
            else:
                gap, normal_gap, _, is_justified = self.get_gaps_from_vls(vl, prev_vl)
                if is_justified:
                    if multi_row:  # Probable center justified table row ?
                        normal_gap = (normal_gap / JUSTIFIED_NORMAL_GAP_MULTIPLIER) * 2.5
                    else:
                        normal_gap = (normal_gap / JUSTIFIED_NORMAL_GAP_MULTIPLIER) * 1.5
                else:
                    if not (is_table_row and len(prev_vl["text"].split()) > 1):
                        normal_gap = 1.5 * normal_gap
                # Check for top difference / bottom difference
                # In addition sometimes a single VL will be spread across multiple line.
                if gap < normal_gap and (abs(top_gap) < 2 or abs(bottom_gap) < 2 or
                                         vl['box_style'][0] - (prev_vl['box_style'][0] + prev_vl['box_style'][4]) < 0) \
                        and vl['text'].strip() not in ['$', '€', '£']:
                    if is_table_row:
                        cline_style = self.class_line_styles[vl["word_classes"][0]]
                        if not multi_row and gap > (cline_style[5] * 3):
                            should_merge = False
                            if (prev_vl_merged and avg_merge_gap and gap < 2 * avg_merge_gap) or vls_has_single_words:
                                should_merge = True
                            # Check whether the gap between the current VL and the next VL is comparable
                            # to that of the previous VL and the current VL. In that case it will be
                            # most probably a justified text
                            if vls_has_single_words and vl_id < len(vls) - 2:
                                gap_1, _, _, _ = self.get_gaps_from_vls(vls[vl_id+2], vl)
                                if gap < 0.7 * gap_1:
                                    should_merge = False
                            if should_merge:
                                if not avg_merge_gap:
                                    avg_merge_gap = gap
                                else:
                                    avg_merge_gap = (avg_merge_gap + gap) * 0.5
                        else:
                            if avg_merge_gap and gap > (3 * avg_merge_gap):
                                should_merge = False
                            else:
                                should_merge = True
                                if not avg_merge_gap:
                                    avg_merge_gap = gap
                                else:
                                    avg_merge_gap = (avg_merge_gap + gap) * 0.5
                                if not multi_row or same_top:
                                    vl_text = vl['text'].strip()
                                    # Merge only single VL having % as text
                                    if len(vl_text) > 1 and \
                                            (vl_text[0] == "%" or
                                             (len(prev_vl["line_parser"]["words"]) > 1 and
                                              prev_vl["line_parser"]["words"][0].get('is_number', False) and
                                              prev_vl['text'].strip()[-1] == "%" and
                                              vl["line_parser"]["words"][0].get('is_number', False))):
                                        # If there are more chars in the text other than %, don't allow merging
                                        # of patterns like "10%   12%".
                                        should_merge = False
                                if should_merge and gap > max_merge_gap and \
                                        (len(prev_vl["text"].strip().split()) > 1 or
                                         len(vl["text"].strip().split()) > 1):
                                    should_merge = False
                                # If we are merging here, update the max_merge_gap.
                                if should_merge:
                                    max_merge_gap = max(max_merge_gap, gap)
                    else:
                        should_merge = True
                    if should_merge and prev_vl['text'].strip()[-1] in ['$', '€', '£', '%'] and \
                            vl['text'].strip()[0] in ['$', '€', '£', '%']:
                        should_merge = False
                elif is_table_row and \
                        not same_top and \
                        len(gap_bw_vls) > 0 and \
                        vl['box_style'][0] <= (prev_vl['box_style'][0] + (2 * prev_vl['box_style'][4])) and \
                        vl['text'].strip() not in ['$', '€', '£'] and \
                        len(list(range(max(int(prev_vl['box_style'][1]), int(vl['box_style'][1])),
                                       min(int(prev_vl['box_style'][2]), int(vl['box_style'][2]))+1))):
                    should_merge = True
            if should_merge:
                # print("merging: ", prev_vl["text"][0:80], "->", vl["text"][0:80], gap, normal_gap, is_justified, avg_merge_gap)
                prev_vl = Doc.merge_line_info(prev_vl, vl, remove_space=True)
                prev_vl_merged = True
            else:
                good_vl.append(prev_vl)
                prev_vl = vl

        if prev_vl:
            good_vl.append(prev_vl)
        is_fake_row = True
        if is_table_row and normal_gap and gap_bw_vls and max(gap_bw_vls) > normal_gap:
            is_fake_row = False
        return good_vl, row_count, is_fake_row

    def are_aligned(self, prev_block, curr_block):
        prev_box = prev_block["visual_lines"][0]['box_style']
        curr_box = curr_block["visual_lines"][0]['box_style']
        return np.abs(prev_box[1] - curr_box[1]) < 0.2

    def do_overlap(self, prev_block, curr_block):
        return False

    def post_fix(self, block):
        if (block["block_type"] == "para" or block["block_type"] == "list_item") and len(block["visual_lines"]) > 0:
            vls = block["visual_lines"]
            word_stats = self.line_style_word_stats[vls[0]["line_style"]]
            lines = []
            block_text = None
            if word_stats["is_justified"]:
                prev_vl = vls[0]
                vl_buf = [prev_vl]
                block_text = prev_vl["text"]
                for vl in vls[1:]:
                    vl_box = vl["box_style"]
                    prev_vl_box = prev_vl["box_style"]
                    new_line = vl_box[0] != prev_vl_box[0]
                    if new_line:
                        lines.append(vl_buf)
                        vl_buf = []
                    if prev_vl["text"] and prev_vl["text"][-1] == "-" and new_line:
                        block_text = block_text[0:-1] + vl["text"]
                    else:
                        block_text = block_text + self.check_add_space_btw_texts(block_text, vl["text"]) + vl["text"]
                    prev_vl = vl
                block["block_text"] = block_text
                if block["block_type"] == "list_item":
                    block["list_type"] = Doc.get_list_item_subtype(block)
                block["block_sents"] = sent_tokenize(block["block_text"])

    def label_table_of_content(self):
        collected_row = []
        header_text = []
        blocks = self.blocks
        for idx, block in enumerate(blocks):
            if block["block_type"] == "header":
                header_text.append(block["block_text"])
        for idx, block in enumerate(blocks):
            if block["page_idx"] > 3:
                break
            if block["block_type"] == "table_row" and len(block["visual_lines"]) == 2:
                collected_row.append({"block_idx": idx, "text": block["visual_lines"][0]["text"]})
            else:
                if collected_row and len(collected_row) > 1:
                    # remove the first row (header)
                    # collected_row = collected_row[1:]
                    header_rows = 0
                    for row in collected_row:
                        text = row["text"]
                        # if line_parser.Line(text).is_header: # using line parser 
                        if text in header_text:
                            header_rows += 1
                    # if len(collected_row) * 0.8 <= header_rows: # using line parser
                    if len(collected_row) * 0.67 <= header_rows:
                        for row in collected_row:
                            blocks[row["block_idx"]]["is_toc"] = True
                collected_row = []
        self.blocks = blocks

    # def set_bounds(self, block):
    #     min_top = 0;
    #     max_top = 0;
    #     min_lef
    def get_page_alignment(self, block):
        block_right = block['visual_lines'][-1]['box_style'][2]
        print("alignment is ", self.page_width, block_right)

    def organize_and_indent_blocks(self, debug=False):
        prev_class_name = None
        prev_block = None
        prev_line_style = None
        indent = 0
        level_stack = []
        table_start_idx = -1
        table_end_idx = -1
        header_block_idx = -1
        header_block_text = ""
        block_buf = []
        organized_blocks = []
        idx = 0
        block_idx = 0
        non_table_row_count = 0
        table_row_count = 0
        n_table_cols = 0
        prev_table_row = None
        prev_too_much_space = False
        space_bw_table_rows = 0.0
        table_row_with_max_cols = None
        svg_page_tags = None
        included_prev_2_prev_blk = False

        while idx < len(self.blocks):
            block = self.blocks[idx]
            block['box_style'] = Doc.calc_block_span(block)
            box_style = block["box_style"]
            # Check whether the block is within the table bbox
            block_within_table_bbox = self.check_block_within_table_bbox(block)
            if block_within_table_bbox:
                # Mark as audited for BBox Detector to honor it.
                block['audited'] = True

            if table_start_idx == -1 and block_within_table_bbox:
                # Set the table_start as this block,
                # if we are within the bounds and table_start_idx is not yet set
                table_start_idx = block_idx
                block["block_type"] = 'table_row'
            # print("state: ", block_idx, len(organized_blocks))
            if not svg_page_tags and not prev_block:
                svg_page_tags = self.page_svg_tags[block["page_idx"]]
            new_page = prev_block and prev_block["page_idx"] != block["page_idx"]
            if new_page:
                if PROGRESS_DEBUG:
                    print('processing blocks in page: ', block["page_idx"])
                svg_page_tags = self.page_svg_tags[block["page_idx"]]

            probable_table_block = False    # self.check_block_within_svg_tags(block, prev_block)
            if probable_table_block:
                block['probable_table_block'] = True
            if BLOCK_DEBUG:
                print(">>>> organizing block: ", block['block_text'][0:80], block["block_type"], "pg: ",
                      block["page_idx"], "vl: ", len(block["visual_lines"]))
                print("\t", "left:", box_style[1], "top:", box_style[0], "right:", box_style[2])
                print("\t", "probable_table_block: ", probable_table_block)

            is_y_overlapped = False
            # collect blocks that are aligned in a line this is for headers flowing into multiple lines
            if prev_block and Doc.have_y_overlap(prev_block, block, check_class=True) and \
                    not prev_block.get('block_modified', False) and not prev_block.get('block_reordered', False):
                # print(n_table_cols, ">>>>> y overlap: ", prev_block['block_text'], '->', block['block_text'])
                is_y_overlapped = True
                if block["block_type"] == 'table_row' and prev_block["block_type"] != 'table_row' and \
                        len(block_buf) > 1:
                    # If previous block is not a table_row and we have more blocks in the buffer, check whether we
                    # have another table_row with the same top. If we have a table_row with the different top, its most
                    # likely that this current table_row should not be considered part of the block buffer.
                    for buf_blk in block_buf[-2::-1]:
                        if buf_blk["block_type"] == 'table_row':
                            if buf_blk["box_style"][0] != box_style[0]:
                                if BLOCK_DEBUG:
                                    print(">>>>> Overriding y overlap: ", prev_block['block_text'],
                                          '->', block['block_text'])
                                is_y_overlapped = False
                            else:
                                is_y_overlapped = True
                            break
                        else:
                            continue
                if is_y_overlapped:
                    if BLOCK_DEBUG:
                        print(">>>>> y overlap: ", prev_block['block_text'], '->', block['block_text'])
                    if len(organized_blocks) > 1 and not block_buf:
                        t_block = organized_blocks[-2]
                        if Doc.have_y_overlap(t_block, block, check_class=True) and \
                                not t_block.get('block_modified', False) and not t_block.get('block_reordered', False):
                            if BLOCK_DEBUG:
                                print(">>>>> y overlap t_block: ", t_block['block_text'], '->', block['block_text'])
                            block_buf.append(t_block)
                            included_prev_2_prev_blk = True
                    block_buf.append(prev_block)
                    prev_block = block
                    idx = idx + 1
                    continue
            if not is_y_overlapped:
                if len(block_buf) > 0:
                    if prev_block:
                        block_buf.append(prev_block)
                    # merge all the collected blocks into a single block
                    new_block = self.merge_blocks(block_buf)
                    block_buf = []
                    reprocess_num = 1
                    if included_prev_2_prev_blk:
                        reprocess_num = 2
                        organized_blocks.pop()
                    organized_blocks.pop()  # replace previous single block with combo
                    idx = idx - 1  # reprocess the current block
                    block_idx = block_idx - reprocess_num
                    block = new_block
                    prev_block = organized_blocks[-1] if organized_blocks else None
                    included_prev_2_prev_blk = False
                    if BLOCK_DEBUG:
                        print("merged block", new_block["block_text"], new_block["block_type"],
                              "vl: ", len(new_block["visual_lines"]))

            block_sents = sent_tokenize(block["block_text"])
            class_name = block["block_class"]

            line_style = block["visual_lines"][-1]["line_style"]  # self.class_line_styles[class_name]
            if block["block_type"] == "header":
                if block["block_text"].startswith("Source:"):
                    block["block_type"] = "para"

            block_type = block['block_type']
            block["block_sents"] = block_sents
            block["header_block_idx"] = header_block_idx
            block["header_text"] = header_block_text

            is_table_row = block_type == 'table_row'
            aligned_para = False
            have_y_overlap = False
            if is_table_row:
                vls = block["visual_lines"]
                # deal with the case when all rows in table do not have same top
                split_idx = 1
                split_vl = vls[0]
                box_0 = split_vl["box_style"]
                box_1 = vls[split_idx]["box_style"] if len(vls) > 1 else None
                box_last = vls[-1]["box_style"]
                misaligned_top = (
                        box_1
                        and "merged_block" not in block
                        and abs(box_0[0] - box_1[0]) > 2
                        and box_0[1] >= box_1[1]
                )
                orig_misaligned_top = misaligned_top
                if misaligned_top and box_last and box_last[1] > box_0[1] and table_start_idx == -1:
                    # Do this treatment only for first row in the table.
                    # We have a Visual Line that may be not part of this Cell.
                    for vl in vls[-1:1:-1]:
                        if abs(box_0[0] - vl["box_style"][0]) < 2 or abs(box_1[0] - vl["box_style"][0]) < 2:
                            misaligned_top = False
                            break
                # misaligned_top = False
                # split_idx = 0
                # print("checking..", vls[0]["text"])
                # if len(vls) > 1 and "merged_block" not in block:
                #     for split_idx, next_vls in enumerate(vls[1:]):
                #
                #         box_1 = next_vls["box_style"]
                #         misaligned_top = (
                #                 abs(box_0.top - box_1.top) > 2
                #                 # and box_0.left >= box_1.left
                #         )
                #         print("\t", next_vls['text'], misaligned_top, box_0.top)
                #         if misaligned_top:
                #             break
                if misaligned_top and box_0[1] >= box_1[1]:
                    has_same_top = False
                    for v_idx in range(len(vls) - 1):
                        if abs(vls[v_idx]["box_style"][0] - vls[v_idx + 1]["box_style"][0]) > 2:
                            continue
                        else:
                            has_same_top = True
                            break
                    if has_same_top and "changed" in vls[v_idx] and vls[v_idx]["changed"]:
                        misaligned_top = False
                # If misaligned_top, reset misaligned_top if one of the vl has matching top.
                if misaligned_top:
                    for vl in vls[1:]:
                        if box_0[0] == vl["box_style"][0]:
                            misaligned_top = False
                            break
                # Check if we have a multi-line first cell element.
                if misaligned_top and split_vl['text'][-1] not in [":"]:
                    min_top = box_0[0]
                    max_bottom = box_0[0] + box_0[4]
                    prev_vl = vls[0]
                    for v_idx, vl in enumerate(vls[1:]):
                        vl_bottom = vl["box_style"][0] + vl["box_style"][4]
                        if vl_bottom > max_bottom:
                            max_bottom = vl_bottom
                            # if there is a line between the vls, then we might be dealing with multi cell. Break it
                            if Doc.check_line_between_box_styles(prev_vl['box_style'],
                                                                 vl['box_style'],
                                                                 svg_page_tags[0]):
                                split_idx = v_idx + 1
                                break
                        elif min_top <= vl_bottom <= max_bottom and vl["box_style"][1] > box_0[2]:
                            misaligned_top = False
                            break
                        else:
                            break
                        prev_vl = vl
                # Reset misaligned top if there is a line between the split_idx and its previous VL.
                if not misaligned_top and orig_misaligned_top != misaligned_top and split_idx > 0:
                    if Doc.check_line_between_box_styles(vls[split_idx - 1]['box_style'],
                                                         vls[split_idx]['box_style'],
                                                         svg_page_tags[0]):
                        misaligned_top = True

                # when a row group is present but gets attached to the next line
                # Don't split, if we have already audited this table
                #   (Checking this only for headers now)
                if misaligned_top and table_start_idx != block_idx:
                    if table_parser.TABLE_DEBUG or BLOCK_DEBUG:
                        print("splitting block: ", block["block_text"])
                    block_1 = self.make_block(vls[0:split_idx], "para", block_idx)
                    block_1['level'] = indent
                    block_1["header_block_idx"] = header_block_idx
                    block_1["header_text"] = header_block_text
                    block_1["is_split_block"] = True
                    if table_parser.TABLE_DEBUG or BLOCK_DEBUG:
                        print("\tsplit_block 1: ", block_1["block_text"])
                    organized_blocks.append(block_1)
                    # the very first block is of this kind
                    if table_start_idx == -1:
                        if table_parser.TABLE_DEBUG:
                            print("\n<table>\n")
                        table_start_idx = block_idx
                        space_bw_table_rows = 0.0
                        table_row_count = table_row_count + 1
                        block_1['block_type'] = 'table_row'
                        table_row_with_max_cols = block_1
                        prev_block = block_1
                    else:
                        prev_block = block_1
                        # block_1['block_type'] = 'para'
                    block_idx = block_idx + 1
                    # print("inserting ", block_idx, len(organized_blocks))
                    block = self.make_block(vls[split_idx:], 'table_row', block_idx)
                    block["header_block_idx"] = header_block_idx
                    block["header_text"] = header_block_text

                if table_start_idx == -1:
                    # fix a case where some kind of header is too close to the table
                    non_table_row_count = 0
                    table_row_with_max_cols = block
                    table_start_idx = block_idx
                    space_bw_table_rows = 0.0
                    if table_parser.TABLE_DEBUG:
                        print("\n<table>\n")
                non_table_row_count = 0
                n_table_cols = max(vhu.count_cols(block['visual_lines']), n_table_cols)
                # print("n_table_cols_1... ", n_table_cols)
                # n_table_cols = max(len(block["visual_lines"]), n_table_cols)
                # prev_table_row = block
                table_row_count = table_row_count + 1
            else:
                if n_table_cols == 2:
                    # print("checking alignment ->>", block["block_type"])
                    # print("\t", block['block_text'][0:80])
                    # print("\t", prev_table_row['block_text'][0:80])
                    have_y_overlap = Doc.have_y_overlap(prev_table_row, block, check_class=False)
                    if have_y_overlap:
                        is_table_row = True
                        # print("setting prev table row to ", block["block_text"])
                        # prev_table_row = block
                    aligned_para = table_parser.para_aligned_with_prev_row(self.page_width, prev_table_row,
                                                                           block, debug=False)
                    # have_y_overlap = Doc.have_y_overlap(prev_block, block, check_class=False)
                    # print("alignment:", aligned_para)
                if not aligned_para and not have_y_overlap:
                    # print("++++", non_table_row_count, "...........", block["block_text"], block["block_type"])
                    # Check there is a line between the blocks. If not, increment the non_table_row_count.
                    if prev_block and not Doc.check_line_between_box_styles(
                        prev_block['box_style'],
                        block['box_style'],
                        svg_page_tags[0],
                        check_gap=True,
                    ):
                        non_table_row_count = non_table_row_count + 1
                        table_row_count = 0
                else:
                    block["aligned_para"] = True
                    table_row_count = table_row_count + 1

            if table_start_idx > - 1:
                table_end_idx = block_idx

            # print(table_start_idx)
            # print(block_idx, len(organized_blocks))
            # print(organized_blocks[block_idx]['block_text'] if len(organized_blocks) > 0 else "start")
            # print(block['block_type'], block['block_text'])
            # if table_start_idx > 0:
            #     print("tr", table_end_idx, block['block_text'], table_start_idx, idx - table_start_idx)
            # table has_ended
            # more than two non-table rows after table row - table has ended ## also add blank space logic heremeans the table has ended
            n_rows = table_end_idx - table_start_idx + 1
            if n_rows > 2:
                temp_trow_block = organized_blocks[table_start_idx]
                space_bw_trow_list = []
                for tblock in organized_blocks[table_start_idx + 1:table_end_idx]:
                    temp_diff_in_space = tblock['box_style'][0] - \
                                         (temp_trow_block['box_style'][0] + temp_trow_block['box_style'][4])
                    space_bw_trow_list.append(temp_diff_in_space)
                    temp_trow_block = tblock
                space_bw_table_rows = np.mean(space_bw_trow_list)

            check_again = True
            no_more_non_table_rows = (not is_table_row
                                      and table_start_idx != -1
                                      and (non_table_row_count > 2
                                           or (len(block['block_text'].split()) > 10 and
                                               different_style and n_rows - non_table_row_count > 1))
                                      and not aligned_para and not have_y_overlap)
            if no_more_non_table_rows and non_table_row_count <= 2 and prev_block:
                prev_block_table_row = prev_block['block_type'] == 'table_row'
                if prev_block_table_row:
                    align_count, prev_count, align_pos = \
                        table_parser.get_alignment_count(prev_block, block, force_check_curr_block=True)
                    if align_count == len(align_pos) and len(set(align_pos)) == 1 and \
                            len(block["visual_lines"][0]["text"].split()) < 10:
                        # We are aligned to a single column
                        no_more_non_table_rows = False
                        non_table_row_count = 0
                        check_again = False
                else:
                    for blk in organized_blocks[-2::-1]:
                        if blk['block_type'] == 'table_row':
                            align_count, prev_count, align_pos = \
                                table_parser.get_alignment_count(blk, block, force_check_curr_block=True)
                            if align_count == len(align_pos) and len(set(align_pos)) == 1 or (
                                    not align_count and blk["box_style"][1] > block["box_style"][2]) and \
                                    len(block["visual_lines"][0]["text"].split()) < 10:
                                # We are aligned to a single column
                                no_more_non_table_rows = False
                                non_table_row_count = 0
                                check_again = False
                            break
            last_block_in_page = False
            if no_more_non_table_rows and non_table_row_count <= 2 and idx < len(self.blocks) - 1:
                if self.blocks[idx + 1]["block_type"] == "table_row" and \
                        self.blocks[idx + 1]['box_style'][0] >= block['box_style'][0] and \
                        (self.blocks[idx + 1]['box_style'][0] + self.blocks[idx + 1]['box_style'][4]) <= \
                        (block['box_style'][0] + block['box_style'][4]):
                    no_more_non_table_rows = False
                    check_again = False
                elif self.blocks[idx + 1]["page_idx"] != block["page_idx"]:
                    # Last block in the page
                    no_more_non_table_rows = False
                    last_block_in_page = True
                    vl1 = block["visual_lines"][0]
                    for vl in block["visual_lines"][1:]:
                        if vl["box_style"][0] > vl1["box_style"][0] + vl1["box_style"][4]:
                            no_more_non_table_rows = True
                            break
                    if not no_more_non_table_rows:
                        block["last_block_in_page"] = True
                        check_again = False
            bad_sequence = not is_table_row and n_rows == 3 and non_table_row_count == 2
            italic_center = self.detect_block_center_aligned(block) and len(block["visual_lines"]) == 1 and \
                block["visual_lines"][0]["line_style"][1] == "italic"
            if bad_sequence:
                # Check if the gap between the lines is considerable for a table row.
                prev_block_style = prev_block['box_style']
                prev_blk_bottom = prev_block_style[0] + prev_block_style[4]
                if 0 < (block['box_style'][0] - prev_blk_bottom) < 2 * block['box_style'][4]:
                    bad_sequence = False
            no_more_table_rows = (no_more_non_table_rows or bad_sequence or italic_center) and table_start_idx != -1
            # print("no_more_table_rows: ", no_more_table_rows, bad_sequence, no_more_non_table_rows)
            if table_start_idx != -1 and \
                    not is_table_row and \
                    self.detect_block_center_aligned(block, enable_width_check=False) and \
                    prev_block and \
                    prev_block["block_type"] != "table_row":
                blk_has_parenthesized_hdr = False
                for blk_vl in block["visual_lines"]:
                    if parenthesized_hdr_pattern.search(blk_vl["text"]) is None:
                        blk_has_parenthesized_hdr = False
                        break
                    else:
                        blk_has_parenthesized_hdr = True
                if blk_has_parenthesized_hdr or (len(block["visual_lines"]) > 1 and
                                                 block["visual_lines"][0]["text"].strip().startswith("(") and
                                                 block["visual_lines"][-1]["text"].strip().endswith(")")) or \
                        self.detect_block_center_aligned(prev_block, enable_width_check=False):
                    no_more_table_rows = True
            # Find GAP between rows
            min_left = 10000
            prev_blk_btm = 0
            gap_bw_rows = []
            gap_bw_actual_rows = []
            left_most_vl = None
            block_vl = block['visual_lines'][0]
            if table_start_idx != -1 and n_rows > 2:
                for tblock in organized_blocks[table_start_idx:table_end_idx]:
                    tb_box = tblock['box_style']
                    if block_vl["line_style"] == tblock['visual_lines'][0]["line_style"] and \
                            n_rows <= 4:
                        # If there is a match in line_style with the possible headers ?
                        # Allow this only for the first actual data row. Here we consider only 3 rows of header ?
                        if prev_blk_btm > 0:
                            row_gap = round(abs(tb_box[0] - prev_blk_btm), 2)
                            gap_bw_rows.append(row_gap)
                            if tblock["block_type"] == "table_row":
                                gap_bw_actual_rows.append(row_gap)
                            continue
                    if tb_box[1] < min_left:
                        left_most_vl = tblock['visual_lines'][0]
                        min_left = tb_box[1]
                    if prev_blk_btm > 0:
                        row_gap = round(abs(tb_box[0] - prev_blk_btm), 2)
                        gap_bw_rows.append(row_gap)
                        if tblock["block_type"] == "table_row":
                            gap_bw_actual_rows.append(row_gap)
                    prev_blk_btm = tb_box[0] + tb_box[4]

            if not no_more_table_rows and non_table_row_count > 0 and table_start_idx != -1 \
                    and not is_table_row and n_rows > 2 and not last_block_in_page and check_again:
                if left_most_vl:
                    prev_box = left_most_vl['box_style']
                    curr_box = block_vl['box_style']
                    block_box = block['box_style']
                    intersection_points = list(range(max(int(prev_box[1]), int(curr_box[1])),
                                                     min(int(prev_box[2]), int(curr_box[2]))+1))

                    if (intersection_points and not block_vl["line_style"] == left_most_vl["line_style"]) or \
                            block_box[1] < min_left or curr_box[3] > 0.6 * self.page_width or \
                            block_box[3] > 0.6 * self.page_width:
                        prev_block_style = organized_blocks[-1]['box_style']
                        prev_blk_bottom = prev_block_style[0] + prev_block_style[4]
                        median_gap_bw_rows = 0.5
                        max_gap_bw_rows = 0.5
                        if len(gap_bw_rows) > 0:
                            median_gap_bw_rows = np.median(gap_bw_rows)
                            max_gap_bw_rows = max(gap_bw_rows)
                        # print(block['box_style'][0], prev_blk_bottom, gap_bw_rows, median_gap_bw_rows)
                        space_bw_curr_and_prev = abs(block['box_style'][0] - prev_blk_bottom)
                        if organized_blocks[-1]['page_idx'] != block['page_idx']:
                            space_bw_curr_and_prev = 0
                        if space_bw_curr_and_prev > 2.5 * median_gap_bw_rows and \
                                space_bw_curr_and_prev > 1.5 * max_gap_bw_rows:
                            no_more_table_rows = True
                        if no_more_table_rows and idx < len(self.blocks) - 1 and \
                                self.blocks[idx + 1]["block_type"] == "table_row" and \
                                prev_block['block_type'] == 'table_row' and n_rows <= 4:
                            # If the next block and previous block has same alignment, then don't break the table.
                            # We apply this condition only for the initial few rows.
                            align_count, prev_count, _ = table_parser.get_alignment_count(prev_block,
                                                                                          self.blocks[idx + 1])
                            if align_count == prev_count:
                                no_more_table_rows = False
                        elif not no_more_table_rows and idx < len(self.blocks) - 1 and \
                                self.blocks[idx + 1]["block_type"] == "table_row" and prev_table_row and \
                                prev_table_row['visual_lines'][0]["line_style"] != block_vl["line_style"]:
                            # If there is a considerable gap between the rows, and there is an alignment
                            # break then consider its a new table row
                            align_count, prev_count, _ = table_parser.get_alignment_count(prev_table_row,
                                                                                          self.blocks[idx + 1])
                            space_bw_curr_and_prev_row = abs(block['box_style'][0] -
                                                             (prev_table_row['box_style'][0] +
                                                              prev_table_row['box_style'][4]))
                            if align_count < prev_count and len(gap_bw_actual_rows) > 0 and \
                                    space_bw_curr_and_prev_row > 1.5 * max(gap_bw_actual_rows) and \
                                    space_bw_curr_and_prev_row > 1.5 * max(gap_bw_rows):
                                no_more_table_rows = True
                if not no_more_table_rows and len(gap_bw_rows) > 0:
                    # If the non-table row element is within 1.5 times median gap between rows,
                    # then reset the non_table_row_count
                    prev_block_style = organized_blocks[-1]['box_style']
                    prev_blk_bottom = prev_block_style[0] + prev_block_style[4]
                    median_gap_bw_rows = np.median(gap_bw_rows)
                    space_bw_curr_and_prev = abs(block['box_style'][0] - prev_blk_bottom)
                    if space_bw_curr_and_prev < 1.5 * median_gap_bw_rows:
                        align_count, _, _ = table_parser.get_alignment_count(prev_block, block)
                        if align_count:
                            # Reset the non_table_row_count if we have an alignment
                            # with one of the cell
                            non_table_row_count = 0

            # # Last effort not to break a table due to the presence of line between the blocks
            if no_more_table_rows and non_table_row_count == 1 and table_start_idx != -1 \
                    and not is_table_row and n_rows > 2 and not last_block_in_page:
                prev_block_style = prev_block['box_style']
                prev_blk_bottom = prev_block_style[0] + prev_block_style[4]
                space_bw_curr_and_prev = block['box_style'][0] - prev_blk_bottom
                if Doc.check_line_between_box_styles(prev_block['box_style'], block['box_style'], svg_page_tags[0]) and\
                        0 < space_bw_curr_and_prev < prev_block_style[4]:
                    no_more_table_rows = False
                    align_count, _, _ = table_parser.get_alignment_count(prev_block, block)
                    if align_count:
                        # Reset the non_table_row_count if we have an alignment
                        # with one of the cell
                        non_table_row_count = 0

            if no_more_table_rows and table_parser.TABLE_BOUNDS_DEBUG:
                print("BREAK----")
                print("\t curr: ", block["block_text"])
                print("\t prev: ", prev_block["block_text"])
                print("\t aligned para: ", aligned_para, non_table_row_count, have_y_overlap)
                print("\t rc: ", non_table_row_count, "ts: ", len(block['block_text'].split()) > 10, different_style,
                      aligned_para)
            #     print("\t", prev_block["box_style"], block["box_style"])
                # table_parser.para_aligned_with_prev_row(self.page_width, prev_table_row, block, debug=True)

            different_section = False
            too_much_space = False
            double_space_bw_table_rows = False
            alignment_break = False
            page_change = False
            prev_block_table_row = False
            different_style = False
            smaller_font = False
            larger_font = False
            align_count = -1
            page_change_alignment_style_check = False
            if prev_block:
                prev_block_table_row = prev_block['block_type'] == 'table_row'
                if not prev_block_table_row and prev_block.get("last_block_in_page", False) and \
                        len(organized_blocks) > 1:
                    prev_block_table_row = organized_blocks[-2]['block_type'] == 'table_row'
                prev_top = prev_block['box_style'][0]
                curr_top = block['box_style'][0]
                prev_bottom = prev_top + prev_block['box_style'][4]
                curr_bottom = curr_top + block['box_style'][4]
                bottom_space = (curr_bottom - prev_bottom)/block['box_style'][4]
                top_diff = curr_top - prev_top
                top_space = top_diff / prev_block['box_style'][4]
                # print("...block::", block["block_text"][0:80])
                # space_between_blocks = bottom_space
                too_much_space = bottom_space > table_end_space_threshold and top_space > table_end_space_threshold
                if line_style in self.line_style_space_stats:
                    too_much_space = top_diff > 1.4 * self.line_style_space_stats[line_style]['most_frequent_space'] \
                                     and curr_top > prev_bottom and \
                                     curr_top - prev_bottom > 1.5 * block['box_style'][4]
                    if space_bw_table_rows and (curr_top - prev_bottom) > 2 * space_bw_table_rows and \
                            (curr_top - prev_bottom) > 2 * self.line_style_space_stats[line_style]['most_frequent_space']:
                        double_space_bw_table_rows = True
                    # if too_much_space:
                    #     print("++++++", block["block_text"][0:20], too_much_space, top_diff, self.line_style_space_stats[line_style]['most_frequent_space'])
                # elif too_much_space:
                #     print("++++++", block["block_text"][0:20], too_much_space, top_diff, top_space, bottom_space)
                smaller_font = line_style[2] < prev_line_style[2] if prev_line_style else False
                larger_font = line_style[2] > prev_line_style[2] if prev_line_style else False
                different_style = line_style != prev_line_style if prev_line_style else False
                has_more_cols = len(block["visual_lines"]) - len(prev_block["visual_lines"]) > 0

                # if table_parser.TABLE_DEBUG and different_section:
                if table_start_idx > 0:  # and 'merged_block' not in prev_block:

                    def determine_align_break(align_count, prev_count, align_pos):
                        align_break = False
                        align_threshold = 0.5
                        if prev_count > 1:
                            align_break = (align_count < 2 or max(align_pos) <= align_count and
                                           align_count / prev_count < align_threshold)
                        else:
                            align_break = align_count < 1
                        return align_break

                    if is_table_row:
                        # if previous block is table row then make sure at least 50% cols are aligned
                        # if previous was not table row then make sure at least 80% rows are aligned
                        if prev_block_table_row:
                            align_count, prev_count, align_pos = table_parser.get_alignment_count(prev_block, block)
                            page_change_alignment_style_check = align_count == prev_count or \
                                                                (align_count > prev_count and
                                                                 block['block_class'] == prev_block['block_class'] and
                                                                 0 in align_pos)
                            alignment_break = determine_align_break(align_count, prev_count, align_pos)
                            pattern_broke = False
                            if not alignment_break and vhu.find_num_cols(block)[0] > prev_count and n_rows > 2:
                                all_rows_has_same_cols = True
                                for tb_row in organized_blocks[table_start_idx:table_end_idx - 1]:
                                    if tb_row["block_type"] == 'table_row':
                                        if vhu.find_num_cols(tb_row)[0] != prev_count:
                                            all_rows_has_same_cols = False
                                            break
                                if all_rows_has_same_cols:
                                    alignment_break = True
                                    pattern_broke = True
                            if alignment_break and not align_count and table_row_with_max_cols and not pattern_broke:
                                # We have no alignment with the previous table row, but still might be worth while to
                                # check with the row with max cols
                                align_count_1, prev_count_1, align_pos_1 = \
                                    table_parser.get_alignment_count(table_row_with_max_cols, block)
                                alignment_break = determine_align_break(align_count_1, prev_count_1, align_pos_1)
                                if alignment_break and table_parser.TABLE_DEBUG:
                                    print("alignment broke_1", align_count_1, prev_count_1, align_pos_1)
                            if alignment_break and \
                                    prev_block.get('merged_block', False) and \
                                    idx + 1 < len(self.blocks) and \
                                    self.blocks[idx + 1] and \
                                    Doc.have_y_overlap(block, self.blocks[idx + 1], check_class=True):
                                # If the previous block is a merged one and the next block has a y_overlap,
                                # we will not do the alignment_break here.
                                alignment_break = False
                            if alignment_break and align_count and align_pos[0] == 0:
                                prev_block_left = prev_block['box_style'][1]
                                for vl in block['visual_lines'][:-1]:
                                    alignment_break = False
                                    if vl['box_style'][2] > prev_block_left:
                                        alignment_break = False
                                        break
                            if alignment_break and table_parser.TABLE_DEBUG:
                                print("alignment broke_0", align_count, prev_count, align_pos)
                        elif prev_table_row and prev_table_row["block_type"] == "table_row" and \
                                (curr_top > prev_table_row['box_style'][0] + prev_table_row['box_style'][4] or
                                 prev_table_row["page_idx"] != block["page_idx"]):
                            align_count, prev_count, align_pos = table_parser.get_alignment_count(prev_table_row, block)
                            align_threshold = 2/3
                            if prev_count > 1:
                                # print("-------------------", prev_table_row["block_text"][0:80], align_count, prev_count, align_count/prev_count)
                                # print("\t\t", block["block_text"][0:80])
                                alignment_break = (align_count < 2 or align_count/prev_count < align_threshold)
                                if alignment_break and align_count == vhu.find_num_cols(block)[0]:
                                    # Reset the alignment break, if all the columns are aligned somehow with
                                    # the previous row
                                    alignment_break = False
                                elif alignment_break and \
                                        align_count/len(block["visual_lines"]) >= align_threshold and \
                                        0 < block_idx - prev_table_row["block_idx"] < 3:
                                    # If most of the visual lines align and if the previous table row is within 3 blocks
                                    alignment_break = False
                            else:
                                alignment_break = align_count < 1

                        if len(organized_blocks[table_start_idx:]) == 1 and alignment_break \
                                and prev_block.get('merged_block', None):
                            # Don't be so strict with the alignment for the second element.
                            alignment_break = False
                    elif prev_block['block_type'] == "table_row" and prev_block["page_idx"] != block["page_idx"]:
                        # Doing this only for a non table row block starting in a new page
                        align_count, prev_count, align_pos = table_parser.get_alignment_count(prev_block, block)
                        page_change_alignment_style_check = align_count == 1 and \
                                                            0 in align_pos and len(block["visual_lines"]) == 1
                        # Create an imaginary block and check whether there is a line above the block
                        prev_box_style = BoxStyle(
                            max(block["box_style"][0] - (2 * block["box_style"][4]), 0),
                            block["box_style"][1],
                            block["box_style"][2],
                            block["box_style"][3],
                            block["box_style"][4]
                        )
                        next_box_style = BoxStyle(
                            block["box_style"][0] + block["box_style"][4] + (2 * block["box_style"][4]),
                            block["box_style"][1],
                            block["box_style"][2],
                            block["box_style"][3],
                            block["box_style"][4]
                        )
                        page_change_alignment_style_check = page_change_alignment_style_check and \
                                                            Doc.check_line_between_box_styles(prev_box_style,
                                                                                              block['box_style'],
                                                                                              svg_page_tags[0],
                                                                                              x_axis_relaxed=True) and \
                                                            Doc.check_line_between_box_styles(block['box_style'],
                                                                                              next_box_style,
                                                                                              svg_page_tags[0],
                                                                                              x_axis_relaxed=True)

                page_change = (new_page and
                               (n_table_cols > 2 or (n_table_cols == 2 and not is_table_row and not aligned_para)))

                # different_section = too_much_space and (alignment_break or smaller_font or larger_font)
                different_section = (too_much_space or prev_too_much_space) and alignment_break
                # Overwriting section check if there is too much space between the table rows and
                # if the previous block is in a different style than the current block
                if not different_section and too_much_space and double_space_bw_table_rows and \
                        block['block_class'] != prev_block['block_class']:
                    different_section = True
                # if different_section:
                #     print("---->", too_much_space, prev_too_much_space, alignment_break)

            # different_section = False

            new_table_on_side = (prev_block
                                 and not page_change
                                 and block['box_style'][1] > prev_block['box_style'][2])
            different_column = (prev_block
                                 and not page_change
                                and block['box_style'][0] < prev_block['box_style'][0])

            new_table = (different_section and is_table_row) or \
                        (is_table_row and page_change and not page_change_alignment_style_check) or \
                        alignment_break

            # new_table = new_table_on_side or (different_section and is_table_row)
            # this is an attempt for bad tables from showing up
            # two_col_table_end = n_table_cols == 2 and not (aligned_para or prev_table_row or table_end_idx == table_start_idx)
            # if two_col_table_end:
            #     print("----------------->", aligned_para, is_table_row, block["block_text"], len(block["visual_lines"]))
            two_col_table_end = False
            different_section = different_section or two_col_table_end  # or different_column
            # if different_section:
            #     print("different section ----->", different_column)
            table_ended = (no_more_table_rows
                           or new_table
                           or different_section
                           or (page_change and not page_change_alignment_style_check))\
                          and not block_within_table_bbox
            if table_ended:
                table_start_set = False
                if table_start_idx != table_end_idx:
                    # if vhu.count_cols(organized_blocks[-1] > 2):
                    #     table_start_idx = table_start_idx - 1
                    #     organized_blocks.pop()
                    #     idx = idx - 1
                    block_idx, footer_count = self.build_table(block_idx, organized_blocks, table_start_idx,
                                                               table_end_idx)
                    all_vls_has_parenthesized_hdr = False
                    last_table_row_blk = organized_blocks[0 - footer_count - 1]
                    if last_table_row_blk and last_table_row_blk['block_type'] == "table_row":
                        for blk_vl in last_table_row_blk["visual_lines"]:
                            if parenthesized_hdr_pattern.search(blk_vl["text"]) is None:
                                all_vls_has_parenthesized_hdr = False
                                break
                            else:
                                all_vls_has_parenthesized_hdr = True
                    if (no_more_table_rows or new_table) and all_vls_has_parenthesized_hdr:
                        # Break down the 2 row table to header & para
                        if organized_blocks[0 - footer_count - 1]["block_type"] == \
                                organized_blocks[0 - footer_count - 2]["block_type"] == "table_row" and \
                                (table_end_idx - footer_count - table_start_idx) == 2:
                            last_block = organized_blocks[0 - footer_count - 1]
                            prev_to_last_block = organized_blocks[0 - footer_count - 2]
                            if vhu.find_num_cols(last_block)[0] == vhu.find_num_cols(prev_to_last_block)[0]:
                                del organized_blocks[0 - footer_count - 2]
                                del organized_blocks[0 - footer_count - 1]
                                start_block_idx = prev_to_last_block["block_idx"]
                                for v_idx, vls in enumerate(last_block["visual_lines"]):
                                    h_blk = self.make_block([vls], "header", start_block_idx)
                                    h_blk["block_class"] = prev_to_last_block["block_class"]
                                    organized_blocks.insert(start_block_idx, h_blk)
                                    start_block_idx += 1
                                    cell_blk = self.make_block([prev_to_last_block["visual_lines"][v_idx]],
                                                               "header_modified_to_para",
                                                               start_block_idx,
                                                               )
                                    cell_blk["block_class"] = last_block["block_class"]
                                    organized_blocks.insert(start_block_idx, cell_blk)
                                    start_block_idx += 1
                                if footer_count:
                                    for blk in organized_blocks[0 - footer_count:]:
                                        blk["block_idx"] = start_block_idx
                                        start_block_idx += 1
                                block_idx = organized_blocks[-1]["block_idx"] + 1
                                if new_table:
                                    table_start_idx = block_idx
                                    table_end_idx = block_idx
                                    table_start_set = True
                    non_table_row_count = 0
                    prev_too_much_space = False

                if new_table:
                    table_row_with_max_cols = block
                    if not table_start_set:
                        table_start_idx = block_idx
                        table_end_idx = block_idx
                    if table_parser.TABLE_DEBUG:
                        print(f"\ttable changed: align: {align_count}, "
                              f"align-break: {alignment_break}, page: {page_change}, section: {different_section}")
                        print("\n<table>\n")
                else:
                    table_start_idx = -1
                    table_end_idx = -1
                    n_table_cols = 0
                    # non_table_row_count = 0
                    if table_parser.TABLE_DEBUG or table_parser.TABLE_BOUNDS_DEBUG:
                        print(f"\ttable ended: section: {different_section}, no rows: {no_more_table_rows}, "
                              f"alignment: {alignment_break}")
                        print("\t", block["block_text"][0:80])
                        print("\n</table>\n")

            prev_class_name = class_name
            prev_line_style = line_style
            if is_table_row:
                prev_table_row = block
            prev_too_much_space = too_much_space
            if block["block_type"] == "list_item":
                block["list_type"] = Doc.get_list_item_subtype(block)
            if self.detect_block_center_aligned(block, enable_width_check=False) and \
                    parenthesized_hdr_pattern.search(block["block_text"]) is not None and \
                    block["block_type"] != "header_modified_to_para":
                if block["block_type"] != "table_row":
                    block["block_type"] = "header"
                    block["header_type"] = "parenthesized_hdr"
                curr_block = block
                block = organized_blocks.pop()
                if block["block_type"] != "table_row" and curr_block["block_type"] != "table_row":
                    # Change the block_class and block_idx
                    block["block_class"], curr_block["block_class"] = curr_block["block_class"], block["block_class"]
                    block["block_idx"], curr_block["block_idx"] = curr_block["block_idx"], block["block_idx"]
                    if block["block_type"] == "header":
                        block["block_type"] = "header_modified_to_para"
                if curr_block["block_type"] == "table_row":
                    if not table_row_with_max_cols or \
                            vhu.find_num_cols(curr_block)[0] > vhu.find_num_cols(table_row_with_max_cols)[0]:
                        table_row_with_max_cols = curr_block
                organized_blocks.append(curr_block)
            if block["block_type"] == "table_row":
                if not table_row_with_max_cols or \
                        vhu.find_num_cols(block)[0] > vhu.find_num_cols(table_row_with_max_cols)[0]:
                    table_row_with_max_cols = block
            organized_blocks.append(block)
            idx = idx + 1
            block["block_idx"] = block_idx
            block_idx = block_idx + 1
            prev_block = block

        if len(block_buf) > 0:
            if prev_block:
                block_buf.append(prev_block)
            # merge all the collected blocks into a single block
            new_block = self.merge_blocks(block_buf)
            block_buf = []
            if BLOCK_DEBUG:
                print("merging last block", new_block["block_text"], new_block["block_type"])
            if new_block["block_type"] == "list_item":
                new_block["list_type"] = Doc.get_list_item_subtype(new_block)
            organized_blocks.pop()  # replace previous single block with combo
            organized_blocks.append(new_block)

        if table_start_idx != table_end_idx:
            self.build_table(block_idx, organized_blocks, table_start_idx, table_end_idx + 1)

        i = 0
        prev_header_block = None
        para_to_header_blocks_font_decider = []
        while i < len(organized_blocks):
            a_block = organized_blocks[i]
            line_props = line_parser.Line(a_block["block_text"])
            if a_block["block_type"] == "header" and line_props.numbered_line:
                first_sent = line_props.line_without_number.split(".")[0]
                if line_parser.Line(first_sent).is_header:
                    a_block["list_type"] = Doc.get_list_item_subtype(a_block)
            if a_block["block_type"] in ["para", "list_item", "header_modified_to_para"]:
                possible_header = a_block["visual_lines"][-1]["line_style"] in self.header_styles
                # Check if block_class is not the same as last VL class,
                # then should check for majority block class also, since most words belong to block_class
                block_class_possible_header = True
                if a_block.get('block_class', '') and \
                        a_block['block_class'] != a_block['visual_lines'][-1].get('class', '') and \
                        self.class_line_styles[a_block['block_class']] not in self.header_styles:
                    block_class_possible_header = False
                # Multi-sentences are not generally headings, so consider them as the original block_type.
                all_vls_incomplete_line = True
                for vls in a_block["visual_lines"]:
                    lp = vls.get("line_parser", None)
                    if lp:
                        all_vls_incomplete_line = all_vls_incomplete_line and lp["incomplete_line"]
                        if not all_vls_incomplete_line:
                            break
                    else:
                        all_vls_incomplete_line = False
                        break
                bulleted_list_item = "list_type" in a_block and a_block["list_type"] in line_parser.list_types.values()
                should_be_header = (possible_header
                                    and line_props.alpha_count > 0
                                    and not bulleted_list_item
                                    and (line_props.word_count < 16 or
                                         (line_props.word_count < 20 and
                                          line_props.incomplete_line and not line_props.continuing_line and
                                          all_vls_incomplete_line and not line_props.last_continuing_char))
                                    and line_props.list_type not in ["letter_arrow"]
                                    and block_class_possible_header)
                if possible_header and not should_be_header:
                    # Remove from the header_styles
                    self.header_styles.remove(a_block["visual_lines"][-1]["line_style"])
                    # Revert any old blocks that was converted to header back to its original type
                    for b in para_to_header_blocks_font_decider:
                        if b["visual_lines"][-1]["line_style"] == a_block["visual_lines"][-1]["line_style"] and\
                                b.get("orig_block_type", "") and b["orig_block_type"] == "para" and \
                                ends_with_sentence_delimiter_pattern.search(b["block_text"]) is not None:
                            b["block_type"] = b["orig_block_type"]
                            b.pop("orig_block_type", None)
                if should_be_header and a_block["block_type"] != "header_modified_to_para":
                    a_block["orig_block_type"] = a_block["block_type"]
                    a_block["block_type"] = "header"
                    para_to_header_blocks_font_decider.append(a_block)
                elif a_block["block_type"] == "header_modified_to_para":
                    a_block["block_type"] = "para"

                should_be_list = line_props.numbered_line
                first_sent = ""
                para_sentence = ""
                add_para_block = False
                section_header = False
                if a_block["block_type"] == "list_item" and should_be_list:
                    line_w_o_num = line_props.line_without_number
                    # Do not divide on texts like 2.03 or section 1.45
                    for m in floating_number_pattern.finditer(line_w_o_num, re.MULTILINE):
                        t = m.group()
                        t = t.replace(".", "__dot__")
                        line_w_o_num = line_w_o_num.replace(m.group(), t)

                    first_sent = line_w_o_num.split(".")[0].strip()
                    first_sent = first_sent.replace("__dot__", ".")

                    lp_first_sent = line_parser.Line(first_sent)
                    different_fonts = False
                    if (lp_first_sent.is_header and lp_first_sent.is_reference_author_name) or \
                            lp_first_sent.is_header_without_comma:
                        diff_in_len = len(a_block['block_text'].split()) - len(line_props.line_without_number.split())
                        if diff_in_len > 0:
                            vl_word_classes = []
                            # Collect the word classes for further processing.
                            for v in a_block['visual_lines']:
                                vl_word_classes.extend(v['word_classes'])
                                if len(vl_word_classes) > (len(first_sent.split()) + diff_in_len + 1):
                                    break
                            if vl_word_classes and len(vl_word_classes) > (len(first_sent.split()) + diff_in_len):
                                prev_class_name = vl_word_classes[len(first_sent.split()) + diff_in_len - 1]
                                curr_class_name = vl_word_classes[len(first_sent.split()) + diff_in_len]
                                if self.has_smaller_or_lighter_header_font(prev_class_name, curr_class_name):
                                    # Check whether the previous word is of higher font than the current one.
                                    different_fonts = True
                    if (lp_first_sent.is_header or lp_first_sent.is_header_without_comma) and\
                            (not lp_first_sent.is_reference_author_name or different_fonts):
                        a_block["block_type"] = "header"
                        a_block["list_type"] = Doc.get_list_item_subtype(a_block)
                        para_sentence = line_props.line_without_number[len(first_sent) + 1:].strip()
                        para_sentence = start_punct_pattern.sub("", para_sentence).strip()
                        if len(a_block["visual_lines"]) >= 1 and para_sentence:
                            add_para_block = True
                    if lp_first_sent.is_header and lp_first_sent.is_header_without_comma \
                            and lp_first_sent.is_reference_author_name:
                        # Last ditch effort to make it not an author name and to consider it as a header.
                        consider_as_header = False
                        for rev_blk in organized_blocks[i::-1]:
                            if rev_blk["block_type"] == "header" and \
                                    self.has_same_or_bigger_font(rev_blk["block_class"], a_block["block_class"]):
                                consider_as_header = True
                                break
                        if consider_as_header:
                            a_block["block_type"] = "header"
                            a_block["list_type"] = Doc.get_list_item_subtype(a_block)
                            para_sentence = line_props.line_without_number[len(first_sent) + 1:].strip()
                            para_sentence = start_punct_pattern.sub("", para_sentence).strip()
                            if len(a_block["visual_lines"]) >= 1 and para_sentence:
                                add_para_block = True
                elif a_block["block_type"] == "para" and \
                        (should_be_list or
                         (a_block["block_text"].lower().startswith("section ") and
                          a_block["block_text"][0].isupper() and
                          section_generic_pattern.search(a_block["block_text"].lower()) is not None)):
                    if should_be_list:
                        first_sent = line_props.line_without_number.split(".")[0]
                        title = a_block["block_text"][:a_block["block_text"].find(first_sent) + len(first_sent)]
                        para_sentence = line_props.line_without_number[len(first_sent) + 1:].strip()
                        para_sentence = start_punct_pattern.sub("", para_sentence).strip()
                        lp_first_sent = line_parser.Line(first_sent)

                        a_block["block_type"] = "list_item"
                        a_block["list_type"] = Doc.get_list_item_subtype(a_block)
                        if lp_first_sent.is_header and len(a_block["visual_lines"]) > 1 and para_sentence:
                            add_para_block = True
                        elif lp_first_sent.is_header and (len(a_block["visual_lines"]) == 1 or
                                                                         not para_sentence) and not lp_first_sent:
                            a_block["block_type"] = "header"
                            a_block["block_sents"] = [first_sent]
                            a_block["block_text"] = title
                    else:
                        # For text with Sections
                        match = section_generic_pattern.match(a_block["block_text"].lower())
                        if match:
                            section_header = True
                            first_sent = a_block["block_text"][:len(match.group())].strip()
                            title = first_sent
                            a_block["block_type"] = "header"
                            a_block["block_sents"] = [first_sent]
                            para_sentence = a_block["block_text"][len(first_sent) + 1:].strip()
                            a_block["block_text"] = title
                            if len(para_sentence):
                                add_para_block = True

                if para_sentence and add_para_block:
                    idx = a_block["block_idx"]
                    title = a_block["block_text"][:a_block["block_text"].find(first_sent) + len(first_sent)]

                    header_block = {
                        "block_class": a_block["block_class"],
                        "block_idx": idx,
                        "block_sents": [first_sent],
                        "block_text": title,
                        "block_type": "header",
                        "box_style": a_block["box_style"],
                        "header_block_idx": a_block.get("header_block_idx", header_block_idx),
                        "header_text": a_block.get("header_text", ""),
                        "page_idx": a_block["page_idx"],
                        "visual_lines": [copy.deepcopy(a_block["visual_lines"][0])],  # Is this correct ???
                    }
                    # Add only if present. Only if should_be_list == True
                    if a_block.get("list_type", None):
                        header_block["list_type"] = a_block["list_type"]

                    para_block = a_block
                    para_block["block_idx"] = idx + 1
                    para_block["block_type"] = "para"
                    para_block["block_sents"].pop(0)
                    para_block["header_text"] = first_sent
                    para_block["header_block_idx"] = idx
                    para_vls = []
                    consider_para_vls = False
                    if section_header or len(a_block["visual_lines"][0]['text']) < len(first_sent):
                        consider_para_vls = True
                        temp_first_sent = first_sent.replace(a_block["visual_lines"][0]["text"], "").strip()
                        block_start_vl_idx = 1
                        if len(a_block["visual_lines"]) == 1:
                            # There is only one VL, so divide them to header and para.
                            block_start_vl_idx = 0
                        for vl_idx, vl in enumerate(a_block["visual_lines"][block_start_vl_idx:]):
                            vl["text"] = start_punct_pattern.sub("", vl["text"].strip()).strip()
                            all_done = True
                            first_sent_words = temp_first_sent.split()
                            for word in first_sent_words:
                                word = start_punct_pattern.sub("", word.strip()).strip()
                                if not vl["text"]:
                                    all_done = False
                                    break
                                elif vl["text"].strip().startswith(word):
                                    temp_first_sent = temp_first_sent.replace(word, "").strip()
                                    vl["text"] = vl["text"][len(word):].strip()
                                    vl["word_classes"] = vl["word_classes"][1:] \
                                        if len(vl["word_classes"]) > 1 else vl["word_classes"]
                            if all_done:
                                vl["text"] = start_punct_pattern.sub("", vl["text"].strip()).strip()
                                start_idx = vl_idx + 1 if block_start_vl_idx > 0 else vl_idx
                                if not vl["text"]:
                                    start_idx += 1
                                para_vls = a_block["visual_lines"][start_idx:]
                                break
                    elif len(header_block['block_text']) + 1 < len(a_block["visual_lines"][0]['text']):
                        # Added "+ 1" to the condition to accommodate for last special character.
                        # Header is actually a part of the first VL. Trim it.
                        consider_para_vls = True
                        a_block["visual_lines"][0]['text'] = \
                            a_block["visual_lines"][0]['text'].replace(header_block['block_text'], "").strip()
                        a_block["visual_lines"][0]['text'] = \
                            start_punct_pattern.sub("", a_block["visual_lines"][0]['text'].strip()).strip()
                        len_header_words = len(header_block['block_text'].split())
                        if len_header_words < len(a_block["visual_lines"][0]["word_classes"]):
                            a_block["visual_lines"][0]["word_classes"] = \
                                a_block["visual_lines"][0]["word_classes"][len(header_block['block_text'].split()):]
                        else:
                            a_block["visual_lines"][0]["word_classes"] = \
                                a_block["visual_lines"][0]["word_classes"][
                                -len(a_block["visual_lines"][0]['text'].split()):]

                        para_vls = a_block["visual_lines"]

                    para_block["visual_lines"] = para_vls if consider_para_vls else a_block["visual_lines"][1:]
                    para_block["block_text"] = para_sentence
                    if not para_block["block_sents"]:
                        para_block["block_sents"] = sent_tokenize(para_sentence)
                    para_block.pop("list_type", None)
                    j = idx + 1
                    while j < len(organized_blocks):
                        organized_blocks[j]["block_idx"] += 1
                        if "header_block_idx" in organized_blocks[j] and organized_blocks[j]["header_block_idx"] > idx:
                            organized_blocks[j]["header_block_idx"] += 1
                        j += 1

                    organized_blocks[idx] = header_block
                    if len(para_block["visual_lines"]):
                        para_props = line_parser.Line(para_block["block_text"])
                        if para_props.numbered_line:
                            para_block['block_type'] = 'list_item'
                            para_block["list_type"] = Doc.get_list_item_subtype(para_block)
                        organized_blocks.insert(idx+1, para_block)
                    i += 1

            self.post_fix(a_block)
            i += 1
        
        self.blocks = self.parse_special_lists(organized_blocks)
        self.divide_para_to_headers()
        self.merge_para_blocks()
        self.merge_header_blocks()
        self.merge_ooo_para_list_blocks()
        self.merge_ooo_list_para_blocks()
        self.merge_center_aligned_header_para_blocks()
        self.correct_blk_idxs()
        # self.indent_blocks()
        indent = indent_parser.IndentParser(self)
        indent.indent_blocks()
        self.blocks = indent.blocks
        # self.class_levels = class_levels
        # print(self.class_levels)

    def build_table(self, block_idx, organized_blocks, table_start_idx, table_end_idx):
        footer_count, footers = self.get_table_footers(organized_blocks, table_start_idx, table_end_idx)
        if table_parser.TABLE_DEBUG:
            print(">>>>> building table.. footer count", footer_count)
            print("\ttable start idx", table_start_idx, organized_blocks[table_start_idx]['block_text'])
            print("\ttable end idx", table_end_idx)
            print("\tblock_idx", block_idx)
        if table_end_idx - footer_count - table_start_idx > 1:
            block_idx, table_end_idx = self.make_table_with_footers(block_idx, footer_count, footers,
                                                                    organized_blocks, table_start_idx, table_end_idx)
        else:
            # one row table
            tr_block = organized_blocks[table_start_idx]
            tr_block['block_type'] = get_block_type(False, False, tr_block["block_text"])[0]
            # for parsing special lists
            tr_block['one_row_table'] = True

        return block_idx, footer_count

    def parse_special_lists(self, blocks):

        def check_special_line(block):
            for line_idx, line in enumerate(block["visual_lines"]):
                # print(line["text"])
                if not "line_parser" in line or not line["line_parser"]["noun_chunks"]:
                    line["line_parser"] = line_parser.Line(line["text"]).to_json()
                if not line["line_parser"]["noun_chunks"]:
                    return False
                noun_chunk = non_alphanumeric_pattern.sub(' ', line["line_parser"]["noun_chunks"][0]).strip()
                text = non_alphanumeric_pattern.sub(' ', line["text"]).strip()
                upper_check = all([token[0].isupper() for token in text.split()])
                bolded_text = line["line_style"][1] == "bold" or line["line_style"][3] > 400
                large_text = line["line_style"][2] > 9
                # print(line["text"])
                # print(noun_chunk == text, bolded_text, large_text)
                if not ((upper_check or noun_chunk) and bolded_text and large_text):
                    return False  
            return True
        
        def blocks_to_list(start_idx, end_idx):
            header_text = ""
            header_idx = end_idx
            while not header_text:
                if blocks[header_idx]["block_type"] == "header":
                    header_text = blocks[header_idx]["block_text"]
                header_idx -= 1
            # convert block to list
            j = start_idx
            # get the longest span between table and header detection
            while j <= end_idx:
                curr_block = blocks[j]
                for line_idx, line in enumerate(curr_block["visual_lines"]):
                    underwriter_block = {
                        "block_class": line["class"],
                        "block_idx": j,
                        "block_sents": [line["text"]],
                        "block_text": line["text"],
                        "block_type": "list_item",
                        "list_type": "",
                        "underwriter_block": True,
                        "box_style": line["box_style"],
                        "header_block_idx": -1,
                        "header_text": header_text,
                        "page_idx": line["page_idx"],
                        "visual_lines": [line]
                    }
                    # replace current block then insert new lists blocks
                    if curr_block in blocks:
                        blocks[j] = underwriter_block
                    else:
                        blocks.insert(j+1, underwriter_block)
                        j += 1
                        # i += 1
                        end_idx += 1
                j += 1

        is_table, is_special = False, False
        center_italic_idx = 0
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if block["block_type"] == "list_item" and not block.get("list_type", None):
                block["list_type"] = Doc.get_list_item_subtype(block)
            if (block["block_type"] == "table_row" or "one_row_table" in block) and not is_table:
                is_table = True
                is_special = True
                table_start_idx = i

            # check if the table is underwriter
            if is_table and is_special:
                is_special = check_special_line(block)
                            
            # another method to check from special header "co-managers" then down
            if 0 < len(block["visual_lines"]) < 4 and block["visual_lines"][0]["line_style"][1] == "italic" \
                    and self.detect_block_center_aligned(block):
                # print("found", block["block_text"])
                center_italic_idx = i + 1
                if center_italic_idx < len(blocks) and self.detect_block_center_aligned(blocks[center_italic_idx]) and \
                        block["page_idx"] != blocks[center_italic_idx]["page_idx"]:
                    center_italic_idx = i
                else:
                    while center_italic_idx < len(blocks) and check_special_line(blocks[center_italic_idx]):
                        # print(blocks[center_italic_idx]["block_text"])
                        center_italic_idx += 1

            if center_italic_idx > i and not is_special:
                blocks_to_list(i+1, center_italic_idx - 1)
                center_italic_idx = 0
            # table ended, check if needs to be converted to list
            elif "is_table_end" in block or "one_row_table" in block:
                end_idx = i
                # take care of 1 column underwriter case (only for table)
                if i + 1 < len(blocks) and block["block_class"] == blocks[i+1]["block_class"]:
                    end_idx += 1
                if is_special:
                    blocks_to_list(table_start_idx, max(center_italic_idx, end_idx))
                # reset variable
                is_table = False

            if "one_row_table" in block:
                del block["one_row_table"]
               
            i += 1  
        return blocks 

    def calculate_block_bounds_from_vls(self, blocks):
        top = blocks[0]['visual_lines'][0]['box_style'][0]
        bottom = blocks[-1]['visual_lines'][0]['box_style'][0] + blocks[-1]['visual_lines'][0]['box_style'][4]
        left = 1000000
        right = -1
        for block in blocks:
            left = min(block['visual_lines'][0]['box_style'][1], left)
            right = max(block['visual_lines'][-1]['box_style'][2], right)

        #returns x, y, w, h
        return (left, top, right, bottom)

    def calculate_block_bounds(self, blocks):
        top = blocks[0]['box_style'][0]
        bottom = blocks[-1]['box_style'][0] + blocks[-1]['box_style'][4]
        left = 1000000
        right = -1
        for block in blocks:
            left = min(block['box_style'][1], left)
            right = max(block['box_style'][2], right)
        #returns x, y, w, h
        return (left, top, right - left, bottom - top)

    def make_table_with_footers(self, block_idx, footer_count, footers, organized_blocks, table_start_idx, table_end_idx):
        possible_table_blocks = organized_blocks[table_start_idx: table_end_idx - footer_count]
        (left, top, w, h) = self.calculate_block_bounds(possible_table_blocks)
        # see if the row before belongs to the table too
        if table_start_idx > 0:
            prev_block = organized_blocks[table_start_idx - 1]
            curr_top_block = organized_blocks[table_start_idx]
            same_class = prev_block["visual_lines"][-1]["line_style"] == curr_top_block["visual_lines"][-1]["line_style"]
            prev_box = prev_block["box_style"]
            curr_top_box = curr_top_block["box_style"]
            # look forward to see if there is alignment
            is_aligned = False
            for row_idx in range(table_start_idx, min(table_end_idx, table_start_idx + 3)):
                # next 3 blocks
                # print(organized_blocks[row_idx]["block_text"])
                align_count, prev_count, align_pos = table_parser.get_alignment_count(prev_block,
                                                                                      organized_blocks[row_idx])
                if align_count / prev_count > 0.5 and len(set(align_pos)) > 1:
                    is_aligned = True
                    break
            if ((same_class or (is_aligned and
                                Doc.check_line_between_box_styles(prev_box, curr_top_box,
                                                                  self.page_svg_tags[curr_top_block["page_idx"]][0],
                                                                  x_axis_relaxed=True)))
                    and "is_table_end" not in prev_block
                    and prev_block["block_type"] != "header_modified_to_para"
                    and (prev_box[1]/left > 1.1)  # or is_aligned)
                    and prev_box[0] < curr_top_box[0]
                    and not self.detect_block_center_aligned(prev_block)
                    and not prev_block["block_text"].isupper()):
                prev_block["visual_lines"], _, _ = self.merge_vls_if_needed(prev_block["visual_lines"])
                prev_block["block_type"] = "table_row"
                # print(">>>> adding", prev_block["block_text"], prev_block["visual_lines"][-1]["line_style"])
                # print("\t>>>> prev", curr_top_block["block_text"], curr_top_block["visual_lines"][-1]["line_style"])
                table_start_idx = table_start_idx - 1

        possible_table_blocks = organized_blocks[table_start_idx: table_end_idx - footer_count]
        # reset bounds using newly added block
        # (left, top, w, h) = self.calculate_block_bounds(possible_table_blocks)

        tp = table_parser.TableParser(self, possible_table_blocks)
        real_blocks = tp.parse_table()
        diff = len(possible_table_blocks) - len(real_blocks)
        if diff > 0:
            if table_parser.TABLE_DEBUG:
                print("old blocks are:", block_idx, len(possible_table_blocks), diff)
                for new_block in possible_table_blocks:
                    print("<---", new_block["block_text"][0:40])

                print("new blocks are:", len(real_blocks), block_idx - diff - 1)
            del organized_blocks[table_start_idx: table_end_idx]
            for new_block in real_blocks:
                if table_parser.TABLE_DEBUG:
                    print("--->", new_block["block_text"][0:40])
                organized_blocks.append(new_block)
            block_idx = block_idx - diff
            table_end_idx = block_idx
            # add back the footers
            for footer in footers:
                organized_blocks.append(footer)
        return block_idx, table_end_idx

    def get_table_footers(self, organized_blocks, table_start_idx, table_end_idx, ):
        end_idx = table_end_idx - 1
        footer_count = 0
        while end_idx > table_start_idx:
            table_block = organized_blocks[end_idx]
            if table_block["block_type"] != 'table_row' and 'aligned_para' not in table_block:
                footer_count = footer_count + 1
                if table_parser.TABLE_DEBUG:
                    print("footer>>>", table_block['block_text'][0:80])
            else:
                break
            end_idx = end_idx - 1
        footers = []
        if footer_count > 0:
            footers = organized_blocks[-footer_count:]
        return footer_count, footers

    def should_ignore(self, block_text, block_type=None):
        ignore = False
        ignore_all_after = False
        for ig in self.ignore_blocks:
            if block_type == "header":
                if block_text == ig.ignore_text and ig.ignore_all_after:
                    ignore_all_after = True
            elif block_text in ig.ignore_text:
                ignore = True
        return ignore, ignore_all_after

    def collapse_group(self, group_buf, group_class_name):
        buf_text = ""
        if len(group_buf) == 0:
            return buf_text, None, [-1]
        total_space = 0
        page_idxs = []
        for idx, item in enumerate(group_buf):
            buf_text = buf_text + self.check_add_space_btw_texts(buf_text, item["text"]) + item["text"]
            page_idxs.append(item["page_idx"])
            if idx > 0:
                total_space = total_space + item["space"]
        # table parsing should be done here
        buf_text = buf_text.lstrip()
        n_lines = len(group_buf)
        if group_class_name in self.class_stats:
            class_stat = self.class_stats[group_class_name]
        else:
            class_stat = {"total_space": 0.0, "n_lines": 0, "n_groups": 0, "texts": []}
        class_stat["total_space"] = class_stat["total_space"] + total_space
        class_stat["n_lines"] = class_stat["n_lines"] + n_lines
        class_stat["texts"].append(buf_text)
        class_stat["n_groups"] = class_stat["n_groups"] + 1
        class_stat["n_joined_lines"] = class_stat["n_lines"] - class_stat["n_groups"]
        class_stat["avg_space"] = 0.0
        # if group_class_name == 'cls_26':  # and class_stat['avg_space'] < 10:
        #     print(class_stat['n_joined_lines'])
        if class_stat["n_joined_lines"] > 0:
            class_stat["avg_space"] = (
                class_stat["total_space"] / class_stat["n_joined_lines"]
            )
        self.class_stats[group_class_name] = class_stat
        buf_info = group_buf[0]
        return buf_text, buf_info, page_idxs

    def compress_blocks(self):
        for block in self.blocks:
            if 'visual_lines' in block:
                del block['visual_lines']
            if 'orig_vls' in block:
                del block['orig_vls']
            if 'effective_header' in block:
                del block['effective_header']['visual_lines']
            if 'effective_para' in block:
                del block['effective_para']['visual_lines']
            if 'child_blocks' in block:
                for child_block in block['child_blocks']:
                    if 'visual_lines' in child_block:
                        del child_block['visual_lines']

    @staticmethod
    def get_list_item_subtype(block):
        lp = line_parser.Line(block["block_text"])
        item_subtype = "bullet"
        if lp.roman_numbered_line:
            item_subtype = "roman"
        elif lp.integer_numbered_line:
            item_subtype = "integer"
        elif lp.letter_numbered_line:
            item_subtype = "letter"
        elif lp.dot_numbered_line:
            item_subtype = "integer-dot"
        else:
            return lp.list_type
        return item_subtype

    @staticmethod
    def merge_line_info(first, second, remove_space=False):
        height = max(first["box_style"][4], second["box_style"][4])
        if first["box_style"][0] != second["box_style"][0]:
            if first["box_style"][0] < second["box_style"][0]:
                height = (second["box_style"][0] + second["box_style"][4]) - first["box_style"][0]
            else:
                height = (first["box_style"][0] + first["box_style"][4]) - second["box_style"][0]

        box_style = BoxStyle(
            first["box_style"][0],
            first["box_style"][1],
            second["box_style"][2],
            first["box_style"][3] + second["box_style"][3],
            height
        )
        combined_text = first["text"] + Doc.check_add_space_btw_texts(first['text'], second["text"]) + second["text"]
        lp_line = line_parser.Line(combined_text)
        combined_block = {
            'box_style': box_style,
            # Below one needs to be majority. (len words)
            'line_style': first["line_style"] if len(first["text"]) > 1 else second["line_style"],
            'text': combined_text,
            'page_idx': first["page_idx"],
            'word_classes': first["word_classes"] + second["word_classes"],
            'class': first["class"],
            'space': 0.0,
            'lp_line': lp_line,
            'line_parser': lp_line.to_json(),
            'changed': (first["changed"] if "changed" in first else False) or (second["changed"] if "changed" in second else False)

        }
        return combined_block

    @staticmethod
    def get_location_key(box_style, line_text):
        line_text = only_text_pattern.sub("", line_text)  # re.sub(r"[^a-zA-Z]+", "", line_text)
        line_text = roman_only_pattern.sub("", line_text)
        return LocationKey(
            int(box_style[0]),
            int(box_style[1]),
            line_text
        )

    @staticmethod
    def find_true_header_footers(
            hf,
            num_pages,
            is_footer=False,
    ):

        def get_hf_keys_with_same_text(hf: dict, hf_key: namedtuple, check_page_pattern, page_pat_val):
            m_keys = []
            m_pages = []
            for key in hf.keys():
                if not check_page_pattern:
                    if page_num_pattern.search(key[2]) is not None:
                        page_pat_val.append(key[2])
                if abs(key[0] - hf_key[0]) < 20 and abs(key[1] - hf_key[1]) < 20 and \
                        (key[2] == hf_key[2] or key[2] in page_pat_val):
                    m_keys.append(key)
                    m_pages.append(hf[key])
            m_pages = [item for sublist in m_pages for item in sublist]
            return m_keys, sorted(list(dict.fromkeys(m_pages))) if len(m_pages) > 1 else m_pages, True, page_pat_val

        def is_footer_key_below_page_num_footer(f_key, refined_footers, footers):
            """
            Checks whether the footer is below the page number footers.
            :param f_key: Footer under consideration.
            :param refined_footers: List of all footers which will be skipped.
            :param footers: List of all footers
            :return: True if the footer is below the page number footers
            """
            f_key_pages = footers[f_key]
            for k, pages in refined_footers.items():
                # Page number footers will have text field == ""
                if f_key_pages[0] in pages and k[0] <= f_key[0]:
                    return True
            return False

        result = {}
        page_pattern_list = []
        check_page_pattern = False
        for hf_key in hf.keys():
            if hf_key in result:
                continue
            key_with_text_added = False
            m_key = None
            for already_added_key in result.keys():
                if already_added_key.text == hf_key.text:
                    key_with_text_added = True
                    m_key = already_added_key
                    break
            if not key_with_text_added:
                matched_keys, list_of_pages, check_page_pattern, page_pattern_list = \
                    get_hf_keys_with_same_text(hf, hf_key, check_page_pattern, page_pattern_list)
            else:
                matched_keys = [hf_key]
                list_of_pages = result[m_key]
                for p in hf[hf_key]:
                    if p not in list_of_pages:
                        list_of_pages.append(p)
            num_matched_pages = len(list_of_pages)
            diff_of_pages = np.diff(list_of_pages)
            if num_matched_pages > 1 and (np.mean(diff_of_pages) <= 2 or
                                          (np.median(diff_of_pages) <= 2 and is_footer
                                           and hf_key.text != "" and
                                           is_footer_key_below_page_num_footer(hf_key, result, hf)) or
                                          (np.median(diff_of_pages) <= 2 and
                                           Counter(diff_of_pages).most_common()[0][0] <= 2 and
                                           np.percentile(diff_of_pages, 75) <= 2)):
                if num_matched_pages > 0.5 * num_pages or hf_key.text == '' or \
                        (num_matched_pages > 0.2 * num_pages and max(list_of_pages) > 2) or \
                            (num_matched_pages > 5 and max(list_of_pages) > 2):
                    # 50% of pages have these OR if text is empty, this is most likely to be a footer with Page numbers
                    if HF_DEBUG:
                        print("will skip header/footer: ", matched_keys, list_of_pages)
                    for key in matched_keys:
                        if hf_key.text != '' or is_footer:
                            result[key] = list_of_pages
                        else:
                            result[key] = hf[key]
        return result

    @staticmethod
    def calc_block_span(block):
        n_lines = 1
        block_vl = block['visual_lines']
        prev_vl_box = block_vl[0]['box_style']
        top = prev_vl_box[0]
        min_left = prev_vl_box[1]
        max_right = prev_vl_box[2]
        height = prev_vl_box[4]
        # print(block['block_text'][0:20], "n_vls:", len(block_vl))
        for vl in block_vl[1:]:
            vl_box = vl['box_style']
            if vl_box[0] > prev_vl_box[0]:
                n_lines = n_lines + 1
                height = height + vl_box[4] + (vl_box[0] - (prev_vl_box[0] + prev_vl_box[4]))
                prev_vl_box = vl_box
            elif vl_box[0] == prev_vl_box[0]:
                n_lines = n_lines + 1
                height = max(height, vl_box[4])
                prev_vl_box = vl_box
            min_left = min(vl_box[1], min_left)
            max_right = max(vl_box[2], max_right)

        box_style = BoxStyle(
            top,
            min_left,
            max_right,
            max_right - min_left,
            height
        )
        # print("--")
        # print("bounds for ", block['block_text'])
        # print(box_props)
        return box_style

    @staticmethod
    def has_page_number(text, last_line_counts):
        # num_only = re.sub(r"[^0-9]+", "", text).strip()
        if text.strip().isdigit():
            return True
        else:
            text_only = text_only_pattern.sub("", text).strip()
            if text_only in last_line_counts and last_line_counts[text_only] > 1:
                return True
        return False

    @staticmethod
    def have_y_overlap(block1, block2, check_class=True):
        do_overlap = False
        same_class = True
        if check_class:
            same_class = block1["block_class"] == block2["block_class"]
        # prev block
        box1 = block1['box_style']
        # curr block
        box2 = block2['box_style']
        if block1["page_idx"] == block2["page_idx"] and same_class:
            box1_bottom = box1[0] + box1[4]
            box2_bottom = box2[0] + box2[4]
            threshold = 1.0
            cond_1 = box1[0] < box2_bottom and box1_bottom - box2[0] > threshold
            cond_2 = box2[0] - box1_bottom < threshold and box2_bottom > box1[0]
            cond_3 = box1_bottom > box2_bottom > box1[0]

            do_overlap = (cond_1 or cond_2 or cond_3) and box2[1] > box1[2]
            # print("!!!", cond_1, cond_2, "->", box2[1], box1.right, box1.top, box1_bottom, box2.top, box2_bottom, do_overlap)
            # print('y-overlap-> ', do_overlap, len(block1["visual_lines"]), block1["block_type"], block1["visual_lines"][-1]["box_style"].right)
            if MERGE_DEBUG and do_overlap:
                print(block1["page_idx"], block2["page_idx"])
                print('y-overlap-> ', do_overlap, block1['block_text'][0:60] + "->" + block2['block_text'][0:60])
                print(box1, box2)
                print(cond_1, box1[0] < box2_bottom, box1_bottom - box2[0] > threshold)
                print(cond_2, box2[0] - box1_bottom > threshold, box2_bottom > box1[0])
                print("\n")
        if block1["page_idx"] == block2["page_idx"] and round(box1[0], 1) == round(box2[0], 1):
            do_overlap = True
        return do_overlap

    @staticmethod
    def merge_vls(vl_merge_buf):
        word_classes = []
        vl_top = sys.maxsize
        vl_height = 0
        vl_left = sys.maxsize
        vl_right = 0
        vl_texts = []
        for mvl in vl_merge_buf:
            vl_box = mvl['box_style']
            word_classes = word_classes + mvl["word_classes"]
            vl_texts.append(mvl['text'])
            vl_top = min(vl_box[0], vl_top)
            vl_left = min(vl_box[1], vl_left)
            vl_height = max(vl_box[0] + vl_box[4] - vl_top, vl_height)
            vl_right = max(vl_box[2], vl_right)

        vl_box_style = BoxStyle(
            vl_top,
            vl_left,
            vl_right,
            vl_right - vl_left,
            vl_height
        )
        vl_text = " ".join(vl_texts)
        if MERGE_DEBUG:
            print(f"\tmerged {len(vl_merge_buf)} vls into: ", vl_text)
        lp_line = line_parser.Line(vl_text)
        merged_vl = {"text": vl_text,
                     "line_style": vl_merge_buf[0]["line_style"],
                     "page_idx": vl_merge_buf[0]["page_idx"],
                     "box_style": vl_box_style,
                     "class": word_classes[0],
                     "line_parser": lp_line.to_json(),
                     "word_classes": word_classes}
        return merged_vl

    def make_block(self, vls, block_type, block_idx):
        block_text = ""
        for vl in vls:
            block_text = block_text + self.check_add_space_btw_texts(block_text, vl["text"]) + vl["text"]
        block = {
            "block_idx": block_idx,
            "page_idx": vls[0]["page_idx"],
            "block_type": block_type,
            "block_text": block_text.strip(),
            "visual_lines": vls,
            "block_class": vls[0]["word_classes"][0],
        }
        block["box_style"] = self.calc_block_span(block)
        block_sents = sent_tokenize(block["block_text"])
        block["block_sents"] = block_sents
        return block

    def merge_blocks(self, blocks):
        merged_text = ""
        vls = []
        merge_vls_idx = 0
        min_top = 1000000
        max_height = 0
        width = 0
        left = blocks[0]['box_style'][1]
        prev_block = None
        any_block_table_row = False
        all_blocks_to_the_right = True
        same_top = True

        if MERGE_DEBUG:
            print(f"merging {len(blocks)} blocks..")
        if len(blocks) == 1:
            return blocks[0]
        for block in blocks:
            any_block_table_row = any_block_table_row or (block["block_type"] == "table_row")
            if same_top and prev_block:
                all_blocks_to_the_right = all_blocks_to_the_right and prev_block["box_style"][2] < block["box_style"][1]
            merged_text = merged_text + self.check_add_space_btw_texts(merged_text, block["block_text"]) \
                          + block["block_text"]
            block_vls = block["visual_lines"]
            # merge visual lines if they are close enough or overlap on x axis - reset merged block bounds
            # if visual lines are far apart, leave them alone
            prev_vl = block_vls[0]
            vl_merge_buf = [prev_vl]
            if MERGE_DEBUG:
                print(" evaluating block: ", block["block_text"], ", #vls: ", len(block_vls))
            for vl in block_vls[1:]:
                same_top = same_top and abs(prev_vl['box_style'][0] - vl['box_style'][0]) < 0.1
                if MERGE_DEBUG:
                    print("\tvl ", vl['text'])
                    print("\tvl buf has ", len(vl_merge_buf))
                vl_style = self.class_line_styles[vl['word_classes'][0]]
                if vl['box_style'][1] <= prev_vl['box_style'][2] + 1.5*vl_style[5]:
                    vl_merge_buf.append(vl)
                    if MERGE_DEBUG:
                        print("\tadding to buffer: ", vl['text'])
                elif len(vl_merge_buf) > 0:
                    merged_vl = self.merge_vls(vl_merge_buf)
                    vls.append(merged_vl)
                    vl_merge_buf = [vl]
                else:
                    if MERGE_DEBUG:
                        print("\tadding to vls: ", vl['text'])
                    vls.append(vl)
                prev_vl = vl
            if len(vl_merge_buf) > 0:
                merged_vl = self.merge_vls(vl_merge_buf)
                vls.append(merged_vl)

            block_box = block['box_style']
            width = width + block_box[3]
            min_top = min(block_box[0], min_top)
            max_height = max(block_box[4], max_height)
            # Merge the Visual Lines.
            if 'merged_block' not in block:
                vls[merge_vls_idx:], _, _ = self.merge_vls_if_needed(vls[merge_vls_idx:],
                                                                     block["block_type"] == "table_row")
            merge_vls_idx = len(vls)
            prev_block = block

        box_style = BoxStyle(
            min_top,
            left,
            left + width,
            width,
            max_height
        )

        lp_line = line_parser.Line(blocks[0]["block_text"])
        block_type = "list_item" if (lp_line.is_list_item or lp_line.numbered_line) else "table_row"
        if not any_block_table_row and block_type != "list_item" and same_top and not all_blocks_to_the_right:
            block_type = blocks[0]["block_type"]
        elif not any_block_table_row and block_type != "list_item" and all_blocks_to_the_right and \
                len(blocks) == 2 and blocks[0]['box_style'][3] >= 0.2 * self.page_width and \
                abs(blocks[0]['box_style'][3] - blocks[1]['box_style'][3]) <= \
                blocks[0]['visual_lines'][0]['line_style'][5] * 3:
            prev_line_ends_with_line_delim = \
                ends_with_sentence_delimiter_pattern.search(blocks[0]["block_text"]) is not None
            if not prev_line_ends_with_line_delim:
                block_type = blocks[0]["block_type"]
        merged_block = {
            "block_idx": blocks[0]["block_idx"],
            "page_idx": blocks[0]["page_idx"],
            "block_type": block_type,
            "block_text": merged_text,
            "box_style": box_style,
            "merged_block": True,
            # 'line_props': line_props,
            "visual_lines": vls,
            "block_class": (blocks[1] if len(blocks) > 1 else blocks[0])["block_class"],
            "block_sents": sent_tokenize(merged_text), 
        }
        if lp_line.is_list_item:
            merged_block["list_type"] = lp_line.list_type
        if MERGE_DEBUG:
            print(f"merged {len(blocks)} blocks - new vl {len(vls)} visual lines")
        return merged_block

    def determine_block_type(self, block):
        block_text = block["block_text"]
        block_is_list = False
        block_is_table_row = False
        vls = block["visual_lines"]
        if len(vls) > 1:
            first_vl = vls[0]
            second_vl = vls[1]
            prev_line_style = self.class_line_styles[
                first_vl["word_classes"][-1]
            ]
            curr_line_style = self.class_line_styles[
                second_vl["word_classes"][0]
            ]
            normal_gap = max(
                prev_line_style[5],
                curr_line_style[5],
            )
            gap = (
                    second_vl["box_style"][1]
                    - first_vl["box_style"][2]
            )
            if gap > table_col_threshold * normal_gap:
                if (first_vl['text'].startswith("(")
                        and ")" in first_vl['text']
                        and first_vl['line_parser']['numbered_line']):
                    block_is_list = True
                else:
                    block_is_table_row = True

        if not block_is_list:
            block_is_list = self.is_list_item(vls[0])

        block_type = get_block_type(block_is_list, block_is_table_row, block_text)[0]
        return block_type

    def get_gaps_from_vls(self, curr_vl, prev_vl):
        """
        Calculate gap and normalized_gap from the current VisualLine and previous VisualLine
        :param curr_vl: Current Visual Line
        :param prev_vl: Previous Visual Line
        :return:
            Actual Gap between the visual line &
            Normalized Gap which can be allowed &
            Actual Normalized Gap which can be allowed &
            True if the line_style is justified else False
        """
        gap = normal_gap = 0
        is_justified = False
        if not (curr_vl and prev_vl):
            return gap, normal_gap, is_justified
        pline_style = self.class_line_styles[prev_vl["word_classes"][-1]]
        cline_style = self.class_line_styles[curr_vl["word_classes"][0]]
        normal_gap = max(pline_style[5], cline_style[5])
        act_normal_gap = table_col_threshold * normal_gap
        normal_gap = act_normal_gap
        if cline_style in self.line_style_word_stats:
            line_word_stats = self.line_style_word_stats[cline_style]
            if line_word_stats["is_justified"]:
                is_justified = True
                if (line_word_stats["avg"] == line_word_stats["median"] == 1.0) and line_word_stats["std"] == 0.0:
                    normal_gap = (JUSTIFIED_NORMAL_GAP_MULTIPLIER - 1) * normal_gap
                else:
                    normal_gap = JUSTIFIED_NORMAL_GAP_MULTIPLIER * normal_gap

        gap = (curr_vl["box_style"][1] - prev_vl["box_style"][2])
        return gap, normal_gap, act_normal_gap, is_justified

    @staticmethod
    def check_block_within_bound(box_style, bound):
        """
        Checks whether the box_style (from the block) falls within the bound
        :param box_style: Box Style of the block
        :param bound: Bounds within which we need to check whether the block belongs or not
            Tuple as (left, top, right, bottom)
        :return: True if block falls within the bounds else False
        """
        (left, top, right, bottom) = bound
        # We are not going to be strict about the bottom of box_style and right of box_style
        # Do we need to ?
        return ((top - box_style[4]) <= box_style[0] <= (bottom + box_style[4])) and \
               (left <= box_style[1] <= right)

    def check_block_within_table_bbox(self, block):
        """
        Checks whether the box_style (from the block) falls within any table bounds from BBOX
        :param block: block whose bounds need to be decided
        :return: True if block falls within the bounds else False
        """
        for table_bbox in self.audited_table_bbox.get(block["page_idx"], []):
            if self.check_block_within_bound(block["box_style"], table_bbox.bbox):
                return True
        return False

    @staticmethod
    def filter_list_of_bbox(list_of_bbox, **kwargs):
        """
        Filter the list of BBOX based on the Key-Value pairs mentioned in kwargs
        Match against all of them
        :param list_of_bbox: List of BBOX
        :param kwargs: Key-value pairs to filter
        :return: Generator object with List of dictionaries matching the query params
        """
        list_of_bbox, kwargs = list(list_of_bbox), dict(kwargs)
        # Each data item is checked against ALL kwargs before matching in the filter
        matches = filter(
            lambda bbox: all([bbox[k] == v for k, v in kwargs.items()]),
            list_of_bbox
        )
        yield from list(matches)

    def create_new_vl_group_for_sections(self, result_list, buf_texts, block_types):
        """
        Creates new VL groups (blocks) for blocks which are classified as 'para'
        and starts with 'Section'.
        :param result_list: List of VL groups.
        :param buf_texts: Text buffers which are already created.
        :param block_types: List of block types.
        :return: Returns the new result_list, buf_texts and block types.
        """
        # This function doesn't take care of the condition when the difference in
        # font is overflowing to the next line
        if len(set(result_list[0][0]['word_classes'])) == 1 and \
                (len(result_list[0]) > 1 and
                 len(set(result_list[0][1]['word_classes'])) == 1):
            if result_list[0][0]['word_classes'][0] != result_list[0][1]['word_classes'][0]:
                block_types = ['header_modified', 'para']
                buf_texts = [result_list[0][0]['text'] +
                             self.check_add_space_btw_texts(result_list[0][0]['text'], result_list[0][1]['text']) +
                             result_list[0][1]['text'],
                             " ".join([s['text'] for s in result_list[0][2:]])]
                result_list = [result_list[0][0:2], result_list[0][2:]]
            elif len(result_list[0][0]['word_classes']) == 1 and \
                    len(result_list[0]) > 2 and \
                    result_list[0][0]['word_classes'][0] != result_list[0][2]['word_classes'][0]:
                split_idx = -1
                for idx, vl in enumerate(result_list[0][3:]):
                    if result_list[0][idx + 3]['word_classes'][0] != result_list[0][2]['word_classes'][0]:
                        split_idx = idx + 3
                        break
                if split_idx > 0:
                    block_types = ['header_modified', 'para']
                    buf_texts = [" ".join([s['text'] for s in result_list[0][:split_idx]]),
                                 " ".join([s['text'] for s in result_list[0][split_idx:]])]
                    result_list = [result_list[0][0:split_idx], result_list[0][split_idx:]]
            return result_list, buf_texts, block_types
        else:
            split_idx = -1
            prefix_vls = None
            if len(set(result_list[0][0]['word_classes'])) > 1:
                split_idx = 0
            elif len(result_list[0]) > 1 and len(set(result_list[0][1]['word_classes'])) > 1:
                prefix_vls = result_list[0][0]
                split_idx = 1
            if split_idx > -1:
                ptag_idx = result_list[0][split_idx].get('ptag_idx', -1)
                if ptag_idx > -1:
                    all_p = self.pages[result_list[0][split_idx]['page_idx']].find_all("p")
                    p_tag = all_p[ptag_idx]
                    word_classes = result_list[0][split_idx]['word_classes']
                    diff_idx = 0
                    for cl_idx, e in enumerate(word_classes[-2::-1]):
                        if e != word_classes[-1]:
                            diff_idx = len(word_classes) - cl_idx - 1
                            break
                    keys = ["word-start-positions", "word-end-positions", "word-fonts"]
                    input_style = style_utils.get_style_kv(p_tag["style"])
                    for key in keys:
                        input_style[key] = input_style[key][2:-2].split("), (")
                    if prefix_vls:
                        prefix_vls['text'] += " " + " ".join(p_tag.text.split()[:diff_idx])
                        right = float(input_style["word-end-positions"][diff_idx - 1].split(",")[0])
                        box_style = BoxStyle(
                            prefix_vls['box_style'][0],
                            prefix_vls['box_style'][1],
                            right,
                            right - prefix_vls['box_style'][1],
                            prefix_vls['box_style'][4]
                        )
                        prefix_vls['box_style'] = box_style
                        prefix_vls['word_classes'].extend(word_classes[:diff_idx])
                        result_list[0][split_idx]['word_classes'] = word_classes[diff_idx:]
                        result_list[0][split_idx]['text'] = " ".join(p_tag.text.split()[diff_idx:])
                        if len(block_types) <= 2:
                            block_types = ['header_modified', 'para']
                            buf_texts = [prefix_vls['text'],
                                         " ".join(result_list[0][split_idx]['text'].split()[diff_idx:])]
                            result_list = [[prefix_vls], [result_list[0][1]]]
                        else:
                            block_types = ['header_modified', 'para', block_types[2:]]
                            buf_texts = [prefix_vls['text'],
                                         " ".join(result_list[0][split_idx]['text'].split()[diff_idx:]),
                                         buf_texts[2:]]
                            result_list = [[prefix_vls], [result_list[0][1:]]]
                    else:
                        text = " ".join(p_tag.text.split()[:diff_idx])
                        left = float(input_style["word-start-positions"][0].split(",")[0])
                        right = float(input_style["word-end-positions"][diff_idx - 1].split(",")[0])
                        box_style = BoxStyle(
                            result_list[0][split_idx]['box_style'][0],
                            left,
                            right,
                            right - left,
                            result_list[0][split_idx]['box_style'][4]
                        )
                        lp_line = line_parser.Line(text)
                        line_info = {
                            "box_style": box_style,
                            "line_style": result_list[0][split_idx]['line_style'],
                            "text": text,
                            "page_idx": result_list[0][split_idx]['page_idx'],
                            "lp_line": lp_line,
                            "line_parser": lp_line.to_json(),
                            "should_ignore": result_list[0][split_idx]['should_ignore'],
                            "changed": result_list[0][split_idx]['changed'],
                            "ptag_idx": result_list[0][split_idx]['ptag_idx'],
                            "word_classes": word_classes[:diff_idx],
                            "class": word_classes[diff_idx - 1]
                        }
                        if len(block_types) <= 1:
                            block_types = ['header_modified', 'para']
                            # If there are 3 words in the first VL (split_idx == 0 here),
                            # then most likely we need the entire VL as the header_modified block.
                            # e.g <font1> Section 2.01 </font1><space><font2> Test</font2>
                            if split_idx == 0 and \
                                    len(result_list[0][split_idx]['word_classes']) >= 3 and \
                                    diff_idx == 2 and \
                                    len(result_list) == 1 and \
                                    len(result_list[0]) == 2:
                                buf_texts = [result_list[0][0]['text'], result_list[0][1]['text']]
                            else:
                                buf_texts = [line_info['text'],
                                             " ".join(result_list[0][split_idx]['text'].split()[diff_idx:])]
                                result_list = [[line_info], [result_list[0][0]]]
                        else:
                            block_types = ['header_modified', 'para', block_types[1:]]
                            buf_texts = [line_info['text'],
                                         " ".join(result_list[0][split_idx]['text'].split()[diff_idx:]),
                                         buf_texts[1:]]
                            result_list = [[line_info], [result_list[0][0:]]]
                return result_list, buf_texts, block_types
            else:
                return result_list, buf_texts, block_types

    def divide_para_to_headers(self):
        """
        Convert paragraphs to headers if VLs in the same line are of header type and
         the number of such VLs groups are more then 75% of the total VLs groups
        :return:
        """
        temp_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            if (blk["block_type"] == "para" or (blk["block_type"] == "list_item"
                                                and blk.get("list_type", "NA") == "letter"
                                                and blk["block_text"][0].isupper())) and \
                    ends_with_sentence_delimiter_pattern.search(blk["block_text"]) is None and \
                    not blk.get("is_row_group", False) and len(blk["visual_lines"]) > 1:
                if blk["block_type"] == "list_item":
                    if len(temp_blocks):
                        if temp_blocks[-1]["block_type"] == "list_item" or \
                                (temp_blocks[-1]["block_type"] != "list_item" and blk["block_text"][0] == 'A'):
                            temp_blocks.append(blk)
                            continue
                block_vls = blk["visual_lines"]
                prev_vl = block_vls[0]
                same_line_vl_group = [[prev_vl]]
                vls_types = []
                for vl in block_vls[1:]:
                    same_top = vhu.compare_top(vl, prev_vl)
                    if same_top:
                        same_line_vl_group[-1].append(vl)
                    else:
                        same_line_vl_group.append([vl])
                    prev_vl = vl
                for vl_group in same_line_vl_group:
                    last_line_text = " ".join([s['text'].strip() for s in vl_group])
                    line_props = line_parser.Line(last_line_text)
                    if line_props.is_header and line_props.noun_chunks:
                        noun_chunk_str = " ".join(line_props.noun_chunks)
                        translated_str = last_line_text.translate(str.maketrans('', '', string.punctuation))
                        if translated_str == noun_chunk_str or \
                                (len(noun_chunk_str.split()) /
                                 (line_props.word_count - line_props.stop_word_count)) > 0.75:
                            vls_types.append("header")
                        else:
                            vls_types.append("NA")
                    else:
                        vls_types.append("NA")

                # Now we have the vls grouped by same top.
                num_headers = vls_types.count("header")
                if num_headers and num_headers/len(vls_types) > 0.75:
                    # More than 75% of text is header. Break here
                    for vl_group in same_line_vl_group:
                        merged_text = " ".join([s['text'].strip() for s in vl_group])
                        new_block = {
                            "block_idx": blk["block_idx"],
                            "page_idx": blk["page_idx"],
                            "block_type": "header",
                            "block_text": merged_text,
                            "visual_lines": vl_group,
                            "block_class": blk["block_class"],
                            "block_sents": [merged_text],
                        }
                        new_block["box_style"] = self.calc_block_span(new_block)
                        temp_blocks.append(new_block)
                else:
                    temp_blocks.append(blk)
            else:
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def merge_para_blocks(self):
        temp_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            if len(temp_blocks) \
                    and (temp_blocks[-1]["block_type"] == blk["block_type"] == "para") \
                    and (temp_blocks[-1]["block_class"] == blk["block_class"] or
                         temp_blocks[-1]["visual_lines"][-1]["word_classes"][-1] ==
                         blk["visual_lines"][0]["word_classes"][0]) \
                    and blk["page_idx"] == temp_blocks[-1]["page_idx"] \
                    and ends_with_sentence_delimiter_pattern.search(temp_blocks[-1]["block_text"]) is None \
                    and not blk.get("is_row_group", False) \
                    and (blk["box_style"][0] - (temp_blocks[-1]["box_style"][0] + temp_blocks[-1]["box_style"][4]) <=
                         blk["visual_lines"][0]['line_style'][2] or
                         temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("last_word_is_co_ordinate_conjunction",
                                                                                False)):
                # We are merging centre_aligned para blocks even if the distance between blocks are considerable
                merged_text = temp_blocks[-1]["block_text"]
                merged_text = merged_text + \
                              self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                              + blk["block_text"]
                merged_block = {
                    "block_idx": temp_blocks[-1]["block_idx"],
                    "page_idx": blk["page_idx"],
                    "block_type": "para",
                    "block_text": merged_text,
                    "merged_block": True,
                    "visual_lines": temp_blocks[-1]["visual_lines"] + blk["visual_lines"],
                    "block_class": temp_blocks[-1]["block_class"],
                    "block_sents": sent_tokenize(merged_text),
                }
                merged_block["box_style"] = self.calc_block_span(merged_block)
                temp_blocks[-1] = merged_block
            elif len(temp_blocks) \
                    and not blk.get("is_row_group", False) \
                    and blk["block_type"] == "para" \
                    and ends_with_sentence_delimiter_pattern.search(temp_blocks[-1]["block_text"]) is None \
                    and (blk["page_idx"] != temp_blocks[-1]["page_idx"] or
                         (blk["page_idx"] == temp_blocks[-1]["page_idx"] and len(temp_blocks) > 1 and
                          temp_blocks[-1]["page_idx"] != temp_blocks[-2]["page_idx"])):
                # Find previous block of the same class type
                prev_same_class_block = None
                prev_temp_idx = -1
                rev_start_idx = -1
                if (blk["page_idx"] == temp_blocks[-1]["page_idx"] and len(temp_blocks) > 1 and
                        temp_blocks[-1]["page_idx"] != temp_blocks[-2]["page_idx"]) and \
                        temp_blocks[-1]["block_type"] != "header":
                    rev_start_idx = -2
                for t_blk_idx, t_blk in enumerate(temp_blocks[rev_start_idx::-1]):
                    if t_blk["block_class"] == blk["block_class"] \
                            and t_blk["block_type"] == "para" \
                            and not t_blk.get("is_row_group", False):
                        if ends_with_sentence_delimiter_pattern.search(t_blk["block_text"]) is None:
                            prev_same_class_block = t_blk
                            prev_temp_idx = len(temp_blocks) - abs(rev_start_idx) - t_blk_idx
                        break
                    elif temp_blocks[rev_start_idx]["page_idx"] != t_blk["page_idx"]:  # Check only last page
                        break
                    elif t_blk["block_type"] == "header":  # Break on the first header encountered
                        break
                if prev_same_class_block and \
                        prev_temp_idx >= 0 and \
                        (blk['visual_lines'][0]["line_parser"].get("continuing_line", False) or
                         prev_same_class_block['visual_lines'][-1]["line_parser"].get("incomplete_line", False)):
                    merged_text = prev_same_class_block["block_text"]
                    merged_text = merged_text + \
                                  self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                                  + blk["block_text"]
                    merged_block = {
                        "block_idx": prev_same_class_block["block_idx"],
                        "page_idx": prev_same_class_block["page_idx"],
                        "block_type": "para",
                        "block_text": merged_text,
                        "merged_block": True,
                        "visual_lines": prev_same_class_block["visual_lines"] + blk["visual_lines"],
                        "block_class": blk["block_class"],
                        "block_sents": sent_tokenize(merged_text),
                    }
                    merged_block["box_style"] = self.calc_block_span(merged_block)
                    temp_blocks[prev_temp_idx] = merged_block
                else:
                    # Add the same block anyways
                    temp_blocks.append(blk)
            elif len(temp_blocks) \
                    and (blk["block_type"] == "para") \
                    and temp_blocks[-1]["block_class"] != blk["block_class"] \
                    and blk["page_idx"] == temp_blocks[-1]["page_idx"] \
                    and (blk['visual_lines'][0]["line_parser"].get("continuing_line", False) or
                         (temp_blocks[-1]['block_type'] == "para" and
                          (temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("incomplete_line", False) or
                           temp_blocks[-1]['visual_lines'][-1]["line_parser"].get(
                               "last_word_is_co_ordinate_conjunction", False)))) \
                    and not blk.get("is_row_group", False):
                # Find previous block of the same class type
                prev_same_class_block = None
                prev_temp_idx = -1
                rev_start_idx = -1
                # If the last block has an incomplete line and if its above the current block, just merge them together.
                if (temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("incomplete_line", False) or
                    temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("last_word_is_co_ordinate_conjunction",
                                                                           False) or
                    (blk['visual_lines'][0]["line_parser"].get("continuing_line", False) and
                     (blk["page_idx"] <= 2 or
                      blk['visual_lines'][0]["line_parser"].get("first_word", "") in
                      line_parser.conjunction_list + ['as']))) and \
                        temp_blocks[-1]['box_style'][0] + temp_blocks[-1]['box_style'][4] < blk['box_style'][0] and \
                        temp_blocks[-1]["block_type"] == "para":
                    # Just assign the last temp_block to be the same_class_block
                    prev_same_class_block = temp_blocks[-1]
                    prev_temp_idx = len(temp_blocks) - 1
                else:
                    for t_blk_idx, t_blk in enumerate(temp_blocks[rev_start_idx::-1]):
                        if t_blk["block_class"] == blk["block_class"] \
                                and t_blk["block_type"] == "para" \
                                and not t_blk.get("is_row_group", False):
                            if ends_with_sentence_delimiter_pattern.search(t_blk["block_text"]) is None:
                                prev_same_class_block = t_blk
                                prev_temp_idx = len(temp_blocks) - abs(rev_start_idx) - t_blk_idx
                            break
                        elif temp_blocks[rev_start_idx]["page_idx"] != t_blk["page_idx"]:  # Check only last page
                            break
                if prev_same_class_block and \
                        prev_temp_idx >= 0:
                    merged_text = prev_same_class_block["block_text"]
                    merged_text = merged_text + \
                                  self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                                  + blk["block_text"]
                    merged_block_class = prev_same_class_block['block_class'] \
                        if len(prev_same_class_block["block_text"].split()) > len(blk["block_text"].split()) \
                        else blk["block_class"]
                    merged_block = {
                        "block_idx": prev_same_class_block["block_idx"],
                        "page_idx": prev_same_class_block["page_idx"],
                        "block_type": "para",
                        "block_text": merged_text,
                        "merged_block": True,
                        "visual_lines": prev_same_class_block["visual_lines"] + blk["visual_lines"],
                        "block_class": merged_block_class,
                        "block_sents": sent_tokenize(merged_text),
                    }
                    merged_block["box_style"] = self.calc_block_span(merged_block)
                    temp_blocks[prev_temp_idx] = merged_block
                else:
                    # Add the same block anyways
                    temp_blocks.append(blk)
            elif len(temp_blocks) \
                    and (temp_blocks[-1]["block_type"] == "para" and blk["block_type"] == "header") \
                    and (temp_blocks[-1]["block_class"] == blk["block_class"] or
                         temp_blocks[-1]["visual_lines"][-1]["word_classes"][-1] ==
                         blk["visual_lines"][0]["word_classes"][0]) \
                    and blk["page_idx"] == temp_blocks[-1]["page_idx"] \
                    and ends_with_sentence_delimiter_pattern.search(temp_blocks[-1]["block_text"]) is None \
                    and not blk.get("is_row_group", False) \
                    and temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("last_word_is_co_ordinate_conjunction",
                                                                                False):
                # We are merging a previous para with a header if the previous para ends with a conjunction and
                # are of the same block class
                merged_text = temp_blocks[-1]["block_text"]
                merged_text = merged_text + \
                              self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                              + blk["block_text"]
                merged_block = {
                    "block_idx": temp_blocks[-1]["block_idx"],
                    "page_idx": blk["page_idx"],
                    "block_type": "para",
                    "block_text": merged_text,
                    "merged_block": True,
                    "visual_lines": temp_blocks[-1]["visual_lines"] + blk["visual_lines"],
                    "block_class": temp_blocks[-1]["block_class"],
                    "block_sents": sent_tokenize(merged_text),
                }
                merged_block["box_style"] = self.calc_block_span(merged_block)
                temp_blocks[-1] = merged_block
            else:
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def merge_header_blocks(self):
        temp_blocks = []
        center_aligned_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            do_merge_blocks = False
            centre_aligned_blk = self.detect_block_center_aligned(blk)
            if len(temp_blocks) \
                    and (temp_blocks[-1]["block_type"] == blk["block_type"] == "header") \
                    and temp_blocks[-1]["block_class"] == blk["block_class"] \
                    and blk["page_idx"] == temp_blocks[-1]["page_idx"] \
                    and (centre_aligned_blk and self.detect_block_center_aligned(temp_blocks[-1]) or
                         temp_blocks[-1]["box_style"][1] == blk["box_style"][1] or
                         temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("last_word_is_co_ordinate_conjunction",
                                                                                False)) and \
                    not blk.get("is_row_group", False) and \
                    not blk.get("list_type", "") and not temp_blocks[-1].get("list_type", ""):
                # "Name" header blocks should not be merged.
                translated_str = blk['block_text'].translate(str.maketrans('', '', string.punctuation))
                json_rec = line_parser.Line(translated_str).to_json()
                name_decider = False
                if json_rec['noun_chunks']:
                    noun_chunk_str = " ".join(json_rec['noun_chunks'])
                    if translated_str == noun_chunk_str or \
                            (len(noun_chunk_str.split()) /
                             (json_rec['word_count'] - json_rec['stop_word_count'])) > 0.75:
                        name_decider = True
                if not name_decider:
                    merged_text = temp_blocks[-1]["block_text"]
                    merged_text = merged_text + \
                                  self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                                  + blk["block_text"]
                    merged_block = {
                        "block_idx": temp_blocks[-1]["block_idx"],
                        "page_idx": blk["page_idx"],
                        "block_type": "header",
                        "block_text": merged_text,
                        "merged_block": True,
                        "visual_lines": temp_blocks[-1]["visual_lines"] + blk["visual_lines"],
                        "block_class": temp_blocks[-1]["block_class"],
                        "block_sents": sent_tokenize(merged_text),
                    }
                    merged_block["box_style"] = self.calc_block_span(merged_block)
                    temp_blocks[-1] = merged_block
                    do_merge_blocks = True

            if not do_merge_blocks:
                if center_aligned_blocks:
                    for b in center_aligned_blocks:
                        merged_text = temp_blocks[-1]["block_text"]
                        merged_text = merged_text + \
                                      self.check_add_space_btw_texts(merged_text, b["block_text"]) \
                                      + b["block_text"]
                        merged_block = {
                            "block_idx": temp_blocks[-1]["block_idx"],
                            "page_idx": b["page_idx"],
                            "block_type": "header",
                            "block_text": merged_text,
                            "merged_block": True,
                            "visual_lines": temp_blocks[-1]["visual_lines"] + b["visual_lines"],
                            "block_class": temp_blocks[-1]["block_class"],
                            "block_sents": sent_tokenize(merged_text),
                        }
                        merged_block["box_style"] = self.calc_block_span(merged_block)
                        temp_blocks[-1] = merged_block
                    center_aligned_blocks = []
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def merge_ooo_para_list_blocks(self):
        temp_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            if blk["block_type"] == "list_item" \
                    and len(temp_blocks) \
                    and temp_blocks[-1]["block_type"] == "para" \
                    and blk["block_class"] == temp_blocks[-1]["block_class"] \
                    and ends_with_sentence_delimiter_pattern.search(temp_blocks[-1]["block_text"]) is None \
                    and not temp_blocks[-1].get("is_row_group", False) \
                    and len(temp_blocks[-1]["block_text"].split()) > 1 \
                    and blk['visual_lines'][0].get("line_parser", {}).get("start_number", "") \
                    not in ["a", "A", "i", "1"] \
                    and not blk.get("underwriter_block", False):
                merged_text = temp_blocks[-1]["block_text"]
                merged_text = merged_text + \
                              self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                              + blk["block_text"]
                merged_block = {
                    "block_idx": temp_blocks[-1]["block_idx"],
                    "page_idx": temp_blocks[-1]["page_idx"],
                    "block_type": "para",
                    "block_text": merged_text,
                    "merged_block": True,
                    "visual_lines": temp_blocks[-1]["visual_lines"] + blk["visual_lines"],
                    "block_class": blk["block_class"],
                    "block_sents": sent_tokenize(merged_text),
                }
                merged_block["box_style"] = self.calc_block_span(merged_block)
                temp_blocks[-1] = merged_block
            else:
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def merge_ooo_list_para_blocks(self):
        """
        Merge blocks identified as lists and paragraphs across different pages
        :return:
        """
        temp_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            if blk["block_type"] == "para" \
                    and len(temp_blocks) \
                    and temp_blocks[-1]["block_type"] == "list_item" \
                    and blk["block_class"] == temp_blocks[-1]["block_class"] \
                    and blk["page_idx"] != temp_blocks[-1]["page_idx"] \
                    and ends_with_sentence_delimiter_pattern.search(temp_blocks[-1]["block_text"]) is None \
                    and not temp_blocks[-1].get("is_row_group", False) \
                    and len(temp_blocks[-1]["block_text"].split()) > 1:
                merged_text = temp_blocks[-1]["block_text"]
                merged_text = merged_text + \
                              self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                              + blk["block_text"]
                temp_blocks[-1]["block_text"] = merged_text
                temp_blocks[-1]["merged_block"] = True
                temp_blocks[-1]["visual_lines"] = temp_blocks[-1]["visual_lines"] + blk["visual_lines"]
                temp_blocks[-1]["block_sents"] = sent_tokenize(merged_text)
                temp_blocks[-1]["box_style"] = self.calc_block_span(temp_blocks[-1])
            else:
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def merge_center_aligned_header_para_blocks(self):
        """
        Merge center aligned blocks (paragraphs or headers).
        Right now the logic will be applied to page 1.
        TODO: Expand the logic to more pages (other than page 1)
        :return:
        """
        temp_blocks = []
        for blk_idx, blk in enumerate(self.blocks):
            centre_aligned_blk = self.detect_block_center_aligned(blk)
            last_temp_block_centre_aligned = False
            if len(temp_blocks):
                last_temp_block_centre_aligned = self.detect_block_center_aligned(temp_blocks[-1])
            if len(temp_blocks) \
                    and (temp_blocks[-1]["block_type"] in ["header", "para"] and
                         blk["block_type"] in ["header", "para"]) \
                    and blk["page_idx"] == temp_blocks[-1]["page_idx"] == 0 \
                    and ((centre_aligned_blk and last_temp_block_centre_aligned) or
                         (centre_aligned_blk and self.detect_block_center_aligned(self.blocks[blk_idx - 1])) or
                         (self.detect_block_center_aligned(blk, False) and last_temp_block_centre_aligned) or
                         temp_blocks[-1]['visual_lines'][-1]["line_parser"].get("last_word_is_co_ordinate_conjunction",
                                                                                False)) \
                    and not blk.get("is_row_group", False) \
                    and not blk.get("list_type", "") \
                    and not temp_blocks[-1].get("list_type", ""):
                merged_text = temp_blocks[-1]["block_text"]
                merged_text = merged_text + \
                              self.check_add_space_btw_texts(merged_text, blk["block_text"]) \
                              + blk["block_text"]
                merged_block = {
                    "block_idx": temp_blocks[-1]["block_idx"],
                    "page_idx": blk["page_idx"],
                    "block_type": "para",
                    "block_text": merged_text,
                    "merged_block": True,
                    "visual_lines": temp_blocks[-1]["visual_lines"] + blk["visual_lines"],
                    "block_class": temp_blocks[-1]["block_class"],
                    "block_sents": sent_tokenize(merged_text),
                }
                merged_block["box_style"] = self.calc_block_span(merged_block)
                temp_blocks[-1] = merged_block
            else:
                temp_blocks.append(blk)
        self.blocks = temp_blocks

    def correct_blk_idxs(self):
        for blk_idx, blk in enumerate(self.blocks):
            blk["block_idx"] = blk_idx

    @staticmethod
    def check_add_space_btw_texts(left_text, right_text):
        delim = ""
        if left_text and right_text:
            if left_text[-1] in ["(", "[", "{", "“"]:
                return delim
            elif right_text[0] in [")", "]", "}", "”", ",", ".", ";"]:
                return delim
            elif left_text[-1] in ["'", '"', '“'] and any((c in right_text) for c in ["'", '"', '”']):
                return delim
            else:
                delim = " "
        return delim

    @staticmethod
    def soft_line_style_check(line_info, prev_line_info):
        if not line_info or not prev_line_info:
            return False
        line_style = line_info["line_style"]
        prev_line_style = prev_line_info["line_style"]
        if line_style[0] == prev_line_style[0] \
                and line_style[1] == prev_line_style[1] \
                and abs(line_style[2] - prev_line_style[2]) < 1.0 \
                and line_style[3] == prev_line_style[3]:
            return True
        elif line_style[0] != prev_line_style[0] \
                and line_style[1] == prev_line_style[1] \
                and line_style[2] == prev_line_style[2] \
                and line_style[3] == prev_line_style[3] \
                and line_style[5] == prev_line_style[5]:
            return True
        elif line_style[0] == prev_line_style[0] \
                and line_style[1] in ["normal", "italic"] and prev_line_style[1] in ["normal", "italic"] \
                and line_style[2] == prev_line_style[2] \
                and line_style[3] == prev_line_style[3] \
                and line_style[5] == prev_line_style[5]:
            return True
        return False

    def has_smaller_or_lighter_header_font(self, prev_class_name, new_class_name):
        prev_blk_line_style = self.class_line_styles[prev_class_name]
        cur_blk_line_style = self.class_line_styles[new_class_name]
        has_smaller_or_lighter_header_font = cur_blk_line_style[2] < prev_blk_line_style[2] or \
                                             ((cur_blk_line_style[2] == prev_blk_line_style[2]) and
                                              cur_blk_line_style[3] < prev_blk_line_style[3])
        return has_smaller_or_lighter_header_font

    def has_same_or_bigger_font(self, prev_class_name, new_class_name):
        prev_blk_line_style = self.class_line_styles[prev_class_name]
        cur_blk_line_style = self.class_line_styles[new_class_name]
        has_same_or_bigger_font = (cur_blk_line_style[2] >= prev_blk_line_style[2] and
                                   not 0 <= cur_blk_line_style[2] - prev_blk_line_style[2] < 0.75) or \
                                  ((cur_blk_line_style[2] == prev_blk_line_style[2]) and
                                   cur_blk_line_style[3] >= prev_blk_line_style[3])
        return has_same_or_bigger_font

    @staticmethod
    def svg_line_operations(lines_list, x1, y1, x2, y2, style):
        if lines_list:
            do_add_to_list = True
            for line in lines_list:
                if abs(x1 - line['x1']) < 1.0 and \
                        abs(y1 - line['y1']) < 1.0 and \
                        abs(x2 - line['x2']) < 1.0 and \
                        abs(y2 - line['y2']) < 1.0:
                    do_add_to_list = False
                    break
                elif (abs(x2 - line['x1']) < 1.0 or
                      abs(x1 - line['x2']) < 1.0) and \
                        abs(y1 - y2) < 1.0 and \
                        abs(line['y1'] - line['y2']) < 1.0 and \
                        abs(y1 - line['y1']) < 1.0:
                    # Have the same top, and the difference between the start and end of the lines are < 1.0 pixel
                    # Merge them
                    # if line['x1'] > x2:
                    line['x1'] = min(x1, line['x1'])
                    # elif x1 > line['x2']:
                    line['x2'] = max(x2, line['x2'])
                    do_add_to_list = False
                    break
                elif (abs(y2 - line['y1']) < 1.0 or
                      abs(y1 - line['y2']) < 1.0) and \
                        abs(x1 - x2) < 1.0 and \
                        abs(line['x1'] - line['x2']) < 1.0 and \
                        abs(x1 - line['x1']) < 1.0:
                    # Have the same x, and the difference between the start and end of the lines are < 1.0 pixel
                    # Merge the vertical lines
                    # if line['y1'] > y2:
                    line['y1'] = min(y1, line['y1'])
                    # elif y1 > line['y2']:
                    line['y2'] = max(y2, line['y2'])
                    do_add_to_list = False
                    break

            if do_add_to_list:
                lines_list.append({
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "style": style,
                })
        else:
            lines_list.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "style": style,
            })
        return lines_list

    @staticmethod
    def remove_duplicate_svg_tags(
            soup,
            svg_children,
    ):
        """
        Removes duplicate lines with the same X (< 1 pixel difference) or
        same Y (< 1 pixel difference).
        Merge rectangles that are < 1 pixel in height to a line
        Don't add rectangles that span the entire page width / height
        """
        lines_list = []
        rect_tag_list = []
        svg_height = 0
        svg_width = 0
        if svg_children:
            svg_height = float(svg_children.attrs.get("height", "0"))
            svg_width = float(svg_children.attrs.get("width", "0"))
        if LINE_DEBUG or PERFORMANCE_DEBUG:
            print("Length of svg_children: ", len(svg_children))
        for svg_child in svg_children:
            if svg_child.name == 'line' and \
                    svg_child.get('x1', None) and \
                    svg_child.get('y1', None) and \
                    svg_child.get('x2', None) and \
                    svg_child.get('y2', None):

                x1 = float(svg_child['x1'])
                y1 = float(svg_child['y1'])
                x2 = float(svg_child['x2'])
                y2 = float(svg_child['y2'])
                style = svg_child.get('style', '')
                # Consider only horizontal or vertical lines.
                if x1 != x2 and y1 != y2:
                    continue
                lines_list = Doc.svg_line_operations(lines_list, x1, y1, x2, y2, style)
            elif svg_child.name == 'rect' and \
                    svg_child.get('x', None) and \
                    svg_child.get('y', None) and \
                    svg_child.get('height', None) and \
                    svg_child.get('width', None):
                if float(svg_child['height']) > 1.0:
                    # Discard rectangles that are almost the size of the page.
                    if not (float(svg_child['height']) >= 0.8 * svg_height and
                            float(svg_child['width']) >= 0.8 * svg_width):
                        rect_tag_list.append(svg_child)
                else:
                    x1 = float(svg_child['x'])
                    y1 = float(svg_child['y'])
                    x2 = x1 + float(svg_child['width'])
                    y2 = y1 + float(svg_child['height'])
                    style = svg_child.get('style', '')
                    lines_list = Doc.svg_line_operations(lines_list, x1, y1, x2, y2, style)

        lines_tag_list = []
        for line in lines_list:
            new_line = soup.new_tag('line')
            for k, v in line.items():
                new_line[k] = v
            lines_tag_list.append(new_line)

        return lines_tag_list, rect_tag_list

    @staticmethod
    def check_line_between_box_styles(
            prev_blk_box_style,
            curr_blk_box_style,
            lines_tag_list,
            check_gap=False,
            x_axis_relaxed=False,
    ):
        """
        Check whether there is a line between the blocks / visual_lines represented by box_styles
        :param prev_blk_box_style:
        :param curr_blk_box_style:
        :param lines_tag_list:
        :param check_gap: Checks the gap between line and the blocks
        :param x_axis_relaxed: Relax the left/right check for the current box style.
        :return:
        """
        ret_val = False
        if prev_blk_box_style and curr_blk_box_style and lines_tag_list:
            top1 = prev_blk_box_style[0]
            bottom1 = top1 + prev_blk_box_style[4]
            left1 = prev_blk_box_style[1]
            right1 = prev_blk_box_style[2]
            top2 = curr_blk_box_style[0]
            left2 = curr_blk_box_style[1]
            right2 = curr_blk_box_style[2]

            for line in lines_tag_list:
                # Not doing exact match on top of the next element as sometimes lines are thick
                if bottom1 <= line['y1'] <= (top2 + 2.0) and \
                        line['x1'] <= left1 <= line['x2'] and \
                        line['x1'] <= left2 <= line['x2'] and \
                        line['x1'] < right1 <= line['x2'] and \
                        line['x1'] < right2 <= line['x2']:
                    if check_gap:
                        if abs(abs(line['y1'] - bottom1) - abs(top2 - line['y1'])) < 2.0:
                            ret_val = True
                    else:
                        ret_val = True
                    break
                elif x_axis_relaxed and \
                        bottom1 <= line['y1'] <= (top2 + 2.0) and \
                        line['x1'] <= left1 < line['x2'] and \
                        line['x1'] < right1 <= line['x2']:
                    if check_gap:
                        if abs(abs(line['y1'] - bottom1) - abs(top2 - line['y1'])) < 2.0:
                            ret_val = True
                    else:
                        ret_val = True
                    break
        return ret_val

    def check_block_within_svg_tags(self, block, prev_block):
        """
        Checks whether the box_style (from the block) falls within a rect svg tag or within 2 svg lines
        :param block: block whose bounds need to be decided
        :param prev_block: To check whether there is a line between the blocks
        :return: True if block falls within the bounds else False
        """
        ret_val = False
        if len(self.page_svg_tags) > block["page_idx"]:
            [line_svg_tags, rect_svg_tags] = self.page_svg_tags[block["page_idx"]]
            box_style = block["box_style"]
            # Check within rectangular bounds.
            for rect in rect_svg_tags:
                rect_left = float(rect['x'])
                rect_top = float(rect['y'])
                rect_bottom = rect_top + float(rect['height'])
                rect_right = rect_left + float(rect['width'])
                if rect_top <= box_style[0] <= rect_bottom and \
                        rect_left <= box_style[1] <= rect_right and \
                        box_style[0] + box_style[4] <= rect_bottom and \
                        box_style[2] <= rect_right:
                    ret_val = True
                    break
        return ret_val

