import argparse
import codecs
import json
import multiprocessing as mp
import os
from itertools import groupby
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from nlm_utils.storage import file_storage
from nlm_ingestor.ingestor import table_parser, visual_ingestor

BASE_URL = (
    "http://host.docker.internal:5010"  # Adjust this if your port mapping is different
)

html_dict = {}


def process_document_with_container(doc_id, pdf_path):
    url = urljoin(BASE_URL, "/api/parseDocument")
    files = {"file": open(pdf_path, "rb")}
    params = {"renderFormat": "all", "useNewIndentParser": "yes", "applyOcr": "no"}
    try:
        response = requests.post(url, files=files, params=params)
        response.raise_for_status()
        print("Response:")
        print(json.dumps(response.json(), indent=2))
        return response.json()["return_dict"]["html"]
    except requests.RequestException as e:
        print(f"Error processing document {doc_id}: {str(e)}")
        return None
    finally:
        files["file"].close()


def pre_process_text(text):
    text = str(text).replace('"', "'").replace("\\", "")
    return text


def retrive_pdf(doc_id):
    file_location = f"/app/files/pdf/{doc_id}.pdf"  # /app for docker mount
    if os.path.isfile(file_location):
        print(f"file {doc_id}.pdf found")
        return file_location

    if not os.path.exists("/app/files/pdf"):  # /app for docker mount
        os.makedirs("/app/files/pdf")  # /app for docker mount
    # open(file_location, 'a').close()
    doc_loc = db["document"].find_one({"id": doc_id})["doc_location"]
    file_storage.download_document(doc_loc, file_location)
    return file_location

def ingestor_debug():
    visual_ingestor.HTML_DEBUG = False
    visual_ingestor.LINE_DEBUG = False
    visual_ingestor.MIXED_FONT_DEBUG = False
    table_parser.TABLE_DEBUG = False
    table_parser.TABLE_COL_DEBUG = False
    visual_ingestor.HF_DEBUG = False
    visual_ingestor.REORDER_DEBUG = False
    visual_ingestor.MERGE_DEBUG = False

def get_html(doc_id):
    pdf_file = f"/app/files/pdf/{doc_id}.pdf"
    html_file = f"/app/files/html/{doc_id}.html"
    ingestor_debug()

    if os.path.isfile(html_file):
        print(f"HTML file {doc_id}.html found")
        with codecs.open(html_file, "r", "utf-8") as f:
            return f.read()

    if not os.path.isfile(pdf_file):
        raise FileNotFoundError(f"PDF file {pdf_file} not found")

    print(f"Processing PDF: {pdf_file}")
    html_content = process_document_with_container(doc_id, pdf_file)
    
    if html_content is None:
        raise Exception(f"Failed to process document {doc_id}")

    # Ensure the directory exists
    os.makedirs(os.path.dirname(html_file), exist_ok=True)

    # Save the HTML content
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Saved HTML content to {html_file}")

    return html_content

def compare_results(test, html_text):
    print("Comparing results")

    soup = BeautifulSoup(html_text, "html.parser")
    page_data = []
    min_indent = 100000

    print("Extracted text content:")
    for tag in soup.find_all(text=True):
        if tag.strip():
            print(f"- {tag.strip()}")
    print(test, "test")
    for tag in soup.findAll("", {"page_idx": str(test["page_idx"])}):
        name = tag.name
        print(tag, name, "\n\n")
        if name in ["td", "tr", "th"]:
            continue
        style = tag.get("style")
        if style and "margin-left: " in style and "px" in style:
            indent = int(style.split("margin-left: ")[1].split("px")[0]) + 20
        elif not style and (tag.get("block_idx") or tag.get("block_idx") == "0"):
            indent = 20
        else:
            indent = None

        if indent:
            min_indent = min(indent, min_indent)
            page_data.append([name, indent])

    for p in page_data:
        p[1] = (p[1] - min_indent) // 20

    print("Resulting page_data structure:")
    print(json.dumps(page_data, indent=2))

    if page_data == test["page_data"]:
        return "correct", page_data
    else:
        return "incorrect", page_data


def print_results(
    total_tests,
    total_documents,
    correct_tables,
    missed_tables,
    incorrect_tables,
):
    def print_table(table):
        s = ""
        for i, row in enumerate(table):
            s += f"{i} {row} \n"
        return s

    def print_document_attrs(doc_id):
        doc = db["document"].find_one({"id": doc_id})
        workspace = db["workspace"].find_one({"id": doc["workspace_id"]})
        return f"Workspace: {workspace['name']}; Document: {doc['name']}, {doc['id']}"

    line_break = "======================================================== \n"
    row_break = "***** \n"
    s = line_break

    if incorrect_tables:
        s += line_break + "Incorrect Matches: \n"
        for match in incorrect_tables:
            s += row_break
            correct = match[0]
            s += f"{print_document_attrs(correct['doc_id'])}; Page: {correct['page_idx']}; location: {correct['page_data']}; \n"
            s += "Stored: \n" + print_table(correct["page_data"])
            s += "Parsed: \n" + print_table(match[1])

    if missed_tables:
        s += line_break + "Missed Matches: \n"
        for match in missed_tables:
            s += row_break
            match_pos = f"{match['top']}, {match['left']} \n"
            s += f"{print_document_attrs(match['doc_id'])}; Page: {match['page_idx']}; location: {match_pos}; Table Name: {match['name']}; Tag: {match['tag']} \n"
            s += print_table(match["table"])

    s += line_break
    s += f"Total documents: {total_documents}, Total tests: {total_tests}, correct: {len(correct_tables)}, incorrect: {len(incorrect_tables)}, missed: {len(missed_tables)} \n"
    s += line_break
    return s


def run_table_test(test):
    try:
        doc_id = test["doc_id"]
        print(f"Processing document: {doc_id}")
        html_text = get_html(doc_id)
        result, data = compare_results(test, html_text)
        return result, data, test
    except Exception as e:
        print(f"Error processing document {doc_id}: {str(e)}")
        return "error", str(e), test


def run_test(doc_id="", num_procs=1):
    if doc_id:
        tests = [{"doc_id": doc_id, "page_idx": 0, "page_data": []}]
    else:
        tests = []
        pdf_dir = "/app/files/pdf"  # /app for docker mount
        for filename in os.listdir(pdf_dir):
            if filename.endswith(".pdf"):
                doc_id = filename[:-4]
                tests.append({"doc_id": doc_id, "page_idx": 0, "page_data": []})

    tests.sort(key=lambda x: x["doc_id"])

    if num_procs > 1:
        with mp.Pool(num_procs) as pool:
            results = pool.map(run_table_test, tests)
    else:
        results = []
        for test in tests:
            try:
                results.append(run_table_test(test))
            except Exception as e:
                print(f"Error processing test: {str(e)}")
                results.append(("error", str(e), test))

    correct_tables = []
    missed_tables = []
    incorrect_tables = []
    total_documents = len(tests)

    for result, data, test in results:
        if result == "correct":
            correct_tables.append(test)
        elif result == "incorrect":
            incorrect_tables.append([test, data])
        elif result == "missed":
            missed_tables.append(test)

    response = print_results(
        len(tests),
        total_documents,
        correct_tables,
        missed_tables,
        incorrect_tables,
    )
    print(response)
    return


if __name__ == "__main__":
    mp.freeze_support()  # This line is correct and should stay here
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--doc_id", required=False)
    arg_parser.add_argument("--num_procs", required=False, type=int, default=1)
    args = arg_parser.parse_args()

    doc_id = args.doc_id if args.doc_id else ""
    num_procs = args.num_procs

    print(f"Running script with -> docId: {doc_id}, num_procs: {num_procs}")
    run_test(doc_id=doc_id, num_procs=num_procs)
