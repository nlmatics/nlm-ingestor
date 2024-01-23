import logging
import re
from statistics import mode

import nltk
import numpy as np

from . import processors_utils

# dash = re.compile(r'^\-+$')
dash = re.compile(r"^\-+\$*$")
numeric = re.compile(r"^[\-\(\$\%]*\d[\d\.\,]*[\$\%\)]*$")
answer_list = ["yes", "no"]
na_list = ["NA", "N/A"]


def check_number_type(num):
    dollar = (
        re.search(r"^[\(]*\$\d[\d\.\,)]*$", num) is not None
        or re.search(r"^[\(]*\d[\d\.\,)]*\$$", num) is not None
    )
    percentage = (
        re.search(r"^[\(]*\%\d[\d\.\,)]*$", num) is not None
        or re.search(r"^[\(]*\d[\d\.\,)]*\%$", num) is not None
    )
    if dollar:
        return "dollar"
    if percentage:
        return "percent"
    else:
        return "num"


def construct_table(table):
    if type(table) == list:
        outstr = "<table class='nlm_content_table'>"
        for row in table:
            outstr += "<tr>"
            for cell in row:
                outstr += "<td>" + cell + "</td>"
            outstr += "</tr>"
    else:
        return "<p>" + "\n" + table + "\n" + "</p> "
    return outstr + "</table>"


def get_row1(row):
    orignal_row = row
    words = row.split(" ")
    cells = []
    try:
        row = processors_utils.super_replace(row, ["(", ")", ",", "$", "%"], "")
        tags = nltk.pos_tag(list(filter(None, row.split(" "))))
    except Exception as e:
        logging.error(e)
        return [orignal_row]  # ""
    strn = ""
    for i in range(len(tags)):
        # previous check
        tag = tags[i][1]
        word = words[i].lstrip().rstrip()
        proc_word = processors_utils.super_replace(word, ["(", ")", ",", "$", "%"], "")
        if len(word) & len(proc_word.replace(" ", "")):
            # print(proc_word)
            start_tag = nltk.pos_tag(proc_word[0])[0][1]
            end_tag = nltk.pos_tag(proc_word[-1])[0][1]
        else:
            start_tag = "CD"
            end_tag = "CD"

        if ((tag == "CD") | (tag == ":")) and (
            (tag == ":") | ((start_tag == "CD") and (end_tag == "CD"))
        ):
            cells.append(strn.strip())
            cells.append(word.lstrip().rstrip())
            strn = ""
        elif (
            ((start_tag == "CD") and (end_tag == "CD")) & (word != "$") & (word == "%")
        ):
            cells.append(strn.strip())
            cells.append(word.lstrip().rstrip())
        else:
            strn += word.lstrip().rstrip() + " "
    if type(cells) == str:
        cells = [cells]
    return cells


# tokens
numeric = re.compile(r"^[\-\(\$\%]*\d[\d\.\,]*[\$\%\)]*$")
dash = re.compile(r"^\-+\$*$")
answer_list = ["yes", "no"]
na_list = ["NA", "N/A"]


def get_row(row):
    row = re.sub(r"(a-zA-Z) +\- +(a-zA-Z)", r"\1-\2", row)
    row = re.sub(r" \$ ", " $", row)
    # row = re.sub(r'(\d[\d\.\,\%\$]+)\s\/\s(\d[\d\.\,\%\$]+)$' , r'\1/\2',row)
    words = row.split(" ")
    row_list = []
    str_buff = ""
    prev_type = ""
    unit_list = []
    for word in words:
        colon_rule = word[-1] == ":"
        if word == "of" and len(row_list) and prev_type != "str":
            str_buff += row_list.pop()
            unit_list.pop()

        if numeric.search(word) is not None:
            if prev_type == "str":
                row_list.append(str_buff.strip())
                str_buff = ""
                unit_list.append("str")
            row_list.append(word)
            prev_type = "num"
            unit_list.append(check_number_type(word))

        elif word.lower() in answer_list:
            if prev_type == "str":
                row_list.append(str_buff.strip())
                unit_list.append("str")
                str_buff = ""
            row_list.append(word)
            prev_type = "yes_no"
            unit_list.append("yes_no")

        elif dash.search(word) is not None:
            if prev_type == "str":
                row_list.append(str_buff.strip())
                unit_list.append("str")
                str_buff = ""
            row_list.append(word)
            prev_type = "-"
            unit_list.append("any")

        elif word in na_list:
            if prev_type == "str":
                row_list.append(str_buff.strip())
                unit_list.append("str")
                str_buff = ""
            row_list.append(word)
            prev_type = "na"
            unit_list.append("any")

        elif colon_rule:
            if prev_type == "str":
                row_list.append(str_buff.strip() + " " + word)
                unit_list.append("str")
                str_buff = ""
            else:
                row_list.append(str_buff.strip())
                unit_list.append("str")
                str_buff = ""
        else:
            str_buff += " " + word
            prev_type = "str"

    if len(str_buff):
        row_list.append(str_buff.strip())
        unit_list.append("str")

    return row_list  # , ", ".join(unit_list)


def group_tables(table_indexes):
    table = []
    tables = []
    table.append(table_indexes[0])  # add first table
    for i in range(len(table_indexes)):
        if i + 1 > len(table_indexes) - 1:
            break  # no more tables to read

        if (table_indexes[i + 1] - table_indexes[i]) == 1:
            table.append(table_indexes[i + 1])

        elif len(table):
            tables.append(np.array(table))
            table = [table_indexes[i + 1]]
    return tables


def format_tables(blocks_df):
    # columns block_text	block_sents	block_type
    # identify all tables in df
    table_indexes = blocks_df[blocks_df.block_type == "table_row"].index

    # if none are found
    if len(table_indexes) == 0:
        return blocks_df

    # group tables
    tables = group_tables(table_indexes)

    invalid = []
    idx = []
    for i in range(len(tables)):
        if len(tables[i]) < 2:
            invalid.append(i)
        else:
            idx.append(i)

    if len(invalid):
        blocks_df.loc[
            np.concatenate(np.array(tables)[np.array(invalid)], axis=0), "block_type",
        ] = "para"
    table_rows = blocks_df[blocks_df.block_type == "table_row"]
    table_list = []
    # print(table_rows)
    for table_idx in idx:
        table_idx = tables[table_idx]
        # print(table_rows.loc[table_idx].values,"\n")
        table = []
        for row_idx, row in table_rows.loc[table_idx].iterrows():
            table += [list(filter(None, get_row(row["block_text"].rstrip())))]

        # check if table is uniform
        table_cell_counts = []
        if len(table) and (len(table[0])):
            table_cell_counts = [len(row) for row in table]
            try:
                cell_count = mode(table_cell_counts)
            except Exception as e:
                logging.error(e)
                cell_count = min(table_cell_counts)
            # non uniform row
            if (sum(table_cell_counts) % len(table[0])) and (cell_count):
                new_table = []
                for row in table:
                    # multiple rows in row
                    if (len(row) > cell_count) and (len(row) % cell_count == 0):
                        rows = int(len(row) / cell_count)
                        for new_row in range(rows):
                            new_row += 1
                            new_table_row = row[
                                new_row * cell_count - cell_count : new_row * cell_count
                            ]
                            new_table.append(new_table_row)
                    else:
                        new_table.append(row)
                table_list.append(new_table)
            else:
                table_list.append(table)
        else:
            table_list.append(table)
    replace = []
    # check for valid tables

    if len(idx):
        for i in np.array(tables)[np.array(idx)]:
            replace.append(i)
        for i in range(len(replace)):
            blocks_df = blocks_df.drop(replace[i])
            blocks_df.loc[replace[i][0]] = {
                "block_type": "table",
                "block_sents": table_list[i],
                "block_text": table_list[i],
            }
        return blocks_df.sort_index().reset_index(drop=True)
    else:
        return blocks_df
