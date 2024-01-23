import xml.etree.ElementTree as ET
import re

from nlm_ingestor.ingestor import processors
from nlm_ingestor.ingestor.visual_ingestor import block_renderer
from nlm_ingestor.ingestor_utils.utils import sent_tokenize
from nlm_ingestor.ingestor_utils.ing_named_tuples import LineStyle

# from nltk import sent_tokenize


class XMLIngestor:
    def __init__(self, file_name):
        self.file_name = file_name
        tree = ET.parse(file_name)
        self.tree = tree
        self.title = None
        self.blocks = []
        self.parse_blocks(tree)
        self.line_style_classes = {}
        self.class_levels = {}
        self.add_styles()
        br = block_renderer.BlockRenderer(self)
        self.html_str = br.render_html()
        self.json_dict = br.render_json()

    def parse_blocks(self, tree):
        root = tree.getroot()
        all_blocks = []
        title = None

        def traverse(parent, level, blocks):
            for child in parent:
                # handle cases when there's only a <country /> tag
                if not child.text:
                    continue
                if len(list(child)) > 0:
                    # print("\t" * (level), "Header", child.tag)
                    header_text = XMLIngestor.make_header(child.tag)
                    header_block = {
                        "block_idx": len(blocks),
                        "page_idx": 0,
                        "block_text": header_text,
                        "block_type": "header",
                        "block_class": "nlm-text-header",
                        "header_block_idx": 0,
                        "level": level,
                    }
                    subheader = " ".join([child.attrib[c] for c in child.attrib])
                    if subheader:
                        header_block["block_text"] += " " + subheader
                    blocks.append(header_block)
                    traverse(child, level + 1, blocks)
                else:
                    # print("\t"*(level + 1), child.text)
                    if not title and child.tag.lower().find("title") != -1:
                        self.title = child.text
                    if child.tag != "textblock":
                        # print("\t" * (level), "Header", child.tag)
                        header_text = XMLIngestor.make_header(child.tag)

                        # header_text = " ".join(child.tag.split("_")).title()
                        header_block = {
                            "block_idx": len(blocks),
                            "page_idx": 0,
                            "block_text": header_text,
                            "block_type": "header",
                            "block_class": "nlm-text-header",
                            "header_block_idx": 0,
                            "level": level,
                        }
                        subheader = " ".join([child.attrib[c] for c in child.attrib])
                        if subheader:
                            header_block["block_text"] += " " + subheader
                        blocks.append(header_block)
                    else:
                        level -= 1
                    lines = child.text.split("\n")
                    # print("\t" * (level + 1), "======")
                    # for line in lines:
                    #     print("\t" * (level + 1), line)
                    # print("\t" * (level + 1), "======")
                    col_blocks = processors.clean_lines(lines, xml=True)
                    header_text = blocks[-1]["block_text"]
                    has_header = False
                    for block in col_blocks:
                        # print("\t" * (level + 1), block["block_text"])
                        inline_header = has_header and block["block_type"] == "para"
                        block["header_text"] = para_header if inline_header else header_text 
                        indent_offset = 2 if inline_header else 1
                        block["level"] = level + indent_offset
                        block["block_idx"] = len(blocks)
                        block["page_idx"] = 0
                        block["block_sents"] = sent_tokenize(block["block_text"])
                        block["block_class"] = "nlm-text-body"
                        block["level_chain"] = (
                            [title, header_text] if title else [header_text]
                        )
                        if len(col_blocks) == 1:
                            block["block_type"] = "para"
                        blocks.append(block)
                        if block["block_type"] == "header":
                            has_header = True
                            para_header = block["block_text"]

        traverse(root, 0, all_blocks)
        self.blocks = all_blocks

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

    @staticmethod
    def camel_case_split(str):
        return re.findall(r'[A-Z](?:[a-z]+|[A-Z]*(?=[A-Z]|$))', str)

    @staticmethod
    def make_header(str):
        header_text = str
        if "_" in header_text:
            header_text = " ".join(header_text.split("_")).title()
        elif header_text.islower():
            header_text = header_text.capitalize()
        else:
            header_text = " ".join(XMLIngestor.camel_case_split(header_text)).title()
        return header_text
