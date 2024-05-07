from src.inputs.InputFile import InputFileType, InputFile


class TextInputFile(InputFile):
    """
    A class representing a text input file.

    This class inherits from InputFile and provides additional functionality
    specific to text files, such as storing the text content.

    Attributes:
        name (str): The name of the text input file.
        path (str): The path to the text input file.
        pages (list[str]): The content of the text input file, split into pages.
    """

    def __init__(self, name: str, path: str, pages: list[str]):
        """
        Initialize a TextInputFile object.

        Args:
            name (str): The name of the text input file.
            path (str): The path to the text input file.
            pages (list[str]): The content of the text input file, split into pages.
        """
        super().__init__(input_file_type=InputFileType.TEXT, name=name, path=path, data={"pages": pages})
