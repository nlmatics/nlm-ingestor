import nlm_ingestor.ingestion_daemon.config as cfg
from nlm_ingestor.file_parser.parser_factory import FileParserFactory

pdf_file_parser = FileParserFactory.instance(
    "application/pdf", cfg.get_config("PDF_PARSER", "tika"),
)
html_file_parser = FileParserFactory.instance(
    "text/html", cfg.get_config("HTML_PARSER", "tika"),
)
