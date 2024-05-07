import unittest
import os
import shutil
from reportlab.pdfgen import canvas
from src.inputs.InputFile import InputFile
from src.parsers.FileParser import FileParser


class TestFileParser(unittest.TestCase):
    def setUp(self):
        self.test_directory = "test-data/"
        os.makedirs(self.test_directory, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_directory):
            # Remove all files and directories within test_directory
            for filename in os.listdir(self.test_directory):
                file_path = os.path.join(self.test_directory, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            # Remove the test_directory itself
            os.rmdir(self.test_directory)

    def create_dummy_pdf(self, pdf_file_path):
        c = canvas.Canvas(pdf_file_path)
        c.drawString(100, 750, "This is a PDF file content")
        c.save()

    def test_parse_pdf(self):
        # Create a dummy PDF file
        pdf_file_path = os.path.join(self.test_directory, "test.pdf")
        self.create_dummy_pdf(pdf_file_path)

        # Test parsing the PDF file
        result = FileParser.parse_file(pdf_file_path)
        self.assertIsInstance(result, InputFile)

    def test_parse_txt(self):
        # Create a dummy text file
        txt_file_path = os.path.join(self.test_directory, "test.txt")
        with open(txt_file_path, "w") as f:
            f.write("This is a text file content")

        # Test parsing the text file
        result = FileParser.parse_file(txt_file_path)
        self.assertIsInstance(result, InputFile)

    def test_parse_unsupported_format(self):
        # Create a dummy file with unsupported format
        unsupported_file_path = os.path.join(self.test_directory, "test.xyz")
        with open(unsupported_file_path, "w") as f:
            f.write("This is a file with unsupported format")

        # Test parsing the unsupported file format
        with self.assertRaises(ValueError):
            FileParser.parse_file(unsupported_file_path)

    def test_parse_directory(self):
        # Create dummy PDF and text files in the test directory
        pdf_file_path = os.path.join(self.test_directory, "test.pdf")
        txt_file_path = os.path.join(self.test_directory, "test.txt")
        self.create_dummy_pdf(pdf_file_path)
        with open(txt_file_path, "w") as f_txt:
            f_txt.write("This is a text file content")

        # Test parsing the test directory
        result = FileParser.parse_directory(self.test_directory)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], InputFile)
        self.assertIsInstance(result[1], InputFile)


if __name__ == '__main__':
    unittest.main()
