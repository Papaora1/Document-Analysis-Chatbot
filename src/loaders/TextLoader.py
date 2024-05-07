import os
from src.inputs.TextInputFile import TextInputFile
from src.inputs.InputFile import InputFile
from src.loaders.Loader import Loader
import nltk
from src.cfg.logging_config import *


class TextLoader(Loader):
    """
    A class for loading text files and creating TextInputFile objects.

    Attributes:
        None
    """

    @staticmethod
    def load_single_file(file_path: str) -> InputFile:
        """
        Load a single text file and create a TextInputFile object.

        Args:
            file_path (str): The path to the text file.

        Returns:
            TextInputFile: An object representing the loaded text file.

        Raises:
            FileNotFoundError: If the specified file_path does not exist.
        """
        with open(file_path, "r") as file:
            text = file.read()
            text_title = os.path.basename(file_path)
            pages = TextLoader.chunk_text(text)

            logger.info("Successfully read {} to TextInputFile object", text_title)
            return TextInputFile(name=text_title, path=file_path, pages=pages)

    @staticmethod
    def chunk_text(text, max_chunk_length=5000):
        """
        Split text into chunks of roughly equal lengths without cutting off words or sentences.

        Args:
            text (str): The input text to be chunked.
            max_chunk_length (int): The maximum length of each chunk.

        Returns:
            list[str]: A list of text chunks.
        """
        # Initialize NLTK sentence tokenizer
        # TODO: Could probably do this somewhere else
        nltk.download('punkt')
        tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')

        # Tokenize text into sentences
        sentences = tokenizer.tokenize(text)

        # Initialize chunk list
        chunks = []
        current_chunk = ""

        # Iterate through sentences and group them into chunks
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= max_chunk_length:
                current_chunk += sentence + " "
            else:
                # If adding the sentence exceeds max_chunk_length, start a new chunk
                chunks.append(current_chunk.strip())
                current_chunk = sentence + " "

        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks
