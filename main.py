import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import OCRDocumentScanner


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OCRDocumentScanner()
    window.show()
    sys.exit(app.exec())