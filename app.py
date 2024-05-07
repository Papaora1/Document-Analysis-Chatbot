from flask import Flask, request, jsonify
from flask_cors import CORS
from src.model.QuestionAnswerModel import QuestionAnswerModel, EmbeddingsOptions, ChainOptions, LanguageModelOptions
from src.parsers.FileParser import FileParser
from src.storage.VectorStore import VectorStoreOptions
from src.cfg.config import *
from src.cfg.logging_config import *
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})  # Allow requests from localhost:3000

# Initialize the QuestionAnswerModel
model = QuestionAnswerModel(EmbeddingsOptions.DEFAULT, ChainOptions.DEFAULT, VectorStoreOptions.DEFAULT,
                            LanguageModelOptions.DEFAULT)

logger.info("Adding setup documents to vector store")

setup_docs = FileParser.parse_directory("./data/bumble_documents")
for doc in setup_docs:
    model.add_document(doc)

logger.info("Done adding setup documents to vector store")


# Route for querying
@app.route('/query', methods=['POST'])
def query():
    data = request.get_json()
    question = data['question']
    answer = model.ask(question)
    return jsonify({'answer': answer})


# Route for adding documents
@app.route('/addDocuments', methods=['POST'])
def add_documents():
    if 'file' in request.files:
        # If the request contains a file, handle file upload
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'})
        file_path = os.path.join('../temp', file.filename)
        file.save(file_path)
        doc = FileParser.parse_file(file_path)
        model.add_document(doc)
        os.remove(file_path)
        return jsonify({'message': 'Document added successfully'})
    elif 'documents' in request.json:
        # If the request contains JSON data, handle adding documents from JSON
        data = request.json
        doc_paths = data['documents']
        docs = []
        for doc_path in doc_paths:
            doc = FileParser.parse_file(doc_path)
            docs.append(doc)
        for doc in docs:
            model.add_document(doc)
        return jsonify({'message': 'Documents added successfully'})
    else:
        return jsonify({'error': 'Invalid request'})


if __name__ == '__main__':
    # Create a temporary directory for file uploads
    os.makedirs('../temp', exist_ok=True)
    app.run(port=5000)
