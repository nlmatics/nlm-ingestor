from typing import List


class Block:
    def __init__(
        self,
        block_text: str = None,
        block_sents: List[str] = None,
        block_type: str = None,
        header_block_idx: int = None,
        header_text: str = None,
    ):
        self._block_text = block_text
        self._block_sents = block_sents
        self._block_type = block_type
        self._header_block_idx = header_block_idx
        self._header_text = header_text
        self.swagger_types = {
            "id": str,
            "block_text": str,
            "block_sents": List[str],
            "block_type": str,
            "header_block_idx": int,
            "header_text": str,
        }

    @property
    def block_text(self) -> str:
        return self._block_text

    @block_text.setter
    def block_text(self, block_text):
        self._block_text = block_text

    @property
    def block_sents(self) -> List[str]:
        return self._block_sents

    @block_sents.setter
    def block_sents(self, block_sents):
        self._block_sents = block_sents

    @property
    def block_type(self) -> str:
        return self._block_type

    @block_type.setter
    def block_type(self, block_type):
        self._block_type = block_type

    @property
    def header_block_idx(self) -> int:
        return self._header_block_idx

    @header_block_idx.setter
    def header_block_idx(self, header_block_idx):
        self._header_block_idx = header_block_idx

    @property
    def header_text(self) -> str:
        return self._header_text

    @header_text.setter
    def header_text(self, header_text):
        self._header_text = header_text

    def to_dict(self):
        """Returns the model properties as a dict

        :rtype: dict
        """
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(
                    map(lambda x: x.to_dict() if hasattr(x, "to_dict") else x, value),
                )
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(
                    map(
                        lambda item: (item[0], item[1].to_dict())
                        if hasattr(item[1], "to_dict")
                        else item,
                        value.items(),
                    ),
                )
            else:
                result[attr] = value

        return result
