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
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFileDialog

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from ui_AudioHelperGUI import Ui_ui_AudioHelperGUI

import BufferManager as BufMan
import pyaudio as pa

from pprint import pformat
import json

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
        #self.initFunction()

    def initFunction(self):
        self.inputs = QComboBox()
        self.outputs = QComboBox()

        # instantiate PyAudio
        self.p = pa.PyAudio()
        # find number of devices (input and output)
        self.numDevices = self.p.get_device_count()

        # start with -1 input and output options because the indices will start counting at 1
        numOut = -1
        numIn = -1
        for i in range(0, self.numDevices):
            if self.p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                self.outputs.addItem(self.p.get_device_info_by_index(i).get('name'))
                numOut = numOut + 1

                # set the default combobox output option based on the output index currently in use
                if self.p.get_device_info_by_index(i).get('name') == self.p.get_device_info_by_index(self.win.defOutput).get('name'):
                    self.outputs.setCurrentIndex(numOut)

            elif self.p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                self.inputs.addItem(self.p.get_device_info_by_index(i).get('name'))
                numIn = numIn + 1

                # set the default combobox input option based on the input index currently in use
                if self.p.get_device_info_by_index(i).get('name') == self.p.get_device_info_by_index(self.win.defInput).get('name'):
                    self.inputs.setCurrentIndex(numIn)

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
        for i in range(0, self.numDevices):
            if self.p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                if self.outputs.currentText() == self.p.get_device_info_by_index(i).get('name'):
                    self.win.buf_man.msgSend("Gen", "change_output", i)
            elif self.p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                if self.inputs.currentText() == self.p.get_device_info_by_index(i).get('name'):
                    self.win.buf_man.msgSend("Mic", "change_input", i)

        self.close()


    def cancel_click(self):
        self.close()

    def closeEvent(self, event):
        logging.info("closing")

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

    # Signals for IPC
    sig_ipc_gen = pyqtSignal(int)
    sig_ipc_mic = pyqtSignal(int)
    sig_ipc_ana = pyqtSignal(int)
    sig_ipc_guido = pyqtSignal(int)

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
            "Ana": self.sig_ipc_ana,
            "Guido": self.sig_ipc_guido
        }

        # Set Up Dictionary with Plot Line Data
        self.line_dict = {}

        self.sweepRunning = False
        self.sweepFreqs = []
        self.sweepAmpls = []

        # Create Buffer Manager
        self.name = name
        self.buf_man = BufMan.BufferManager(name, ipc_dict)

        # instantiate PyAudio
        p = pa.PyAudio()
        # find number of devices (input and output)
        numDevices = p.get_device_count()

        # set the default output index in Guido
        for i in range(0, numDevices):
            if p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                self.defOutput = i
                logging.info(f"Default output: {p.get_device_info_by_index(i).get('name')}")
                break

        # set the default input index in Guido
        for i in range(0, numDevices):
            if p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                self.defInput = i
                logging.info(f"Default input: {p.get_device_info_by_index(i).get('name')}")
                break

        # Some Basic Window Setup
        self.setWindowTitle("AudioHelper")
        self.resize(660, 550)

        # Create Plot for Spectrum
        layout = QVBoxLayout(self.plt_canvas)              # Plug into the placeholder widget
        plt_canvas = FigureCanvas(Figure())
        plt_canvas.figure.subplots_adjust(0.13, 0.15, 0.97, 0.95)  # left,bottom,right,top
        layout.addWidget(plt_canvas)
        layout.addWidget(NavigationToolbar(plt_canvas, self))

        self.plt_ax = plt_canvas.figure.subplots()
        self.plt_ax.grid(visible=True, which='both', axis='x')
        self.plt_ax.grid(visible=True, which='major', axis='y')
        self.plt_ax.semilogx()
        self.plt_ax.set_xlabel('Frequency [Hz]', size="small")
        self.plt_ax.set_ylabel('Amplitude [dB]', size="small")
        self.plt_ax.set_ylim(C_SPEC_MIN_DB, C_SPEC_MAX_DB)
        self.plt_ax.set_xlim(C_SPEC_MIN_FREQ, C_SPEC_MAX_FREQ)
        self.plt_ax.set_yticks(np.arange(C_SPEC_MIN_DB, C_SPEC_MAX_DB, C_SPEC_GRID_DB))
        self.plt_ax.xaxis.set_tick_params(labelsize="small")
        self.plt_ax.yaxis.set_tick_params(labelsize="small")

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
        self.txt_aud_gen_freq1.textChanged.connect(self.txt_aud_gen_freq1_textChanged)

        self.sld_aud_gen_freq2.sliderMoved.connect(self.sld_aud_gen_freq2_sliderMoved)
        self.txt_aud_gen_freq2.editingFinished.connect(self.txt_aud_gen_freq2_editingFinished)

        self.sld_aud_gen_vol.valueChanged.connect(self.sld_aud_gen_vol_valueChanged)
        self.txt_aud_gen_vol.editingFinished.connect(self.txt_aud_gen_vol_editingFinished)
        self.txt_aud_gen_vol.textChanged.connect(self.txt_aud_gen_vol_textChanged)

        # Connect AudioAnalyzer Signals
        self.btn_aud_ana_enable.clicked.connect(self.btn_aud_ana_enable_click)

        self.btn_setup.clicked.connect(self.setup_btn_click)

        self.btn_cfg_load.clicked.connect(self.btn_cfg_load_click)
        self.btn_cfg_save.clicked.connect(self.btn_cfg_save_click)

        self.btn_aud_ana_cal.clicked.connect(self.btn_aud_ana_cal_click)

    def closeEvent(self, event):
        logging.info("Main window will close in 1 second...")
        self.sig_closing.emit()
        time.sleep(1)
        logging.info("Main window closing")

    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        ###logging.info(f"{self.name} received {msg_type} from {snd_name} : {msg_data}")
        ack_data = None

        # Process Message
        if msg_type == "plot_data":
            [name, freq_list, ampl_list] = msg_data
            self.update_plot(name, freq_list, ampl_list)

        elif msg_type == "remove_plot":
            self.remove_plot(msg_data)

        elif msg_type == "default_output":
            self.defOutput = msg_data

        elif msg_type == "default_input":
            self.defInput = msg_data

        elif msg_type == "sweep_finished":
            logging.info("AudioAna says Sweep Finished")
            self.btn_aud_gen_enable.setText("Sweep")

        elif msg_type == "cfg_load":
            for param in msg_data.keys():
                val = msg_data[param]
                if (param == "mode"):
                    ind = self.cmb_aud_gen_mode.findText(val)
                    if ind >= 0:
                        self.cmb_aud_gen_mode.setCurrentIndex(ind)
                elif (param == "freq1"):
                        self.txt_aud_gen_freq1.setText(val)
                        self.txt_aud_gen_freq1_editingFinished()
                elif (param == "freq2"):
                    self.txt_aud_gen_freq2.setText(val)
                    self.txt_aud_gen_freq2_editingFinished()
                elif (param == "vol"):
                    self.txt_aud_gen_vol.setText(val)
                    self.txt_aud_gen_vol_editingFinished()

        elif msg_type == "REQ_cfg_save":
            ack_data = {
                "mode": self.cmb_aud_gen_mode.currentText(),
                "freq1": self.txt_aud_gen_freq1.text(),
                "freq2": self.txt_aud_gen_freq2.text(),
                "vol": self.txt_aud_gen_vol.text()
            }

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
        setupWin.initFunction()         # run the initFunction separately from __init__ so that setupWin.win exists for the function
        setupWin.exec()

    def btn_cfg_load_click(self):
        (fname, filt) = QFileDialog.getOpenFileName(self, "Load configuration", None, 'Config files (*.json);;All files (*)')
        if fname == "":
            return

        self.set_silence()

        logging.info(f"Loading configuration from {fname}")
        cfg_data = {}
        with open(fname, mode="r", encoding="utf-8") as read_file:
            cfg_data = json.load(read_file)
        for rcv_name in cfg_data.keys():
            self.buf_man.msgSend(rcv_name, "cfg_load", cfg_data[rcv_name])

    def btn_cfg_save_click(self):
        cfg_data = {}
        for rcv_name in self.buf_man.ipcReceivers():
            rcv_data = self.buf_man.msgSend(rcv_name, "REQ_cfg_save")
            if rcv_data != None:
                cfg_data[rcv_name] = rcv_data
        cfg_str = json.dumps(cfg_data)
        logging.info(f"cfg_str = \n{cfg_str}\n")

        (fname, filt) = QFileDialog.getSaveFileName(self, "Save configuration", None, 'JSON Files (*.json);;All Files (*)')
        if fname == "":
            return

        logging.info(f"Saving configuration to {fname}")
        with open(fname, mode="w", encoding="utf-8") as write_file:
            json.dump(cfg_data, write_file, indent=4)

    def btn_aud_ana_cal_click(self):
        logging.info(f"Clicked the Calibrate button")
        if self.btn_aud_ana_cal.text() == "Calibrate":
            cal_name = self.cmb_aud_ana_cal.currentText()
            self.buf_man.msgSend("Ana", "apply_cal", cal_name)
            self.btn_aud_ana_cal.setText("Clear Cal")
        else:
            self.buf_man.msgSend("Ana", "apply_cal", None)
            self.btn_aud_ana_cal.setText("Calibrate")

    def set_silence(self):
        logging.info("Stopping all sound")

        # Clean Up GUI
        mode = self.cmb_aud_gen_mode.currentText()
        if mode == 'Single Tone':
            self.lbl_aud_gen_freq2.setEnabled(False)
            self.sld_aud_gen_freq2.setEnabled(False)
            self.txt_aud_gen_freq2.setEnabled(False)
            self.lbl_aud_gen_freq2_unit.setEnabled(False)

            ###val = self.sld_aud_gen_freq1.value()
            ###self.sld_aud_gen_freq2.setValue(val)
            val = self.txt_aud_gen_freq1.text()
            self.txt_aud_gen_freq2.setText(val)
            self.txt_aud_gen_freq2_editingFinished()

            self.btn_aud_gen_enable.setText("Play")

        elif mode == "Noise":
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

            self.btn_aud_gen_enable.setText("Play")

        elif mode == "Sweep":
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

            self.btn_aud_gen_enable.setText("Sweep")

        # Stop Anything Making a Sound
        self.buf_man.msgSend("Gen", "silent", None)
        self.buf_man.msgSend("Ana", "sweep", False)

    def btn_aud_gen_enable_click(self):
        if self.btn_aud_gen_enable.text() == "Stop":
            logging.info("Telling AudioGen to turn off")
            self.buf_man.msgSend("Gen", "enable", False)
            self.btn_aud_gen_enable.setText("Play")

        elif self.btn_aud_gen_enable.text() == "Play":
            logging.info("Telling AudioGen to turn on")
            self.buf_man.msgSend("Gen", "change_mode", self.cmb_aud_gen_mode.currentText())
            self.buf_man.msgSend("Gen", "change_freq", self.txt_aud_gen_freq1.text())
            self.buf_man.msgSend("Gen", "change_vol", self.txt_aud_gen_vol.text())
            self.buf_man.msgSend("Gen", "enable", True)
            self.btn_aud_gen_enable.setText("Stop")

        elif self.btn_aud_gen_enable.text() == "Stop Sweep":
            logging.info("Telling AudioAna to stop sweeping")
            self.buf_man.msgSend("Ana", "sweep", False)
            self.btn_aud_gen_enable.setText("Sweep")

        elif self.btn_aud_gen_enable.text() == "Sweep":
            logging.info("Telling AudioAna to start sweeping")
            self.buf_man.msgSend("Gen", "change_mode", self.cmb_aud_gen_mode.currentText())
            self.buf_man.msgSend("Ana", "change_start_freq", self.txt_aud_gen_freq1.text())
            self.buf_man.msgSend("Ana", "change_stop_freq", self.txt_aud_gen_freq2.text())
            self.buf_man.msgSend("Gen", "change_vol", self.txt_aud_gen_vol.text())
            self.buf_man.msgSend("Ana", "sweep", True)
            self.btn_aud_gen_enable.setText("Stop Sweep")

    def cmb_aud_gen_mode_currentTextChanged(self, mode):
        logging.info(f"AudioGen mode changed to {mode}")
        self.set_silence()

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

    def txt_aud_gen_freq1_textChanged(self, newFreq):
        self.buf_man.msgSend("Gen", "change_freq", newFreq)

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

    def txt_aud_gen_vol_textChanged(self, newVolDB):
        self.buf_man.msgSend("Gen", "change_vol", newVolDB)

    # ----------------------------------------------------------------------
    # AudioAnalyzer Interface
    #
    def btn_aud_ana_enable_click(self):
        if self.btn_aud_ana_enable.text() == "Freeze":
            logging.info("Telling AudioAna to turn off")
            self.buf_man.msgSend("Mic", "enable", False)
            self.btn_aud_ana_enable.setText("Analyze")
        else:
            logging.info("Telling AudioAna to turn on")
            self.buf_man.msgSend("Mic", "enable", True)
            self.btn_aud_ana_enable.setText("Freeze")

    def update_plot(self, name, freq_list, ampl_list):
        # Remove DC element
        freq_list = np.delete(freq_list,0)
        ampl_list = np.delete(ampl_list,0)

        # Tranlsate to dB
        ampl_list = np.clip(ampl_list, 1e-6, None)      # np.log10() won't like 0s
        ampl_list = 20 * np.log10(ampl_list)                         # Translate to dB
        ampl_list = np.clip(ampl_list, C_SPEC_MIN_DB, C_SPEC_MAX_DB) # Limit to plot range

        # Update Existing Plot Line
        if name in self.line_dict.keys():
            ###logging.info(f"Updating plot line: {name}")
            line_obj = self.line_dict[name]["line_obj"]
            line_obj.set_data(freq_list, ampl_list)
            line_obj.figure.canvas.draw()

        # Add New Plot Line
        else:
            ###logging.info(f"Adding plot line: {name}")
            plt_refs = self.plt_ax.plot(freq_list, ampl_list, label = name)
            self.line_dict[name] = {
                "line_obj": plt_refs[0]     # Store Line2D object to reference layer
            }
            self.plt_ax.legend(fontsize="small")
            if name != "Cal":
                self.cmb_aud_ana_cal.addItem(name)
            plt_refs[0].figure.canvas.draw()

    def remove_plot(self, name):
        if name in self.line_dict.keys():
            ###logging.info(f"Removing plot line: {name}")
            if "line_obj" in self.line_dict[name]:
                self.line_dict[name]["line_obj"].remove()
            self.plt_ax.legend(fontsize="small")

            ind = self.cmb_aud_ana_cal.findText(name)
            if ind != -1:
                self.cmb_aud_ana_cal.removeItem(ind)

            self.line_dict.pop(name)

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
