# ==============================================================================
# IMPORTS
#
import sys
import time
from PyQt5.Qt import *
from PyQt5.QtCore import QObject, pyqtSignal
import logging


# ==============================================================================
# CLASS DEFINITION
#
class AudioHelperGUI(QMainWindow):
    """Class: AudioHelperGUI
    Main GUI window for the application.

    Inherits from:
        QMainWindow     - PyQt5 application window
    """

    sig_closing = pyqtSignal()     # Signal thrown when main window is about to close
    sig_audio_gen_enable = pyqtSignal(bool)

    def __init__(self):
        super(QMainWindow, self).__init__()

        self.setWindowTitle("Watermelon Plotter")
        self.resize(300, 150)

        layout = QVBoxLayout()

        self.watermelon = Watermelon()
        layout.addWidget(self.watermelon)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setValue(10)
        self.size_slider.setRange(1, 100)
        self.size_slider.valueChanged.connect(self.size_changed)
        layout.addWidget(self.size_slider)

        self.stop_btn = QPushButton("Disable Tone", self)
        self.stop_btn.clicked.connect(self.stop_btn_click)
        layout.addWidget(self.stop_btn)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def closeEvent(self, event):
        logging.info("Main window will close in 1 second...")
        self.sig_closing.emit()
        time.sleep(1)
        logging.info("Main window closing")

    def stop_btn_click(self):
        if self.stop_btn.text() == "Disable Tone":
            logging.info("Telling AudioGen to turn off")
            self.sig_audio_gen_enable.emit(False)
            self.stop_btn.setText("Enable Tone")
        else:
            logging.info("Telling AudioGen to turn on")
            self.sig_audio_gen_enable.emit(True)
            self.stop_btn.setText("Disable Tone")

    def size_changed(self, i):
        self.watermelon.set_size(i)


# ==============================================================================
# TEMP CLASS DEFINITION
#
class Watermelon(QWidget):
    """Class: AudioHelperGUI"""
    def __init__(self):
        super(Watermelon, self).__init__()

        self.size = 10

        self.setAutoFillBackground(True)

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor('white'))
        self.setPalette(palette)

    def set_size(self, new_size):
        self.size = new_size
        self.repaint()

    def paintEvent(self, event):
        frm_h = self.height()
        frm_w = self.width()
        s = self.size

        x1 = int((frm_w/2) - (frm_w*s/100/2))
        y1 = int((frm_h/2) - (frm_h*s/100/2))

        w = int(frm_w*s/100)
        h = int(frm_h*s/100)

        if frm_h > frm_w:
            pen_width = int(frm_w/10*s/100)
        else:
            pen_width = int(frm_h/10*s/100)
        if pen_width < 1:
            pen_width = 1

        qp = QPainter()
        qp.begin(self)
        qp.setPen(QPen(QColor('green'), pen_width))
        qp.drawEllipse(x1, y1, w, h)   # (left, top, width, height)
        qp.end()

        super().paintEvent(event)


# ==============================================================================
# MODULE TESTBENCH
#
'''
if __name__ == "__main__":
    print(f"Hey User!  This is just testing {__file__}")
    app = QApplication(sys.argv)

    window = AudioHelperGUI()
    window.show()

    app.exec()
    print("DONE")
'''
