import os

import urllib3
from bs4 import BeautifulSoup
from minio import Minio
from pymongo import MongoClient

from ingestor import ingest_and_render_file

db_client = MongoClient(os.getenv("MONGO_HOST", "localhost"))
db = db_client[os.getenv("MONGO_DATABASE", "doc-store-dev")]

httpClient = urllib3.PoolManager(maxsize=1000)

minioClient = Minio(
    os.getenv("MINIO_URL", "localhost:9000"),
    access_key=os.getenv("MINIO_ACCESS", "user"),
    secret_key=os.getenv("MINIO_SECRET", "password"),
    secure=False,
    http_client=httpClient,
)


def get_tika_documents(test_case_dict, test_dir="test_dir/tika"):
    # check if pdf document exists in test_dir
    for document in test_case_dict:
        doc_location = test_case_dict[document]["doc_location"] + ".html"
        doc_name = test_case_dict[document]["name"]
        doc_location = doc_location.replace("gs://doc-store-dev/", "")
        dest_file_location = f"{test_dir}/{doc_name}.html"

        # fetches all the raw documents needed to run the test
        # path to test_dir needs to exist
        minioClient.fget_object(
            "doc-store-dev",
            doc_location,
            dest_file_location,
        )

    pass


def create_block_list(total_blocks):
    """
    convert array of blocks to match test-case format
    """
    block_list = []
    for block in total_blocks:
        block_list.append(
            (block["page_idx"], block["block_type"], block["block_text"].strip()),
        )
    return block_list


def get_full_tables(blocks):
    # prev_block_idx = 0
    table_list = []
    table = []
    page_idx = 0
    top = 0
    left = 0
    table_start = False
    for block in blocks:
        if "is_table_start" in block:
            table_start = True
        # print()
        # print(block['block_type'], block['block_text'], table_start)
        if (block["block_type"] == "table_row" or table_start) and (
            "cell_values" in block
        ):
            # block_idx = block["block_idx"]
            # table_start = 'is_table_start' in block
            table_end = "is_table_end" in block

            if len(table) != 0:
                # print("table cont")
                # print(block.keys(), block['block_type'], block['block_text'])
                table.append(block["cell_values"])

            elif len(table) == 0:
                # print("new table")
                top = block["box_style"][0]
                left = block["box_style"][1]
                page_idx = block["page_idx"]
                table = [block["cell_values"]]

            # print(block['block_idx'], block['block_text'])
            # print()
            # prev_block_idx = block_idx
            if table_end:
                table_start = False
                table_end = False
                table_list.append(((page_idx, top, left), "table", table))
                table = []
    else:
        if len(table):
            # print("adding to table list")
            table_list.append(((page_idx, top, left), "table", table))
    return table_list


def ingest_documents(
    test_case_dict, tika_documents="dump", ingested_document_dir="dump/ingest_output",
):
    # dump the rendered html documents in the output dir
    total_blocks = (
        {}
    )  # dictionary where key is document name and value are document blocks
    for document in test_case_dict:
        document_name = test_case_dict[document]["name"]
        tika_file = f"{tika_documents}/{document_name}.html"
        blocks, block_texts, sents, file_data, result, _num_pages = ingest_and_render_file(
            tika_file, False,
        )

        # inferred_title = result["title_page_fonts"]["first_level"][:2]
        # write ingestor output to file
        output_file = (
            f"{ingested_document_dir}/{document_name.replace('.pdf', '_ingested')}.html"
        )
        out_html = eval('{"text' + file_data.split('"text')[1])["text"]

        with open(output_file, "w") as file:
            file.write(out_html)

        tables = get_full_tables(
            blocks,
        )  # get list of ((page, top, left), table), blocks contain table_rows
        total_blocks[document_name] = {"blocks": blocks, "tables": tables}

    return total_blocks


def score_ingestor(total_blocks, test_case_dict):
    stats_dict = {}
    for document_id in test_case_dict:
        document_name = test_case_dict[document_id]["name"]
        stats_dict[document_name] = {"missed_case": []}
        block_list = create_block_list(total_blocks[document_name]["blocks"])
        table_list = total_blocks[document_name]["tables"]
        correct = 0
        wrong = 0
        total = len(test_case_dict[document_id]["test_case_list"])
        for test_case in test_case_dict[document_id]["test_case_list"]:
            if test_case[1] == "table":
                if test_case in table_list:
                    correct += 1
                else:
                    stats_dict[document_name]["missed_case"].append(test_case)
                    wrong += 1
            else:
                if test_case in block_list:
                    correct += 1
                else:
                    stats_dict[document_name]["missed_case"].append(test_case)
                    wrong += 1
        stats_dict[document_name]["correct"] = correct
        stats_dict[document_name]["wrong"] = wrong
        stats_dict[document_name]["total_cases"] = total
    return stats_dict


def get_documents(test_case_dict, test_dir="test_dir/raw"):
    # check if pdf document exists in test_dir
    for document in test_case_dict:
        doc_location = test_case_dict[document]["doc_location"]
        doc_name = test_case_dict[document]["name"]
        doc_location = doc_location.replace("gs://doc-store-dev/", "")
        dest_file_location = f"{test_dir}/{doc_name}"

        # fetches all the raw documents needed to run the test
        # path to test_dir needs to exist
        minioClient.fget_object(
            "doc-store-dev",
            doc_location,
            dest_file_location,
        )

    pass


def convert_html_table_to_2D_array(html_table):
    soup = BeautifulSoup(html_table, "html.parser")
    top = soup.find("table")["top"]
    left = soup.find("table")["left"]
    # Will there ever be multiple table headers?
    table_header = [th.text for th in soup.find_all("th")]
    table = [table_header] if len(table_header) else []
    table_row = []
    for tr in soup.find_all("tr"):
        table_cells = tr.find_all("td")
        if len(table_cells):
            table_row = []
            for td in table_cells:
                table_row.append(td.text)
        if len(table_row):
            table.append(table_row)
    return float(top), float(left), table


def collect_test_cases(workspace_id):
    ingestor_test_cases = db["ingestor_test_cases"].find({"workspace_id": workspace_id})
    test_case_dict = {}
    for test_case in ingestor_test_cases:
        document_id = test_case["document_id"]
        block_html = test_case["block_html"]
        page_idx, block_type, block_text = (
            test_case["page_idx"],
            test_case["block_type"],
            test_case["block_text"],
        )
        # if the text is a table convert
        top = 0
        left = 0
        if block_type == "table":
            top, left, block_text = convert_html_table_to_2D_array(
                block_html,
            )  # table as 2d array

        if document_id not in test_case_dict:
            # collect document info
            document = db["document"].find_one({"id": document_id})
            document_name = document["name"]  # filename
            document_title = document["title"]  # interpreted title
            doc_location = document["doc_location"]
            test_case_dict[document_id] = {
                "name": document_name,
                "title": document_title,
                "doc_location": doc_location,
            }
            if block_type == "table":
                test_case_dict[document_id]["test_case_list"] = [
                    ((page_idx, top, left), block_type, block_text),
                ]
            else:
                test_case_dict[document_id]["test_case_list"] = [
                    (page_idx, block_type, block_text),
                ]
        else:
            if block_type == "table":
                test_case_dict[document_id]["test_case_list"].append(
                    ((page_idx, top, left), block_type, block_text),
                )
            else:
                test_case_dict[document_id]["test_case_list"].append(
                    (page_idx, block_type, block_text),
                )

    return test_case_dict


# def run_test(test):
#     # test workspace_id
#     test_case_dict = collect_test_cases(test)
#     test_case_dict = get_tika_documents(test_case_dict, test_dir='dump')
#     test_case_dict = ingest_documents(test_case_dict, tika_documents='dump')
#     pass
#
#
# def run_all_tests():
#
#    pass


if __name__ == "__main__":
    test_case_dict = collect_test_cases("daebe892")
    print(test_case_dict)
    get_documents(test_case_dict)
    get_tika_documents(test_case_dict)
    total_blocks = ingest_documents(
        test_case_dict,
        tika_documents="test_dir/tika",
        ingested_document_dir="test_dir/ingest_output",
    )
    stats_dict = score_ingestor(total_blocks, test_case_dict)
    print(stats_dict)
