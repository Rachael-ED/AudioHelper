# ==============================================================================
# IMPORTS
#
import sys
import time
import logging

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
import pyaudio as pa

from pprint import pformat

matplotlib.use('Qt5Agg')

# ==============================================================================
# CONSTANTS AND GLOBALS
#
C_AUD_GEN_MODE_LIST = ['Single Tone', 'Noise', 'Sweep']

C_SPEC_MAX_DB = 80
C_SPEC_MIN_DB = -80
C_SPEC_GRID_DB = 10

C_SPEC_MAX_FREQ = 20000    # [Hz]
C_SPEC_MIN_FREQ = 50       # [Hz]

C_VOL_MAX_DB = 0
C_VOL_MIN_DB = -60

C_FREQ_MAX = 20000
C_FREQ_MIN = 50

# ==============================================================================
# CLASS: SETUP WINDOW
#
class SetupWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.initFunction()

    def initFunction(self):
        self.inputs = QComboBox()
        self.outputs = QComboBox()

        # instantiate PyAudio
        self.p = pa.PyAudio()
        # find number of devices (input and output)
        self.numDevices = self.p.get_device_count()

        for i in range(0, self.numDevices):
            if self.p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                self.outputs.addItem(self.p.get_device_info_by_index(i).get('name'))
            elif self.p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                self.inputs.addItem(self.p.get_device_info_by_index(i).get('name'))

        # label inputs and outputs
        inputLabel = QLabel("Select Input:")
        outputLabel = QLabel("Select Ouptut:")

        # Add cancel and Save buttons
        options = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        # Show all the buttons
        layout = QGridLayout()
        layout.addWidget(inputLabel, 0, 1)
        layout.addWidget(self.inputs, 1, 1)
        layout.addWidget(outputLabel, 2, 1)
        layout.addWidget(self.outputs, 3, 1)
        layout.addWidget(options, 4, 1)
        self.setLayout(layout)

        # Connect buttons
        options.accepted.connect(self.ok_click)
        options.rejected.connect(self.cancel_click)

    def ok_click(self):
        print("ok clicked")
        for i in range(0, self.numDevices):
            if self.p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                if self.outputs.currentText() == self.p.get_device_info_by_index(i).get('name'):
                    self.newOutputIndex = i
            elif self.p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                if self.inputs.currentText() == self.p.get_device_info_by_index(i).get('name'):
                    self.newInputIndex = i

        self.win.newOutput(self.newOutputIndex)
        self.win.newInput(self.newInputIndex)
        self.close()


    def cancel_click(self):
        self.close()

    def closeEvent(self, event):
        print("closing")

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
    sig_audio_ana_sweep = pyqtSignal(bool)
    sig_mic_reader_enable = pyqtSignal(bool)
    sig_assignNewOutputIndex = pyqtSignal(int)
    sig_assignNewInputIndex = pyqtSignal(int)

    # Signals for IPC
    sig_ipc_gen = pyqtSignal(int)
    sig_ipc_mic = pyqtSignal(int)
    sig_ipc_ana = pyqtSignal(int)

    # ----------------------------------------------------------------------
    # Initialization & Termination
    #
    def __init__(self, name="Guido"):
        # Call parent class' init
        super(QMainWindow, self).__init__()
        self.setupUi(self)

        # Set Up Dictionary with IPC Signals for BufMan
        ipc_dict = {       # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
            "Gen": self.sig_ipc_gen,
            "Mic": self.sig_ipc_mic,
            "Ana": self.sig_ipc_ana
        }

        # Create Buffer Manager
        self.name = name
        self.buf_man = BufMan.BufferManager(name, ipc_dict)

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
        self.plt_ax.set_ylabel('Amplitude [dB]')
        self.plt_ax.set_ylim(C_SPEC_MIN_DB, C_SPEC_MAX_DB)
        self.plt_ax.set_xlim(C_SPEC_MIN_FREQ, C_SPEC_MAX_FREQ)
        self.plt_ax.set_yticks(np.arange(C_SPEC_MIN_DB, C_SPEC_MAX_DB, C_SPEC_GRID_DB))
        self.plt_ax.xaxis.set_tick_params(labelsize="small")
        self.plt_ax.yaxis.set_tick_params(labelsize="small")

        # Create Plot for Latest Amplitude Measurement
        self.plt_line_meas_freq = np.linspace(C_SPEC_MIN_FREQ, C_SPEC_MAX_FREQ, 16384)
        self.plt_line_meas_ampl = np.array([0] * 16384)
        plt_refs = self.plt_ax.plot(self.plt_line_meas_freq, self.plt_line_meas_ampl, label = 'Live')
        self.plt_line_meas = plt_refs[0]

        # Create Plot for Average Amplitude
        self.plt_line_avg_freq = np.linspace(C_SPEC_MIN_FREQ, C_SPEC_MAX_FREQ, 16384)
        self.plt_line_avg_ampl = np.array([0] * 16384)
        plt_refs = self.plt_ax.plot(self.plt_line_avg_freq, self.plt_line_avg_ampl, label = "Average")
        self.plt_line_avg = plt_refs[0]

        # Add Legend
        self.plt_ax.legend(fontsize="small")

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

        self.btn_setup.clicked.connect(self.setup_btn_click)

        self.btn_aud_ana_cal.clicked.connect(self.btn_aud_ana_cal_click)

    def closeEvent(self, event):
        logging.info("Main window will close in 1 second...")
        self.sig_closing.emit()
        time.sleep(1)
        logging.info("Main window closing")

    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        ack_data = None

        # Process Message
        if msg_type == "plot_data":
            self.update_plot(msg_data)
        else:
            logging.info(f"ERROR: {self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")

        # Acknowledge/Release Message
        self.buf_man.msgAcknowledge(buf_id, ack_data)

    # ----------------------------------------------------------------------
    # AudioGen Widgets
    #

    def setup_btn_click(self):
        setupWin = SetupWindow()
        setupWin.win = self
        setupWin.exec()

    def btn_aud_ana_cal_click(self):
        logging.info(f"Clicked the Calibrate button")
        self.buf_man.msgSend("Gen", "test_msg", "data to Gen")
        self.buf_man.msgSend("Mic", "test_msg", "data to Mic")
        self.buf_man.msgSend("Ana", "test_msg", "data to Ana")

        cfg_dict = self.buf_man.msgSend("Gen", "REQ_cfg")
        logging.info(f"Current AudioGen Config:\n{pformat(cfg_dict)}")

    def newOutput(self, newOutputIndex):
        logging.info(f"in new output index {newOutputIndex}")
        self.sig_assignNewOutputIndex.emit(newOutputIndex)

    def newInput(self, newInputIndex):
        self.sig_assignNewInputIndex.emit(newInputIndex)

    def btn_aud_gen_enable_click(self):
        if self.btn_aud_gen_enable.text() == "Stop":
            logging.info("Telling AudioGen to turn off")
            self.buf_man.msgSend("Gen", "enable", False)
            self.btn_aud_gen_enable.setText("Play")
        elif self.btn_aud_gen_enable.text() == "Play":
            logging.info("Telling AudioGen to turn on")
            self.buf_man.msgSend("Gen", "enable", True)
            self.btn_aud_gen_enable.setText("Stop")
        elif self.btn_aud_gen_enable.text() == "Stop Sweep":
            logging.info("Telling AudioAna to stop sweeping")
            self.sig_audio_ana_sweep.emit(False)
            self.btn_aud_gen_enable.setText("Sweep")
        elif self.btn_aud_gen_enable.text() == "Sweep":
            logging.info("Telling AudioAna to start sweeping")
            self.sig_audio_ana_sweep.emit(True)
            self.btn_aud_gen_enable.setText("Stop Sweep")

    def cmb_aud_gen_mode_currentTextChanged(self, mode):
        logging.info(f"AudioGen mode changed to {mode}")
        if mode == 'Single Tone':
            self.lbl_aud_gen_freq2.setEnabled(False)
            self.sld_aud_gen_freq2.setEnabled(False)
            self.txt_aud_gen_freq2.setEnabled(False)
            self.lbl_aud_gen_freq2_unit.setEnabled(False)

            val = self.sld_aud_gen_freq1.value()
            self.sld_aud_gen_freq2.setValue(val)

            self.btn_aud_gen_enable.setText("Play")

            self.sig_audio_ana_sweep.emit(False)

        elif mode == "Noise":
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

            self.btn_aud_gen_enable.setText("Play")

            self.sig_audio_ana_sweep.emit(False)

        elif mode == "Sweep":
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

            self.btn_aud_gen_enable.setText("Sweep")

    def sld_pos_to_freq(self, pos):
        freq = round(10**(pos/1000), 1)   # Hz
        freq = max(C_FREQ_MIN, freq)
        freq = min(C_FREQ_MAX, freq)
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
        vol = max(vol, C_VOL_MIN_DB)
        vol = min(vol, C_VOL_MAX_DB)
        #logging.info(f"AudioGen vol text changed to {vol}%")

        self.txt_aud_gen_vol.setText(f"{vol}")
        self.sld_aud_gen_vol.setValue(vol)


    # ----------------------------------------------------------------------
    # AudioAnalyzer Interface
    #
    def btn_aud_ana_enable_click(self):
        if self.btn_aud_ana_enable.text() == "Freeze":
            logging.info("Telling AudioAna to turn off")
            self.sig_mic_reader_enable.emit(False)
            self.btn_aud_ana_enable.setText("Analyze")
        else:
            logging.info("Telling AudioAna to turn on")
            self.sig_mic_reader_enable.emit(True)
            self.btn_aud_ana_enable.setText("Freeze")

    #OLD#def update_plot(self, buf_id):
    def update_plot(self, spec_buf):
        # Retrieve Buffer to Plot
        #OLD#[name, freq_list, ampl_list] = self.buf_man.free(buf_id)
        [name, freq_list, ampl_list] = spec_buf

        # Remove DC element
        freq_list = np.delete(freq_list,0)
        ampl_list = np.delete(ampl_list,0)

        # Tranlsate to dB
        ampl_list = np.clip(ampl_list, 1e-6, None)      # np.log10() won't like 0s
        ampl_list = 20 * np.log10(ampl_list)                         # Translate to dB
        ampl_list = np.clip(ampl_list, C_SPEC_MIN_DB, C_SPEC_MAX_DB) # Limit to plot range

        # Update Measurement Plot
        if (name == "meas"):
            self.plt_line_meas_freq = freq_list
            self.plt_line_meas_ampl = ampl_list
            self.plt_line_meas.set_data(self.plt_line_meas_freq, self.plt_line_meas_ampl)
            self.plt_line_meas.figure.canvas.draw()

        elif (name == "avg"):
            self.plt_line_avg_freq = freq_list
            self.plt_line_avg_ampl = ampl_list
            self.plt_line_avg.set_data(self.plt_line_avg_freq, self.plt_line_avg_ampl)
            self.plt_line_avg.figure.canvas.draw()

        else:
            logging.info(f"ERROR: Invalid plot line to update ({name})")

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
