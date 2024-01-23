import json
import logging
from collections import namedtuple
from nlm_ingestor.ingestor_utils.utils import NpEncoder
from nlm_ingestor.ingestor_utils import utils
from nlm_ingestor.ingestor.visual_ingestor import block_renderer
from . import processors

class TextIngestor:
    def __init__(self, doc_location, parse_options):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        render_format = parse_options.get("render_format", "all") \
            if parse_options else "all"
       
        with open(doc_location) as f:
            raw_lines = f.readlines()

        blocks, _block_texts, _sents, _file_data, result, page_dim, num_pages = parse_blocks(
            raw_lines=raw_lines
        )
        return_dict = {
            "page_dim": page_dim,
            "num_pages": num_pages,
        }
        if render_format == "json":
            return_dict["result"] = result[0].get("document", {})
        elif render_format == "all":
            return_dict["result"] = result[1].get("document", {})
        self.return_dict = return_dict

def parse_blocks(raw_lines):

    blocks = processors.clean_lines(raw_lines)
    page_blocks = [blocks]

    blocks = blocks_to_json(page_blocks)

    blocks = [item for sublist in blocks for item in sublist]
    title = ""
    if len(blocks) > 0:
        title = blocks[0]["block_text"]
        if len(title) > 50:
            title = title[0:50] + "..."
    sents, _ = utils.blocks_to_sents(blocks)
    block_texts, _ = utils.get_block_texts(blocks)
    #this code needs a more complete rework
    doc_dict = {"blocks": blocks, "line_style_classes": {}, "class_levels": {}}
    doc = namedtuple("ObjectName", doc_dict.keys())(*doc_dict.values())
    br = block_renderer.BlockRenderer(doc)
    html_str = br.render_html()
    json_dict = br.render_json()


    result = [
        {"title": title, "text": html_str, "title_page_fonts": {"first_level": [title]}},
        {"title": title, "document": json_dict, "title_page_fonts": {"first_level": [title]}},  # JSON not enabled now.
    ]

    file_data = [json.dumps(res, cls=NpEncoder) for res in result]

    return blocks, block_texts, sents, file_data, result, [1, 1], 0

def blocks_to_json(page_blocks):
    results = []
    block_count = 0
    for page_idx, blocks in enumerate(page_blocks):
        result = []
        block_start = block_count
        header_block_idx = -1
        header_block_text = ""
        for block_idx_in_page, block in enumerate(blocks):
            if block["block_text"]:
                block_sents = utils.sent_tokenize(block["block_text"])
                # header_block_idx = block["header_block_idx"]
                if block["block_type"] == "header":
                    header_block_idx = block["block_idx"]
                    header_block_text = block["block_text"]

                result.append(
                    {
                        "block_text": block["block_text"],
                        "block_idx": block["block_idx"],
                        "block_sents": block_sents,
                        "block_type": block["block_type"],
                        "header_block_idx": block_start + header_block_idx,
                        "page_idx": page_idx,
                        "block_idx_in_page": block_start + block_idx_in_page,
                        "header_text": header_block_text,
                        "text_group_start_idx": block["text_group_start_idx"],
                        "block_list": block["block_list"],
                        "level":0,
                        "block_class": block["block_class"] if "block_class" in block else {}
                    },
                )
                block_count += 1
        results.append(result)
    return results
