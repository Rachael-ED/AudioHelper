# ==============================================================================
# IMPORTS
#
import sys
import time
import logging
import random
import re

import numpy as np

from PyQt5.Qt import *
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from ui_AudioHelperGUI import Ui_ui_AudioHelperGUI

import BufferManager as BufMan

matplotlib.use('Qt5Agg')

# ==============================================================================
# CONSTANTS AND GLOBALS
#
C_AUD_GEN_MODE_LIST = ['Single Tone', 'Noise', 'Sweep']


# ==============================================================================
# CLASS: MAIN WINDOW
#
class AudioHelperGUI(QMainWindow, Ui_ui_AudioHelperGUI):
    """Class: AudioHelperGUI
    Main GUI window for the application.

    Inherits from:
        QMainWindow              - PyQt5 application window
        Ui_ui_AudioHelperGUI     - Created by Qt Designer
                                   To translate the resulting .ui file, run the following from the Terminal:
                                       pyuic5 -o ui_AudioHelperGUI.py ui_AudioHelperGUI.ui
    """

    # ----------------------------------------------------------------------
    # Class Data
    #
    sig_closing = pyqtSignal()     # Signal thrown when main window is about to close
    sig_audio_gen_enable = pyqtSignal(bool)
    sig_audio_ana_enable = pyqtSignal(bool)
    sig_changeFreq = pyqtSignal(int)

    # ----------------------------------------------------------------------
    # Initialization & Termination
    #
    def __init__(self):
        # Call parent class' init
        super(QMainWindow, self).__init__()
        self.setupUi(self)

        # Create Buffer Manager
        self.buf_man = BufMan.BufferManager("AudioHelperGUI")
        self.buf_id_list = []   # Temporary for testing

        # Some Basic Window Setup
        self.setWindowTitle("AudioHelper")
        self.resize(700, 500)

        # Create Plot for Spectrum
        layout = QVBoxLayout(self.plt_canvas)              # Plug into the placeholder widget
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

        # Configure AudioGen Widgets
        self.txt_aud_gen_freq1.setValidator(QDoubleValidator())
        self.txt_aud_gen_freq2.setValidator(QDoubleValidator())
        self.txt_aud_gen_vol.setValidator(QIntValidator())

        self.cmb_aud_gen_mode.addItems(C_AUD_GEN_MODE_LIST)
        self.cmb_aud_gen_mode.setCurrentIndex(0)

        # Configure AudioAnalyzer Widgets
        # ... nothing yet ...

        # Connect AudioGen Signals
        self.cmb_aud_gen_mode.currentTextChanged.connect(self.cmb_aud_gen_mode_currentTextChanged)

        self.btn_aud_gen_enable.clicked.connect(self.btn_aud_gen_enable_click)

        self.sld_aud_gen_freq1.sliderMoved.connect(self.sld_aud_gen_freq1_sliderMoved)
        self.txt_aud_gen_freq1.editingFinished.connect(self.txt_aud_gen_freq1_editingFinished)

        self.sld_aud_gen_freq2.sliderMoved.connect(self.sld_aud_gen_freq2_sliderMoved)
        self.txt_aud_gen_freq2.editingFinished.connect(self.txt_aud_gen_freq2_editingFinished)

        self.sld_aud_gen_vol.valueChanged.connect(self.sld_aud_gen_vol_valueChanged)
        self.txt_aud_gen_vol.editingFinished.connect(self.txt_aud_gen_vol_editingFinished)

        # Connect AudioAnalyzer Signals
        self.btn_aud_ana_enable.clicked.connect(self.btn_aud_ana_enable_click)

    def closeEvent(self, event):
        logging.info("Main window will close in 1 second...")
        self.sig_closing.emit()
        time.sleep(1)
        logging.info("Main window closing")

    # ----------------------------------------------------------------------
    # AudioGen Widgets
    #
    def btn_aud_gen_enable_click(self):
        if self.btn_aud_gen_enable.text() == "Stop":
            logging.info("Telling AudioGen to turn off")
            self.sig_audio_gen_enable.emit(False)
            self.btn_aud_gen_enable.setText("Play")
        else:
            logging.info("Telling AudioGen to turn on")
            self.sig_audio_gen_enable.emit(True)
            self.btn_aud_gen_enable.setText("Stop")

    def cmb_aud_gen_mode_currentTextChanged(self, mode):
        logging.info(f"AudioGen mode changed to {mode}")
        if mode == 'Single Tone':
            self.lbl_aud_gen_freq2.setEnabled(False)
            self.sld_aud_gen_freq2.setEnabled(False)
            self.txt_aud_gen_freq2.setEnabled(False)
            self.lbl_aud_gen_freq2_unit.setEnabled(False)

            val = self.sld_aud_gen_freq1.value()
            self.sld_aud_gen_freq2.setValue(val)
        else:
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

    def sld_pos_to_freq(self, pos):
        freq = round(10**(pos/1000), 1)   # Hz
        return freq

    def sld_freq_to_pos(self, freq):   # Hz
        freq = max([1, freq])
        pos = round(1000*np.log10(freq))
        pos = min([pos, self.sld_aud_gen_freq1.maximum()])
        pos = max([pos, self.sld_aud_gen_freq1.minimum()])
        return pos

    def sld_aud_gen_freq1_sliderMoved(self):
        pos = self.sld_aud_gen_freq1.value()
        freq = self.sld_pos_to_freq(pos)
        #logging.info(f"AudioGen start freq slider changed to pos = {pos} => freq = {freq}")

        # Change Text Box to Match
        self.txt_aud_gen_freq1.setText(f"{freq}")

        # Keep Start & Stop Frequencies Consistent
        if float(self.txt_aud_gen_freq2.text()) < freq:
            self.txt_aud_gen_freq2.setText(f"{freq}")
            self.sld_aud_gen_freq2.setValue(pos)
        elif not self.sld_aud_gen_freq2.isEnabled():
            self.txt_aud_gen_freq2.setText(f"{freq}")
            self.sld_aud_gen_freq2.setValue(pos)

    def sld_aud_gen_freq2_sliderMoved(self):
        pos = self.sld_aud_gen_freq2.value()
        freq = self.sld_pos_to_freq(pos)
        #logging.info(f"AudioGen stop freq slider changed to pos = {pos} => freq = {freq}")

        # Change Text Box to Match
        self.txt_aud_gen_freq2.setText(f"{freq}")

        # Keep Start & Stop Frequencies Consistent
        if float(self.txt_aud_gen_freq1.text()) > freq:
            self.txt_aud_gen_freq1.setText(f"{freq}")
            self.sld_aud_gen_freq1.setValue(pos)

    def txt_aud_gen_freq1_editingFinished(self):
        orig_freq = float(self.txt_aud_gen_freq1.text())

        # Range Checking
        freq = orig_freq
        freq = max(freq, self.sld_pos_to_freq(self.sld_aud_gen_freq1.minimum()))
        freq = min(freq, self.sld_pos_to_freq(self.sld_aud_gen_freq1.maximum()))
        freq = round(freq, 1)
        self.txt_aud_gen_freq1.setText(f"{freq}")

        pos = self.sld_freq_to_pos(freq)
        #logging.info(f"AudioGen start freq text changed to freq = {freq = {freq} => pos = {pos}")

        # Update Slider to Match
        self.sld_aud_gen_freq1.setValue(pos)

        # Keep Start & Stop Frequencies Consistent
        if float(self.txt_aud_gen_freq2.text()) < freq:
            self.txt_aud_gen_freq2.setText(f"{freq}")
            self.sld_aud_gen_freq2.setValue(pos)
        elif not self.txt_aud_gen_freq2.isEnabled():
            self.txt_aud_gen_freq2.setText(f"{freq}")
            self.sld_aud_gen_freq2.setValue(pos)

    def txt_aud_gen_freq2_editingFinished(self):
        orig_freq = float(self.txt_aud_gen_freq2.text())

        # Range Checking
        freq = orig_freq
        freq = max(freq, self.sld_pos_to_freq(self.sld_aud_gen_freq2.minimum()))
        freq = min(freq, self.sld_pos_to_freq(self.sld_aud_gen_freq2.maximum()))
        freq = round(freq, 1)
        self.txt_aud_gen_freq2.setText(f"{freq}")

        pos = self.sld_freq_to_pos(freq)
        # logging.info(f"AudioGen start freq text changed to freq = {freq} => pos = {pos}")

        # Update Slider to Match
        self.sld_aud_gen_freq2.setValue(pos)

        # Keep Start & Stop Frequencies Consistent
        if float(self.txt_aud_gen_freq1.text()) > freq:
            self.txt_aud_gen_freq1.setText(f"{freq}")
            self.sld_aud_gen_freq1.setValue(pos)

    def sld_aud_gen_vol_valueChanged(self, vol):
        # logging.info(f"AudioGen vol slider changed to {vol}%")

        # Change text entry only if the current value would not map to this position (avoid inf recursion)
        txt_vol = int(self.txt_aud_gen_vol.text())
        if txt_vol != vol:
            self.txt_aud_gen_vol.setText(f"{vol}")

    def txt_aud_gen_vol_editingFinished(self):
        vol = int(self.txt_aud_gen_vol.text())
        vol = max(vol, 0)
        vol = min(vol, 100)
        #logging.info(f"AudioGen vol text changed to {vol}%")

        self.txt_aud_gen_vol.setText(f"{vol}")
        self.sld_aud_gen_vol.setValue(vol)


    # ----------------------------------------------------------------------
    # AudioAnalyzer Interface
    #
    def btn_aud_ana_enable_click(self):
        if self.btn_aud_ana_enable.text() == "Freeze":
            logging.info("Telling AudioAna to turn off")
            self.sig_audio_ana_enable.emit(False)
            self.btn_aud_ana_enable.setText("Analyze")
        else:
            logging.info("Telling AudioAna to turn on")
            self.sig_audio_ana_enable.emit(True)
            self.btn_aud_ana_enable.setText("Freeze")

    def update_plot(self, buf_id):
        """
        self.buf_id_list.append(buf_id)
        if (len(self.buf_id_list) < 4):
            return
        #elif (len(self.buf_id_list) > 8):
        #    pass
        elif (random.random() < 0.1):
            return
        buf_id = self.buf_id_list.pop(0)
        """

        buf = self.buf_man.free(buf_id)
        self.plt_line_meas_freq = buf[0]
        self.plt_line_meas_ampl = buf[1]

        # Remove DC element
        self.plt_line_meas_freq = np.delete(self.plt_line_meas_freq,0)
        self.plt_line_meas_ampl = np.delete(self.plt_line_meas_ampl,0)

        self.plt_ax.set_xlim(self.plt_line_meas_freq[0], self.plt_line_meas_freq[-1])
        self.plt_ax.set_ylim(np.min(self.plt_line_meas_ampl), np.max(self.plt_line_meas_ampl))

        self.plt_line_meas.set_data(self.plt_line_meas_freq, self.plt_line_meas_ampl)
        self.plt_line_meas.figure.canvas.draw()


# ==============================================================================
# MODULE TESTBENCH
#
if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)

    print(f"Hey User!  This is just testing {__file__}")
    app = QApplication(sys.argv)

    window = AudioHelperGUI()
    window.show()

    app.exec()
    print("DONE")
