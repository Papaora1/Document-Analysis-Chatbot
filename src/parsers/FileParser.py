import os
from src.loaders.PdfLoader import PdfLoader
from src.loaders.TextLoader import TextLoader
from src.inputs.InputFile import InputFile
from src.cfg.logging_config import *


class FileParser:
    """
    A class for parsing files and directories to create InputFile objects.

    This class provides methods for parsing individual files and entire directories,
    generating InputFile objects based on their file type.

    Attributes:
        None
    """

    @staticmethod
    def parse_file(file_path) -> InputFile:
        """
        Parse a single file and create an InputFile object.

        Args:
            file_path (str): The path to the file.

        Returns:
            InputFile: An object representing the parsed file.

        Raises:
            ValueError: If the file format is unsupported.
        """
        if file_path.endswith(".pdf"):
            return PdfLoader.load_single_file(file_path)
        elif file_path.endswith(".txt"):
            return TextLoader.load_single_file(file_path)
        else:
            raise ValueError("Unsupported file format")

    @staticmethod
    def parse_directory(directory_path) -> list[InputFile]:
        """
        Parse all files in a directory and create InputFile objects for each file.

        Args:
            directory_path (str): The path to the directory.

        Returns:
            list[InputFile]: A list of InputFile objects representing the parsed files.
        """
        parsed_files = []
        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)
            if os.path.isfile(file_path):
                parsed_file = FileParser.parse_file(file_path)
                parsed_files.append(parsed_file)
        logger.info("Successfully parse files in {} to InputFile objects", directory_path)
        return parsed_files
