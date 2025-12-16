from PySide6.QtWidgets import QApplication

from .constants import APP_NAME
from .window import MainWindow


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.resize(1200, 700)
    window.show()

    app.exec()


if __name__ == "__main__":
    main()
