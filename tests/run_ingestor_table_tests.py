import argparse
import codecs
import os
import multiprocessing as mp
from itertools import groupby

from bs4 import BeautifulSoup
from nlm_utils.storage import file_storage
from pymongo import MongoClient
from tika import parser

from nlm_ingestor.ingestor import table_parser
from nlm_ingestor.ingestor import visual_ingestor

db_client = MongoClient(os.getenv("MONGO_HOST", "localhost"))
db = db_client[os.getenv("MONGO_DATABASE", "doc-store-dev")]
html_dict = {}

manager = mp.Manager()
total_documents = manager.list()
correct_tables = manager.list()
missed_tables = manager.list()
incorrect_tables = manager.list()


def ingestor_debug():
    visual_ingestor.HTML_DEBUG = False
    visual_ingestor.LINE_DEBUG = False
    visual_ingestor.MIXED_FONT_DEBUG = False
    table_parser.TABLE_DEBUG = False
    table_parser.TABLE_COL_DEBUG = False
    visual_ingestor.HF_DEBUG = False
    visual_ingestor.REORDER_DEBUG = False
    visual_ingestor.MERGE_DEBUG = False


def pre_process_text(text):
    text = str(text).replace('"', "'").replace("\\", "")
    return text


def retrive_pdf(doc_id):
    file_location = f"files/pdf/{doc_id}.pdf"
    if os.path.isfile(file_location):
        print(f"file {doc_id}.pdf found")
        return file_location

    if not os.path.exists("files/pdf"):
        os.makedirs("files/pdf")
    # open(file_location, 'a').close()
    doc_loc = db["document"].find_one({"id": doc_id})["doc_location"]
    file_storage.download_document(doc_loc, file_location)
    return file_location


def retrive_html(doc_id):
    file_location = f"files/html/{doc_id}.html"
    if os.path.isfile(file_location):
        print(f"file {doc_id}.html found")
        return codecs.open(file_location, "r", "utf-8").read()
    if not os.path.exists("files/html"):
        os.makedirs("files/html")
    return ""


def get_html(doc_id, doc_type):
    parsed = ""
    if doc_type == "html":
        parsed = retrive_html(doc_id)
    if not parsed:
        file_location = retrive_pdf(doc_id)
        print("parsing pdf")
        # Turn off OCR by default
        timeout = 9000
        headers = {
            "X-Tika-OCRskipOcr": "true"
        }
        parsed = parser.from_file(file_location, xmlContent=True, requestOptions={'headers': headers, 'timeout': timeout})
        print("pdf parsed")
        if not os.path.exists("files/html"):
            os.makedirs("files/html")
        f = open(f"files/html/{doc_id}.html", "w")
        f.write(str(parsed))
        f.close()
    # download document to temp then parse it
    soup = BeautifulSoup(str(parsed), "html.parser")
    pages = soup.find_all("div", class_=lambda x: x in ["page"])
    print("starting visual ingestor")
    ingestor_debug()
    parsed_doc = visual_ingestor.Doc(pages, [])
    print("visual ingestor finishes")
    # os.remove(file_location)
    # get the html str to compare with
    html_text = parsed_doc.html_str
    return html_text


def compare_results(test, html_text):
    print("comparing results")
    # search on the entire html for table with provided attributes
    # print(html_text)
    soup = BeautifulSoup(html_text, "lxml")
    table = soup.find(
        "table",
        {"page_idx": test["page_idx"], "left": test["left"]},
    )
    if not table:
        return "missed", test

    table_body = table.find("tbody")
    data = []
    rows = table_body.find_all("tr")
    for row in rows:
        cols = row.find_all("th") if row.find_all("th") else row.find_all("td")
        cols = [pre_process_text(x.text.strip()) for x in cols]
        data.append([x for x in cols])
    # check if the contents in the table matches
    # print(data)
    # print(test["table"])

    processed_table = []
    for row in test["table"]:
        cols = [pre_process_text(x.strip()) for x in row]
        processed_table.append(cols)

    if data == processed_table:
        return "correct", data
    else:
        table = soup.find(
            "table",
            {"page_idx": test["page_idx"], "top": test["top"], "left": test["left"]},
        )
        if not table:
            return "incorrect", data
        table_body = table.find("tbody")
        data = []
        rows = table_body.find_all("tr")
        for row in rows:
            cols = row.find_all("th") if row.find_all("th") else row.find_all("td")
            cols = [pre_process_text(x.text.strip()) for x in cols]
            data.append([x for x in cols])
        if data != processed_table:
            return "incorrect", data
        else:
            return "correct", data


def print_results(
    total_tests,
    total_documents,
    correct_tables,
    missed_tables,
    incorrect_tables,
):
    def print_table(table):
        # format table nicely before printing it
        s = ""
        for i in range(len(table)):
            row = table[i]
            s += f"{i} {row} \n"
        return s

    def print_document_attrs(doc_id):
        doc = db["document"].find_one({"id": doc_id})
        workspace = db["workspace"].find_one({"id": doc["workspace_id"]})
        return f"Workspace: {workspace['name']}; Document: {doc['name']}, {doc['id']}"

    # print stuff
    line_break = "======================================================== \n"
    row_break = "***** \n"
    s = ""
    s += line_break
    if len(incorrect_tables) > 0:
        s += line_break
        s += "Incorrect Matches: \n"
        for match in incorrect_tables:
            s += row_break
            correct = match[0]
            correct_pos = f"{correct['top']}, {correct['left']}"
            s += f"{print_document_attrs(correct['doc_id'])}; Page: {correct['page_idx']}; location: {correct_pos}; " \
                 f"Table Name: {correct['name']}; Tag: {correct['tag']} \n"
            s += "Stored: \n"
            s += print_table(correct['table'])
            s += "Parsed: \n"
            s += print_table(match[1])

    if len(missed_tables) > 0:
        s += line_break
        s += "Missed Matches: \n"
        for match in missed_tables:
            s += row_break
            match_pos = f"{match['top']}, {match['left']} \n"
            s += f"{print_document_attrs(match['doc_id'])}; Page: {match['page_idx']}; location: {match_pos}; Table Name: {match['name']}; Tag: {match['tag']} \n"
            s += print_table(match["table"])

    s += line_break
    s += f"Total documents: {total_documents}, Total tests: {total_tests}, correct: {len(correct_tables)}, incorrect: {len(incorrect_tables)}, missed: {len(missed_tables)} \n"
    s += line_break
    return s


def run_table_test(tests):
    global correct_tables
    global missed_tables
    global incorrect_tables
    global total_documents

    local_correct_tables = []
    local_missed_tables = []
    local_incorrect_tables = []

    for test in tests:
        doc_id = test["doc_id"]
        print(f"document: {doc_id}")
        if doc_id not in html_dict:
            html_text = get_html(doc_id, doc_type=doc_type)
            html_dict[doc_id] = html_text
            total_documents.append(1)
        else:
            html_text = html_dict[doc_id]
        result, data = compare_results(test, html_text)
        if result == "correct":
            correct_tables.append(test)
            local_correct_tables.append(test)
        elif result == "incorrect":
            incorrect_tables.append([test, data])
            local_incorrect_tables.append([test, data])
        elif result == "missed":
            missed_tables.append(test)
            local_missed_tables.append(test)
    # response = print_results(
    #     len(tests),
    #     1,
    #     local_correct_tables,
    #     local_missed_tables,
    #     local_incorrect_tables,
    # )
    # print(response)
    return


def run_test(doc_id="", doc_type="html", num_procs=1):
    # doc_id: html_str
    global correct_tables
    global missed_tables
    global incorrect_tables
    global total_documents

    if doc_id:
        query = {"doc_id": doc_id}
    else:
        query = {}
    # loop through every document in every collection
    tests = [doc for doc in db["ingestor_table_test_cases"].find(query)]
    tests.sort(key=lambda x: x['doc_id'])
    groups = []
    for k, v in groupby(tests, key=lambda x: x['doc_id']):
        groups.append(list(v))    # Store group iterator as a list

    if len(groups) > 1:
        number_of_processes = num_procs
        with mp.Pool(number_of_processes) as pool:
            pool.map(run_table_test, groups)
    elif len(groups) == 1:
        run_table_test(groups[0])

    response = print_results(
        len(tests),
        len(total_documents),
        correct_tables,
        missed_tables,
        incorrect_tables,
    )
    print(response)
    return


if __name__ == "__main__":
    doc_id = ""
    doc_type = "html"
    num_procs = 1
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--doc_id", required=False)
    arg_parser.add_argument("--doc_type", required=False)
    arg_parser.add_argument("--num_procs", required=False)
    args = arg_parser.parse_args()

    doc_id_list = []
    if args.doc_id:
        doc_id_list = args.doc_id.split(',')
    if args.doc_type:
        doc_type = args.doc_type
    if args.num_procs:
        num_procs = int(args.num_procs)
    print(f"running script with -> docId: {doc_id_list}, docType: {doc_type}, num_procs: {num_procs}")
    if len(doc_id_list) > 0:
        for doc_id in doc_id_list:
            run_test(doc_id=doc_id, doc_type=doc_type, num_procs=num_procs)
    else:
        run_test(doc_id='', doc_type=doc_type, num_procs=num_procs)
