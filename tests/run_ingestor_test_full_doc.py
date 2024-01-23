import argparse
import codecs
import os
import time
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
correct_docs = manager.list()
missed_docs = manager.list()
incorrect_docs = manager.list()


def ingestor_debug():
    visual_ingestor.HTML_DEBUG = False
    visual_ingestor.LINE_DEBUG = False
    visual_ingestor.MIXED_FONT_DEBUG = False
    table_parser.TABLE_DEBUG = False
    table_parser.TABLE_COL_DEBUG = False
    visual_ingestor.HF_DEBUG = False
    visual_ingestor.REORDER_DEBUG = False
    visual_ingestor.MERGE_DEBUG = False


def retrive_pdf(doc_id):
    file_location = f"files/pdf/parsers/{doc_id}.pdf"
    if os.path.isfile(file_location):
        print(f"file {doc_id}.pdf found")
        return file_location

    if not os.path.exists("files/pdf/parsers"):
        os.makedirs("files/pdf/parsers")
    # open(file_location, 'a').close()
    doc_loc = db["document"].find_one({"id": doc_id})["doc_location"]
    file_storage.download_document(doc_loc, file_location)
    return file_location


def retrive_html(doc_id):
    file_location = f"files/html/parsers/{doc_id}.html"
    if os.path.isfile(file_location):
        print(f"file {doc_id}.html found")
        return codecs.open(file_location, "r", "utf-8").read()
    if not os.path.exists("files/html/parsers"):
        os.makedirs("files/html/parsers")
    return ""


def get_html(doc_id, doc_type):
    parsed = ""
    if doc_type == "html":
        parsed = retrive_html(doc_id)
    if not parsed:
        file_location = retrive_pdf(doc_id)
        print("parsing pdf")
        parsed = parser.from_file(file_location, xmlContent=True)
        print("pdf parsed")
        if not os.path.exists("files/html/parsers"):
            os.makedirs("files/html/parsers")
        f = open(f"files/html/parsers/{doc_id}.html", "w")
        f.write(str(parsed))
        f.close()
    # download document to temp then parse it
    soup = BeautifulSoup(str(parsed), "html.parser")
    pages = soup.find_all("div", class_=lambda x: x not in ["annotation"])
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
    if test['html_str'] == html_text:
        return "correct", html_text
    else:
        return "incorrect", html_text
    # soup = BeautifulSoup(html_text, 'html.parser')
    # page_data = []
    # min_indent = 100000
    # for tag in soup.findAll("", {"page_idx": test["page_idx"]}):
    #     name = tag.name
    #     if name in ["td", "tr", "th"]:
    #         continue
    #     style = tag.get("style")
    #     if style and "margin-left: " in style and "px" in style:
    #         indent = int(style.split("margin-left: ")[1].split("px")[0]) + 20
    #     elif not style and (tag.get("block_idx") or tag.get("block_idx") == "0"):
    #         indent = 20
    #     else:
    #         indent = None
    #
    #     if indent:
    #         min_indent = min(indent, min_indent)
    #         page_data.append([name, indent])
    #
    #
    # for p in page_data:
    #     p[1] = (p[1]- min_indent) // 20
    #
    # if page_data == test["page_data"]:
    #     return "correct", page_data
    # else:
    #     return "incorrect", page_data


def print_results(
    total_tests,
    total_documents,
    correct_docs,
    missed_docs,
    incorrect_docs,
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
    if len(incorrect_docs) > 0:
        s += line_break
        s += "Incorrect Matches: \n"
        ts = time.time()
        for match in incorrect_docs:
            s += row_break
            correct = match[0]
            s += f"{print_document_attrs(correct['doc_id'])};\n"
            if not os.path.exists("files/html/parsers"):
                os.makedirs("files/html/parsers")
            f = open(f"files/html/parsers/{correct['doc_id']}_incorrect_{int(ts)}.html", "w")
            f.write(str(match[1]))
            f.close()
            f = open(f"files/html/parsers/{correct['doc_id']}_correct_{int(ts)}.html", "w")
            f.write(str(correct['html_str']))
            f.close()

    s += line_break
    s += f"Total documents: {total_documents}, Total tests: {total_tests}, " \
         f"correct: {len(correct_docs)}, incorrect: {len(incorrect_docs)}, missed: {len(missed_docs)} \n"
    s += line_break
    return s


def run_full_doc_test(tests):
    global correct_docs
    global missed_docs
    global incorrect_docs
    global total_documents

    local_correct_docs = []
    local_missed_docs = []
    local_incorrect_docs = []

    for test in tests:
        try:
            doc_id = test["doc_id"]
            print(f"document: {doc_id}")
            html_text = get_html(doc_id, doc_type=doc_type)
            # if doc_id not in html_dict:
            #     html_text = get_html(doc_id, doc_type=doc_type)
            #     html_dict[doc_id] = html_text
            #     total_documents.append(1)
            # else:
            #     html_text = html_dict[doc_id]
            result, data = compare_results(test, html_text)
            
            if result == "correct":
                correct_docs.append(test)
                local_correct_docs.append(test)
            elif result == "incorrect":
                incorrect_docs.append([test, data])
                local_incorrect_docs.append([test, data])
            elif result == "missed":
                missed_docs.append(test)
                local_missed_docs.append(test)
        except Exception as e:
            print(e)
    # response = print_results(
    #     len(tests),
    #     1,
    #     local_correct_docs,
    #     local_missed_docs,
    #     local_incorrect_docs,
    # )
    # print(response)
    return


def run_test(doc_id="", doc_type="html", num_procs=1):
    # doc_id: html_str
    global correct_docs
    global missed_docs
    global incorrect_docs
    global total_documents

    if doc_id:
        query = {"doc_id": doc_id}
    else:
        query = {}
    # loop through every document in every collection
    tests = [doc for doc in db["ingestor_full_doc_test_cases"].find(query)]
    tests.sort(key=lambda x: x['doc_id'])
    groups = []
    for k, v in groupby(tests, key=lambda x: x['doc_id']):
        groups.append(list(v))    # Store group iterator as a list

    if len(groups) > 1:
        number_of_processes = num_procs
        with mp.Pool(number_of_processes) as pool:
            pool.map(run_full_doc_test, groups)
    else:
        run_full_doc_test(groups[0])

    response = print_results(
        len(tests),
        len(total_documents),
        correct_docs,
        missed_docs,
        incorrect_docs,
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
