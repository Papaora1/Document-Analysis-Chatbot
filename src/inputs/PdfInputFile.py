from src.inputs.InputFile import InputFile, InputFileType


class PdfInputFile(InputFile):
    """
    A class representing a PDF input file.

    This class inherits from InputFile and provides additional functionality
    specific to PDF files, such as storing the content of individual pages.

    Attributes:
        name (str): The name of the PDF input file.
        path (str): The path to the PDF input file.
        pages (list): A list containing the content of each page of the PDF file.
    """

    def __init__(self, name: str, path: str, pages: list):
        """
        Initialize a PdfInputFile object.

        Args:
            name (str): The name of the PDF input file.
            path (str): The path to the PDF input file.
            pages (list): A list containing the content of each page of the PDF file.
        """
        super().__init__(input_file_type=InputFileType.PDF, name=name, path=path, data={"pages": pages})
