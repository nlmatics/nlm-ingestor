from nlm_ingestor.ingestor_utils.ing_named_tuples import BoxStyle, LineStyle

font_weights = {"normal": 400, "bold": 600, "bolder": 900, "lighter": 200}
font_families = {"bold": 600, "light": 200}
font_scale = 1.2


def parse_tika_style(style_str: str, text_str: str, page_width: float) -> dict:
    """
    Takes tika format style and simplifies it for sorting and grouping
    Input style format is:
    'top1:121.11969px;start-font-size:4.1408234px;font-size:4.1408234px;font-family:RobotoRegular;font-style:normal;font-weight:normal;top:121.11969px;position:absolute;text-indent:384.37286px;word-start-positions:[(384.37286,121.11969,4.1408234,normal)];last-char:(466.20337, 121.11969);word-end-positions:[(466.20337,121.11969,4.1408234,normal)]'
    Output style format is:
    location aspects of the style
    BoxStyle(top=121.12, left=384.37, width=0.0, height=4.14
    line properties
    LineStyle(line_height=4.14, font_family='RobotoRegular', font_style='normal', font_size=4.14, font_weight=400)
    """

    input_style = get_style_kv(style_str)
    word_start_pos = input_style["word-start-positions"][2:-2].split("), (")
    word_end_pos = input_style["word-end-positions"][2:-2].split("), (")
    word_fonts = input_style["word-fonts"][2:-2].split("), (")
    left = round(float(word_start_pos[0].split(",")[0]), 2)
    right = round(float(word_end_pos[-1].split(",")[0]), 2)
    # height = parse_px(input_style['height'])
    font_size_height = parse_px(input_style['font-size'])
    if right < left:
        # We have some issues here with Tika
        # Are all the word end positions having the same top? aka, same line are we dealing with?
        same_top = True
        for idx, _ in enumerate(word_end_pos[:-1]):
            if abs(round(float(word_end_pos[idx].split(",")[1]), 2) -
                   round(float(word_end_pos[idx + 1].split(",")[1]), 2)) <= 2:
                same_top = True
            else:
                same_top = False
                break
        # We are on the same Visual Line and we cannot have a right before left.
        if same_top:
            last_word_start_pos = round(float(word_start_pos[-1].split(",")[0]), 2)
            if last_word_start_pos >= right:
                last_word_len = len(text_str.split()[-1].strip())
                font_space_width = round(float(word_fonts[-1].split(",")[5]), 2)
                right = last_word_start_pos + (last_word_len * font_space_width)
            else:
                # Last word also is on the left side of the first word.
                font_space_width = round(float(word_fonts[0].split(",")[5]), 2)
                right = left + (len(text_str) * font_space_width)
    box_style = BoxStyle(
        parse_px(input_style['top']),
        left,
        right,
        right - left,
        font_size_height
    )
    font_family = input_style['font-family']
    font_weight = input_style['font-weight']
    font_weight = get_numeric_font_weight(font_family, font_weight)
    font_size = round(font_scale * font_size_height, 1)
    text_transform = 'none'  # "uppercase" if text_str.isupper() else "none"
    text_align = 'left'  # "center" if is_center_aligned else "left"
    font_space_width = 1.5
    word_line_styles = []
    for wf_idx, wf in enumerate(word_fonts):
        if "," in font_family and font_family in wf:
            new_font_family = font_family.replace(",", "-")
            wf = wf.replace(font_family, new_font_family)
        wf_parts = wf.split(",")
        wf_font_space_width = round(float(wf_parts[5]), 2)
        word_line_styles.append(
            LineStyle(
                wf_parts[0],
                wf_parts[2],
                round(font_scale * float(wf_parts[3]), 1),
                get_numeric_font_weight(wf_parts[0], wf_parts[1]),
                text_transform,
                wf_font_space_width,
                text_align,
            )
        )
        if wf_idx == 0:
            font_space_width = wf_font_space_width

    line_style = LineStyle(
        font_family,
        input_style["font-style"],
        font_size,
        font_weight,
        text_transform,
        font_space_width,
        text_align
    )
    # print(word_start_pos[1])
    # for word_font in word_fonts:
    #     print(word_font)
    return box_style, line_style, word_line_styles


def get_style_kv(style_str):
    parts = style_str.split(";")
    input_style = {}
    for part in parts:
        kv = part.split(":")
        if len(kv) == 2:
            input_style[kv[0].strip()] = kv[1].strip()
    return input_style


def get_numeric_font_weight(font_family, font_weight):
    if font_weight in font_weights:
        font_weight = font_weights[font_weight]
    for key in font_families.keys():
        # print("-", key, font_family, font_weight)
        if font_family.lower().find(key) != -1:
            font_weight = font_families[key]
        # print(key, font_family, font_weight)
    if font_family.lower().endswith(".b"):
        font_weight = font_weights["bold"]
    return round(float(font_weight))


def parse_px(px):
    return round(float(px[0:-2]), 2)


def format_p_tag(p, filter_out_pattern, filter_ls_pattern, soup):
    """
    Create a new p_tag from the existing one, if the text contains some characters that needs to be cleared off.
    New p_tag will be created if the pattern is present on the left side of the token. else the original p_tag will
    be modified and returned
    :param p: p_tag whose text need to be put under scanner.
    :param filter_out_pattern: Filter out pattern
    :param filter_ls_pattern: Filter out Left side pattern
    :param soup: BeautifulSoup object
    :return: New p_tag (if any) and param representing whether we have changed p_tag or not.
    """
    input_style = None
    indices_to_remove = []
    new_text = []
    keys = ["word-start-positions", "word-end-positions", "word-fonts"]
    changed = False
    new_p = None
    new_p_end_idx = -2
    for idx, tok in enumerate(p.text.split()):
        new_tok = filter_out_pattern.sub("", tok)
        if not len(new_tok):
            if not input_style:
                input_style = get_style_kv(p["style"])
                # Convert to a list of items on which we can act upon.
                for key in keys:
                    input_style[key] = input_style[key][2:-2].split("), (")
            indices_to_remove.append(idx)
        elif len(new_tok) < len(tok):
            # We have the delimiter pattern part of the word itself.
            left_side_pattern = filter_ls_pattern.search(tok) is not None
            if not input_style:
                input_style = get_style_kv(p["style"])
                # Convert to a list of items on which we can act upon.
                for key in keys:
                    input_style[key] = input_style[key][2:-2].split("), (")
            if left_side_pattern:
                # pattern is on the left side
                if len(new_text):
                    # We have some tokens already in the list. Create a p_tag for the words till now.
                    # Right now we assume that there will one filter pattern match in the whole original p_tag.
                    new_input_style = input_style.copy()
                    # Change the string
                    new_p = soup.new_tag('p')
                    new_p.string = " ".join(new_text)
                    for key in keys:
                        new_input_style[key] = new_input_style[key][:idx]
                        new_input_style[key] = "[(" + "), (".join(new_input_style[key]) + ")]"
                    # Create string out of dictionary
                    new_p["style"] = ";".join([":".join([key, str(val)]) for key, val in new_input_style.items()])
                    # Reset the text
                    new_text = []
                new_p_end_idx = idx - 1
                [word_start_x, word_start_y] = input_style["word-start-positions"][idx].split(",")
                [_, _, _, _, _, val] = input_style["word-fonts"][idx].split(",")
                word_start_x = float(word_start_x) + (float(val) * (len(tok) - len(new_tok)))
                input_style["word-start-positions"][idx] = str(word_start_x) + "," + word_start_y
            else:
                [word_end_x, word_end_y] = input_style["word-end-positions"][idx].split(",")
                [_, _, _, _, _, val] = input_style["word-fonts"][idx].split(",")
                word_end_x = float(word_end_x) - (float(val) * (len(tok) - len(new_tok)))
                input_style["word-end-positions"][idx] = str(word_end_x) + "," + word_end_y
            new_text.append(str(new_tok))
        else:
            new_text.append(str(tok))
    if input_style:
        changed = True
        # Change the string
        p.string = " ".join(new_text)
        for i in sorted(indices_to_remove, reverse=True):
            del input_style["word-start-positions"][i]
            del input_style["word-end-positions"][i]
            del input_style["word-fonts"][i]
            if new_p_end_idx >= -1:
                new_p_end_idx -= len([i for i in indices_to_remove if i <= new_p_end_idx])
        # Create string out of the list
        for key in keys:
            if new_p_end_idx >= -1:
                # Recreate the style parameters.
                if key == 'word-start-positions':
                    input_style['text-indent'] = str(input_style[key][new_p_end_idx + 1].split(",")[0])
                elif key == 'word-fonts':
                    [font_family, font_weight, font_style, _, _, _] = input_style[key][new_p_end_idx + 1].split(",")
                    input_style['font-family'] = str(font_family)
                    font_weight = get_numeric_font_weight(font_family, font_weight)
                    input_style['font-weight'] = font_weight
                    input_style['font-style'] = font_style
                input_style[key] = input_style[key][new_p_end_idx + 1:]
            input_style[key] = "[(" + "), (".join(input_style[key]) + ")]"
        # Create string out of dictionary
        p["style"] = ";".join([":".join([key, str(val)]) for key, val in input_style.items()])

    return new_p, changed


