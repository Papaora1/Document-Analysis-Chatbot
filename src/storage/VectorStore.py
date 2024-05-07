from enum import Enum

from langchain_core.vectorstores import VectorStoreRetriever
from src.inputs.InputFile import InputFile
from langchain_core.embeddings import Embeddings


class VectorStoreOptions(Enum):
    """
    An enumeration representing options for vector store types.

    Attributes:
        CHROMA (str): Represents the Chroma vector store.
        DEFAULT (str): Represents the default vector store.
    """
    CHROMA = "Chroma"
    DEFAULT = "Default"


class VectorStore:
    """
    A base class representing a vector store.

    This class defines an interface for vector stores and provides methods
    for adding documents and converting the vector store to a retriever.

    Attributes:
        vector_store_type (VectorStoreOptions): The type of the vector store.
        embeddings (Embeddings): The embeddings used by the vector store.
    """

    def __init__(
            self,
            vector_store_type: VectorStoreOptions,
            embeddings: Embeddings
    ):
        """
        Initialize a VectorStore object.

        Args:
            vector_store_type (VectorStoreOptions): The type of the vector store.
            embeddings (Embeddings): The embeddings used by the vector store.
        """
        self.vector_store_type = vector_store_type
        self.embeddings = embeddings

    def add_document(self, input_file: InputFile) -> None:
        """
        Add a document to the vector store.

        This method must be implemented by subclasses.

        Args:
            input_file (InputFile): InputFile containing the document to be added.

        Returns:
            None
        """
        raise NotImplementedError("add_document method must be implemented in subclasses")

    def as_retriever(self) -> VectorStoreRetriever:
        """
        Convert the vector store to a retriever.

        This method must be implemented by subclasses.

        Returns:
            VectorStoreRetriever: The retriever representation of the vector store.
        """
        raise NotImplementedError("as_retriever method must be implemented in subclasses")
