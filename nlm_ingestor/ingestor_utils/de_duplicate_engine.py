import logging
import os
from collections import defaultdict

import numpy as np
from nlm_utils.model_client import EncoderClient


class DeDuplicateEngine:
    def __init__(self, settings, threshold=0.9):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.logger.info(
            f"Initing Duplicated Detection Engine with settings {settings}",
        )

        self.inited = False
        self.threshold = threshold
        self.encoder = EncoderClient(
            model="sif",
            url=os.getenv("MODEL_SERVER_URL", "https://services.nlmatics.com"),
        )
        if not settings:
            self.logger.info(
                "No settings provided, Duplicated Detection Engine not inited ",
            )
            return

        # build embeddings for ignore_block
        self.embeddings = defaultdict(list)
        self.settings = defaultdict(list)
        for setting in settings:
            self.embeddings[setting["level"]].append(setting["text"])
            self.settings[setting["level"]].append(setting)

        # convert text to embeddings
        for level, texts in self.embeddings.items():
            self.embeddings[level] = self.encoder(texts)["embeddings"]
        self.inited = True

    def check_duplicate(self, embeddings={}):
        report = {"is_duplicated": False, "ignore_all_after": False}
        # engine not inited with settings, return False
        if not self.inited:
            return report

        assert len(embeddings) > 0, ValueError("Both text and text_emb are None")
        for level, embedding in embeddings.items():
            # level has no settings, return False
            if level not in self.embeddings:
                continue

            scores = np.dot(self.embeddings[level], embedding)
            most_similar_idx = np.argmax(scores)
            if scores[most_similar_idx] > self.threshold:
                self.logger.info(
                    f"found duplicate with score: {scores[most_similar_idx]}, settings: {self.settings[level][most_similar_idx]}",
                )
                report["is_duplicated"] = True
                report["ignore_all_after"] = (
                    report["ignore_all_after"]
                    or self.settings[level][most_similar_idx]["ignore_all_after"]
                )
        # nothing matched, return False
        return report
