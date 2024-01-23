class FileParser:
    """Interface for FileConverter implementations"""

    def convert_to_html(self, file_path):
        raise NotImplementedError()

    def convert_to_text(self, file_path):
        raise NotImplementedError()
