from abc import ABC
from enum import Enum


class InputFileType(Enum):
    """
    An enumeration representing types of input files.

    Attributes:
        TEXT (str): Represents a text file.
        PDF (str): Represents a PDF file.
        UNKNOWN (str): Represents an unknown file type.
    """
    TEXT = "text"
    PDF = "pdf"
    UNKNOWN = "unknown"


class InputFile(ABC):
    """
    An abstract base class representing an input file.

    This class defines attributes for storing information about an input file,
    including its type, name, path, and additional data.

    Attributes:
        input_file_type (InputFileType): The type of the input file.
        name (str): The name of the input file.
        path (str): The path to the input file.
        data (dict): Additional data associated with the input file.
    """

    def __init__(self, input_file_type: InputFileType, name: str, path: str, data: dict):
        """
        Initialize an InputFile object.

        Args:
            input_file_type (InputFileType): The type of the input file.
            name (str): The name of the input file.
            path (str): The path to the input file.
            data (dict): Additional data associated with the input file.
        """
        self.__input_file_type = input_file_type
        self.__name = name
        self.__path = path
        self.__data = data

    @property
    def input_file_type(self) -> InputFileType:
        """
        Get the type of the input file.
        """
        return self.__input_file_type

    @input_file_type.setter
    def input_file_type(self, value: InputFileType):
        """
        Set the type of the input file.
        """
        self.__input_file_type = value

    @property
    def name(self) -> str:
        """
        Get the name of the input file.
        """
        return self.__name

    @name.setter
    def name(self, value: str):
        """
        Set the name of the input file.
        """
        self.__name = value

    @property
    def path(self) -> str:
        """
        Get the path to the input file.
        """
        return self.__path

    @path.setter
    def path(self, value: str):
        """
        Set the path to the input file.
        """
        self.__path = value

    @property
    def data(self) -> dict:
        """
        Get additional data associated with the input file.
        """
        return self.__data

    @data.setter
    def data(self, value: dict):
        """
        Set additional data associated with the input file.
        """
        self.__data = value
