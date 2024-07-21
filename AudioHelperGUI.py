# ==============================================================================
# IMPORTS
#
import sys
import time
import logging

import numpy as np

from PyQt5.Qt import *
from PyQt5.QtCore import QObject, pyqtSignal

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

matplotlib.use('Qt5Agg')


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
    sig_audio_ana_enable = pyqtSignal(bool)

    def __init__(self):
        # Call parent class' init
        super(QMainWindow, self).__init__()

        # Some Basic Window Setup
        self.setWindowTitle("AudioHelper")
        self.resize(600, 600)

        layout = QVBoxLayout()

        # Create Plot for Spectrum
        plt_canvas = FigureCanvas(Figure(figsize=(5, 3)))
        layout.addWidget(plt_canvas)
        layout.addWidget(NavigationToolbar(plt_canvas, self))

        self.plt_ax = plt_canvas.figure.subplots()
        self.plt_ax.grid(visible=True, which='both', axis='x')
        self.plt_ax.grid(visible=True, which='major', axis='y')
        self.plt_ax.semilogx()
        self.plt_ax.set_xlabel('Frequency [Hz]')
        self.plt_ax.set_ylabel('Amplitude [dBm]')
        self.plt_line_meas_freq = np.linspace(50, 50000, 1000)
        self.plt_line_meas_ampl = np.random.randint(0, 10, 1000)
        plt_refs = self.plt_ax.plot(self.plt_line_meas_freq, self.plt_line_meas_ampl)
        self.plt_line_meas = plt_refs[0]
        #self.plt_line_meas.figure.canvas.draw()

        self.btn_aud_ana_enable = QPushButton("Disable Analysis", self)
        self.btn_aud_ana_enable.clicked.connect(self.btn_aud_ana_enable_click)
        layout.addWidget(self.btn_aud_ana_enable)

        self.btn_aud_gen_enable = QPushButton("Disable Tone", self)
        self.btn_aud_gen_enable.clicked.connect(self.btn_aud_gen_enable_click)
        layout.addWidget(self.btn_aud_gen_enable)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def closeEvent(self, event):
        logging.info("Main window will close in 1 second...")
        self.sig_closing.emit()
        time.sleep(1)
        logging.info("Main window closing")

    def btn_aud_gen_enable_click(self):
        if self.btn_aud_gen_enable.text() == "Disable Tone":
            logging.info("Telling AudioGen to turn off")
            self.sig_audio_gen_enable.emit(False)
            self.btn_aud_gen_enable.setText("Enable Tone")
        else:
            logging.info("Telling AudioGen to turn on")
            self.sig_audio_gen_enable.emit(True)
            self.btn_aud_gen_enable.setText("Disable Tone")

    def btn_aud_ana_enable_click(self):
        if self.btn_aud_ana_enable.text() == "Disable Analysis":
            logging.info("Telling AudioAna to turn off")
            self.sig_audio_ana_enable.emit(False)
            self.btn_aud_ana_enable.setText("Enable Analysis")
        else:
            logging.info("Telling AudioAna to turn on")
            self.sig_audio_ana_enable.emit(True)
            self.btn_aud_ana_enable.setText("Disable Analysis")

    def update_plot(self):
        self.plt_line_meas_freq = np.linspace(50, 50000, 1000)
        self.plt_line_meas_ampl = np.random.randint(0, 10, 1000)
        self.plt_line_meas.set_data(self.plt_line_meas_freq, self.plt_line_meas_ampl)
        self.plt_line_meas.figure.canvas.draw()

# ==============================================================================
# MODULE TESTBENCH
#
if __name__ == "__main__":
    print(f"Hey User!  This is just testing {__file__}")
    app = QApplication(sys.argv)

    window = AudioHelperGUI()
    window.show()

    app.exec()
    print("DONE")
