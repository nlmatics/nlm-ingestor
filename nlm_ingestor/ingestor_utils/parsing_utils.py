from collections import Counter
import nlm_ingestor.ingestor.visual_ingestor

"""
Contains utility functions for comparing and reconstructing
blocks
"""


def check_possible_table(prev_block, curr_block):
    """
    Sometimes a table row is not identifiable until
    The second row is resolved. In that case this
    function checks the previous block to see if
    it is potentially apart of the table
    """
    span1 = prev_block["visual_lines"][0]["box_style"][1], prev_block["visual_lines"][-1]["box_style"][2]
    span2 = curr_block["visual_lines"][0]["box_style"][1], curr_block["visual_lines"][-1]["box_style"][2]
    # only proceed if there is a high overlap for the bottom and above rows
    overlap = calculate_discrete_overlap(span1, span2)

    if round(overlap) == 1:
        prev_block_space_dict = get_line_spaces(prev_block['visual_lines'])
        curr_block_space_dict = get_line_spaces(curr_block['visual_lines'])
        if len(prev_block_space_dict) > 1 and curr_block_space_dict:
            possible_gaps, gap_threshold = find_potential_gaps(prev_block_space_dict)
            if 0.75 * min(curr_block_space_dict) < max(prev_block_space_dict):
                # Allow gap_threshold if we are almost 75% of the gaps
                # between the VLs in current block
                gap_threshold = round(min(prev_block_space_dict))
            if gap_threshold == 0:
                return False, [], []
            new_block_children, new_visual_lines = format_to_tr_block(prev_block, gap_threshold)
            if compare_centroids(curr_block, new_block_children) or \
                    compare_right_align(curr_block, prev_block):
                cells = [block['text'] for block in new_block_children]
                return True, cells, new_visual_lines
    return False, [], []


def calculate_discrete_overlap(p1, p2, small=True):
    """
    p1 should p2 should be tuples
    containing spans x1, x2
    small is a param to use either the
    larger or smaller span for
    computing overlap
    """
    p1 = set(range(int(p1[0]), int(p1[1])))
    p2 = range(int(p2[0]), int(p2[1]))
    if len(p1) > len(p2):
        if small:
            denominator = len(p2)
        else:
            denominator = len(p1)
    else:
        if small:
            denominator = len(p1)
        else:
            denominator = len(p2)
    if denominator == 0:
        denominator = 1
    return len(p1.intersection(p2)) / denominator


def get_line_spaces(line):
    """
    This functions tries to find
    any abnormal gaps or significant
    spaces in a line
    """
    spaces = []
    prev_end_point = 0
    for idx, i in enumerate(line):
        spaces.append(round(i['box_style'][1] - prev_end_point, 1))
        prev_end_point = i['box_style'][2]
    # the first space is the text-indent. Ignore this
    return Counter(spaces[1:])


def compare_centroids(curr_block, new_block_children):
    """
    this function compares the center of the
    cell columns. If there is a very high similarity
    This would suggest the new block is tr match for
    the table scheme.
    """
    centroid_diff = []
    # TODO add logic to shift only considering case
    # where is header is shifted one cell to the right
    for i, j in zip(line_tr_centroids(curr_block)[1:], new_block_children):
        centroid_diff.append(int(i['center'] - j['centroid']))
    # print(centroid_diff)
    return sum(centroid_diff) == 0


def find_potential_gaps(gap_count):
    """
    This function checks if a table row
    can be formed from the current table
    row spacing scheme. This is for edge
    cases when tika doesn't properly
    chunk the cells of a line
    """
    possible_gaps = 0
    min_gap = min(gap_count)
    gap_threshold = []
    for gap_size in gap_count:
        if gap_size > (min_gap * 3):
            gap_threshold.append(gap_size)
            possible_gaps += gap_count[gap_size]
    if len(gap_threshold):
        return possible_gaps, min(gap_threshold)  # suggested splits
    return [], 0


def format_to_tr_block(prev_block, gap_threshold):
    """
    merge child blocks in visual lines
    this will be the suggested visual lines
    dict_keys(['box_style', 'line_style', 'text', 'page_idx', 'line_parser', 'word_classes', 'class', 'space'])
    """
    new_block_children = []
    prev_child_x2 = prev_block['visual_lines'][0]['box_style'][2]
    prev_child = prev_block['visual_lines'][0]
    block_text = prev_block['visual_lines'][0]['text']
    block_buff = [prev_child]
    new_visual_lines = []
    child = None
    for child in prev_block['visual_lines'][1:]:
        child_x1 = child['box_style'][1]

        if gap_threshold <= round(child_x1 - prev_child_x2):
            new_child_block = nlm_ingestor.ingestor.visual_ingestor.Doc.merge_vls(block_buff)
            new_visual_lines.append(new_child_block)
            new_block_children.append({"text": block_text,
                                       "centroid": get_centroid(block_buff[0]['box_style'][1],
                                                                block_buff[-1]['box_style'][2]),
                                       "span": (prev_child['box_style'][1], child['box_style'][2])
                                       })
            block_text = child['text']  # new block
            block_buff = [child]
        else:
            block_buff.append(child)
            block_text += " " + child['text']
        prev_child = child
        prev_child_x2 = child['box_style'][2]
    else:
        if block_buff and child:
            new_block_children.append({"text": block_text,
                                       "centroid": get_centroid(block_buff[0]['box_style'][1],
                                                                block_buff[-1]['box_style'][2]),
                                       "span": (prev_child['box_style'][1], child['box_style'][2])
                                       })
            new_child_block = nlm_ingestor.ingestor.visual_ingestor.Doc.merge_vls(block_buff)
            new_visual_lines.append(new_child_block)
    return new_block_children, new_visual_lines


def get_centroid(x1, x2):
    return x1 + (x2 - x1) / 2


def line_tr_centroids(line):
    tr1 = []
    for p in line['visual_lines']:
        x1 = p['box_style'][1]
        x2 = p['box_style'][2]
        tr1.append({"center": get_centroid(x1, x2), "span": (x1, x2)})
    return tr1


def compare_right_align(curr_block, prev_block):
    """
    this function compares the right alignment of VLs starting from 2nd VL onwards.
    """
    right_align = False
    for i, j in zip(curr_block['visual_lines'][1:], prev_block['visual_lines'][:]):
        if abs(i['box_style'][2] - j['box_style'][2]) <= 2:
            right_align = True
        else:
            right_align = False
            break
    return right_align

