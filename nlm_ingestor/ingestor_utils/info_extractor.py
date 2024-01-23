import os
from collections import Counter

from nlm_utils.model_client.classification import ClassificationClient

from nlm_ingestor.ingestor import line_parser
from nlm_ingestor.ingestor.visual_ingestor import table_parser
import copy

from nlm_utils.utils import ensure_bool
from nlm_utils.utils import query_preprocessing as preprocess

use_qatype = ensure_bool(os.getenv("USE_QATYPE", False)) or ensure_bool(os.getenv("INDEX_QATYPE", False))


def create_all_definition_links(kv_pairs, all_quoted_words):
    all_definitions = {}
    for kv in kv_pairs:
        if kv["key"] not in all_definitions:
            all_definitions[kv["key"]] = []
        all_definitions[kv["key"]].append({
            "block_idx": kv["block"]["block_idx"],
            "block_text": kv["block"]["block_text"],
        })

    for qw in all_quoted_words:
        quote_block_texts = [
            {"text": qw_context.get('block_text', ''), "block_idx": qw_context["block_idx"]}
            for qw_context in all_quoted_words[qw]
        ]
        definition_contexts = preprocess.identify_non_reporting_expression(qw, quote_block_texts)
        if qw not in all_definitions:
            all_definitions[qw] = []
        for def_context in definition_contexts:
            is_already_added = False
            for def_cont in all_definitions[qw]:
                if def_cont["block_idx"] == def_context["block_idx"]:
                    is_already_added = True
                    break
            if not is_already_added:
                all_definitions[qw].append({
                    "block_idx": def_context["block_idx"],
                    "block_text": def_context["text"],
                })
    return all_definitions


def extract_key_data(
    texts,
    infos,
    bbox={},
    add_info=False,
    do_summaries=True,
):
    qa_client = None
    if use_qatype:
        qa_client = ClassificationClient(
            model="roberta",
            task="roberta-phraseqa",
            url=os.getenv("MODEL_SERVER_URL", "https://services.nlmatics.com"),
        )
    noun_chunk_locs = {}
    # all noun chunks in the document
    noun_chunks = []
    # summary by header
    summary_by_header = {}
    # mapping from noun_chunk to headers
    noun_chunk_headers = {}
    # all the contexts that have quoted words e.g. definitions
    kv_pairs = []
    qw_queries = []
    qw_contexts = []
    all_quoted_words = {}

    def get_summary_key(info):
        # info["header_text"]
        if info:
            return info["block_text"] + "-" + str(info["block_idx"])
        else:
            return ""

    for match_idx, (text, info) in enumerate(zip(texts, infos)):
        if "ignore" not in info or not info["ignore"]:
            if do_summaries and info["block_type"] == "header":
                summary_by_header[get_summary_key(info)] = {
                    "title": info["block_text"],
                    "block": copy.deepcopy(info),
                    "block_idx": info["block_idx"],
                    "match_idx": match_idx,
                    "noun_chunks": [],
                    "n_quoted_words": 0,
                    "kv_pairs": [],
                    "tables": [],
                    "table_bbox": [],
                    "audited": False,
                }

                if info["block_idx"] in bbox:
                    summary_by_header[get_summary_key(info)]["header_bbox"] = bbox[
                        info["block_idx"]
                    ]["bbox"]

            if (
                info["block_type"] != "table_row"
                and table_parser.row_group_key not in info
            ):
                line = line_parser.Line(text)
                quoted_words = []
                for qw in line.quoted_words:
                    stop_word = True
                    # Remove any stop words.
                    for word in qw.split():
                        if word not in preprocess.CROSS_REFERENCE_STOP_WORDS:
                            stop_word = False
                            break
                    if not stop_word and len(qw) >= 2:
                        quoted_words.append(qw)
                if len(quoted_words) > 0:
                    for qw in quoted_words:
                        kv_data = {
                            "block": info,                      # so that we can link in UI
                            "all_quoted_words": quoted_words,   # to know all other quoted words in query
                            "key": qw,                          # key of the k, v pairs we are extracting
                        }
                        if add_info:
                            kv_data["match_text"] = text
                        kv_pairs.append(
                            kv_data,
                        )
                        if qw not in all_quoted_words:
                            all_quoted_words[qw] = [
                                info,
                            ]
                        else:
                            if info not in all_quoted_words[qw]:
                                all_quoted_words[qw].append(info)
                        qw_queries.append(qw)
                        qw_contexts.append(text)
                noun_chunks.extend(line.noun_chunks)

                for chunk in line.noun_chunks:
                    if chunk not in noun_chunk_locs:
                        noun_chunk_locs[chunk] = [match_idx]
                    else:
                        noun_chunk_locs[chunk].append(match_idx)
                    header_text = info["header_text"]
                    if not header_text == "" and not info["block_type"] == "header":
                        header_block_info = {
                            "block_idx": info["header_block_idx"],
                            "block_text": info["header_text"],
                        }
                        key = get_summary_key(header_block_info)
                        if key not in summary_by_header:
                            continue
                        summary_by_header[key]["noun_chunks"].append(chunk)
                        chunk_key = chunk
                        if chunk_key not in noun_chunk_headers:
                            noun_chunk_headers[chunk_key] = [header_text]
                        else:
                            noun_chunk_headers[chunk_key].append(header_text)

    # todo use yi's dataframe code here
    table = {}
    header_block_info = None
    is_rendering_table = False
    if do_summaries:
        for block in infos:
            if "is_table_start" in block:
                is_rendering_table = True
                header_block_info = {
                    "block_idx": block["header_block_idx"],
                    "block_text": block["header_text"],
                }
                if block["block_idx"] in bbox:
                    table_bbox = bbox[block["block_idx"]]["bbox"]
                    audited = bbox[block["block_idx"]]["audited"]
                else:
                    table_bbox = [-1, -1, -1, -1]
                    audited = False
                table = {"rows": [], "cols": [], "name": header_block_info["block_text"]}
            if is_rendering_table:
                cell_values = block.get("cell_values", [])
                if "is_header" in block:
                    table["cols"] = cell_values
                elif "is_header_group" not in block:
                    table["rows"].append(cell_values)
                # If we are rendering a table, do not consider headers
                if block["block_type"] == "header" and \
                        "is_table_start" not in block and \
                        get_summary_key(block) in summary_by_header:
                    del summary_by_header[get_summary_key(block)]
            if "is_table_end" in block and header_block_info:
                summary_key = get_summary_key(header_block_info)
                if summary_key and summary_key not in summary_by_header:
                    summary_by_header[summary_key] = {
                        "title": header_block_info["block_text"],
                        "block": copy.deepcopy(block),
                        "block_idx": header_block_info["block_idx"],
                        "match_idx": match_idx,
                        "header_bbox": [-1, -1, -1, -1],
                        "noun_chunks": [],
                        "n_quoted_words": 0,
                        "kv_pairs": [],
                        "tables": [],
                        "table_bbox": [],
                        "audited": False,
                    }
                else:
                    summary_by_header[summary_key]["block"]["table_page_idx"] = block["page_idx"]

                summary_by_header[summary_key]["tables"].append(table)
                summary_by_header[summary_key]["table_bbox"].append(table_bbox)
                summary_by_header[summary_key]["audited"] = audited

                is_rendering_table = False

    if qw_queries and qa_client:
        qw_answers = qa_client(qw_queries, qw_contexts)["answers"]
        for qw_info, (_, qw_answer) in zip(kv_pairs, qw_answers[0].items()):
            qw_info["value"] = qw_answer["text"]
    # now merge the result from individual kv pairs into header wise summary
    # filtered_kv_pairs = []
    if qa_client:
        kv_pairs = [
            item for item in kv_pairs if item.get("value", "")
        ]  # Select entries with non-null value
    else:
        kv_pairs = []
    if do_summaries:
        for pair in kv_pairs:
            header_key = get_summary_key(pair["block"])
            if header_key not in summary_by_header:
                continue
            kv = {"key": pair["key"], "value": pair["value"]}
            summary = summary_by_header[header_key]
            summary["block"]["n_quoted_words"] = len(pair["all_quoted_words"])
            summary["kv_pairs"].append(kv)
    # turn the map into a list
    summaries = []
    for header_text, summary in summary_by_header.items():
        # summary["title"] = header_text
        counter = Counter(summary["noun_chunks"])
        top_chunks = counter.most_common(8)
        summary["noun_chunks"] = []
        for chunk in top_chunks:
            summary["noun_chunks"].append(chunk[0])

        # detach tables from headers, so the paras won't indent under the table 
        if summary["block"]["block_type"] == "header" and len(summary["tables"]) > 0:
            #     # duplicate the block summary for header and table
            #     header_block = copy.deepcopy(summary)
            #     header_block["tables"] = []
            #     header_block["table_bbox"] = []
            #     summaries.append(header_block)
            #
            #     # offset the table block summary by 1
            #     summary["block_idx"] += 1
            #     summary["match_idx"] += 1
            #     summary["block"]["block_idx"] += 1
            #     summary["block"]["header_block_idx"] += 1
            #     summary["block"]["header_match_idx"] += 1
            #     summary["block"]["level"] += 1

            # insert header text to the beginning (nearest) header chain, so that outline in the UI re-maps it
            summary["block"]["level_chain"].insert(0, {
                "block_idx": summary["block_idx"],
                "block_text": summary["block"]["block_text"],
            })
        summaries.append(summary)
    # sort the summaries by order of appearance
    summaries.sort(key=lambda x: x["match_idx"])

    # Construct the reference definitions to enable linking.
    reference_definitions = create_all_definition_links(kv_pairs, all_quoted_words)

    return summaries, kv_pairs, reference_definitions
