import logging

import nlm_ingestor.ingestion_daemon.config as cfg

logger = logging.getLogger(__name__)
logger.setLevel(cfg.log_level())


class FileParserFactory:
    """Factory for parser instances for various formats"""

    __instance = dict()
    supported_implementations = {"application/pdf": ["tika"], "text/html": ["tika"]}

    @classmethod
    def instance(cls, format, impl):
        if impl not in FileParserFactory.supported_implementations[format]:
            raise Exception(f"unknown implementation {impl} for file format {format}")
        if format not in FileParserFactory.__instance:
            if impl == "tika":
                # logger.info("tika pasers")
                from nlm_ingestor.file_parser.tika_parser import TikaFileParser

                FileParserFactory.__instance[format] = TikaFileParser()
        return FileParserFactory.__instance[format]
