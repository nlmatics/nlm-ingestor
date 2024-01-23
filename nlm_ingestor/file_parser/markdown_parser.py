import json
import logging
import os

import mistune
from nlm_ingestor.ingestor_utils.utils import sent_tokenize

import nlm_ingestor.ingestion_daemon.config as cfg
from nlm_ingestor.ingestor_utils.ing_named_tuples import LineStyle
from nlm_ingestor.ingestor.visual_ingestor import block_renderer


# initialize logging
logger = logging.getLogger(__name__)
logger.setLevel(cfg.log_level())

def parse_markdown_to_blocks(markdown_text):
    state = {}

    markdown_text, state = mistune.html.before_parse(markdown_text, state)
    mistune_tokens = mistune.html.block.parse(markdown_text, state)

    mistune_tokens = mistune.html.before_render(mistune_tokens, state)
    html_str = mistune.html.block.render(mistune_tokens, mistune.html.inline, state)
    html_str = mistune.html.after_render(html_str, state)

    blocks = []
    cur_table_idx = 0
    level = 0
    for idx, mistune_token in enumerate(mistune_tokens):
        if mistune_token["type"] == "newline":
            continue

        if "params" in mistune_token:
            level = mistune_token["params"][0]

        cur_blocks = {
            "paragraph": convert_mistune_to_paragraph,
            "table": convert_mistune_to_table,
            "heading": convert_mistune_to_header,
            "list": convert_mistune_to_list_item,
            "block_quote": convert_mistune_to_paragraphs,
            "block_code": convert_mistune_to_code_paragraph,
        }[mistune_token["type"]](mistune_token, level)

        for block in cur_blocks:
            block["block_idx"] = idx
            block["page_idx"] = 0
            if mistune_token["type"] == "table":
                block["table_idx"] = cur_table_idx
            blocks.append(block)
        if mistune_token["type"] == "table":
            cur_table_idx += 1

    return blocks, html_str


def convert_mistune_to_paragraph(token, level):
    return [
        {
            "block_type": "para",
            "block_text": token["text"],
            "block_sents": sent_tokenize(token["text"]),
            "level": level,
        },
    ]

def convert_mistune_to_code_paragraph(token, level):
    return [
        {
            "block_type": "para",
            "block_text": token["raw"],
            "block_sents": sent_tokenize(token["raw"]),
            "level": level,
        },
    ]

def convert_mistune_to_table(token, level):
    blocks = []
    for child in token["children"]:
        if child["type"] == "table_head":
            cell_values = [x["text"] for x in child["children"]]
            block = {
                "block_type": "table_row",
                "is_header_group": True,
                "col_spans": [1] * len(child["children"]),
                "cell_values": cell_values,
                "block_text": " ".join(cell_values),
                "level": level,
            }
            blocks.append(block)
        elif child["type"] == "table_body":
            for row in child["children"]:
                cell_values = [x["text"] for x in row["children"]]
                block = {
                    "block_type": "table_row",
                    "cell_values": cell_values,
                    "block_text": " ".join(cell_values),
                    "level": level,
                }
                blocks.append(block)

    blocks[0]["is_table_start"] = True
    blocks[-1]["is_table_end"] = True

    return blocks


def convert_mistune_to_header(token, level):
    blocks = [
        {
            "block_type": "header",
            "block_text": token["text"],
            "level": level - 1,
        },
    ]
    level += 1
    return blocks


def convert_mistune_to_list_item(token, level):
    blocks = []
    for child in token["children"]:
        block = {
            "block_type": "list_item",
            # right now I only handle first level child of list_item
            "block_text": child["children"][0]["text"],
            "block_sents": [child["children"][0]["text"]],
            "level": level,
        }
        blocks.append(block)
    return blocks

def convert_mistune_to_paragraphs(token, level):
    print("token is:", token)
    blocks = []
    for child in token["children"]:
        if token["type"] == "paragraph":
            block = {
                "block_type": "para",
                "block_text": child["text"],
                "block_sents": sent_tokenize(child["text"]),
                "level": level,
            }
            blocks.append(block)
        elif "raw" in child:
            block = {
                "block_type": "para",
                "block_text": child["raw"],
                "block_sents": sent_tokenize(child["raw"]),
                "level": level,
            }
            blocks.append(block)
    return blocks

class MarkdownDocument:
    def __init__(self, doc_location):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        markdown_text = ""
        with open(doc_location) as file:
            markdown_text = file.read()
        self.blocks, self.html_str = parse_markdown_to_blocks(markdown_text)
        for block in self.blocks:
            block["block_class"] = ""
        self.line_style_classes = {}
        self.class_levels = {}

        br = block_renderer.BlockRenderer(self)
        self.json_dict = br.render_json()
