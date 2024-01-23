import copy
import numpy as np
from collections import Counter

from nlm_ingestor.ingestor.visual_ingestor import vi_helper_utils as vhu
from nlm_ingestor.ingestor_utils.ing_named_tuples import BoxStyle
from nlm_ingestor.ingestor import line_parser

# TODO: setting TABLE_DEBUG to true cause line 1193 to break in visual ingestor
# UnboundLocalError: local variable 'align_count' referenced before assignment
# print(f"table changed: align: {align_count}, page: {page_change}, section: {different_section}")
TABLE_DEBUG = False
TABLE_COL_DEBUG = False
TABLE_HG_DEBUG = False
TABLE_2_COL_DEBUG = False
TABLE_BOUNDS_DEBUG = False
header_group_key = "is_header_group"
row_group_key = "is_row_group"
header_key = "is_header"


def get_alignment_count(prev_block, curr_block, force_check_curr_block=False):
    # alignment check
    prev_line = prev_block["visual_lines"]
    curr_line = curr_block["visual_lines"]
    # print("comparing lines", prev_line[0]['text'], curr_line[0]["text"])

    shorter_line = prev_line if len(prev_line) < len(curr_line) and not force_check_curr_block else curr_line
    longer_line = prev_line if shorter_line == curr_line else curr_line
    # print("short", shorter_line[0]['text'], len(prev_line), len(curr_line))
    # print("long", longer_line[0]['text'])
    alignment_count = 0
    alignment_pos = []
    for i in range(len(shorter_line)):
        short_pos = shorter_line[i]["box_style"]
        # print(shorter_line[i]["text"], short_pos[1], short_pos[2])
        left_alignment, right_alignment, center_alignment, within_bounds = False, False, False, False
        for j in range(0, len(longer_line)):
            long_pos = longer_line[j]["box_style"]
            # print("\t", longer_line[j]["text"], long_pos[1], long_pos[2])
            if short_pos[1] != 0:
                alignment_deviation = (short_pos[1] - long_pos[1]) / short_pos[1]
                if abs(alignment_deviation) <= 0.1:
                    left_alignment = True
                    break
            # check right align
            if short_pos[2] != 0:
                alignment_deviation = (short_pos[2] - long_pos[2]) / short_pos[2]
                if abs(alignment_deviation) <= 0.1:
                    right_alignment = True
                    break
            # check center align
            short_center = (short_pos[2] - short_pos[1]) / 2 + short_pos[2]
            long_center = (long_pos[2] - long_pos[1]) / 2 + long_pos[2]
            if short_center != 0:
                alignment_deviation = (short_center - long_center) / short_center
                if abs(alignment_deviation) <= 0.1:
                    center_alignment = True
                    break
            if len(list(range(max(int(short_pos[1]), int(long_pos[1])),
                              min(int(short_pos[2]), int(long_pos[2]))+1))) >= len(shorter_line[i]["text"]):
                within_bounds = True
                break
        if left_alignment or right_alignment or center_alignment or within_bounds:
            if left_alignment and j == len(longer_line) - 1:
                if list(range(max(int(short_pos[1]), int(long_pos[1])),
                              min(int(short_pos[2]), int(long_pos[2]))+1)):
                    alignment_count = alignment_count + 1
                    alignment_pos.append(j)
            elif within_bounds and prev_block["block_type"] == curr_block["block_type"] == 'table_row':
                alignment_count = alignment_count + 1
                alignment_pos.append(j)
            else:
                alignment_count = alignment_count + 1
                alignment_pos.append(j)
        elif prev_block["block_type"] == curr_block["block_type"] == 'table_row' and \
                vhu.find_num_cols(prev_block)[0] == vhu.find_num_cols(curr_block)[0]:
            # We don't have any mathematical alignment. But still might be part of the table?
            # Check if the VL of shorter line has a corresponding match to the same VL of longer line.
            if i < len(shorter_line) - 1:
                next_longer_col_pos = longer_line[i + 1]["box_style"]
                cur_longer_col_pos = longer_line[i]["box_style"]
                if cur_longer_col_pos[1] < short_pos[2] < next_longer_col_pos[1]:
                    alignment_count = alignment_count + 1
                    alignment_pos.append(i)
            elif i == len(shorter_line) - 1:
                prev_longer_col_pos = longer_line[i-1]["box_style"]
                cur_longer_col_pos = longer_line[i]["box_style"]
                if prev_longer_col_pos[2] < short_pos[1] < cur_longer_col_pos[2]:
                    alignment_count = alignment_count + 1
                    alignment_pos.append(i)
        elif i == 0 and \
                len(longer_line) > 1 and \
                longer_line[i]["box_style"][1] <= short_pos[1] < longer_line[i + 1]["box_style"][1] and \
                longer_line[i]["box_style"][1] <= short_pos[2] < longer_line[i + 1]["box_style"][1]:
            # if both the left and right of the short line is within the longer_line[0][left] and longer_line[1][left]
            alignment_count = alignment_count + 1
            alignment_pos.append(i)
    return alignment_count, vhu.find_num_cols(prev_block)[0], alignment_pos


def para_aligned_with_prev_row(page_width, prev_block, curr_block, debug=False):
    prev_vls = prev_block["visual_lines"]
    curr_vls = curr_block["visual_lines"]
    are_aligned = False
    if debug:
        print("comparing: ", curr_block["block_text"])
        print("\t and ", prev_block["block_text"])
    if len(prev_vls) > 1:
        '''
        The invocation of this function is from a 2 column-table logic.
        However, say if the previous table row has 2 Visual Lines in the first column, we have to take the
        3rd visual line to compare the alignment, if the current block is of type other than table_row.
        '''
        if curr_block["block_type"] == 'header':
            prev_vl = prev_vls[0]
        else:
            prev_vl = prev_vls[-1]
        prev_blk_col_cnt = vhu.count_cols(prev_block['visual_lines'])
        if prev_blk_col_cnt == 1:
            #  We had a multi line first column.
            same_top_index = vhu.same_top_index(prev_block)
            if same_top_index:
                prev_vl = prev_vls[same_top_index]

        # first column of current row
        curr_vl = curr_vls[0]
        # Check whether the current VL is a list item?
        is_curr_vl_list_item = False
        if len(curr_vl['text'].strip()) == 1 and curr_vl['text'].strip() in line_parser.list_types.keys():
            is_curr_vl_list_item = True
            if len(curr_vls) > 1:
                for vl in curr_vls[1:]:
                    if not (len(vl['text'].strip()) == 1 and vl['text'].strip() in line_parser.list_types.keys()):
                        curr_vl = vl
                        break

        are_aligned = (np.abs(curr_vl['box_style'][1] - prev_vl['box_style'][1]) < 80
                       and prev_vl['box_style'][1] > page_width/6)
        same_class = prev_vl["line_style"] == curr_vl["line_style"]
        if are_aligned and not same_class and debug:
            print("---- aligned with different fonts", curr_vl['text'][0:40],
                  prev_block["block_class"], prev_vl['text'][0:40], curr_block["block_class"])
        if not is_curr_vl_list_item:
            # For cases where the first VL in current block is a list_item character, Allow some leniency.
            # Do we need to check for line_style ? Might be the case that the list item is of a different style.
            are_aligned = are_aligned and same_class
            if curr_block["block_type"] == 'header' and are_aligned:
                # Check whether we are spanning multiple columns ?
                if curr_vl['box_style'][2] > prev_vls[-1]['box_style'][1]:
                    # We have an intersection
                    are_aligned = False

        if debug:
            if are_aligned:
                print("----aligned", curr_vl['text'][0:40], prev_vl['text'][0:40])
            else:
                print("----not aligned (", prev_blk_col_cnt, "), ", curr_vl['text'][0:40], "--------",
                      prev_vl['text'][0:40], )
                print("----not aligned", prev_vl["line_style"], "..", curr_vl["line_style"], ".....", page_width/6)

    return are_aligned


def get_box_string(block):
    box_style = block['box_style']
    def r(x):
        return round(x, 2)
    return f"{r(box_style[1])}, {r(box_style[2])}, {r(box_style[0])}, {r(box_style[0] + box_style[4])}"


class TableParser:
    def __init__(self, doc, blocks):
        self.doc = doc
        self.blocks = blocks
        self.has_merged_cells = False
        # self.add_table_data(blocks)

    def parse_table(self):
        self.add_table_data()
        return self.blocks

    def add_table_data(self):
        if TABLE_DEBUG:
            print('creating table from blocks: ', len(self.blocks))

        n_block_cols = self.evaluate_table()
        if TABLE_DEBUG:
            print('n_block_cols: ', n_block_cols, " Length is : ", len(n_block_cols))
        max_header_idx = 5
        n_table_cols = max(n_block_cols[0:max_header_idx])
        max_table_cols = max(n_block_cols)
        header_block = None
        block_with_most_columns = None
        header_block_idx = 0
        for idx, block in enumerate(self.blocks):
            # line_style = self.class_line_styles[block['class']]
            # is_header = line_style in self.header_styles
            if n_block_cols[idx] == n_table_cols:
                block_with_most_columns = block
            if not header_block and n_block_cols[idx] >= n_table_cols - 1:
                line_style = self.doc.class_line_styles[block["block_class"]]
                # if not line_parser.Line(block['block_text']).is_table_row:#line_style.font_weight > 400:# and not line_parser.Line(block['block_text']).is_table_row:  # add font size here too
                header_block = block
                header_block_idx = idx
                if TABLE_DEBUG:
                    print("found header: ", block["block_text"], f"with {len(block['visual_lines'])} visual lines")

        col_spans = []
        # Do we need to include header block in the determination of spans.
        hdr_blk_col_count, _ = vhu.find_num_cols(self.blocks[header_block_idx])
        span_determine_start_idx = header_block_idx
        for blk in self.blocks[header_block_idx + 1:]:
            if blk['block_type'] == 'table_row':
                blk_col_count, _ = vhu.find_num_cols(blk)
                if blk_col_count == hdr_blk_col_count:
                    span_determine_start_idx = header_block_idx + 1
                break
        # Dataset to hold a single cell span
        single_cell_col_span = []
        for idx, block in enumerate(self.blocks[span_determine_start_idx:]):
            vls = block["visual_lines"]
            if TABLE_COL_DEBUG:
                print(">>>", block['block_text'], " n_vls:", len(vls), "type: ", block["block_type"])
            if len(vls) < n_block_cols[header_block_idx]:
                # We have a row with column count less than the header column count.
                # Probable header again ? Don't let it decide the number of spans.
                do_continue = True
                for vl in vls:
                    if vl['box_style'][2] < self.blocks[header_block_idx]['box_style'][1]:
                        do_continue = False
                if do_continue:
                    continue
            last_currency_vl_col_span = None
            if (block["block_type"] == "para" and len(vls) > n_table_cols and
                    block['box_style'][3] > 0.75 * self.doc.page_width) or block["block_type"] == "header":
                # Don't let a paragraph decide the span if the number of VLS are more
                # than the table_cols and width of the block is > 75% of the page_width
                # Header blocks will eventually turn to be a row_group spanning all the columns
                continue
            for vl in vls:
                col_style = vl["box_style"]
                span_exists = False
                # do_overlap = (
                #     row_style[1] <= col_header_style[2]
                #     and row_style[2] >= col_header_style[1]
                # )
                col_spans = sorted(col_spans, key=lambda x: x[0])
                if TABLE_COL_DEBUG:
                    print("-> aligning", vl["text"], col_style[1], ", ", col_style[2])
                    print("-* spans", col_spans)

                for col_idx, col_span in enumerate(col_spans):
                    if TABLE_COL_DEBUG:
                        print("\t-span: ", col_idx, col_span)

                    span_exists = (
                            col_style[1] <= col_span[1]
                            and col_style[2] >= col_span[0]
                    )
                    if block["block_type"] == "table_row" and vl['text'].strip()[0] in ['$', '€', '£']:
                        if last_currency_vl_col_span and last_currency_vl_col_span == col_span:
                            # Don't put 2 currency data in same column span
                            span_exists = False
                    if span_exists:
                        # col_span[0] = min(col_style[1], col_span[0])
                        if (col_style[2] > col_span[1] and
                                (col_idx == len(col_spans) - 1 or col_style[2] < col_spans[col_idx + 1][0])):
                            if TABLE_COL_DEBUG:
                                print(f"\texpanding span right to {col_style[2]}: ")
                            col_span[1] = max(col_style[2], col_span[1])
                        else:
                            if TABLE_COL_DEBUG:
                                print(f"\tusing span")
                            if len(col_spans) > max_table_cols and \
                                    col_idx < len(col_spans) - 1 and col_span[1] < col_style[2] <= \
                                    col_spans[col_idx + 1][1]:
                                # More column spans than the max table cols identified.
                                # Try to merge them?
                                if TABLE_COL_DEBUG:
                                    print(f"\texpanding span right to {col_spans[col_idx + 1][1]}: ")
                                col_span[1] = col_spans[col_idx + 1][1]
                                del col_spans[col_idx + 1]
                            elif (col_style[1] < col_span[0] and
                                  col_style[2] <= col_span[1] and
                                  (col_idx == 0 or col_style[1] > col_spans[col_idx - 1][1])):
                                col_span[0] = min(col_style[1], col_span[0])

                        if block["block_type"] == "table_row" and vl['text'].strip()[0] in ['$', '€', '£']:
                            last_currency_vl_col_span = col_span
                        # Remove from the single_cell_col_span, if adding another entry to the span
                        for (s, v) in single_cell_col_span:
                            if col_span == s:
                                single_cell_col_span.remove((s, v))
                                break
                        break
                if not span_exists:
                    if TABLE_COL_DEBUG:
                        print("\t>>>adding span: ", col_style[1], ", ", col_style[2], vl['text'], col_spans)
                    col_spans.append([col_style[1], col_style[2]])
                    single_cell_col_span.append(([col_style[1], col_style[2]], {
                        "block_idx": idx,
                    }))
                    if last_currency_vl_col_span and last_currency_vl_col_span[1] > col_style[1]:
                        # Re adjust the col span of last_currency_vl_col_span.
                        # We cannot have 2 col spans overlapping each other
                        col_spans = [[col_span[0], col_style[1] - 1] if (col_span == last_currency_vl_col_span)
                                     else col_span for col_span in col_spans]

        col_spans.sort(key=lambda x: x[0])

        for (k, v) in single_cell_col_span:
            temp_col_spans = copy.deepcopy(col_spans)
            blk_idx = v["block_idx"]
            blk = self.blocks[span_determine_start_idx + blk_idx]
            vls = blk["visual_lines"]
            unattended_vls = []
            if k in temp_col_spans and temp_col_spans.index(k):     # Only if we are dealing with col_spans in between
                temp_col_spans.remove(k)
                for vl in vls:
                    col_style = vl["box_style"]
                    for col_span in temp_col_spans:
                        span_exists = (
                            col_style[1] <= col_span[1] and col_style[2] >= col_span[0]
                        )
                        if span_exists:
                            temp_col_spans.remove(col_span)
                        else:
                            unattended_vls.append(vl)
                for (k1, _) in single_cell_col_span:
                    if k1 in temp_col_spans:
                        temp_col_spans.remove(k1)
                if unattended_vls and temp_col_spans:
                    col_style = unattended_vls[0]["box_style"]
                    for col_idx, col_span in enumerate(temp_col_spans):
                        cond = col_style[1] > col_span[1]
                        if col_idx != len(temp_col_spans) - 1:
                            next_span_idx = col_spans.index(col_span) + 1
                            cond = cond and col_spans[next_span_idx][0] > col_style[2]

                        k_index = col_spans.index(k)
                        col_spans.remove(k)
                        col_span_idx = col_spans.index(col_span)
                        if cond:
                            col_spans[col_span_idx][1] = max(col_style[2], col_span[1])
                            break
                        elif col_style[2] < col_span[0]:
                            col_spans[col_span_idx][0] = min(col_style[1], col_span[0])
                            break
                        else:
                            # Add back.
                            col_spans.insert(k_index, k)

        n_table_cols = len(col_spans)
        if n_table_cols > 2:
            header_block[header_key] = True
        elif n_table_cols == 2:
            # For a 2 column table, check whether the header block has all Visual Lines belonging to the same class.
            # If yes, set header_key == True for rendering to work.
            change_in_vl_class = False
            prev_vl_class = header_block['visual_lines'][0]['class']
            for vl in header_block['visual_lines'][1:]:
                if prev_vl_class != vl['class']:
                    change_in_vl_class = True
                    break
                prev_vl_class = vl['class']
            if not change_in_vl_class:
                # Need to make sure that the next table_row has a different class than the header vls class.
                for idx, block in enumerate(self.blocks[header_block_idx + 1:]):
                    if block["block_type"] != "table_row":
                        continue
                    else:
                        # We have a table row here.
                        for vl in block['visual_lines']:
                            if prev_vl_class != vl['class']:
                                change_in_vl_class = True
                                break
                        # Do check only for one table row.
                        break
                if change_in_vl_class:
                    header_block[header_key] = True
                    # If we decide on the header_block,
                    # Remove merging flag, so that effective_header and effective_para will not be generated.
                    self.has_merged_cells = False

        if TABLE_DEBUG:
            print('table dim', n_table_cols, len(self.blocks))
        prev_block = None
        if TABLE_COL_DEBUG:
            print("col-spans: ", col_spans)
        for idx, row_block in enumerate(self.blocks):
            row_block["header_cell_values"] = (
                header_block.get("cell_values", []) if header_block else []
            )
            # row_block['header_cell_values'] = header_block['cell_values'] if header_block else []
            if row_block["block_type"] == "table_row" or row_block.get(header_key, False):
                self.align_columns(header_block, row_block, block_with_most_columns, col_spans)
            else:
                # Deal with paragraph in between table rows.
                already_aligned = False
                if row_block["block_type"] in ["para", "list_item"]:
                    new_vls, _, _ = self.doc.merge_vls_if_needed(row_block["visual_lines"])
                    if len(row_block["visual_lines"]) > len(new_vls) >= len(col_spans):
                        vls_intersect = False
                        for vl in new_vls:
                            for span_idx, span in enumerate(col_spans):
                                if span[0] <= vl['box_style'][1] < span[1]:
                                    if span_idx < len(col_spans) - 1:
                                        vls_intersect = (vl['box_style'][2] >= col_spans[span_idx + 1][0])
                                        break
                            if vls_intersect:
                                break
                        if not vls_intersect:
                            row_block["visual_lines"] = new_vls
                            self.align_columns(header_block, row_block, block_with_most_columns, col_spans)
                            already_aligned = True
                    # Check whether the para block fits within a single col_span
                    row_blk_style = row_block["box_style"]
                    for span_idx, span in enumerate(col_spans):
                        if ((span[0] <= row_blk_style[1] < span[1] or
                             (span_idx == 0 and row_blk_style[1] < span[1]))
                            and span[0] < row_blk_style[2] <= span[1]) or \
                                (span[0] <= row_blk_style[1] and span_idx < len(col_spans) - 2 and
                                 row_blk_style[2] < col_spans[span_idx + 1][0]) or \
                                (span[1] >= row_blk_style[2] and span_idx > 0 and
                                 row_blk_style[1] > col_spans[span_idx - 1][1]):
                            # Align here
                            row_block["visual_lines"] = new_vls
                            self.align_columns(header_block, row_block, block_with_most_columns, col_spans)
                            already_aligned = True
                            break
                        elif span[0] <= row_blk_style[1] < span[1]:
                            # No need to loop more spans here. break and make it a full row.
                            break
                elif row_block["block_type"] == "header" and row_block["block_idx"] < header_block["block_idx"]:
                    self.align_columns(header_block, row_block, block_with_most_columns, col_spans)
                    already_aligned = True
                if not already_aligned:
                    if TABLE_DEBUG:
                        print("full_row", row_block['block_text'], row_block['box_style'])
                    # row_block["block_type"] = "table_row"
                    # not sure why this was there
                    # if not self.are_aligned(header_block, row_block):
                    row_block[row_group_key] = True
                    row_block["col_span"] = n_table_cols
                    row_block["cell_values"] = [row_block["block_text"]]
                    # else:
                    #     self.align_missing_columns(col_spans, row_block)

            prev_block = row_block

        # Let's do some post-processing.
        # For now let's do post-processing only for non-table rows
        reset_header_cell_values = False
        new_blocks = []
        for idx, block in enumerate(self.blocks):
            if reset_header_cell_values:
                block["header_cell_values"] = (
                    header_block.get("cell_values", []) if header_block else []
                )
            num_cell_values = sum(1 for c in block["cell_values"] if c)

            if block["block_type"] != "table_row" and not block.get(header_key, False) and \
                    len(block["cell_values"]) > 1 and\
                    num_cell_values == 1 and\
                    0 < idx < len(self.blocks) - 1 and \
                    not block["block_text"].strip().endswith(":"):
                prev_block_bottom = new_blocks[-1]["box_style"][0] + new_blocks[-1]["box_style"][4]
                next_block_top = self.blocks[idx + 1]["box_style"][0]
                curr_block_top = block["box_style"][0]
                curr_block_bottom = block["box_style"][0] + block["box_style"][4]
                gap_with_prev_block = int(curr_block_top - prev_block_bottom)
                gap_with_next_block = int(next_block_top - curr_block_bottom)
                ret = False
                if gap_with_prev_block < gap_with_next_block and new_blocks[-1].get(header_key, False) and \
                        block["cell_values"][0]:
                    # Don't merge with header block.
                    gap_with_prev_block = gap_with_next_block
                    gap_with_next_block = 1
                if gap_with_prev_block < 0 or gap_with_prev_block < gap_with_next_block:
                    # Merge to previous block
                    ret = TableParser.merge_row_block_with_dest(block, new_blocks[-1], True)
                    if ret and self.blocks[idx - 1].get(header_key, False):
                        reset_header_cell_values = True
                elif (gap_with_prev_block > gap_with_next_block and
                      (gap_with_prev_block < 3 * gap_with_next_block or
                       block.get("row_merged", False))) or \
                        (self.blocks[idx + 1]["block_type"] != "table_row" and
                         block["box_style"][1] <= self.blocks[idx + 1]["box_style"][1] <= block["box_style"][2]):
                    # Merge to next block
                    ret = TableParser.merge_row_block_with_dest(block, self.blocks[idx + 1], False)
                if not ret:
                    block[row_group_key] = True
                    block["col_span"] = n_table_cols
                    block["cell_values"] = [block["block_text"]]
                    new_blocks.append(block)
            elif block["block_type"] != "table_row" and \
                    not block.get(header_key, False) and \
                    num_cell_values != n_table_cols:
                block[row_group_key] = True
                block["col_span"] = n_table_cols
                block["cell_values"] = [block["block_text"]]
                new_blocks.append(block)
            else:
                new_blocks.append(block)

        self.blocks = new_blocks

        for block in self.blocks:
            if "cell_values" not in block:
                print("can't find cell values", block["block_text"][0:80])
            elif self.has_merged_cells and len(block["cell_values"]) > 1 and len(block["visual_lines"]) > 1:
                vls = block["visual_lines"]
                eff_header_block = self.doc.make_block(vls[0:1], "header", block["block_idx"])
                eff_para_block = self.doc.make_block(vls[1:], 'para', block["block_idx"])
                # eff_para_block["header_text"] = eff_header_block["block_text"]
                eff_para_block["header_text"] = eff_header_block["block_text"]

                block["effective_header"] = eff_header_block
                block["effective_para"] = eff_para_block
        if n_table_cols == 1:
            self.blocks = [self.doc.merge_blocks(self.blocks)]
            if TABLE_DEBUG:
                print("merged 1 col table: ", self.blocks[-1]["block_text"][0:80])
        else:
            self.blocks[0]["is_actual_table_start"] = True
            if self.has_merged_cells:
                self.blocks[0]["has_merged_cells"] = True
            self.blocks[0]["is_table_start"] = True
            # header_block["is_table_start"] = True
            self.blocks[-1]["is_table_end"] = True

            if TABLE_DEBUG:
                print("last row: ", self.blocks[-1]["block_text"][0:80])
                print(f"built table: n_table_cols: {n_table_cols}")

    def are_aligned(self, prev_block, curr_block):
        prev_box = prev_block["visual_lines"][0]['box_style']
        curr_box = curr_block["visual_lines"][0]['box_style']
        return np.abs(prev_box[1] - curr_box[1]) < 0.2

    def align_header_group(self, col_spans, tr_block):
        tr_vls = tr_block["visual_lines"]
        cell_values = []
        hg_col_spans = []
        # print("short - tr", [vl['text'] for vl in row_block['visual_lines']])
        # print("\n", len(tr_vls), tr_block['block_text'])
        # align the columns by detecting left center or right alignment with a bunch of columns
        # print("header group: ", [vl['text'] for vl in tr_vls])
        # print("header: ", [vl['text'] for vl in th_vls])
        # print("diff: ", len(th_vls) - len(tr_vls))
        tr_block[header_group_key] = True
        # skip the first one - should mostly work
        last_col_header_idx = 1
        if col_spans[0][1] >= tr_vls[0]['box_style'][1] or \
                (len(col_spans) > 2 and (col_spans[0][1] +
                                         (col_spans[1][0] - col_spans[0][1]) / 2) >= tr_vls[0]['box_style'][1]):
            last_col_header_idx = 0
        if last_col_header_idx:
            cell_values.append("")
            hg_col_spans = [1]
        last_col_span = col_spans[last_col_header_idx]
        n_cols = 0
        for vl in tr_vls:
            cell_values.append(vl["text"])
            hg_style = vl["box_style"]
            hg_mid_point = hg_style[1] + (hg_style[2] - hg_style[1]) / 2
            if TABLE_HG_DEBUG:
                print("aligning hg : ", vl["text"], hg_mid_point)
            mid_points = []
            for col_header_idx in range(last_col_header_idx, len(col_spans)):
                col_span = col_spans[col_header_idx]
                n_cols = n_cols + 1
                mid_point = (
                    col_span[0]
                    + (col_span[1] - col_span[0]) / 2
                )
                col_span_adjusted_right = col_span[1]  # Initializing to column span right
                if col_header_idx <= len(col_spans) - 2:
                    col_span_adjusted_right += (col_spans[col_header_idx + 1][0] - col_span[1]) / 2
                # distance = abs((hg_mid_point - mid_point)/mid_point)
                if TABLE_HG_DEBUG:
                    print(col_header_idx, col_span, mid_point)
                mid_points.append(mid_point)
                if mid_point > hg_mid_point or col_span_adjusted_right >= hg_style[2]:
                    if TABLE_HG_DEBUG:
                        print("stopping at ", col_header_idx, mid_point)

                    #
                    # last_col_header_idx = col_header_idx + 1
                    # if last_col_header_idx < len(col_spans):
                    #     last_col_span = col_spans[last_col_header_idx]
                    # n_cols = 0
                    break
            mid_points = np.asarray(mid_points)
            n_cols = len(mid_points)  # (np.abs(mid_points - hg_mid_point)).argmin()
            if TABLE_HG_DEBUG:
                print(mid_points, n_cols)
            hg_col_spans.append(int(n_cols))
            last_col_header_idx = last_col_header_idx + n_cols
            if last_col_header_idx < len(col_spans):
                last_col_span = col_spans[last_col_header_idx]
                # if abs((hg_mid_point - mid_point) / mid_point) < 0.01:
                #     hg_col_spans.append(n_cols)
                #     last_col_header_idx = col_header_idx + 1
                #     if last_col_header_idx < len(col_spans):
                #         last_col_span = col_spans[last_col_header_idx]
                #     n_cols = 0
                #     break
        # print("hg_col_spans: ", hg_col_spans, cell_values)
        tr_block["col_spans"] = hg_col_spans
        tr_block["cell_values"] = cell_values

    def align_missing_columns(self, col_spans, tr_block):
        # align the columns by skipping spaces
        cell_values = [[] for i in range(len(col_spans))]
        tr_vls = tr_block["visual_lines"]
        last_col_header_idx = 0
        # for each vl in the row
        if TABLE_COL_DEBUG:
            print(f"\taligning into {len(col_spans)} spans: ", tr_block['block_text'][0:80])
        last_vl_span = None
        all_vls_in_same_span = False
        for vl in tr_vls:
            row_style = vl["box_style"]
            col_found = False
            # look for best column fit
            for col_header_idx in range(0, len(col_spans)):
                col_span = col_spans[col_header_idx]
                span_left = col_span[0]
                span_right = col_span[1]
                # print(col_header_style[1], row_style[1], col_header_style[2])
                do_overlap = (
                    row_style[1] <= span_right
                    and row_style[2] >= span_left
                )
                if do_overlap:
                    if TABLE_COL_DEBUG:
                        print(f"\t{vl['text']} aligns with {col_span}")
                    cell_values[col_header_idx].append(vl["text"])
                    # cell_values.append(cell_value)
                    last_col_header_idx = col_header_idx + 1
                    col_found = True
                    if not last_vl_span:
                        last_vl_span = col_header_idx
                    else:
                        all_vls_in_same_span = last_vl_span == col_header_idx
                        last_vl_span = col_header_idx
                    break
                else:
                    if TABLE_COL_DEBUG:
                        print(f"\t{vl['text']} doesn't align with {col_span}")
                        print("\t\t>> ", row_style[1], row_style[2], span_left, span_right)
                    # cell_values.append(cell_value)
            if not col_found:
                # If the vl doesn't fit into any of the span,
                # we will try the best approach to accommodate it
                for col_header_idx in range(0, len(col_spans) - 1):
                    col_span = col_spans[col_header_idx]
                    next_col_span = col_spans[col_header_idx + 1]
                    if col_span[0] <= row_style[1] and next_col_span[0] >= row_style[2]:
                        cell_values[col_header_idx].append(vl["text"])
                        if TABLE_COL_DEBUG:
                            print(f"\t{vl['text']} aligns with {col_span}")
                        if not last_vl_span:
                            last_vl_span = col_header_idx
                        else:
                            all_vls_in_same_span = last_vl_span == col_header_idx
                            last_vl_span = col_header_idx
        if all_vls_in_same_span:
            new_vl = self.doc.merge_vls(tr_vls)
            tr_block["visual_lines"] = [new_vl]
            if TABLE_COL_DEBUG:
                print(f"\tMerged TR Block VLs {new_vl} while aligning.")
        cell_values_texts = [" ".join(vals) for vals in cell_values]
        tr_block["cell_values"] = cell_values_texts

    def align_columns(self, th_block, tr_block, block_with_most_columns, col_spans):
        tr_vls = tr_block["visual_lines"]
        if TABLE_COL_DEBUG:
            print(f"aligning {len(tr_vls)} columns: ", tr_block['block_text'][0:80])

        # print(len(th_vls), len(tr_vls))
        # if len(block_with_most_columns['visual_lines']) == len(tr_vls):  # row has all columns
        if len(col_spans) == len(tr_vls):  # row has all columns
            cell_values = []
            for vl in tr_vls:
                cell_value = vl["text"]
                # print(cell_value)
                cell_values.append(cell_value)
            tr_block["cell_values"] = cell_values
        else:
            if th_block and tr_block["block_idx"] < th_block["block_idx"]:
                if len(col_spans) - len(tr_vls) >= 1:
                    self.align_header_group(col_spans, tr_block)
                else:# something really bad has happened, but let's assign cell values nevertheless
                    cell_values = []
                    for vl in tr_vls:
                        cell_value = vl["text"]
                        cell_values.append(cell_value)
                    tr_block["cell_values"] = cell_values
            else:
                # self.align_missing_columns_old(block_with_most_columns, tr_block)
                self.align_missing_columns(col_spans, tr_block)

    def evaluate_table(self):
        max_consecutive_rows = 0
        row_count = 0
        non_row_count = 0
        col_count = 0
        n_block_cols = []
        for (idx, block) in enumerate(self.blocks):
            if TABLE_DEBUG:
                print("---", block['block_text'][0:80])
                print("\t", block['block_type'], "n_cols:",
                      len(block["visual_lines"]),
                      f"page_idx: {block['page_idx']}",
                      get_box_string(block))
                for vls in block["visual_lines"]:
                    print("\t", vls['text'])
            if block["block_type"] == "table_row":
                is_reduced = self.reduce_row_block(block)
                if is_reduced and TABLE_DEBUG:
                    print("\t", "reduced_n_cols:", len(block["visual_lines"]))
                if False:  # is_reduced:
                    n_block_cols.append(len(block["visual_lines"]))
                else:
                    num_cols, _ = vhu.find_num_cols(block)
                    if TABLE_DEBUG:
                        print("Found number of cols : ", num_cols)
                    n_block_cols.append(num_cols)

                row_count = row_count + 1
                non_row_count = 0
            else:
                n_block_cols.append(1)
                non_row_count = non_row_count + 1
                max_consecutive_rows = max(max_consecutive_rows, row_count)
                row_count = 0
        col_count = max(n_block_cols)
        if TABLE_DEBUG:
            print("Col count:", col_count)
        if col_count == 2:
            self.reduce_two_column_table()
        if TABLE_2_COL_DEBUG:
            print("max_cons_rows", max_consecutive_rows, "cols", col_count)
        return n_block_cols

    def insert_vls(self, vls, block):
        block["visual_lines"].insert(0, vls)
        block['box_style'] = self.doc.calc_block_span(block)
        block['block_text'] = vls['text'] + " " + block["block_text"]

    def reduce_row_block(self, block):
        same_top = True
        vls = block["visual_lines"]
        p_vl_top = vls[0]['box_style'][0]
        for vl in vls[1:]:
            if abs(vl['box_style'][0] - p_vl_top) > 5:
                same_top = False
            p_vl_top = vl['box_style'][0]
        if same_top:
            # Sort based on left value if all VLs are of the same top.
            # There are cases when merging the VLs, left is not taken care.
            vls = sorted(block["visual_lines"], key=lambda line: line['box_style'][1])
        prev_vl = vls[0]
        new_vls = []
        vl_buf = []
        for curr_vl in vls[1:]:
            prev_box = prev_vl['box_style'] if len(vl_buf) == 0 else vl_buf[0]['box_style']
            curr_box = curr_vl['box_style']
            changed = False
            are_joined = (curr_box[0] - prev_box[0] > 5
                          and curr_box[1] > prev_box[1]
                          and curr_box[1] - prev_box[1] < 20)
            if not are_joined and curr_box[1] >= prev_box[1] and curr_box[1] - prev_box[1] < 20:
                if curr_vl.get("changed", False):
                    # Case where we have a multi row entry in column and
                    # there was a column delimiter which we deleted.
                    are_joined = True
                    changed = True
            if not are_joined and 0 < curr_box[1] - prev_box[2] < 1.5 * prev_vl['line_style'][5] and \
                    curr_box[4] <= 0.75 * prev_box[4]:
                # If the current VL is a short (in height) text when compared to the previous VL
                are_joined = True
            if are_joined:
                new_vl = self.doc.merge_line_info(prev_vl, curr_vl)
                '''
                if changed:
                    # Do we need to check for multi-line column data (spanning more than 2 lines)
                    # TODO:
                    new_vl = self.doc.merge_line_info(prev_vl, curr_vl)
                else:
                    new_vl = self.doc.merge_line_info(prev_vl, curr_vl)
                '''
                prev_vl = new_vl
                vl_buf.append(prev_vl)
            else:
                new_vls.append(prev_vl)
                prev_vl = curr_vl
                vl_buf = []
        new_vls.append(prev_vl)
        block["visual_lines"] = new_vls
        word_classes = [item for sublist in [vl["word_classes"] for vl in new_vls] for item in sublist]
        block["block_class"] = Counter(word_classes).most_common()[0][0]
        return len(vls) != len(new_vls)

    def reduce_two_column_table(self):
        prev_block = None
        new_blocks = []
        for block in self.blocks:
            #clone the vls
            if prev_block:
                # visual lines of previous block
                prev_vls = prev_block["visual_lines"]
                # visual lines of current block
                curr_vls = block["visual_lines"]

                prev_cols = len(prev_vls)
                curr_cols = len(curr_vls)

                prev_type = prev_block["block_type"]
                curr_type = block["block_type"]
                if TABLE_2_COL_DEBUG:
                    print("2 2 2 2 evaluating block -> ", block["block_text"][0:80], curr_cols, prev_type, curr_type)
                if prev_type != "table_row" and curr_type == "table_row":
                    # if a table_row follows a para, then merge the contents of the first column
                    # this is the case where the first column title is split into multiple lines
                    prev_vl = prev_vls[0]
                    curr_vl = curr_vls[0]
                    are_aligned = np.abs(curr_vl['box_style'][1] - prev_vl['box_style'][1]) < 20
                    # If a table-row follows a non-table_row and if the second VL of the table_row has
                    # intersection points with the above non_table_row, then don't merge them together
                    if are_aligned and \
                            curr_cols == 2 and \
                            curr_vls[1]['box_style'][1] < prev_vl['box_style'][2]:
                        are_aligned = False
                    if are_aligned:
                        new_vl = self.doc.merge_line_info(prev_vl, curr_vl)
                        block["visual_lines"][0] = new_vl
                        block["block_text"] = prev_vl['text'] + " " + block["block_text"]
                        self.has_merged_cells = True
                        if TABLE_2_COL_DEBUG:
                            # merging left column
                            print("l l l l: ", block["block_text"][0:80])
                    else:
                        if TABLE_2_COL_DEBUG:
                            # merging left column
                            print("t t t t: ", prev_block["block_text"][0:80])
                        new_blocks.append(prev_block)
                    prev_block = block
                elif prev_type == "table_row" and curr_type != "table_row" and len(prev_vls) > 1:
                    # if current block is para, merge its contents with previous block
                    # second column of previous row
                    prev_vl = prev_vls[1]
                    # first column of current row
                    curr_vl = curr_vls[0]
                    min_left_diff = 10000
                    min_left_idx = 0
                    for vl_idx, vl in enumerate(prev_vls[1:]):
                        temp_min_left_diff = np.abs(curr_vl['box_style'][1] - vl['box_style'][1])
                        if temp_min_left_diff < 40 and temp_min_left_diff <= min_left_diff:
                            min_left_diff = temp_min_left_diff
                            min_left_idx = vl_idx
                    are_aligned = min_left_diff < 40
                    if are_aligned:
                        # merge the row spanning both columns with previous row
                        vl_buf = [prev_vls[min_left_idx + 1]]
                        for vl in curr_vls:
                            vl_buf.append(vl)
                        # new_vl = self.doc.merge_line_info(prev_vl, curr_vl)
                        new_vl = self.doc.merge_vls(vl_buf)
                        # change second column of previous block
                        prev_block["visual_lines"][min_left_idx + 1] = new_vl
                        self.has_merged_cells = True
                        prev_block["block_text"] = " ".join(vl["text"] for vl in prev_vls)
                        # print("r r r r: ", prev_block["block_text"])
                        prev_block["block_type"] = "table_row"
                        if TABLE_2_COL_DEBUG:

                            print("r r r r: ", prev_block["block_text"][0:80])
                            print("\t", curr_vl['box_style'][1], prev_vl['box_style'][min_left_idx + 1])
                        # new_blocks.append(prev_block)
                        # the current block is skipped
                    else:
                        if TABLE_2_COL_DEBUG:
                            print("n n n n: ", prev_block["block_text"][0:80])
                        new_blocks.append(prev_block)
                        prev_block = block
                elif prev_type != "table_row" and curr_type != "table_row":
                    # print(">>>>checking overlap", prev_block['block_text'][0:40], "->", block['block_text'][0:40])
                    # print("\t", prev_block['box_style'], block['box_style'])
                    # this is where the left and right column cell data meet - make a table row so that we can
                    # keep going through the logic
                    if self.doc.have_y_overlap(prev_block, block, check_class=False):
                        if TABLE_2_COL_DEBUG:
                            print("m m m m: ", prev_block["block_text"][0:40], "->", block["block_text"][0:40])
                        new_block = self.doc.merge_blocks([prev_block, block])
                        new_block["block_type"] = "table_row"
                        # new_blocks.append(new_block)
                        prev_block = new_block
                    else:
                        # print("e e e e: ", block["block_text"])
                        new_blocks.append(prev_block)
                        prev_block = block
                else:
                    # print("e e e e: ", block["block_text"])
                    new_blocks.append(prev_block)
                    prev_block = block
            else:
                prev_block = block
        new_blocks.append(prev_block)
        if TABLE_2_COL_DEBUG:
            print("==============Final")
            for block in new_blocks:
                vls = block["visual_lines"]
                if len(vls) > 1:
                    print(vls[0]["text"][0:40], "----", vls[1]["text"][0:40])
                else:
                    print("*", vls[0]["text"][0:40], "----", "*"*40)
            # print("setting combined blocks", new_blocks[0]["block_text"])
            print("difference in blocks is: ", len(self.blocks) - len(new_blocks))
        self.blocks = new_blocks

    @staticmethod
    def merge_row_block_with_dest(row_block, dest_block, merge_to_prev):
        min_top = min(row_block["box_style"][0], dest_block["box_style"][0])
        min_left = min(row_block["box_style"][1], dest_block["box_style"][1])
        max_right = max(row_block["box_style"][2], dest_block["box_style"][2])
        max_bottom = max((row_block["box_style"][0] + row_block["box_style"][4]),
                         (dest_block["box_style"][0] + dest_block["box_style"][4]))

        box_style = BoxStyle(
            min_top,
            min_left,
            max_right,
            max_right - min_left,
            max_bottom - min_top
        )
        row_cell_index = None
        for idx, c in enumerate(row_block["cell_values"]):
            if c:
                row_cell_index = idx
        # Handle only first or last cell
        if row_cell_index == 0 or (row_cell_index == len(row_block["cell_values"]) - 1 and
                                   len(dest_block["cell_values"]) == row_cell_index + 1):
            if merge_to_prev:
                # TODO: Need to check whether we need to modify all the required data.
                # dest_block["visual_lines"].extend(row_block["visual_lines"])
                # dest_block["block_sents"][-1] = dest_block["block_sents"][-1] + " " + row_block["block_sents"][0]
                # if len(row_block["block_sents"]) > 1:
                #     dest_block["block_sents"].extend(row_block["block_sents"][1:])
                dest_block["block_text"] = dest_block["block_text"] + " " + row_block["block_text"]
                dest_block["box_style"] = box_style
                dest_block["cell_values"][row_cell_index] = dest_block["cell_values"][row_cell_index] + " " \
                                                            + row_block["cell_values"][row_cell_index]
                dest_block["visual_lines"].extend(row_block["visual_lines"])
            else:
                dest_block["block_text"] = row_block["block_text"] + " " + dest_block["block_text"]
                dest_block["box_style"] = box_style
                dest_block["cell_values"][row_cell_index] = row_block["cell_values"][row_cell_index] + " " + \
                                                            dest_block["cell_values"][row_cell_index]
                temp_vls = copy.deepcopy(row_block["visual_lines"])
                temp_vls.extend(dest_block["visual_lines"])
                dest_block["visual_lines"] = temp_vls
            dest_block["row_merged"] = True
            return True
        else:
            return False
