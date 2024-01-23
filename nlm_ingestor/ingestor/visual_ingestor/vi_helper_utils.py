"""
Abode for all Visual Ingestor Helper Utils.
"""
import numpy as np


def count_cols(vls):
    """
    Count the number of columns in the group of visual lines
    :param block: A Block of visual lines
    :return: Number of columns detected
    """
    if len(vls) == 0:
        return 0
    count = 1
    prev_line_info = vls[0]
    for line_info in vls[1:]:
        same_top = compare_top(line_info, prev_line_info)
        if same_top:
            count = count + 1
        else:
            break
    return count


def same_top_index(block):
    """
    Return the index of Visual Line which has the same top as the first visual line
    :param block: A Block of visual lines
    :return: Return the index of Visual Line which has the same top as the first visual line
    """
    vls = block['visual_lines']
    if len(vls) == 0:
        return 0
    first_vline = vls[0]
    index = 0
    for line_info in vls[1:]:
        index += 1
        same_top = compare_top(line_info, first_vline)
        if same_top:
            break
        else:
            continue
    return index


def compare_top(line_info, prev_line_info):
    """
    Compares the top of provided line_info to detect if both share the same top
    :param line_info: Current Line Info
    :param prev_line_info: Previous Line Info
    :return: True if both the line_info have the same top
    """
    curr_top = line_info['box_style'][0]
    prev_top = prev_line_info["box_style"][0]
    curr_line_top_adj = curr_top + (line_info['box_style'][4]/2)
    prev_line_top_adj = prev_top + (prev_line_info['box_style'][4]/2)
    # prev_bottom = prev_top + prev_line_info['box_style'][4]
    diff = abs(curr_line_top_adj - prev_line_top_adj)/curr_line_top_adj
    # same_top = 0.99 * prev_line_top_adj <= curr_line_top_adj <= 1.01 * prev_line_top_adj
    same_top = (diff < 0.005) or (abs(curr_top - prev_top) < (prev_line_info["box_style"][4] / 4))
    # same_top = prev_top <= curr_top <= prev_bottom
    # print("top compare: ", prev_line_info['text'], line_info['text'], same_top, diff)
    # ratio = prev_line_info['box_style'].top/line_info['box_style'].top
    # same_top = 0.97 <= ratio <= 1.01
    return same_top


def find_num_cols(block):
    """
    Find the number of columns from the Visual Lines of a block.
    Here we try to find the if there are disjoint x,y co-ordinates in Visual Lines.
    Invoke this preferably for a Table block
    :param block: Grouping of visual lines
    :return: Number of columns and Visual Lines which are considered for the calculation.
    TODO: Visual Lines returned might not be an accurate one depicting the actual cell. (cases where there are
            centre aligned data points.)
    """
    vls = block["visual_lines"]
    col_vls = [vls[0]]
    num_cols = 1
    for curr_vl in vls[1:]:
        found_intersection = False
        for col_vl in col_vls:
            col_box = col_vl['box_style']
            curr_box = curr_vl['box_style']
            if list(range(max(int(col_box[1]), int(curr_box[1])),
                          min(int(col_box[2]), int(curr_box[2]))+1)):
                # We have an intersection point.
                found_intersection = True
                break
        if not found_intersection:
            col_vls.append(curr_vl)
            num_cols += 1
    return num_cols, col_vls


def count_num_lines(visual_lines):
    """
    Count the number of actual lines based on the box_style[0] ==> Top
    :param visual_lines: Visual lines under consideration
    :returns: number of lines (0, if there are no visual_lines)
    """
    num_lines = 0
    if len(visual_lines):
        prev_vl = visual_lines[0]
        for vl in visual_lines[1:]:
            same_top = compare_top(vl, prev_vl)
            if not same_top:
                num_lines += 1
            prev_vl = vl
    return num_lines


def get_avg_space_bw_multi_line_vls(visual_lines):
    """
    Retrieve the average space between multi line visual_lines
    :param visual_lines: Visual lines under consideration
    :returns:
        average space: (0, if there is no visual lines or 1 line)
        spaces: list of spaces
    """
    avg_space = 0
    spaces = []
    prev_vl = visual_lines[0]
    for vl in visual_lines[1:]:
        same_top = compare_top(vl, prev_vl)
        if not same_top and prev_vl["box_style"][0] < vl["box_style"][0]:
            spaces.append(vl["box_style"][0] - (prev_vl["box_style"][0] + prev_vl["box_style"][4]))
        prev_vl = vl
    if len(spaces):
        avg_space = np.mean(spaces)
    return avg_space, spaces
