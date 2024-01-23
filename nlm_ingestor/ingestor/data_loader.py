import pandas as pd
from nlm_ingestor.ingestor import processors
from nlm_ingestor.ingestor_utils.utils import sent_tokenize

from nlm_ingestor.ingestor.visual_ingestor import block_renderer
from nlm_ingestor.ingestor_utils.ing_named_tuples import LineStyle


class DataRowFileInfo:

    def __init__(self, row, col_names, filename_col, title_col_range):
        self.row = row
        self.title_col_range = title_col_range
        self.filename_col = filename_col
        self.filename = row[col_names[filename_col]]
        self.title = ""
        self.blocks = []
        self.col_names = col_names
        self.line_style_classes = {}
        self.class_levels = {}
        self.add_styles()
        self.make_blocks()
        br = block_renderer.BlockRenderer(self)
        self.html_str = br.render_html()
        self.json_dict = br.render_json()

    def make_blocks(self):
        block_idx = 0
        blocks = []
        self.title = " ".join(map(str, self.row[self.title_col_range[0]:self.title_col_range[1]]))
        title_block = {
            "block_idx": block_idx,
            "page_idx": 0,
            "block_text": self.title,
            "block_type": "header",
            "block_class": "nlm-text-title",
            "level": 0,
        }
        blocks.append(title_block)
        block_idx = block_idx + 1
        for col_name in self.col_names:
            header_text = " ".join(col_name.split("_"))
            header_block = {
                "block_idx": block_idx,
                "page_idx": 0,
                "block_text": header_text,
                "block_type": "header",
                "block_class": "nlm-text-header",
                "header_block_idx": 0,
                "level": 1,
            }
            blocks.append(header_block)
            block_idx = block_idx + 1
            col_val = str(self.row[col_name])
            lines = col_val.split("\n")
            col_blocks = processors.clean_lines(lines)
            for block in col_blocks:
                block["header_text"] = header_text
                block["level"] = 2
                block["block_idx"] = block_idx
                block["page_idx"] = 0
                block["block_sents"] = sent_tokenize(block["block_text"])
                block["block_class"] = "nlm-text-body",
                block["level_chain"] = [self.title, header_text] if self.title else [header_text]
                if len(col_blocks) == 1:
                    block["block_type"] = "para"
                block_idx = block_idx + 1
                blocks.append(block)
        self.blocks = blocks

    def add_styles(self):
        title_style = LineStyle(
            "Roboto, Georgia, serif",
            "bold",
            14.0,
            "500",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[title_style] = 'nlm-text-title'
        self.class_levels['nlm-text-title'] = 0
        header_style = LineStyle(
            "Roboto, Georgia, serif",
            "normal",
            12.0,
            "600",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[header_style] = 'nlm-text-header'
        self.class_levels['nlm-text-header'] = 1
        para_style = LineStyle(
            "Roboto, Georgia, serif",
            "normal",
            10.0,
            "400",
            "left",
            0,  # TODO: Decide what font_space_width needs to be added
            "left"
        )
        self.line_style_classes[para_style] = 'nlm-text-body'
        self.class_levels['nlm-text-body'] = 2


class DataLoader:

    def __init__(self, file_name, filename_col=1, title_col_range=[1, 3]):
        if file_name.endswith(".csv"):
            self.df = pd.read_csv(file_name)
        else:
            self.df = pd.read_excel(file_name, engine='openpyxl')
        self.df = self.df.fillna('N/A')
        self.title_col_range = title_col_range
        self.filename_col = filename_col
        self.data_row_file_infos = []
        self.parse_data_row_file_infos()

    def parse_data_row_file_infos(self):
        if self.title_col_range[0] > len(self.df.columns) or self.title_col_range[0] < 0:
            self.title_col_range[0] = 0
            self.title_col_range[1] = 2
        else:
            self.title_col_range[0] = self.title_col_range[0] - 1
            self.title_col_range[1] = self.title_col_range[1] - 1
        if self.filename_col > len(self.df.columns) or self.filename_col < 0:
            self.filename_col = 0
        else:
            self.filename_col = self.filename_col - 1

        for index, row in self.df.iterrows():
            print("processing row: ", index)
            row_file_info = DataRowFileInfo(row=row,
                                            col_names=self.df.columns,
                                            filename_col=self.filename_col,
                                            title_col_range=self.title_col_range)
            self.data_row_file_infos.append(row_file_info)
