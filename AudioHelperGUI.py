# ==============================================================================
# IMPORTS
#
import sys
import time
import logging
import re
import os
import traceback
from datetime import datetime

import numpy as np

from PyQt5.Qt import *
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFileDialog, QMessageBox, QInputDialog

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from ui_AudioHelperGUI_v1a import Ui_ui_AudioHelperGUI

import BufferManager as BufMan
import pyaudio as pa

from pprint import pformat
import json
import csv

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

C_STEPS_MAX = 100
C_STEPS_MIN = 1

C_GAIN_MAX_DB = 200
C_GAIN_MIN_DB = 0

C_AVG_DUR_MAX = 10
C_AVG_DUR_MIN = 0

C_FREQ_MAX = 20000
C_FREQ_MIN = 50

# ==============================================================================
# CLASS: HELP
#
class HelpWindow(QDialog):
    def __init__(self):
        super().__init__()

    def initFunction(self):
        helpWindow = QLabel("Hey user! Need help? Too bad! :)")
        layout = QGridLayout()
        layout.addWidget(helpWindow, 0, 1)
        self.setLayout(layout)

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
        outputLabel = QLabel("Select Output:")

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

        # Set Up Dictionary with Default Values for Standard Lines
        self.line_def_dict = {
            "Live": {
                "colour": "tab:blue",
                "zorder": 2,
                "alpha": 1
            },
            "Avg": {
                "colour": "tab:orange",
                "zorder": 2.1,
                "alpha": 0.8
            },
            "Cal": {
                "colour": "tab:green",
                "zorder": 2.2,
                "alpha": 0.7
            },
            "Sweep": {
                "colour": "tab:red",
                "zorder": 2.3,
                "alpha": 0.7
            },
        }

        # Plot Colours
        #     Used for plots other than the standard lines
        self.line_colours = ['tab:purple', 'tab:brown', 'tab:pink', 'tab:gray', 'tab:olive', 'tab:cyan']
        self.next_line_colour_ind = 0

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
        self.resize(660, 580)

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
        self.txt_aud_gen_steps.setValidator(QIntValidator())

        self.cmb_aud_gen_mode.addItems(C_AUD_GEN_MODE_LIST)
        self.cmb_aud_gen_mode.setCurrentIndex(0)

        # Configure AudioAnalyzer Widgets
        self.txt_ana_gain.setValidator(QIntValidator())
        self.txt_ana_avg.setValidator(QDoubleValidator())

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

        self.sld_aud_gen_steps.valueChanged.connect(self.sld_aud_gen_steps_valueChanged)
        self.txt_aud_gen_steps.editingFinished.connect(self.txt_aud_gen_steps_editingFinished)
        self.txt_aud_gen_steps.textChanged.connect(self.txt_aud_gen_steps_textChanged)

        self.knb_ana_avg.valueChanged.connect(self.knb_ana_avg_valueChanged)
        self.txt_ana_avg.editingFinished.connect(self.txt_ana_avg_editingFinished)
        #self.txt_ana_avg.textChanged.connect(self.txt_ana_avg_textChanged)

        self.knb_ana_gain.valueChanged.connect(self.knb_ana_gain_valueChanged)
        self.txt_ana_gain.editingFinished.connect(self.txt_ana_gain_editingFinished)
        #self.txt_ana_gain.textChanged.connect(self.txt_ana_gain_textChanged)

        self.knb_ana_threshold.valueChanged.connect(self.knb_ana_threshold_valueChanged)
        self.txt_ana_threshold.editingFinished.connect(self.txt_ana_threshold_editingFinished)

        # Connect AudioAnalyzer Signals
        self.btn_aud_ana_enable.clicked.connect(self.btn_aud_ana_enable_click)

        self.cmb_aud_ana_cal.currentTextChanged.connect(self.cmb_aud_ana_cal_currentTextChanged)

        self.btn_setup.clicked.connect(self.setup_btn_click)

        self.btn_cfg_load.clicked.connect(self.btn_cfg_load_click)
        self.btn_cfg_save.clicked.connect(self.btn_cfg_save_click)

        self.btn_aud_ana_cal.clicked.connect(self.btn_aud_ana_cal_click)

        self.btn_load_data.clicked.connect(self.btn_load_data_click)
        self.btn_save_data.clicked.connect(self.btn_save_data_click)
        self.btn_clear_data.clicked.connect(self.btn_clear_data_click)
        self.btn_copy_data.clicked.connect(self.btn_copy_data_click)
        self.btn_showhide_data.clicked.connect(self.btn_showhide_data_click)

        self.btn_help.clicked.connect(self.btn_help_click)

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

        elif msg_type == "hide_plot":
            self.hide_plot(msg_data)

        elif msg_type == "show_plot":
            self.show_plot(msg_data)

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
                elif (param == "steps"):
                    self.txt_aud_gen_steps.setText(val)
                    self.txt_aud_gen_steps_editingFinished()

        elif msg_type == "REQ_cfg_save":
            ack_data = {
                "mode": self.cmb_aud_gen_mode.currentText(),
                "freq1": self.txt_aud_gen_freq1.text(),
                "freq2": self.txt_aud_gen_freq2.text(),
                "vol": self.txt_aud_gen_vol.text(),
                "steps": self.txt_aud_gen_steps.text()
            }

        elif (msg_type == "MsgBox") or (msg_type == "REQ_MsgBox"):
            param_list = ["", "Ok", "AudioHelper"]   # Default parameters
            for i in range(0,len(msg_data)):
                param_list[i] = msg_data[i]
            [msg_str, msg_box_type, title] = param_list
            ret_val = self.MsgBox(msg_str, msg_box_type, title)
            if msg_type == "REQ_MsgBox":
                ack_data = ret_val

        else:
            logging.info(f"ERROR: {self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")

        # Acknowledge/Release Message
        self.buf_man.msgAcknowledge(buf_id, ack_data)

    # ----------------------------------------------------------------------
    # Standard Message Boxes
    #
    def MsgBox(self, msg_str, msg_box_type = "Ok", title = "AudioHelper"):
        msg_box = QMessageBox(self)
        msg_box.setText(msg_str)
        msg_box.setWindowTitle(title)

        if msg_box_type == "OkCancel":
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

        elif msg_box_type == "YesNo":
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        elif msg_box_type == "YesNoCancel":
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)

        elif msg_box_type == "WarnOkCancel":
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

        elif msg_box_type == "Error":
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)

        else:
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)

        ret_val = msg_box.exec()

        if ret_val == QMessageBox.Ok:
            return True
        elif ret_val == QMessageBox.Cancel:
            if msg_box_type == "YesNoCancel":
                return None
            return False
        elif ret_val == QMessageBox.Yes:
            return True
        elif ret_val == QMessageBox.No:
            return False

        return None

    # ----------------------------------------------------------------------
    # AudioGen Widgets
    #

    def btn_help_click(self):
        helpWin = HelpWindow()
        helpWin.win = self
        helpWin.initFunction()
        helpWin.exec()

        logging.info(f"Clicked the Help button")

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
        if self.btn_aud_ana_cal.text() == "Calibrate":
            name = self.cmb_aud_ana_cal.currentText()
            logging.info(f"Calibrating with {name}")
            if name in self.line_dict.keys():
                freq_list = self.line_dict[name]["freq_list"]
                ampl_list = self.line_dict[name]["ampl_list"]
                self.buf_man.msgSend("Ana", "apply_cal", [freq_list, ampl_list])
                self.btn_aud_ana_cal.setText("Clear Cal")
        else:
            logging.info(f"Clearing Calibration")
            self.buf_man.msgSend("Ana", "apply_cal", None)
            self.btn_aud_ana_cal.setText("Calibrate")
            self.remove_plot("Cal")

    def btn_load_data_click(self):
        (fname, filt) = QFileDialog.getOpenFileName(self, "Load data", None, 'Csv Files (*.csv);;All Files (*)')
        if fname == "":
            return

        logging.info(f"Loading configuration from {fname}")

        # Slurp .csv file into dictionary.  The header is the first row, and contains the dictionary keys
        data_dict = {}
        freq_key = None
        ampl_key = None
        ampldb_key = None
        is_first_row = True
        with open(fname, mode="r", encoding="utf-8") as csv_file:
            csv_reader = csv.DictReader(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            for row_dict in csv_reader:
                for key, value in row_dict.items():
                    # Set Up List and Detect Fields on First Row
                    if is_first_row:
                        data_dict[key] = []    # Create list to load data
                        if re.search('freq', key, re.IGNORECASE):
                            freq_key = key
                        elif re.search('ampl.*db', key, re.IGNORECASE):
                            ampldb_key = key
                        elif re.search('ampl', key, re.IGNORECASE):
                            ampl_key = key

                    # Store Value in Dictionary
                    if (not key is None) and (not value is None):
                        data_dict[key].append(value)

                is_first_row = False

        # Retrieve Frequency from File
        if freq_key is None:
            self.MsgBox("Unable to find frequency in file", "Error")
            return
        freq_list = np.array(data_dict[freq_key]).astype(np.float32)

        # Retrieve Amplitudes from File
        if (ampl_key is None) and (ampldb_key is None):
            self.MsgBox("Unable to find amplitude in file", "Error")
            return
        ampl_list = None
        if ampl_key is None:
            ampldb_list = np.array(data_dict[ampldb_key]).astype(np.float32)
            ampl_list = 10**(np.divide(ampldb_list, 20))
        else:
            ampl_list = np.array(data_dict[ampl_key]).astype(np.float32)

        # Get Name for New Series
        def_name = os.path.basename(fname)
        def_name = re.sub(".csv$", "", def_name, flags=re.IGNORECASE)
        name, input_ok = QInputDialog.getText(self, 'Load Data', 'Enter the name for the data:', text=def_name)
        if not input_ok:
            return
        if name is None:
            return
        if name in self.line_dict.keys():
            self.MsgBox(f"Data already loaded for {name}", "Error")
            return

        # Add Plot
        self.update_plot(name, freq_list, ampl_list)

    def btn_save_data_click(self):
        name = self.cmb_aud_ana_cal.currentText()
        if name in self.line_dict.keys():
            (fname, filt) = QFileDialog.getSaveFileName(self, "Save data", None, 'Csv Files (*.csv);;All Files (*)')
            if fname == "":
                return

            logging.info(f"Saving data to {fname}")

            with open(fname, mode='w') as csv_file:
                csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                csv_writer.writerow(['Freq [Hz]', 'Amplitude [1]', 'Amplitude [dB]'])
                freq_list = self.line_dict[name]["freq_list"]
                ampl_list = self.line_dict[name]["ampl_list"]
                ampldb_list = self.line_dict[name]["ampldb_list"]
                for ind in range(0, len(freq_list)):
                    csv_writer.writerow([freq_list[ind], ampl_list[ind], ampldb_list[ind]])

    def btn_clear_data_click(self):
        name = self.cmb_aud_ana_cal.currentText()
        logging.info(f"Clicked Clear Data: {name}")
        self.remove_plot(name)

    def btn_copy_data_click(self):
        src_name = self.cmb_aud_ana_cal.currentText()
        logging.info(f"Clicked Copy Data: {src_name}")

        # Capture Data to Store Right Away
        # If it's live, it might be changing...
        if not src_name in self.line_dict:
            return
        freq_list = np.copy(self.line_dict[src_name]["freq_list"])
        ampl_list = np.copy(self.line_dict[src_name]["ampl_list"])

        # Get Name for New Series
        def_name = src_name + datetime.now().strftime("_%y%m%d_%H%M%S")
        name, input_ok = QInputDialog.getText(self, 'Copy Data', 'Enter the new name for the data:', text=def_name)
        if not input_ok:
            return
        if name is None:
            return
        if name in self.line_dict.keys():
            self.MsgBox(f"Data already loaded for {name}", "Error")
            return

        # Add Plot
        self.update_plot(name, freq_list, ampl_list)

    def btn_showhide_data_click(self):
        name = self.cmb_aud_ana_cal.currentText()
        logging.info(f"Clicked Show/Hide Data: {name}")

        if not (name in self.line_dict.keys()):          # Line doesn't exist
            return
        if self.btn_showhide_data.text() == "Show":
            self.show_plot(name)
        elif self.btn_showhide_data.text() == "Hide":
            self.hide_plot(name)

        self.btn_showhideclear_update()

    def cmb_aud_ana_cal_currentTextChanged(self):
        self.btn_showhideclear_update()

    def btn_showhideclear_update(self):
        #logging.info(f"Called btn_showhideclear_update()\n{traceback.print_stack()}")

        name = self.cmb_aud_ana_cal.currentText()
        if (len(self.line_dict) < 1) or (name is None) or (not (name in self.line_dict.keys())):  # Line doesn't exist
            self.btn_showhide_data.setEnabled(False)
            self.btn_clear_data.setEnabled(False)
            self.btn_save_data.setEnabled(False)
            self.btn_aud_ana_cal.setEnabled(False)
            return

        self.btn_save_data.setEnabled(True)              # If it exists, it can be saved

        num_lines_shown = 0
        cal_is_shown = False
        for nm in self.line_dict.keys():
            if "line_obj" in self.line_dict[nm]:
                num_lines_shown = num_lines_shown + 1
                if nm == "Cal":
                    cal_is_shown = True

        if self.btn_aud_ana_cal.text() == "Calibrate":
            self.btn_aud_ana_cal.setEnabled(True)
        else:
            if (num_lines_shown == 1) and cal_is_shown:    # Don't allow Cal Clear cause nothing in the window
                self.btn_aud_ana_cal.setEnabled(False)
            else:
                self.btn_aud_ana_cal.setEnabled(True)

        if "line_obj" in self.line_dict[name]:           # Line already shown
            self.btn_showhide_data.setText("Hide")

            if num_lines_shown > 1:                          # It's not the only line shown
                self.btn_showhide_data.setEnabled(True)
                self.btn_clear_data.setEnabled(True)
            else:                                           # It's the only line shown
                self.btn_showhide_data.setEnabled(False)
                self.btn_clear_data.setEnabled(False)

        else:                                            # Line is hidden
            self.btn_showhide_data.setText("Show")
            self.btn_showhide_data.setEnabled(True)
            self.btn_clear_data.setEnabled(True)

    def set_silence(self):
        logging.info("Stopping all sound")

        # Clean Up GUI
        mode = self.cmb_aud_gen_mode.currentText()
        if mode == 'Single Tone':
            self.lbl_aud_gen_freq2.setEnabled(False)
            self.sld_aud_gen_freq2.setEnabled(False)
            self.txt_aud_gen_freq2.setEnabled(False)
            self.lbl_aud_gen_freq2_unit.setEnabled(False)

            self.lbl_aud_gen_steps.setEnabled(False)
            self.sld_aud_gen_steps.setEnabled(False)
            self.txt_aud_gen_steps.setEnabled(False)
            self.lbl_aud_gen_steps_unit.setEnabled(False)

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

            self.lbl_aud_gen_steps.setEnabled(False)
            self.sld_aud_gen_steps.setEnabled(False)
            self.txt_aud_gen_steps.setEnabled(False)
            self.lbl_aud_gen_steps_unit.setEnabled(False)

            self.btn_aud_gen_enable.setText("Play")

        elif mode == "Sweep":
            self.lbl_aud_gen_freq2.setEnabled(True)
            self.sld_aud_gen_freq2.setEnabled(True)
            self.txt_aud_gen_freq2.setEnabled(True)
            self.lbl_aud_gen_freq2_unit.setEnabled(True)

            self.lbl_aud_gen_steps.setEnabled(True)
            self.sld_aud_gen_steps.setEnabled(True)
            self.txt_aud_gen_steps.setEnabled(True)
            self.lbl_aud_gen_steps_unit.setEnabled(True)

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
            self.buf_man.msgSend("Ana", "change_sweep_points", self.txt_aud_gen_steps.text())
            self.buf_man.msgSend("Ana", "sweep", True)
            self.btn_aud_gen_enable.setText("Stop Sweep")
            self.buf_man.msgSend("Ana", "clear_sweep", None)

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

    def sld_aud_gen_steps_valueChanged(self, steps):
        # logging.info(f"Sweep steps slider changed to {steps}%")

        # Change text entry only if the current value would not map to this position (avoid inf recursion)
        txt_steps = int(self.txt_aud_gen_steps.text())
        if txt_steps != steps:
            self.txt_aud_gen_steps.setText(f"{steps}")

    def txt_aud_gen_steps_editingFinished(self):
        steps = int(self.txt_aud_gen_steps.text())
        steps = max(steps, C_STEPS_MIN)
        steps = min(steps, C_STEPS_MAX)
        #logging.info(f"AudioGen steps text changed to {steps}%")

        self.txt_aud_gen_steps.setText(f"{steps}")
        self.sld_aud_gen_steps.setValue(steps)

    def txt_aud_gen_steps_textChanged(self, newSteps):
        self.buf_man.msgSend("Ana", "change_sweep_points", newSteps)

    def knb_ana_gain_valueChanged(self, val):
        # logging.info(f"AudioAnalyzer gain knob changed to {val}%")

        # Change text entry only if the current value would not map to this position (avoid inf recursion)
        txt_val = int(self.txt_ana_gain.text())
        if txt_val != val:
            self.txt_ana_gain.setText(f"{val}")
        self.buf_man.msgSend("Ana", "change_gain_db", val)

    def txt_ana_gain_editingFinished(self):
        val = int(self.txt_ana_gain.text())
        val = max(val, C_GAIN_MIN_DB)
        val = min(val, C_GAIN_MAX_DB)
        #logging.info(f"AudioAnalyzer gain knob text changed to {val}%")

        self.txt_ana_gain.setText(f"{val}")
        self.knb_ana_gain.setValue(val)

    #def txt_ana_gain_textChanged(self, newGainDB):
    #    self.buf_man.msgSend("Ana", "change_gain", newGainDB)

    def knb_ana_avg_valueChanged(self, val):
        # logging.info(f"AudioAnalyzer averaging duration knob changed to {val}%")
        val = val / 10

        # Change text entry only if the current value would not map to this position (avoid inf recursion)
        txt_val = float(self.txt_ana_avg.text())
        if txt_val != val:
            self.txt_ana_avg.setText(f"{val}")

        self.buf_man.msgSend("Ana", "change_hist_dur", val)

    def txt_ana_avg_editingFinished(self):
        val = float(self.txt_ana_avg.text())
        val = max(val, C_AVG_DUR_MIN)
        val = min(val, C_AVG_DUR_MAX)
        #logging.info(f"AudioAnalyzer averaging duration knob text changed to {val}%")

        self.txt_ana_avg.setText(f"{val}")
        self.knb_ana_avg.setValue(val*10)

    #def txt_ana_avg_textChanged(self, new_avg_dur):
    #    self.buf_man.msgSend("Ana", "change_avg_dur", new_avg_dur)

    def knb_ana_threshold_valueChanged(self, val):
        # Change text entry only if the current value would not map to this position (avoid inf recursion)
        txt_val = float(self.txt_ana_threshold.text())
        if txt_val != float(val/100):
            self.txt_ana_threshold.setText(f"{val/100}")

        #print(f"SENDING THRESHOLD {val/100}")
        self.buf_man.msgSend("Ana", "change_threshold", val/100)

    def txt_ana_threshold_editingFinished(self):
        val = float(self.txt_ana_threshold.text())

        if val > 1.00:
            val = 1.00
        elif val < 0.00:
            val = 0.00

        # logging.info(f"AudioAnalyzer averaging duration knob text changed to {val}%")

        self.txt_ana_threshold.setText(f"{val}")
        self.knb_ana_threshold.setValue(val * 100)

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

        # Translate to dB
        ampldb_list = np.clip(ampl_list, 1e-12, None)       # np.log10() won't like 0s
        ampldb_list = 20 * np.log10(ampldb_list)                         # Translate to dB
        ampldb_list = np.clip(ampldb_list, C_SPEC_MIN_DB, C_SPEC_MAX_DB) # Limit to plot range

        # Update Existing Plot Line
        if name in self.line_dict.keys():
            ###logging.info(f"Updating plot line: {name}")
            self.line_dict[name]["freq_list"] = freq_list
            self.line_dict[name]["ampl_list"] = ampl_list
            self.line_dict[name]["ampldb_list"] = ampldb_list

            if "line_obj" in self.line_dict[name]:
                line_obj = self.line_dict[name]["line_obj"]
                line_obj.set_data(freq_list, ampldb_list)
                line_obj.figure.canvas.draw()

        # Add New Plot Line
        else:
            ###logging.info(f"Adding plot line: {name}")
            colour = ""
            alpha = 0.5
            zorder = 2.5 + len(self.line_def_dict)/100   # On top of standard lines
            if name in self.line_def_dict.keys():
                colour = self.line_def_dict[name]["colour"]
                alpha = self.line_def_dict[name]["alpha"]
                zorder = self.line_def_dict[name]["zorder"]
            else:
                colour = self.line_colours[self.next_line_colour_ind]
                self.next_line_colour_ind = (self.next_line_colour_ind + 1) % len(self.line_colours)
            plt_refs = self .plt_ax.plot(freq_list, ampldb_list, color=colour, label=name, zorder=zorder, alpha=alpha)

            self.line_dict[name] = {
                "line_obj": plt_refs[0],     # Store Line2D object to reference layer
                "freq_list": freq_list,
                "ampl_list": ampl_list,
                "ampldb_list": ampldb_list,
                "colour": colour,
                "alpha": alpha,
                "zorder": zorder
            }

            if len(self.line_dict) <= 1:
                self.btn_clear_data.setEnabled(False)
            else:
                self.btn_clear_data.setEnabled(True)

            self.plt_ax.legend(fontsize="small")
            self.cmb_aud_ana_cal.addItem(name)
            self.btn_showhideclear_update()

            plt_refs[0].figure.canvas.draw()

    def remove_plot(self, name):
        if len(self.line_dict) <= 1:
            logging.info(f"ERROR: Cannot remove last plot")
            return
        if name in self.line_dict.keys():
            ###logging.info(f"Removing plot line: {name}")
            if "line_obj" in self.line_dict[name]:
                self.line_dict[name]["line_obj"].remove()
            self.plt_ax.legend(fontsize="small")

            ind = self.cmb_aud_ana_cal.findText(name)
            if ind != -1:
                self.cmb_aud_ana_cal.removeItem(ind)

            self.line_dict.pop(name)
            if len(self.line_dict) <= 1:
                self.btn_clear_data.setEnabled(False)
            else:
                self.btn_clear_data.setEnabled(True)

            self.plt_ax.get_figure().canvas.draw()

            self.btn_showhideclear_update()

    def hide_plot(self, name):
        if not (name in self.line_dict.keys()):          # Line doesn't exist
            return
        if not ("line_obj" in self.line_dict[name]):     # Line already hidden
            return

        ###logging.info(f"Hiding plot line: {name}")
        self.line_dict[name]["line_obj"].remove()
        self.line_dict[name].pop("line_obj")
        self.plt_ax.legend(fontsize="small")
        self.plt_ax.get_figure().canvas.draw()

        self.btn_showhideclear_update()

    def show_plot(self, name):
        if not (name in self.line_dict.keys()):          # Line doesn't exist
            return
        if "line_obj" in self.line_dict[name]:           # Line already shown
            return
        if not ("freq_list" in self.line_dict[name]):    # Shouldn't happen
            return
        if not ("ampldb_list" in self.line_dict[name]):  # Shouldn't happen
            return

        freq_list = self.line_dict[name]["freq_list"]
        ampldb_list = self.line_dict[name]["ampldb_list"]
        colour = self.line_dict[name]["colour"]
        zorder = self.line_dict[name]["zorder"]
        alpha = self.line_dict[name]["alpha"]

        plt_refs = self.plt_ax.plot(freq_list, ampldb_list, color=colour, label=name, zorder=zorder, alpha=alpha)
        self.line_dict[name]["line_obj"] = plt_refs[0]  # Store Line2D object to reference layer

        self.plt_ax.legend(fontsize="small")

        plt_refs[0].figure.canvas.draw()

        self.btn_showhideclear_update()

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
