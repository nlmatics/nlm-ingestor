import json
import logging
import re
import numpy as np
from collections import defaultdict, namedtuple
from typing import Optional

from bs4 import BeautifulSoup

from nlm_ingestor.file_parser import pdf_file_parser
from timeit import default_timer
from .visual_ingestor import visual_ingestor
from nlm_ingestor.ingestor.visual_ingestor.new_indent_parser import NewIndentParser
from nlm_ingestor.ingestor_utils.utils import NpEncoder, \
    detect_block_center_aligned, detect_block_center_of_page
from nlm_ingestor.ingestor_utils import utils

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
text_only_pattern = re.compile(r"[^a-zA-Z]+")

class PDFIngestor:
    def __init__(self, doc_location, parse_options):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        parse_pages = parse_options.get("parse_pages", False) \
            if parse_options else ()
        render_format = parse_options.get("render_format", "all") \
            if parse_options else "all"
        use_new_indent_parser = parse_options.get("use_new_indent_parser", False) \
            if parse_options else False
        
        tika_html_doc = parse_pdf(doc_location, parse_options)
        # print("tika_html_doc", tika_html_doc)
        blocks, _block_texts, _sents, _file_data, result, page_dim, num_pages = parse_blocks(
            tika_html_doc,
            render_format=render_format,
            parse_pages=parse_pages,
            use_new_indent_parser=use_new_indent_parser
        )
        return_dict = {
            "page_dim": page_dim,
            "num_pages": num_pages,
        }
        if render_format == "json":
            return_dict["result"] = result[0].get("document", {})
            self.doc_result_json = result[0]
        elif render_format == "all":
            return_dict["result"] = result[1].get("document", {})
            self.doc_result_json = result[1]
        self.return_dict = return_dict
        self.file_data = _file_data
        self.blocks = blocks


def parse_pdf(doc_location, parse_options):
    apply_ocr = parse_options.get("apply_ocr", False) if parse_options else False
    if not apply_ocr:
        wall_time = default_timer() * 1000
        logger.info("Parsing PDF")
        parsed_content = pdf_file_parser.parse_to_html(doc_location)
        logger.info(
            f"PDF Parsing finished in {default_timer() * 1000 - wall_time:.4f}ms on workspace",
        )
        soup = BeautifulSoup(str(parsed_content), "html.parser")
        pages = soup.find_all("div", class_=lambda x: x not in ['annotation'])
        p_per_page = []
        for page in pages:
            p_per_page.append(len(page.find_all("p")))
        p_per_page = np.array(p_per_page)
        sparse_page_count = np.count_nonzero(p_per_page < 4)
        if apply_ocr:
            # even if ocr is enabled, we don't want to run it if the document is not sparse
            needs_ocr = sparse_page_count / len(pages) > 0.3
            if needs_ocr:
                logger.info(
                    f"Running PDF OCR: sparse_page_count: {sparse_page_count}, n_pages: {len(pages)}")

    else:
        wall_time = default_timer() * 1000
        parsed_content = pdf_file_parser.parse_to_html(doc_location, do_ocr=True)
        parse_and_apply_hocr(parsed_content)
        logger.info(
            f"PDF OCR finished in {default_timer() * 1000 - wall_time:.4f}ms on workspace",
        )
    return parsed_content
        

def parse_and_apply_hocr(parsed_content):
    def get_kv_from_attr(attr_str, sep=" "):
        #     print(attr_str)
        kv_string = attr_str.split(";")
        kvs = {}
        for kv in kv_string:
            parts = kv.strip().split(sep)
            k = parts[0]
            v = parts[1:]
            if len(v) == 1:
                v = v[0].strip()
            kvs[k] = v
        return kvs

    soup = BeautifulSoup(str(parsed_content), "html.parser")
    pages = soup.find_all("div", class_='page')
    for page in pages:
        page_kv = get_kv_from_attr(page.get('style'), ":")
        page_height = float(page_kv['height'].replace("px", ""))
        page_width = float(page_kv['width'].replace("px", ""))
        ocr_pages = page.find_all('div', class_='ocr_page')
        if len(ocr_pages) > 0:
            ocr_page = ocr_pages[0]
            ocr_page_kv = get_kv_from_attr(ocr_page.get('title'))
            ocr_page_width = float(ocr_page_kv['bbox'][2])
            ocr_page_height = float(ocr_page_kv['bbox'][3])
            x_scale = page_width / ocr_page_width
            y_scale = page_height / ocr_page_height
            lines = page.find_all('span', class_='ocr_line')
            for line in lines:
                title = line.get('title')
                p_tag = soup.new_tag("p")
                line_kv = get_kv_from_attr(title)
                x0 = float(line_kv['bbox'][0]) * x_scale
                y0 = float(line_kv['bbox'][1]) * y_scale
                x1 = float(line_kv['bbox'][0]) * x_scale
                y1 = float(line_kv['bbox'][1]) * y_scale
                height = y1 - y0
                font_size = float(line_kv['x_size']) * y_scale
                font_size = 12
                p_tag.string = line.text.strip().replace("\\n*", "")
                style = f"position: absolute; top:{y0}px; text-indent:{x0}px;"
                style += f"height: {height};font-size:{font_size}px;"
                words = line.find_all('span', class_='ocrx_word')
                word_start_positions = []
                word_end_positions = []
                for word in words:
                    word_kv = get_kv_from_attr(word.get('title'))
                    word_x0 = float(word_kv['bbox'][0]) * x_scale
                    word_y0 = float(word_kv['bbox'][1]) * y_scale
                    word_x1 = float(word_kv['bbox'][0]) * x_scale
                    word_y1 = float(word_kv['bbox'][1]) * y_scale
                    word_start_positions.append((word_x0, word_y0))
                    word_end_positions.append((word_x1, word_y1))
                style += f"word-start-positions: {word_start_positions}; word-end-positions: {word_end_positions};"
                default_font_family = "TimesNewRomanPSMT"
                default_font = f"({default_font_family},normal,normal,{font_size},{font_size},{font_size / 4.0})"
                word_fonts = ", ".join([default_font for w in word_end_positions])
                style += f"font-family: {default_font_family};font-style: normal;font-weight: normal;word-fonts: [{word_fonts}]"
                p_tag.attrs["style"] = style
                page.append(p_tag)
            for ocr_block in page.find_all('div', class_='ocr'):
                ocr_block.decompose()
    html_str = str(soup.html)
    html_str = html_str.replace("\\n", "")
    html_str = html_str.replace("\\t", "")
    parsed_content['content'] = html_str

def parse_blocks(
        tika_html_doc,
        render_format: str = "all",
        parse_pages: tuple = (),
        use_new_indent_parser: bool = False,
):
    soup = BeautifulSoup(str(tika_html_doc), "html.parser")
    meta_tags = soup.find_all("meta")
    title = None
    for tag in meta_tags:
        if tag["name"].endswith(":title"):
            title = tag["content"]
            break
    pages = soup.find_all("div", class_=lambda x: x in ['page'])
    # read ignore blocks here
    ignore_blocks = []
    if parse_pages:
        start_page_no, end_page_no = parse_pages
        pages = pages[start_page_no:end_page_no + 1]
    parsed_doc = visual_ingestor.Doc(pages, ignore_blocks, render_format)
    if use_new_indent_parser:
        indent_parser = NewIndentParser(parsed_doc, parsed_doc.blocks)
        indent_parser.indent()
    title_page_fonts = top_pages_info(parsed_doc)
    parsed_doc.compress_blocks()
    blocks = parsed_doc.blocks
    sents, _ = utils.blocks_to_sents(blocks)
    block_texts, _ = utils.get_block_texts(blocks)
    if render_format == "json":
        result = [{"title": title, "document": parsed_doc.json_dict, "title_page_fonts": title_page_fonts}]
    elif render_format == "html":
        result = [{"title": title, "text": parsed_doc.html_str, "title_page_fonts": title_page_fonts}]
    else:
        result = [
            {"title": title, "text": parsed_doc.html_str, "title_page_fonts": title_page_fonts},
            {"title": title, "document": parsed_doc.json_dict, "title_page_fonts": title_page_fonts},
        ]

    file_data = [json.dumps(res, cls=NpEncoder) for res in result]

    return blocks, block_texts, sents, file_data, \
            result, [parsed_doc.page_width, parsed_doc.page_height], len(pages) - 1

def top_pages_info(parsed_doc):
    font_freq = {}
    for idx, block in enumerate(parsed_doc.blocks):
        if block["page_idx"] > 2:       # Consider only the first 2 pages
            break
        if not block["block_type"] == "header" and not block["block_idx"] < 1:
            continue
        for line in block["visual_lines"]:
            line_font = line["line_style"][2]       # font_size
            line_text = line["text"]
            if line_font in font_freq:
                font_freq[line_font].append({
                    "text": line_text,
                    "page": block["page_idx"],
                    "block_idx": block["block_idx"],
                    "enum_idx": idx     # Adding enum_idx as the block_idx can be wrong here.
                })
            else:
                font_freq[line_font] = [
                    {
                        "text": line_text,
                        "page": block["page_idx"],
                        "block_idx": block["block_idx"],
                        "enum_idx": idx     # Adding enum_idx as the block_idx can be wrong here.
                     }
                ]
    # Sort the font_freq in descending order.
    sorted_freq = {}
    for key in sorted(font_freq, reverse=True):
        sorted_freq[key] = font_freq[key]

    res = {}
    title_page = sorted_freq[list(sorted_freq.keys())[0]][0]["page"] if len(sorted_freq) > 0 else []
    temp = []
    title_candidates = []

    def retrieve_title_candidates(key_idx):
        temp_ = []
        title_candidates_ = []
        if len(sorted_freq) > 0 and len(list(sorted_freq.keys())) > key_idx:
            for freq_ in sorted_freq[list(sorted_freq.keys())[key_idx]]:
                if (parsed_doc.blocks[freq_["enum_idx"]]["box_style"][0] >= parsed_doc.page_height / 2) or \
                        not len(text_only_pattern.sub("", freq_["text"]).strip()):
                    continue
                if len(temp_) == 0 or abs(temp_[-1]["block_idx"] - freq_["block_idx"]) <= 1:
                    temp_.append(freq_)
                if freq_["page"] == title_page:
                    freq_["center_aligned"] = detect_block_center_aligned(parsed_doc.blocks[freq_["enum_idx"]],
                                                                          parsed_doc.page_width)
                    freq_["all_caps"] = parsed_doc.blocks[freq_["enum_idx"]]["block_text"].isupper()
                    freq_["center_of_page"] = detect_block_center_of_page(parsed_doc.blocks[freq_["enum_idx"]],
                                                                          parsed_doc.page_height)
                    title_candidates_.append(freq_)
        return temp_, title_candidates_

    # Check only the first 2 font_sizes
    for i in range(0, 2):
        temp, title_candidates = retrieve_title_candidates(i)
        if len(temp):
            break
    # Contains candidates from the title page of the same font (probable largest font)
    if title_candidates:
        new_temp = []
        # Preference to center_of_page
        for freq in title_candidates:
            if freq["center_of_page"]:
                new_temp.append(freq)
            elif len(new_temp) and abs(new_temp[-1]["block_idx"] - freq["block_idx"]) <= 1:
                new_temp.append(freq)
        # Next Preference to all_caps
        if not new_temp:
            for freq in title_candidates:
                if freq["all_caps"]:
                    new_temp.append(freq)
                elif len(new_temp) and abs(new_temp[-1]["block_idx"] - freq["block_idx"]) <= 1:
                    new_temp.append(freq)
        # Next Preference to center_aligned
        if not new_temp:
            for freq in title_candidates:
                if freq["center_aligned"]:
                    new_temp.append(freq)
                elif len(new_temp) and abs(new_temp[-1]["block_idx"] - freq["block_idx"]) <= 1:
                    new_temp.append(freq)
        if new_temp:
            temp = new_temp

    res["first_level"] = [freq["text"] for freq in temp] if len(temp) > 0 else []
    # first level subtitle
    res["first_level_sub"] = []
    for i in range(1, 4):
        # stop after the largest text other than title is found
        if res["first_level_sub"] or i >= len(sorted_freq):
            break
        # loop through next largest texts that's on the title page
        for freq in sorted_freq[list(sorted_freq.keys())[i]]:
            if freq["page"] == title_page:
                res["first_level_sub"].append(freq["text"])

    res["second_level"] = [
        freq["text"] for freq in sorted_freq[list(sorted_freq.keys())[1]]
    ] if len(sorted_freq) > 1 else []
    res["third_level"] = [
        freq["text"] for freq in sorted_freq[list(sorted_freq.keys())[2]]
    ] if len(sorted_freq) > 2 else []
    return res
