import os
import PyPDF2

from src.inputs.PdfInputFile import PdfInputFile
from src.inputs.InputFile import InputFile
from src.loaders.Loader import Loader
from src.cfg.logging_config import *


class PdfLoader(Loader):
    """
    A class for loading PDF files and creating PdfInputFile objects.

    Attributes:
        None
    """

    @staticmethod
    def load_single_file(file_path: str) -> InputFile:
        """
        Load a single PDF file and create a PdfInputFile object.

        Args:
            file_path (str): The path to the PDF file.

        Returns:
            PdfInputFile: An object representing the loaded PDF file.

        Raises:
            FileNotFoundError: If the specified file_path does not exist.
        """
        with open(file_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            pdf_title = os.path.basename(file_path)
            pages = []
            for page_num in range(len(pdf_reader.pages)):
                page_content = pdf_reader.pages[page_num].extract_text()
                pages.append(page_content)

            logger.info("Successfully read {} to PdfInputFile object", pdf_title)
            return PdfInputFile(name=pdf_title, path=file_path, pages=pages)
