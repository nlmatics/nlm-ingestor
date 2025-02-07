import json
import logging
import os
import re
import shutil
import tempfile
import traceback
from timeit import default_timer

import numpy as np
from bs4 import BeautifulSoup
from nlm_utils.utils import ensure_bool

import nlm_ingestor.ingestion_daemon.config as cfg
from nlm_ingestor.file_parser import markdown_parser, pdf_file_parser
from nlm_ingestor.ingestor import (
    html_ingestor,
    pdf_ingestor,
    text_ingestor,
    xml_ingestor,
)
from nlm_ingestor.ingestor_utils.utils import NpEncoder

# initialize logging
logger = logging.getLogger(__name__)
logger.setLevel(cfg.log_level())
run_table_detection: bool = ensure_bool(os.getenv("RUN_TABLE_DETECTION", False))
title_text_only_pattern = re.compile(r"[^a-zA-Z]+")
title_delimiter_remove_pattern = re.compile(r"[.;'\"\-,\n\r]")


def ingest_document(
    doc_name,
    doc_location,
    mime_type,
    parse_options: dict = None,
):
    print(f"Parsing {mime_type} at {doc_location} with name {doc_name}")
    ingestor = None
    if mime_type == "application/pdf":
        print("using pdf parser")
        ingestor = pdf_ingestor.PDFIngestor(doc_location, parse_options)
        return_dict = ingestor.return_dict
    elif mime_type in {"text/markdown", "text/x-markdown"}:
        print("using markdown parser")
        ingestor = markdown_parser.MarkdownDocument(doc_location)
        return_dict = {"result": ingestor.json_dict}
    elif mime_type == "text/html":
        print("using html parser")
        ingestor = html_ingestor.HTMLIngestor(doc_location)
        return_dict = {
            "result": ingestor.json_dict,
        }
    elif mime_type == "text/plain":
        print("using text parser")
        ingestor = text_ingestor.TextIngestor(doc_location, parse_options)
        return_dict = ingestor.return_dict
    elif mime_type == "text/xml":
        print("using xml parser")
        ingestor = xml_ingestor.XMLIngestor(doc_location)
        return_dict = {
            "result": ingestor.json_dict,
        }
    else:  # use tika parser as a catch all
        print(f"defaulting to tika parser for mime_type {mime_type}")
        parsed_content = pdf_file_parser.parse_to_html(doc_location)
        with open(doc_location, "w") as file:
            file.write(parsed_content["content"])
        ingestor = html_ingestor.HTMLIngestor(doc_location)
        return_dict = {
            "result": ingestor.json_dict,
        }

    if doc_location and os.path.exists(doc_location):
        os.unlink(doc_location)
        print(f"File {doc_location} deleted")
    return return_dict, ingestor
