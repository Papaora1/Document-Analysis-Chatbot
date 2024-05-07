from abc import ABC, abstractmethod
from src.inputs.InputFile import InputFile


class Loader(ABC):
    """
    An abstract base class for file loaders.

    This class defines an interface for loading files and provides
    a method for loading a single file, which subclasses must implement.

    Attributes:
        None
    """

    @staticmethod
    @abstractmethod
    def load_single_file(file_path: str) -> InputFile:
        """
        Load a single file and return an InputFile object.

        This method must be implemented by subclasses.

        Args:
            file_path (str): The path to the file.

        Returns:
            InputFile: An object representing the loaded file.

        Raises:
            FileNotFoundError: If the specified file_path does not exist.
        """
        pass
