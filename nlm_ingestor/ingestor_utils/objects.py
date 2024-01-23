from dataclasses import dataclass  # noreorder

from typing import Any
from typing import List


@dataclass
class DocumentData:
    file_idx: str
    filename: str
    sents_texts: List[Any]
    sents_infos: List[Any]
    sents_embeddings: List[Any]
    sents_is_table_row: List[Any]
    sents_bm25_stats: List[Any]
    blocks_texts: List[Any]
    blocks_infos: List[Any]
    blocks_embeddings: List[Any]
    blocks_bm25_stats: List[Any]
    blocks_is_table_row: List[Any]
