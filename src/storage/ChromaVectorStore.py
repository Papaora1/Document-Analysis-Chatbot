from langchain_core.documents import Document
from src.inputs.InputFile import InputFile, InputFileType
from src.storage.VectorStore import VectorStore, VectorStoreOptions
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings
from src.cfg.logging_config import *


class ChromaVectorStore(VectorStore):
    """
    A class representing a Chroma vector store.

    This class extends VectorStore and provides specific functionality for storing
    and retrieving documents using the Chroma vector store.

    Attributes:
        vector_store (Chroma): The Chroma vector store.
    """

    def __init__(self, embeddings: Embeddings):
        """
        Initialize a ChromaVectorStore object.

        Args:
            embeddings (Embeddings): The embeddings used by the vector store.
        """
        super().__init__(vector_store_type=VectorStoreOptions.CHROMA, embeddings=embeddings)
        self.vector_store = Chroma(embedding_function=embeddings)

    def add_document(self, input_file: InputFile) -> None:
        """
        Add a document to the Chroma vector store.

        Args:
            input_file (InputFile): InputFile containing the document to be added.

        Returns:
            None
        """
        input_file_type = input_file.input_file_type

        new_docs = []
        if input_file_type == InputFileType.PDF:
            pdf_title = input_file.name
            pages = input_file.data.get("pages")

            for i in range(len(pages)):
                page = pages[i]
                new_docs.append(
                    Document(text=page, page_content=page, metadata={"title": pdf_title, "page_number": i + 1}))
        elif input_file_type == InputFileType.TEXT:
            text_title = input_file.name
            pages = input_file.data.get("pages")

            for i in range(len(pages)):
                page = pages[i]
                new_docs.append(
                    Document(text=page, page_content=page, metadata={"title": text_title, "page_number": i + 1}))
        else:
            logger.error("Unexpected InputFileType {}", input_file.path)
            raise ValueError("Unsupported file format {}", input_file.path)

        logger.info("Successfully added {} to Chroma Vector Store", input_file.name)
        self.vector_store.add_documents(new_docs)

    def as_retriever(self):
        """
        Convert the Chroma vector store to a retriever.

        Returns:
            ChromaRetriever: The retriever representation of the Chroma vector store.
        """
        return self.vector_store.as_retriever()
