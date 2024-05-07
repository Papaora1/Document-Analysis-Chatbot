import unittest
import os
from src.model.QuestionAnswerModel import QuestionAnswerModel, EmbeddingsOptions, ChainOptions, \
    LanguageModelOptions
from src.parsers.FileParser import FileParser
from src.storage.VectorStore import VectorStoreOptions
from src.cfg.logging_config import *
from src.cfg.config import *


class TestQuestionAnswerModel(unittest.TestCase):
    def setUp(self):
        self.model = QuestionAnswerModel(EmbeddingsOptions.DEFAULT, ChainOptions.DEFAULT, VectorStoreOptions.DEFAULT,
                                         LanguageModelOptions.DEFAULT)
        self.docs = FileParser.parse_directory("../data/bumble_documents")

        for doc in self.docs:
            self.model.add_document(doc)

    def test_ask_question(self):

        question = "How much did Bumble revenue grow?"
        answer = self.model.ask(question)
        logger.info("Question: {}", question)
        logger.info("Answer: {}", answer)

        question = "What are Bumble’s key investment highlights and weaknesses?"
        answer = self.model.ask(question)
        logger.info("Question: {}", question)
        logger.info("Answer: {}", answer)

        question = "How are latest industry trends affecting Bumble?"
        answer = self.model.ask(question)
        logger.info("Question: {}", question)
        logger.info("Answer: {}", answer)

        question = "What are 10 takeaways from Bumble’s equity research PDFs?"
        answer = self.model.ask(question)
        logger.info("Question: {}", question)
        logger.info("Answer: {}", answer)

        question = "What are 10 takeaways about Bumble from Tegus expert call transcripts?"
        answer = self.model.ask(question)
        logger.info("Question: {}", question)
        logger.info("Answer: {}", answer)


if __name__ == '__main__':
    unittest.main()
