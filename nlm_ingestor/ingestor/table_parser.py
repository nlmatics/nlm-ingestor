import logging

import numpy as np
import pandas as pd


class TableParser:
    def __init__(self, infos):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.tables = {}
        self.two_column_table_idx = set()
        self.resolved_tables = set()

        if not infos:
            return

        table_infos = []
        table_start_idx = None
        for idx, info in enumerate(infos):
            if info.get("is_table_start", False) and not info.get("has_merged_cells", False):
                self.logger.debug(f"Found table start from match_idx:{idx}")
                table_start_idx = idx
                table_infos.append(info)
            elif table_start_idx is not None and info.get("is_table_end", False):
                table_infos.append(info)
                self.logger.debug(f"Table ends with match_idx:{idx}")
                # resolve table
                try:
                    df = self.resolve_table_from_infos(table_infos)
                    if isinstance(df, pd.DataFrame):
                        self.logger.info(
                            f"Found table at match_idx:{idx} of shape {df.shape}",
                        )
                        self.tables[table_start_idx] = df
                        if (
                            df.shape[1] == 1
                            and df.columns[0] == "_UNKNOWN_COLUMN_1_"
                            and df.index.name == "_UNKNOWN_COLUMN_0_"
                        ):
                            for info_idx in range(len(table_infos)):
                                self.two_column_table_idx.add(idx - info_idx)
                        self.resolved_tables.add(table_infos[0]["table_idx"])
                    else:
                        self.logger.error(
                            f"Found table at match_idx:{idx} but failed to parse\n{table_infos[:2]}",
                        )
                except Exception:
                    self.logger.error(
                        f"Failed to parse table:\n{table_infos[:2]}",
                        exc_info=True,
                    )

                # reset
                table_infos = []
                table_start_idx = None
            elif table_start_idx:
                table_infos.append(info)

    def resolve_table_from_infos(self, table_infos):

        # find column_names
        column_names = []
        cur_index = 0
        # process header_group and header to get column_names
        while cur_index < len(table_infos) and (table_infos[cur_index].get("is_header_group", False) or table_infos[
            cur_index
        ].get("is_header", False)):
            column_info = table_infos[cur_index]
            if "col_spans" in column_info:
                column_names.append([])
                for span_idx, span_width in enumerate(column_info["col_spans"]):
                    for i in range(span_width):
                        if len(column_names) > 0:
                            column_names[-1].append(column_info["cell_values"][span_idx])
            else:
                column_names.append(column_info["cell_values"])
            cur_index += 1

        if cur_index == len(table_infos):
            self.logger.error(f"No actual table rows other than headers.. skipping current table")
            return
        # only one level of column_name, flatten
        if len(column_names) == 1 and isinstance(column_names[0], list):
            column_names = column_names[0]

        # process table entry
        data = []
        multi_index = []
        max_width = 0
        cur_row_group_header = "_UNKNOWN_INDEX_"
        for info in table_infos[cur_index:]:
            # found row_group
            if info.get("is_row_group", False):
                cur_row_group_header = " ".join(info["cell_values"]).strip()
                continue
            # prevent bad parsing and table with no headers.
            max_width = max(max_width, len(info["cell_values"]))
            data.append([x.strip() or "" for x in info["cell_values"]])
            multi_index.append(cur_row_group_header)

        # expand the number of columns to max_width if needed.

        # table has no header, assuming it is single level table
        if len(column_names) == 0:
            for i in range(max_width):
                column_names.append(f"_UNKNOWN_COLUMN_{i}_")
        # table is single level, fill up missing column_names
        elif isinstance(column_names[0], str):
            i = 0
            for idx, column_name in enumerate(column_names):
                if not column_name.strip():
                    column_names[idx] = f"_UNKNOWN_COLUMN_{i}_"
                    i += 1
        # multi-level columns
        elif isinstance(column_names[0], list):
            for column_level in range(len(column_names)):
                diff = max_width - len(column_names[column_level])
                # column name longer than max_width, trim
                if diff < 0:
                    column_names[column_level] = column_names[column_level][:max_width]
                elif diff > 0:
                    for i in range(diff):
                        column_names[column_level].append("")

                # fill empty column name
                i = 0
                for idx, column_name in enumerate(column_names[column_level]):

                    if not column_name.strip():
                        # use previous column name for super level columns
                        if column_level < len(column_names) - 1 and column_names[
                            column_level
                        ][idx - 1].startswith("_UNKNOWN_COLUMN"):
                            column_names[column_level][idx] = column_names[
                                column_level
                            ][idx - 1]
                        else:
                            column_names[column_level][idx] = f"_UNKNOWN_COLUMN_{i}_"
                            i += 1
            merged_col_names = []

            i = 0
            for idx in range(len(column_names[0])):
                col_names_at_idx = []
                for col_level in range(len(column_names)):
                    col_name = column_names[col_level][idx]
                    col_names_at_idx.append(col_name if "_UNKNOWN_COLUMN" not in col_name else "")
                merged_col_names_at_idx = " ".join(col_names_at_idx)

                if not merged_col_names_at_idx:
                    merged_col_names_at_idx = f"_UNKNOWN_COLUMN_{i}_"
                    i += 1

                merged_col_names.append(merged_col_names_at_idx)
            column_names = merged_col_names
        try:
            # create df
            # print("creating tables with column names:", column_names)
            # print("data is:", data)
            df = pd.DataFrame(data, columns=column_names)

            # drop all None columns
            df = df.dropna(how="all", axis="columns").fillna("")
        except Exception as e:
            self.logger.error(f"Failed to create DataFrame. Please check ingestor. {e} \n"
                              f"col names:\n{column_names} \ndata:\n{data[0:3]}")
            return

        index_column = self.resolve_index(df)
        self.logger.debug(f"Column with idx:{index_column} is index")

        if len(set(multi_index)) > 1:
            df["_MULTI_INDEX_"] = multi_index
            if index_column is None:
                df = df.set_index("_MULTI_INDEX_")
            else:
                df = df.set_index(["_MULTI_INDEX_", df.columns[index_column]])
        else:

            if index_column is not None:
                df = df.set_index(df.columns[index_column])

        # # validate df
        # if not df.empty:
        #     # less than 50% of the entries contain data, invalid df
        #     if (
        #         df.replace(r"^\s*$", np.nan, regex=True).count().sum()
        #         < df.shape[0] * df.shape[1] * 0.5
        #     ):
        #         self.logger.info("50% entries is empty, skipping current table")
        #         return

        return df

    def resolve_index(self, df):
        # table has only one column, no index needed
        if len(df.columns) <= 1:
            return None

        unwanted_chars = ["$", "€", ",", "N/A", "%", "(", ")", "/"]
        shapes = []
        for column_idx in [0, -1]:
            column = df.columns[column_idx]
            column_value = df.iloc[:, column_idx].copy()
            for char in unwanted_chars:
                column_value = column_value.str.replace(char, "", regex=False)

            _shape = {
                "no_column_name": "_UNKNOWN_" in str(column),
                "number_column": pd.to_numeric(
                    column_value,
                    errors="coerce",
                )
                .dropna()
                .shape[0],
                "is_unique": column_value.unique().shape[0] <= 1,
                "is_duplicated": column_value.reset_index().duplicated().any(),
            }
            if column_idx == 0 and _shape["number_column"]:
                # Check whether we are dealing with a year column
                _shape["is_year_column"] = pd.to_numeric(
                    column_value,
                    errors="coerce",
                ).dropna().between(1900, 2500).all()

            shapes.append(_shape)

        first_column_impossible = False
        last_column_impossible = False

        # # column is unique, or duplicated when combine with existing, it must not be index
        # if shapes[0]["is_unique"] or shapes[0]["is_duplicated"]:
        #     self.logger.debug(f"First column has duplicates, it can not be an index")
        #     first_column_impossible = True

        # first column is number, it can not be an index only if the column is not an year value
        if shapes[0]["number_column"] and not shapes[0].get("is_year_column", False):
            self.logger.debug("First column is number, it can not be an index")
            first_column_impossible = True

        # # column is unique, or duplicated when combine with existing, it must not be index
        # if shapes[-1]["is_unique"] or shapes[-1]["is_duplicated"]:
        #     self.logger.debug(f"Last column has duplicates, it can not be an index")
        #     last_column_impossible = True

        # fist column is possible
        if first_column_impossible is False:
            # first column has no name, and other contain column name
            if shapes[0]["no_column_name"] and any(
                [x["no_column_name"] for x in shapes[1:]],
            ):
                self.logger.debug(
                    "First column has no name, and other contain column name",
                )
                return 0
            # first column has no number, and other contain numbers
            elif (
                shapes[0]["number_column"] == 0
                and max([x["number_column"] for x in shapes[1:]]) > 0
            ):

                self.logger.debug(
                    "First column has no number, and other contain numbers",
                )
                return 0

        # last column is possible
        if last_column_impossible is False:
            # last column has no name, and other contain column name
            if shapes[-1]["no_column_name"] and any(
                [x["no_column_name"] for x in shapes[:-1]],
            ):

                self.logger.debug(
                    "Last column has no name, and other contain column name",
                )
                return -1
            # last column has no number, and other contain numbers
            elif (
                shapes[-1]["number_column"] == 0
                and max([x["number_column"] for x in shapes[:-1]]) > 0
            ):
                self.logger.debug(
                    "Last column has no number, and other contain numbers",
                )
                return -1

        # default first column as index
        if not first_column_impossible:
            self.logger.debug("default first column as index")
            return 0
        else:
            return None

    def flatten_index_to_list(self, index_to_flatten):
        indexes = []
        for idx, index in enumerate(index_to_flatten.to_list()):
            if not index:
                continue
            # multi-level index
            if isinstance(index, tuple):
                for i in range(len(index)):
                    value = index[: i + 1]
                    if len(value) == 1 and not value[0].startswith("_UNKNOWN"):
                        indexes.append(value[0])
                    else:
                        indexes.append(value)
            else:
                indexes.append((idx, index))
        return indexes

    def create_es_index(self, df):
        es_index = []
        cell_texts = []
        index_name = ""
        if isinstance(df.index, pd.Index):
            name = str(df.index.name)
            if not name.startswith("_UNKNOWN"):
                index_name = name.strip()

        def process_index_name(texts):
            index = []
            for text in texts:
                if not isinstance(text, str) or text.startswith("_UNKNOWN"):
                    continue
                index.append(text.replace(":", "").strip())
            return index

        # create es record for rows
        cols = df.columns
        if isinstance(df.index, pd.MultiIndex) and all(isinstance(col, tuple) for col in df.columns):
            df.columns = [' '.join(col).strip() for col in df.columns]

        for idx, (index, row) in enumerate(df.iterrows()):
            if not isinstance(index, tuple):
                index = [index]
            else:
                index = index
            # remove inferred keys
            indexes = process_index_name(index)

            table_row = {
                "idx": idx,
                "index": [{"text": x} for x in indexes],
                "index_text": " ".join(indexes),
                "text": " ".join(indexes + row.values.tolist()),
                "type": "row",
            }
            table_row_index_text = table_row["index_text"]
            # Create the cell level data.
            for columnIndex, value in row.items():
                if not columnIndex.startswith("_UNKNOWN"):
                    if not index_name.startswith("("):
                        final_text = index_name + " " + table_row_index_text + " " + columnIndex + " " + value
                    else:
                        final_text = table_row_index_text + " " + columnIndex + " " + value + " " + index_name
                else:
                    if not index_name.startswith("("):
                        final_text = index_name + " " + table_row_index_text + " " + value
                    else:
                        final_text = table_row_index_text + " " + value + " " + index_name
                cell_texts.append(final_text.strip())

            es_index.append(table_row)
        df.columns = cols

        # create es record for columns
        for idx, (index, column) in enumerate(df.items()):
            # for column in df.columns:
            if not isinstance(index, tuple):
                index = [index]
            else:
                index = index

            indexes = process_index_name(index)

            table_column = {
                "idx": idx,
                "index": [{"text": x} for x in indexes],
                "index_text": " ".join(indexes),
                "text": " ".join(indexes + column.values.tolist()),
                "type": "col",
            }
            es_index.append(table_column)

        # create es record for index
        if isinstance(df.index, pd.RangeIndex):
            pass
        elif isinstance(df.index, pd.MultiIndex):
            for idx, name in enumerate(df.index.names):
                name = str(name)
                if "_UNKNOWN" not in name:
                    table_index = {
                        "idx": idx,
                        "index": [{"text": name}],
                        "index_text": name,
                        "text": name,
                        "type": "index",
                    }
                    es_index.append(table_index)
        elif isinstance(df.index, pd.Index):
            name = str(df.index.name)
            if not name.startswith("_UNKNOWN"):
                table_index = {
                    "idx": 0,
                    "index": [{"text": name}],
                    "index_text": name,
                    "text": name,
                    "type": "index",
                }
                es_index.append(table_index)

        return es_index, cell_texts
