from functools import cmp_to_key
import numpy as np

REORDER_DEBUG = False
TOP_THRESHOLD = 15


class OrderFixer:
    def __init__(self, doc, page_blocks, offset):
        self.doc = doc
        self.page_blocks = page_blocks
        self.offset_blocks = page_blocks[0:offset]
        self.blocks_to_reorder = page_blocks[offset:]
        self.contiguous_blocks = []
        self.ratios = []

    def group_by_left(self, blocks):
        blocks_sorted_by_left = sorted(
            blocks,
            key=lambda blk: (blk["visual_lines"][0]["box_style"][1], blk["visual_lines"][0]["box_style"][0])
        )
        if REORDER_DEBUG:
            self.print_blocks(blocks_sorted_by_left, "left ordered")
        contiguous_blocks = []
        prev_left = 1000000
        block_buf = []
        left_range = [100000, 0]
        for b in blocks_sorted_by_left:
            curr_box = b["visual_lines"][0]["box_style"]
            curr_left = curr_box[1]
            if abs(prev_left - curr_left) < 20:
                left_range[0] = min(curr_left, left_range[0])
                left_range[1] = max(curr_left, left_range[1])
                block_buf.append(b)
            else:
                if len(block_buf) > 0:
                    # if len(block_buf) == 1:  # Most likely left_range is still [100000, 0]
                    #    left_range[0] = min(curr_left, left_range[0])
                    #    left_range[1] = max(curr_left, left_range[1])
                    cb = {"blocks": block_buf, "left_range": left_range}
                    contiguous_blocks.append(cb)
                block_buf = [b]
                left_range = [100000, 0]
            prev_left = curr_left
        if len(block_buf) > 0:
            cb = {"blocks": block_buf, "left_range": left_range}
            contiguous_blocks.append(cb)
        n_blocks = len(blocks)
        contiguous_blocks = sorted(
            contiguous_blocks,
            key=lambda c_blk: c_blk["left_range"][0],
        )

        def calc_c_blok_bound(c_blk):
            """
            Calculate bound of the contiguous_block (considering only non-table rows)
            Returns: (left, top, right, bottom), non_table_row_blocks
            """
            # Retrieve all non table rows.
            non_table_row_blocks: list = [blk for blk in c_blk['blocks'] if blk["block_type"] != "table_row"]
            if not non_table_row_blocks:
                return (0, 0, 0, 0), non_table_row_blocks
            # Sort them by y.
            non_table_row_blocks.sort(key=lambda blk: blk["visual_lines"][0]["box_style"][0])
            top = non_table_row_blocks[0]['visual_lines'][0]['box_style'][0]
            bottom = non_table_row_blocks[-1]['visual_lines'][0]['box_style'][0] + \
                     non_table_row_blocks[-1]['visual_lines'][0]['box_style'][4]
            left = 1000000
            right = -1
            for blk in non_table_row_blocks:
                left = min(blk['visual_lines'][0]['box_style'][1], left)
                right = max(blk['visual_lines'][-1]['box_style'][2], right)
            return (left, top, right, bottom), non_table_row_blocks

        def check_within_cb_bounds(blk, cb_bound, top_sorted_blocks):
            """
            Check whether the blk is within in the bounds as dictated by cb_bound.
            """
            b_left = blk['visual_lines'][0]['box_style'][1]
            b_top = blk['visual_lines'][0]['box_style'][0]
            left, top, right, bottom = cb_bound
            nearest_top = 0
            # Get the previous block's y-coord
            for s_blk in top_sorted_blocks:
                if s_blk['visual_lines'][0]['box_style'][0] <= b_top:
                    nearest_top = s_blk['visual_lines'][0]['box_style'][0]
                else:
                    break
            if nearest_top:
                if (b_top - nearest_top) > 35:  # If we are too far off from the last point
                    return False
            if top <= b_top <= bottom and left <= b_left <= right:
                return True
            else:
                return False

        if REORDER_DEBUG:
            for cg in contiguous_blocks:
                print(
                    f"============= Left ordered contiguous_blocks {len(cg['blocks'])}"
                    f" .. Range {cg['left_range']}============ ",
                )
                for b in cg['blocks']:
                    print(
                        f" Type:: {b['block_type']} .... {b['block_text']}...."
                        f"{b['visual_lines'][0]['box_style'][1]} .... {b['visual_lines'][0]['box_style'][0]}...."
                        f"{b['visual_lines'][-1]['box_style'][0]} ",
                    )
        first_column = contiguous_blocks[0]
        bounds, non_table_row_blocks = calc_c_blok_bound(first_column)
        cnt_table_rows = sum(map(lambda blk: blk["block_type"] == "table_row", first_column["blocks"]))
        cnt_table_row_vls = sum(map(lambda blk: len(blk["visual_lines"]) if blk["block_type"] == "table_row" else 0,
                                    first_column["blocks"]))
        first_column_vls = sum(map(lambda blk: len(blk["visual_lines"]), first_column["blocks"]))
        for block in first_column["blocks"]:
            if (len(contiguous_blocks) > 1 and
                    block["visual_lines"][-1]["box_style"][2] > contiguous_blocks[1]["left_range"][1]):
                if block["block_type"] == "table_row" and \
                        (cnt_table_row_vls / first_column_vls) < .40 and \
                        (cnt_table_rows / len(first_column["blocks"])) < 0.40 and \
                        not check_within_cb_bounds(block, bounds, non_table_row_blocks):
                    if REORDER_DEBUG:
                        print("splitting spanning block:", block["block_text"])
                        print("splitting spanning BOUNDS:", bounds)
                        print("splitting spanning block:", block)
                    print("splitting line:", block['block_text'])
                    block_vls = block["visual_lines"]
                    split_points = []
                    split_cbs = []

                    # for vl_idx, vl in enumerate(block_vls[1:]):
                    #    best_fit_diff = 10000
                    #    best_fit_cb_idx = -1
                    #    for cb_idx, cb in enumerate(contiguous_blocks[1:]):
                    #        if vl["box_style"][1] >= cb["left_range"][0]:
                    #            diff = vl["box_style"][1] - cb["left_range"][0]
                    #            if diff < best_fit_diff:
                    #                best_fit_cb_idx = cb_idx + 1
                    #                best_fit_diff = diff
                    #    split_points.append(vl_idx + 1)
                    #    split_cbs.append(contiguous_blocks[best_fit_cb_idx])
                    for cb_idx, cb in enumerate(contiguous_blocks[1:]):
                        for vl_idx, vl in enumerate(block_vls):
                            if vl["box_style"][1] >= cb["left_range"][0]:
                                split_points.append(vl_idx)
                                split_cbs.append(cb)
                                continue

                    n_splits = len(split_points)
                    if n_splits > 0:
                        # split this line and insert it at the right y at the right column
                        for split_idx, split_point in enumerate(split_points):
                            if n_splits - 1 > split_idx:
                                # print(n_splits, split_idx)
                                sub_vls = block_vls[
                                    split_point: split_points[split_idx + 1]
                                ]
                            else:
                                sub_vls = block_vls[split_point:]
                            if len(sub_vls) > 0:
                                new_block = self.doc.make_block(sub_vls, "para", 0)
                                new_block["block_type"] = self.doc.determine_block_type(
                                    new_block,
                                )
                                if REORDER_DEBUG:
                                    print(
                                        "adding new block:",
                                        new_block["block_text"],
                                        new_block["block_type"],
                                    )
                                # self.insert_oo_block(block_1, split_cbs[split_idx]['blocks'])
                                split_cbs[split_idx]["blocks"].append(new_block)
                                n_blocks = n_blocks + 1
                        # truncate the original block
                        block["visual_lines"] = block_vls[0 : split_points[0]]
                        block_text = ""
                        for vl in block["visual_lines"]:
                            block_text = block_text + " " + vl["text"]
                        block["block_text"] = block_text
                        block["block_type"] = self.doc.determine_block_type(block)
                        if REORDER_DEBUG:
                            print("Left out blocks:", block_text, block["block_type"])

        ratios = []

        def is_table_rows(blk, buf_blocks):
            """
            If the last element in buf_blocks is a table row and
            current element is also a table row, check for the difference in y-cord.
            if y_cord is less than 70 (10% of the height, which is normally ~700), Return True
            Else False
            """
            if len(buf_blocks) > 0:
                last_blk = buf_blocks[-1]
                if blk["block_type"] == last_blk["block_type"] == "table_row":
                    if 0 \
                            <= blk["visual_lines"][0]["box_style"][0] - last_blk["visual_lines"][0]["box_style"][0] \
                            <= 70:
                        return True
                    else:
                        return False
                else:
                    return False
            else:
                return False

        good_cb = []
        if len(contiguous_blocks) > 1:
            for idx, cb in enumerate(contiguous_blocks):
                items = cb["blocks"]
                top_sorted = sorted(
                    items,
                    key=lambda b: b["visual_lines"][0]["box_style"][0],
                )
                block_buf = []
                prev_top = -10000
                for b in top_sorted:
                    curr_box = b["visual_lines"][0]["box_style"]
                    curr_top = curr_box[0]
                    if abs(curr_top - prev_top) < 35:  # or is_table_rows(b, block_buf):
                        block_buf.append(b)
                    else:
                        if len(block_buf) > 1:
                            # TODO: left_range is wrong here. Need to recalculate it.
                            good_cb.append(
                                {"blocks": block_buf, "left_range": cb["left_range"]},
                            )
                            block_buf = []  # Reset
                        block_buf.append(b)
                    prev_top = curr_top
                if len(block_buf) > 0:
                    good_cb.append({"blocks": block_buf, "left_range": cb["left_range"]})
        contiguous_blocks = good_cb

        for idx, cb in enumerate(contiguous_blocks):
            items = cb["blocks"]
            ratio = len(items) / n_blocks
            ratios.append(ratio)
            top_sorted = sorted(
                items,
                key=lambda b: b["visual_lines"][0]["box_style"][0],
            )
            contiguous_blocks[idx]["blocks"] = top_sorted
            if REORDER_DEBUG:
                key = "left contiguous" + str(idx)
                print("\n", key, "ratio: ", ratio)
                self.print_blocks(top_sorted, key)

        return contiguous_blocks, ratios

    def print_blocks(self, blocks, description):
        if REORDER_DEBUG:
            print(f"==== {description} ===")
            print(f"==== {len(blocks)} ===")
            for b in blocks:
                print("\t", b["block_text"][0:120], "... ", b['block_type'])
            print(f"==== end {description} ===\n")

    def insert_out_of_order_block(self, oob, main_block):
        if len(oob["visual_lines"]) == 1 and self.doc.is_list_item(
                oob["visual_lines"][0],
        ):
            if REORDER_DEBUG:
                print("skipping...")
            return True
        if REORDER_DEBUG:
            print("finding location for --", oob["block_text"][0:80])
        ob_top = oob["visual_lines"][0]["box_style"][0]
        ob_left = oob["visual_lines"][0]["box_style"][1]
        ob_right = oob["visual_lines"][0]["box_style"][2]
        prev_top = main_block[0]["visual_lines"][0]["box_style"][0]
        location_found = False
        for idx, gb in enumerate(main_block):
            gb_top = gb["visual_lines"][0]["box_style"][0]
            gb_left = gb["visual_lines"][0]["box_style"][1]
            cond = (gb_top >= ob_top) if idx == 0 else (gb_top >= ob_top > prev_top)
            if cond:
                #  Do we need to determine block type again.
                # oob["block_type"] = self.doc.determine_block_type(oob)
                if REORDER_DEBUG:
                    print(
                        "found location before --",
                        main_block[idx]["block_text"][0:120],
                    )
                if gb_top == ob_top or abs(gb_top - ob_top) < 0.1:
                    # If we are of the same top, look left-wise to pick the right spot.
                    for insert_idx, insert_gb in enumerate(main_block[idx:]):
                        insert_top = insert_gb["visual_lines"][0]["box_style"][0]
                        insert_left = insert_gb["visual_lines"][0]["box_style"][1]
                        if abs(insert_top - ob_top) < 0.1 and insert_left < ob_left:
                            continue
                        else:
                            main_block.insert(idx + insert_idx, oob)
                            location_found = True
                            break
                else:
                    # If there is a match of bottom,
                    # check whether the current left is greater than the previous right.
                    if (oob["box_style"][0] + oob["box_style"][4]) == (
                            main_block[idx]["box_style"][0] + main_block[idx]["box_style"][4]
                    ) and oob["box_style"][1] > main_block[idx]["box_style"][2]:
                        main_block.insert(idx + 1, oob)
                    else:
                        main_block.insert(idx, oob)
                    location_found = True
                    break
            elif gb_top < ob_top and \
                    gb_left > ob_right and \
                    ((oob["visual_lines"][-1]["box_style"][0] + oob["visual_lines"][-1]["box_style"][4]) <=
                     (gb["visual_lines"][-1]["box_style"][0] + gb["visual_lines"][-1]["box_style"][4])):
                main_block.insert(idx, oob)
                location_found = True
            if location_found:
                break
            prev_top = gb_top
        if not location_found:
            if main_block[0]["visual_lines"][0]["page_idx"] == oob["visual_lines"][0]["page_idx"]:
                if REORDER_DEBUG:
                    print("appending oob to end --")
                main_block.append(oob)
            else:
                if REORDER_DEBUG:
                    print("appending oob to start --")
                main_block.insert(0, oob)
        return False

    def reorder_two_column_layout(self):
        skipped_blocks = 0
        if REORDER_DEBUG:
            print("==== original ===")
            for b in self.blocks_to_reorder:
                print(b["block_text"][0:120])
            print("==== end original ===")
        main_block_idx = np.argmax(self.ratios)
        main_blocks = self.contiguous_blocks[main_block_idx]
        reordered_blocks = []
        for idx, cb in enumerate(self.contiguous_blocks):
            if REORDER_DEBUG:
                print(f"contiguous block with length {len(cb)} and ratio {self.ratios[idx]} .. ",
                      cb[0]["block_text"][0:120])
            if idx != main_block_idx and self.ratios[idx] < 0.2:
                oo_blocks = cb
                if REORDER_DEBUG:
                    print("==== out of order ===")
                    for b in oo_blocks:
                        print("---", b["block_text"][0:120], b["block_type"])
                    print("==== end out of order ===")
                for oob in oo_blocks:
                    is_skipped = self.insert_out_of_order_block(oob, main_blocks)
                    if is_skipped:
                        skipped_blocks = skipped_blocks + 1
            reordered_blocks = main_blocks
        ratios_to_act = [i for i in self.ratios if i >= 0.2]
        if len(ratios_to_act) == 2:
            next_main_blk_idx = np.array(self.ratios).argsort()[-2:][::-1][1]
            if ratios_to_act[0] == ratios_to_act[1]:
                # Reset the next_main_blk_idx to 1 if both the ratios are same.
                next_main_blk_idx = 1
            if np.argmax(ratios_to_act) == 0:  # main_block is the first contiguous_blocks
                reordered_blocks.extend(self.contiguous_blocks[next_main_blk_idx])
            else:
                if self.contiguous_blocks[next_main_blk_idx][0]['box_style'][0] < reordered_blocks[-1]['box_style'][0]:
                    temp = reordered_blocks
                    reordered_blocks = self.contiguous_blocks[next_main_blk_idx]
                    reordered_blocks.extend(temp)
                else:
                    reordered_blocks.extend(self.contiguous_blocks[next_main_blk_idx])
        if REORDER_DEBUG:
            self.print_blocks(reordered_blocks, "two-col reordered")
        return reordered_blocks, skipped_blocks

    def reorder_multi_column_layout(self):
        if REORDER_DEBUG:
            self.print_blocks(self.blocks_to_reorder, "original")
        contiguous_blocks, ratios = self.group_by_left(self.blocks_to_reorder)
        if REORDER_DEBUG:
            print(">>ratios: ", ratios)
        # main_block_idx = [np.argmax(ratios)]
        # first isolate all the large blocks and get their bounds
        main_block_idxs = []
        main_block_bounds = []
        for idx, ratio in enumerate(ratios):
            if ratio > 0.05 and len(contiguous_blocks[idx]["blocks"]) > 1:
                main_block_items = contiguous_blocks[idx]["blocks"]
                main_block_idxs.append(idx)
                main_block_bounds.append(
                    self.doc.calculate_block_bounds_from_vls(main_block_items),
                )
                if REORDER_DEBUG:
                    print("==== main block ===")
                    print("\t#lines:", len(main_block_items))
                    for item in main_block_items:
                        print("\t", item["block_text"][0:80])
                    print("==== end main block ===")

        # main_blocks = contiguous_blocks[main_block_idx]
        # skipped_blocks = 0
        for idx, cb in enumerate(contiguous_blocks):
            if REORDER_DEBUG:
                print(
                    f"contiguous block {len(cb)}",
                    cb["blocks"][0]["block_text"][0:120],
                )
            if idx not in main_block_idxs:
                oo_blocks = cb["blocks"]
                new_cb_blocks = []
                if REORDER_DEBUG:
                    print("==== out of order ===")
                    for b in oo_blocks:
                        print("---", b["block_text"][0:120], b["block_type"])
                    print("==== end out of order ===")
                for oob in oo_blocks:
                    spot_found = False
                    for main_block_idx, cb_idx in enumerate(main_block_idxs):
                        mb = contiguous_blocks[cb_idx]
                        mb_left, mb_top, mb_right, mb_bottom = main_block_bounds[
                            main_block_idx
                        ]
                        ob_box = oob["visual_lines"][0]["box_style"]
                        ob_in_mb = (mb_left <= ob_box[1] <= mb_right) and (
                            mb_top <= ob_box[0] <= mb_bottom
                        )
                        if ob_in_mb and len(cb["blocks"]) > 0:
                            if REORDER_DEBUG:
                                print("found spot for: ", oob["block_text"],
                                      " in ", contiguous_blocks[cb_idx]["blocks"][0]["block_text"])
                            mb["blocks"].append(oob)
                            spot_found = True
                            break
                    if not spot_found:
                        new_cb_blocks.append(oob)
                cb["blocks"] = new_cb_blocks

        reordered_blocks = []
        # remove empty blocks
        # for cb in contiguous_blocks:
        #     if len(cb["blocks"]) == 0:
        #         contiguous_blocks.remove(cb)

        def cb_compare(cb_1, cb_2):
            cb_1_box = cb_1["blocks"][0]["visual_lines"][0]["box_style"]
            cb_2_box = cb_2["blocks"][0]["visual_lines"][0]["box_style"]
            cb_1_blk_box = cb_1["blocks"][0]["box_style"]
            cb_2_blk_box = cb_2["blocks"][0]["box_style"]
            top_diff = cb_1_box[0] - cb_2_box[0]
            left_diff = cb_1_box[1] - cb_2_box[1]
            if self.doc.have_y_overlap(cb_1["blocks"][0], cb_2["blocks"][0]) or \
                    list(range(max(int(cb_1_blk_box[0]), int(cb_2_blk_box[0])),
                               min(int(cb_1_blk_box[0] + cb_1_blk_box[4]), int(cb_2_blk_box[0] + cb_2_blk_box[4]))+1)):
                return left_diff
            else:
                return top_diff

        good_cb = []
        for cb in contiguous_blocks:
            if len(cb["blocks"]) > 0:
                good_cb.append(cb)
                # print("-->", cb["blocks"][0]["block_text"])
                # print("\t-->", cb["blocks"][0]["visual_lines"][0]["box_style"][0])

        contiguous_blocks = good_cb
        # sort all blocks by top and left
        contiguous_blocks = sorted(contiguous_blocks, key=cmp_to_key(cb_compare))
        # combine all the blocks, sort each continuous block again by top
        for cb in contiguous_blocks:
            merged_blocks = self.get_cb_blocks(cb)
            reordered_blocks = reordered_blocks + merged_blocks
        if REORDER_DEBUG:
            self.print_blocks(reordered_blocks, "multi-col reordered")
        return reordered_blocks, 0

    def get_cb_blocks(self, cb):
        blocks = sorted(
            cb["blocks"],
            key=lambda b: b["visual_lines"][0]["box_style"][0],
        )
        prev_block = blocks[0]
        prev_top = prev_block["visual_lines"][-1]["box_style"][0]
        cb_blocks = []
        merge_buf = [prev_block]
        for curr_block in blocks[1:]:
            merged = False
            curr_top = curr_block["visual_lines"][-1]["box_style"][0]
            if (
                prev_block["block_type"] == "list_item" or len(merge_buf) > 1
            ) and not prev_block["block_text"].endswith("."):
                if curr_block["block_type"] == "para":
                    space = curr_top - prev_top
                    line_style = prev_block["visual_lines"][-1]["line_style"]
                    if space <= 1.1 * line_style[2]:
                        merge_buf.append(curr_block)
                        merged = True

            if not merged:
                cb_blocks.append(self.doc.merge_blocks(merge_buf))
                merge_buf = [curr_block]
            prev_block = curr_block
            prev_top = curr_top
        cb_blocks.append(self.doc.merge_blocks(merge_buf))
        return cb_blocks

    def order_two_contiguous_blocks(self, contiguous_blocks, ratios):
        def comparator():
            def blk_compare(blk1, blk2):
                cb_1_box = blk1["visual_lines"][0]["box_style"]
                cb_1_last_box = blk1["visual_lines"][-1]["box_style"]
                cb_2_box = blk2["visual_lines"][0]["box_style"]
                cb_2_last_box = blk2["visual_lines"][-1]["box_style"]
                top_diff = cb_1_box[0] - cb_2_box[0]
                left_diff = cb_1_box[1] - cb_2_box[1]
                # Check whether we have an intersection of y coordinate
                if list(range(max(int(cb_1_box[0]), int(cb_2_box[0])),
                              min(int(cb_1_last_box[0] + cb_1_last_box[4]),
                                  int(cb_2_last_box[0] + cb_2_last_box[4]))+1)):
                    return left_diff
                else:
                    return top_diff
            return blk_compare
        cmp = comparator()
        reordered_blocks = []
        # Calculate primary and secondary cb based on the number of blocks in it
        num_blocks_in_cb = [len(cb) for cb in contiguous_blocks]
        #if num_blocks_in_cb[0] == num_blocks_in_cb[1]:
        num_blocks_in_cb = ratios
        primary_cb = contiguous_blocks[np.argmax(num_blocks_in_cb)]
        secondary_cb = contiguous_blocks[np.argmin(num_blocks_in_cb)]
        page_style = list(self.doc.page_styles[primary_cb[-1]["visual_lines"][0]["page_idx"]])

        _, _, _, bottom_2 = self.doc.calculate_block_bounds_from_vls(secondary_cb)

        secondary_cb_in_bw_primary = False
        blk_to_check_style = secondary_cb[0]['box_style']
        min_left = 10000    # Store min_left till the condition is met
        max_right = -1      # Store max right till the condition is met
        for blk_idx, blk in enumerate(primary_cb[:-1]):
            if blk['box_style'][0] < bottom_2:
                # Consider only blocks within the bottom of the secondary_cb
                min_left = min(min_left, blk['box_style'][1])
                max_right = max(max_right, blk['box_style'][2])
                # Check whether the first block of secondary_cb is between 2 blocks of the primary
                if blk['box_style'][0] <= blk_to_check_style[0] <= primary_cb[blk_idx + 1]['box_style'][0]:
                    if min_left <= blk_to_check_style[1] <= max_right:
                        secondary_cb_in_bw_primary = True
                    break
        if secondary_cb_in_bw_primary:
            # We are going to create a single block by mixing everything together.
            # May not be the right thing to do.
            # TODO: Check later for any anomalies
            blocks_to_reorder = contiguous_blocks[0]
            blocks_to_reorder.extend(contiguous_blocks[1])
            reordered_blocks = sorted(blocks_to_reorder, key=cmp_to_key(cmp))
        else:
            # Individual blocks are sorted separately and merged
            for cb in contiguous_blocks:
                if not len(reordered_blocks):
                    reordered_blocks = sorted(cb, key=cmp_to_key(cmp)) \
                        if not page_style[3].get("probable_multi_column", False) else cb
                else:
                    reordered_blocks.extend(sorted(cb, key=cmp_to_key(cmp))
                                            if not page_style[3].get("probable_multi_column", False) else cb)

        return reordered_blocks

    def reorder(self):
        contiguous_blocks = []
        block_buf = []
        prev_top = -10000
        total_lines = 0

        if REORDER_DEBUG:
            print(
                f"============= Blocks to Reorder {len(self.blocks_to_reorder)}  ============ ",
            )
            for b in self.blocks_to_reorder:
                print(
                    f" Type:: {b['block_type']} ... {b['page_idx']}.... {b['block_text']}...."
                    f"{b['visual_lines'][0]['box_style'][1]} .... {b['visual_lines'][0]['box_style'][0]}...."
                    f"{b['visual_lines'][-1]['box_style'][0]} ",
                )

        # find all blocks that are contiguous across the y axis
        temp_storage = []
        probable_multi_column = False
        prev_block = None
        for b in self.blocks_to_reorder:
            curr_box = b["visual_lines"][0]["box_style"]
            curr_top = curr_box[0]

            if curr_top >= prev_top or abs(curr_top - prev_top) < TOP_THRESHOLD or \
                    (len(block_buf) > 0 and block_buf[-1]["page_idx"] != b["page_idx"]) or \
                    (prev_block and
                     0 <= b["visual_lines"][-1]["box_style"][0] - prev_block['visual_lines'][-1]['box_style'][0]
                     < TOP_THRESHOLD):
                if len(temp_storage):
                    block_buf.extend(temp_storage)
                    probable_multi_column = True
                    temp_storage = []
                block_buf.append(b)
            else:
                # contiguous_blocks.append(block_buf)
                # block_buf = [b]
                add_to_temp = False
                for b_idx, b_buf in enumerate(block_buf):
                    curr_b_buf_box = b_buf["visual_lines"][0]["box_style"]
                    curr_b_buf_top = curr_b_buf_box[0]
                    if abs(curr_b_buf_top - curr_top) < TOP_THRESHOLD and \
                            curr_b_buf_box[2] < curr_box[1] and len(b_buf["visual_lines"]) > 3 and \
                            b_buf["block_type"] != "table_row":
                        for b_temp_buf in block_buf[b_idx + 1:]:
                            add_to_temp = True
                            if b_temp_buf["visual_lines"][0]["box_style"][2] > curr_box[1] or \
                                    b_temp_buf["block_type"] == "table_row":
                                add_to_temp = False
                                break
                if not add_to_temp and len(block_buf) > 0 and block_buf[-1]["block_type"] != "table_row":
                    prev_last_vl_box_style = block_buf[-1]["visual_lines"][-1]["box_style"]
                    prev_first_vl_box_style = block_buf[-1]["visual_lines"][0]["box_style"]
                    if prev_first_vl_box_style[0] > prev_last_vl_box_style[0] and \
                            prev_first_vl_box_style[2] < prev_last_vl_box_style[1] and \
                            (abs((prev_last_vl_box_style[0] + prev_last_vl_box_style[4]) - curr_top) < TOP_THRESHOLD or
                             (curr_top > (prev_last_vl_box_style[0] + prev_last_vl_box_style[4]))):
                        probable_multi_column = True
                        add_to_temp = True
                if add_to_temp and b["block_type"] != "table_row":
                    temp_storage.append(b)
                else:
                    if len(temp_storage):
                        if len(block_buf):
                            contiguous_blocks.append(block_buf)
                        block_buf = temp_storage
                        temp_storage = []
                    contiguous_blocks.append(block_buf)
                    block_buf = [b]
            prev_top = curr_top
            total_lines = total_lines + len(b["visual_lines"])
            prev_block = b

        if probable_multi_column:
            page_style = list(self.doc.page_styles[self.page_blocks[-1]["visual_lines"][0]["page_idx"]])
            page_style[3]["probable_multi_column"] = True
            self.doc.page_styles[self.page_blocks[-1]["visual_lines"][0]["page_idx"]] = tuple(page_style)
        if total_lines == 0:
            return self.page_blocks, False
        if len(temp_storage):
            if len(block_buf):
                block_buf.extend(temp_storage)
            else:
                block_buf = temp_storage
        contiguous_blocks.append(block_buf)

        def line_count(cb):
            count = 0
            for blk in cb:
                count = count + len(blk["visual_lines"])
            return count
        ratios = [line_count(cb) / total_lines for cb in contiguous_blocks]
        if len(ratios) > 1 and REORDER_DEBUG:
            print(f"multi-column layout: n_cols = {len(ratios)}: ", ratios)
        self.contiguous_blocks = contiguous_blocks
        self.ratios = ratios

        def find_cb_left_and_right(cb):
            min_left = 10000
            max_right = -1
            for blk in cb:
                min_left = min(blk['box_style'][1], min_left)
                max_right = max(blk['box_style'][2], max_right)
            return (min_left, max_right)
        multi_column_oo_blocks = len(ratios) < 20 and np.min(ratios) < 0.2
        two_column_oo_blocks = len(ratios) < 3 and np.min(ratios) < 0.2
        if two_column_oo_blocks or ((len([i for i in ratios if i >= 0.05]) < 3) and len(ratios) > 2):
            reordered_blocks, skipped_blocks = self.reorder_two_column_layout()
        elif multi_column_oo_blocks:
            block_dim = [find_cb_left_and_right(cb) for cb_idx, cb in enumerate(self.contiguous_blocks)
                         if ratios[cb_idx] >= 0.05]
            block_dim.sort(key=lambda x: x[0])
            intersect = False
            for b_dim_index, (b_dim_left, b_dim_right) in enumerate(block_dim):
                for b_dim in block_dim[b_dim_index+1:]:
                    if b_dim_right >= b_dim[0]:
                        intersect = True
                        break
            if not intersect:
                page_style = list(self.doc.page_styles[self.page_blocks[-1]["visual_lines"][0]["page_idx"]])
                page_style[3]["probable_multi_column"] = True
                self.doc.page_styles[self.page_blocks[-1]["visual_lines"][0]["page_idx"]] = tuple(page_style)
                reordered_blocks = self.blocks_to_reorder
            else:
                reordered_blocks, skipped_blocks = self.reorder_multi_column_layout()
            # reordered_blocks = self.blocks_to_reorder
        elif len(ratios) == 2:
            reordered_blocks = self.order_two_contiguous_blocks(self.contiguous_blocks, ratios)
        else:
            reordered_blocks = self.blocks_to_reorder

        new_blocks = self.offset_blocks + reordered_blocks
        # assert(len(new_blocks) + skipped_blocks == len(self.page_blocks))
        return new_blocks, two_column_oo_blocks or multi_column_oo_blocks
