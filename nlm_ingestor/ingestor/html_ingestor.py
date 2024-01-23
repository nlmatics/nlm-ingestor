import logging

from bs4 import BeautifulSoup
from nlm_ingestor.ingestor_utils.ing_named_tuples import LineStyle
from nlm_ingestor.ingestor.visual_ingestor import block_renderer
from nlm_ingestor.ingestor_utils.utils import sent_tokenize
from nlm_ingestor.ingestor import line_parser
import codecs


class HTMLIngestor:
    def __init__(self, file_name, sec=False):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        if str(type(file_name)) == "<class 'bs4.element.Tag'>":
            self.html = file_name
        else:
            f = codecs.open(file_name, 'r')
            self.html = BeautifulSoup(f.read(), features="lxml")
            self.html = self.html.find("body")
        self.sec = sec
        self.blocks = []
        self.parse_blocks()

        self.line_style_classes = {}
        self.class_levels = {}
        self.add_styles()

        br = block_renderer.BlockRenderer(self)
        self.html_str = br.render_html()
        self.json_dict = br.render_json()

    def parse_blocks(self):
        self.logger.info("parsing html file")

        header_tags = ["h1", "h2", "h3", "h4", "h5", "h6"]
        para_tags = ["p", "span"]
        # list: li
        # bold: b, em, strong
        i = 0
        children = self.html.findChildren(recursive=True)
        level_stack = []
        header_stack = []

        while i < len(children):
            child = children[i]
            if not child.text.strip():
                i += 1
                continue

            tag = child.name
            if self.sec:
                # some containers are actually p 
                div_is_para = True
                current_level_child = [c.name for c in child.findChildren(recursive=False)]
                if len(current_level_child) > 0:
                    for name in current_level_child:
                        if name != "font":
                            div_is_para = False
                # use styles to determine headers
                style = self.parse_style(child.get("style"))
                if "font-weight" in style and style["font-weight"] == "bold":
                    line = line_parser.Line(child.text)
                    if line.is_header:
                        tag = "h3"
                        if child.text.isupper():
                            tag = "h2"

            else:
                div_is_para = False

            div_text = ""
            if self.sec:
                for c in child.findAll(text=True, recursive=False):
                    if c.strip():
                        div_text += c

            if tag in header_tags:
                if len(level_stack) == 0:
                    level_stack = [tag]
                    header_stack = [child.text]
                    level = 0
                elif tag in level_stack:
                    level = level_stack.index(tag)
                    level_stack = level_stack[:level+1]
                    header_stack = header_stack[:level]
                    header_stack.append(child.text)
                else:
                    idx = 0
                    while idx < len(level_stack) and level_stack[idx] in header_tags and \
                            header_tags.index(level_stack[idx]) < header_tags.index(tag):
                        idx += 1
                    level_stack = level_stack[:idx]
                    level_stack.append(tag)
                    header_stack = header_stack[:idx]
                    header_stack.append(child.text)
                    level = idx

                header_block = {
                    "block_idx": len(self.blocks),
                    "page_idx": 0,
                    "block_text": child.text,
                    "block_type": "header",
                    "block_class": "nlm-text-header",
                    "header_block_idx": 0,
                    "level": level,
                    "header_text": header_stack[-1] if header_stack else "",
                    "level_chain": header_stack[::-1],
                }
                self.blocks.append(header_block)
                i += len(child.findChildren(recursive=True))

            elif tag in para_tags or div_text or div_is_para:
                is_header = False
                line = line_parser.Line(child.text)
                para_child_tag = None
                if line.is_header:
                    is_header = True
                if child.name == "p":
                    para_child = child.findChildren(recursive=True)
                    if len(para_child) > 0:
                        para_child_tag = child.name + "_" + para_child[0].name
                if is_header and para_child_tag:
                    if len(level_stack) == 0:
                        level_stack = [para_child_tag]
                        header_stack = [child.text]
                        level = 0
                    elif para_child_tag in level_stack:
                        level = level_stack.index(para_child_tag)
                        level_stack = level_stack[:level+1]
                        header_stack = header_stack[:level]
                        header_stack.append(child.text)
                    else:
                        idx = len(level_stack)
                        level_stack = level_stack[:idx]
                        level_stack.append(para_child_tag)
                        header_stack = header_stack[:idx]
                        header_stack.append(child.text)
                        level = idx

                    header_block = {
                        "block_idx": len(self.blocks),
                        "page_idx": 0,
                        "block_text": child.text,
                        "block_type": "header",
                        "block_class": "nlm-text-header",
                        "header_block_idx": 0,
                        "level": level,
                        "header_text": header_stack[-1] if header_stack else "",
                        "level_chain": header_stack[::-1],
                    }
                    self.blocks.append(header_block)
                else:
                    para_block = {
                        "block_idx": len(self.blocks),
                        "page_idx": 0,
                        "block_text": child.text,
                        "block_type": "para",
                        "block_class": "nlm-text-body",
                        "header_block_idx": 0,
                        "block_sents": sent_tokenize(child.text),
                        "level": len(level_stack),
                        "header_text": header_stack[-1] if header_stack else "",
                        "level_chain": header_stack[::-1],
                    }
                    self.blocks.append(para_block)

                i += len(child.findChildren(recursive=True))

            elif tag == "li":
                list_block = {
                    "block_idx": len(self.blocks),
                    "page_idx": 0,
                    "block_text": child.text,
                    "block_type": "list_item",
                    "list_type": "",
                    "block_class": "nlm-list-item",
                    "header_block_idx": 0,
                    "block_sents": sent_tokenize(child.text),
                    "level": len(level_stack),
                    "header_text": header_stack[-1] if header_stack else "",
                    "level_chain": header_stack[::-1],
                }
                self.blocks.append(list_block)
                i += len(child.findChildren(recursive=True))

            elif tag == "table":
                rows = child.find_all('tr')
                table_start_idx = len(self.blocks)
                empty_cols = []
                for row in rows:
                    cols = row.find_all(['th', 'td'])
                    col_text = []
                    col_spans = []
                    empty_col = []
                    header_group_flag = False
                    all_th = True
                    for col_idx, col in enumerate(cols):
                        text = col.text.replace(u'\xa0', '')
                        text = text.strip()
                        col_text.append(text)
                        if not text:
                            empty_col.append(col_idx)
                        if not col.name == "th" and text and not col.find('b'):
                            all_th = False
                        if col.get("colspan"):
                            header_group_flag = True
                        col_spans.append(int(col.get("colspan")) if col.get("colspan") else 1)
                    empty_cols.append(empty_col)

                    if not ''.join(col_text).strip():
                        # Empty Row
                        continue

                    if len(rows) > 1:
                        table_row = {
                            "block_idx": len(self.blocks),
                            "page_idx": 0,
                            "block_text": ' '.join([c for c in col_text]),
                            "block_type": "table_row",
                            "block_class": "nlm-table-row",
                            "header_block_idx": 0,
                            "block_sents": sent_tokenize(' '.join([c for c in col_text])),
                            "level": len(level_stack),
                            "header_text": header_stack[-1] if header_stack else "",
                            "level_chain": header_stack[::-1],
                            "cell_values": col_text,
                            "col_spans": col_spans,
                        }
                        if header_group_flag:
                            table_row["is_header_group"] = True
                        if all_th:
                            table_row["is_header"] = True
                        self.blocks.append(table_row)
                    else:
                        blk_text = ' '.join(col_text)
                        line = line_parser.Line(child.text)
                        is_list_item = False
                        if line.is_list_item:
                            is_list_item = True
                        t_block = {
                            "block_idx": len(self.blocks),
                            "page_idx": 0,
                            "block_text": blk_text,
                            "block_type": "para",
                            "block_class": "nlm-text-body",
                            "header_block_idx": 0,
                            "block_sents": sent_tokenize(blk_text),
                            "level": len(level_stack),
                            "header_text": header_stack[-1] if header_stack else "",
                            "level_chain": header_stack[::-1],
                        }
                        if is_list_item:
                            t_block["block_type"] = "list_item"
                            t_block["block_class"] = "nlm-list-item"
                            t_block["list_type"] = ""
                        self.blocks.append(t_block)

                if len(rows) > 1:
                    self.blocks[table_start_idx]['is_table_start'] = True
                    self.blocks[-1]["is_table_end"] = True
                    # Remove any empty columns if there are intersection
                    empty_col_intersection = set.intersection(*map(set, empty_cols))
                    if empty_col_intersection:
                        # Start from the last as we are popping members out
                        # might change the number of elements in the list
                        for inter in list(empty_col_intersection)[::-1]:
                            for blk in self.blocks[table_start_idx:]:
                                blk["col_spans"].pop(inter)
                                blk["cell_values"].pop(inter)

                i += len(child.findChildren(recursive=True))

            i += 1

    def add_styles(self):
        title_style = LineStyle(
            "Roboto, Georgia, serif",
            "bold",
            14.0,
            "500",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[title_style] = "nlm-text-title"
        self.class_levels["nlm-text-title"] = 0
        header_style = LineStyle(
            "Roboto, Georgia, serif",
            "normal",
            12.0,
            "600",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[header_style] = "nlm-text-header"
        self.class_levels["nlm-text-header"] = 1
        para_style = LineStyle(
            "Roboto, Georgia, serif",
            "normal",
            10.0,
            "400",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[para_style] = 'nlm-text-body'
        self.class_levels['nlm-text-body'] = 2

    def parse_style(self, style_str):
        d = {}
        if not style_str:
            return d
        for style in style_str.split(";"):
            style = style.strip()
            if ":" in style:
                key, value = style.split(":")
                d[key] = value
        return d
