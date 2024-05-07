from enum import Enum
from langchain_core.embeddings import Embeddings
from langchain.chains.base import Chain
from langchain_core.language_models import BaseLanguageModel
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain_openai import OpenAIEmbeddings
from src.inputs.InputFile import InputFile
from src.storage.ChromaVectorStore import ChromaVectorStore
from src.storage.VectorStore import VectorStore, VectorStoreOptions
from src.cfg.logging_config import *


class EmbeddingsOptions(Enum):
    """
    An enumeration representing options for embeddings.

    Attributes:
        CHAT_GPT (str): Represents Chat GPT embeddings.
        DEFAULT (str): Represents the default embeddings.
    """
    CHAT_GPT = "Chat GPT"
    DEFAULT = "Default"


class ChainOptions(Enum):
    """
    An enumeration representing options for chains.

    Attributes:
        RetrievalQA (str): Represents the RetrievalQA chain.
        DEFAULT (str): Represents the default chain.
    """
    RetrievalQA = "RetrievalQA"
    DEFAULT = "Default"


class LanguageModelOptions(Enum):
    """
    An enumeration representing options for language models.

    Attributes:
        GPT_3_5_TURBO (str): Represents the GPT-3.5-turbo language model.
        DEFAULT (str): Represents the default language model.
    """
    GPT_3_5_TURBO = "gpt-3.5-turbo"
    DEFAULT = "Default"


class QuestionAnswerModel:
    """
    A class representing a question-answer model.

    This class allows for easy configuration and usage of a question-answer system,
    including options for embeddings, chains, language models, and vector stores.

    Attributes:
        embeddings (Embeddings): The embeddings used by the model.
        vector_store (VectorStore): The vector store used by the model.
        vector_store_type (VectorStoreOptions): The type of the vector store.
        language_model (BaseLanguageModel): The language model used by the model.
        chain (Chain): The chain used by the model.
    """

    def __init__(
            self,
            embeddings: EmbeddingsOptions,
            chain: ChainOptions,
            vector_store: VectorStoreOptions,
            language_model: LanguageModelOptions
    ):
        """
        Initialize a QuestionAnswerModel object.

        Args:
            embeddings (EmbeddingsOptions): The embeddings option for the model.
            chain (ChainOptions): The chain option for the model.
            vector_store (VectorStoreOptions): The vector store option for the model.
            language_model (LanguageModelOptions): The language model option for the model.
        """
        self.embeddings = self.initialize_embeddings(embeddings)
        self.vector_store = self.initialize_vector_store(vector_store)
        self.vector_store_type = vector_store
        self.language_model = self.initialize_language_model(language_model)
        self.chain = self.initialize_chain(chain)

    @staticmethod
    def initialize_embeddings(embeddings: EmbeddingsOptions) -> Embeddings:
        """
        Initialize embeddings based on the selected option.

        Args:
            embeddings (EmbeddingsOptions): The embeddings option.

        Returns:
            Embeddings: The initialized embeddings.
        """
        if embeddings == EmbeddingsOptions.CHAT_GPT:
            return OpenAIEmbeddings()
        else:
            return OpenAIEmbeddings()

    def initialize_vector_store(self, vector_store: VectorStoreOptions) -> VectorStore:
        """
        Initialize a vector store based on the selected option.

        Args:
            vector_store (VectorStoreOptions): The vector store option.

        Returns:
            VectorStore: The initialized vector store.
        """
        if vector_store == VectorStoreOptions.CHROMA:
            return ChromaVectorStore(self.embeddings)
        else:
            return ChromaVectorStore(self.embeddings)

    @staticmethod
    def initialize_language_model(language_model: LanguageModelOptions) -> BaseLanguageModel:
        """
        Initialize a language model based on the selected option.

        Args:
            language_model (LanguageModelOptions): The language model option.

        Returns:
            BaseLanguageModel: The initialized language model.
        """
        if language_model == LanguageModelOptions.GPT_3_5_TURBO:
            return ChatOpenAI(model_name="gpt-3.5-turbo")
        else:
            return ChatOpenAI(model_name="gpt-3.5-turbo")

    def initialize_chain(self, chain: ChainOptions) -> Chain:
        """
        Initialize a chain based on the selected option.

        Args:
            chain (ChainOptions): The chain option.

        Returns:
            Chain: The initialized chain.
        """
        if chain == ChainOptions.RetrievalQA:
            return RetrievalQA.from_chain_type(self.language_model, retriever=self.vector_store.as_retriever())
        else:
            return RetrievalQA.from_chain_type(self.language_model, retriever=self.vector_store.as_retriever())

    def add_document(self, input_file: InputFile) -> None:
        """
        Add a document to the model.

        Args:
            input_file (InputFile): InputFile containing the document to be added.

        Returns:
            None
        """
        self.vector_store.add_document(input_file)
        self.chain.retriever = self.vector_store.as_retriever()

    def ask(self, question: str) -> str:
        """
        Ask a question and get the answer from the model.

        Args:
            question (str): The question to ask.

        Returns:
            str: The answer to the question.
        """
        logger.info("Model received question: {}", question)
        answer = self.chain.invoke(question).get("result")
        logger.info("Model return answer: {}", answer)
        return answer
