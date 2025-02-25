# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging
import re

import BufferManager as BufMan

import numpy as np
from scipy.fft import rfft, rfftfreq

# ==============================================================================
# CONSTANTS AND GLOBALS
#
C_FREQ_MAX = 20000
C_FREQ_MIN = 50

C_SWEEP_DWELL_DUR = 0.5    # Time for each sweep tone [s]

# ==============================================================================
# CLASS DEFINITION
#
class AudioAnalyzer(QObject):
    """ Class: AudioAnalyzer
        Analyzes incoming audio data

        Inherits from:
            QObject     - Allows object to be assigned to QThread to run in the background.
    """

    finished = pyqtSignal()

    # Signals for IPC
    sig_ipc_gen = pyqtSignal(int)
    sig_ipc_mic = pyqtSignal(int)
    sig_ipc_guido = pyqtSignal(int)

    def __init__(self, name="Ana"):
        super().__init__()

        # Set Up Dictionary with IPC Signals for BufMan
        ipc_dict = {       # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
            "Gen": self.sig_ipc_gen,
            "Mic": self.sig_ipc_mic,
            "Guido": self.sig_ipc_guido
        }

        # Create Buffer Manager
        self.name = name
        self.buf_man = BufMan.BufferManager(name, ipc_dict)

        self.sweep_on = False
        self.sweep_running = False
        self._stop_requested = False
        self.start_freq = C_FREQ_MIN
        self.stop_freq = C_FREQ_MAX
        self.sweep_points = 100
        self.hist_dur = 3      # Length [seconds] of history buffer
        self.hist_list = []    # List of recent analysis runs.  [timestamp, freq_list, ampl_list]

    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        ack_data = None

        # Process Message
        if msg_type == "mic_data":
            self.analyze(msg_data)
        elif msg_type == "sweep":
            self.sweep(msg_data)
        elif msg_type == "change_start_freq":
            self.changeStartFreq(msg_data)
        elif msg_type == "change_stop_freq":
            self.changeStopFreq(msg_data)
        else:
            logging.info(f"ERROR: {self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")

        # Acknowledge/Release Message
        self.buf_man.msgAcknowledge(buf_id, ack_data)

    def sweep(self, sweepOn=True):
        self.sweep_on = sweepOn
        logging.info(f"AudioAnalyzer sweep = {sweepOn}")

    def changeStartFreq(self, newFreq):
        if re.search('^\d+(\.\d+)?$', newFreq):
            newFreq = float(newFreq)   # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.start_freq = C_FREQ_MIN
                #logging.info(f"AudioAna start_freq = {self.start_freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.start_freq = C_FREQ_MAX
                #logging.info(f"AudioAna start_freq = {self.start_freq}Hz = MAX")
            else:
                self.start_freq = newFreq
                #logging.info(f"AudioAna start_freq = {self.start_freq}Hz")

    def changeStopFreq(self, newFreq):
        if re.search('^\d+(\.\d+)?$', newFreq):
            newFreq = float(newFreq)   # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.stop_freq = C_FREQ_MIN
                #logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.stop_freq = C_FREQ_MAX
                #logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz = MAX")
            else:
                self.stop_freq = newFreq
                #logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz")

    def stop(self):
        logging.info("AudioAnalyzer stop requested")
        self._stop_requested = True

    def hist_clean(self):
        cur_time = time.monotonic()
        age_out_time = cur_time - self.hist_dur
        ind = 0   # Index of oldest entry that has not aged out
        while ind < len(self.hist_list):
            [timestamp, freq_list, ampl_list] = self.hist_list[ind]
            if timestamp >= age_out_time:
                break
            ind += 1
        if ind >= len(self.hist_list):   # All entries have aged out
            self.hist_list = []
        elif ind > 0:                    # Some entries have aged out
            del self.hist_list[:ind]

    def hist_add(self, freq_list, ampl_list):
        self.hist_clean()
        self.hist_list.append([time.monotonic(), freq_list, ampl_list])

    def analyze(self, voltageAndTime):
        # Retrieve buffer with mic waveform
        [time_list, volt_list] = voltageAndTime

        num_samp = len(volt_list)               # Number of audio samples
        t_samp = time_list[1] - time_list[0]    # Audio sampling period

        # Calculate Frequency Spectrum
        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)              # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)            # Amplitude spectrum of measurement

        # Add to History
        self.hist_add(freq_list, ampl_list)

        # Send Amplitude Spectrum to Guido
        spec_buf = ["meas", freq_list, ampl_list]
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
        #logging.info(f"{self.name}: Analyzed spectrum.  num_samp={num_samp}, t_samp={t_samp}, df={meas_f[1] - meas_f[0]}")

        # Calc Average Amplitude Over History Buffer
        #     Here, we'll calc the average in a "log sense".
        #     That is, for each frequency in the spectrum, we'll calc the following over all N buffers in the history:
        #         logavg = 10^( AVERAGE{ log(ampl) } )
        #     Actually, we're using a natural log and then using "e^" rather than "10^".
        #     When it's plotted by Guido, this will give us the average dB over the history time.
        #     Note: I started with the more obvious "just take the arithmetic average", but found that it didn't
        #           behave very naturally because the resulting dB value was heavily influenced by the max
        #           in the history buffer.  Plotting the "average dB" gives better behaviour.
        calc_err = 0
        avg_ampl_list = np.array([0] * len(freq_list)).astype(np.float64)
        for [hist_timestamp, hist_freq_list, hist_ampl_list] in self.hist_list:
            if not np.array_equal(hist_freq_list, freq_list):
                calc_err = 1
            elif len(hist_ampl_list) != len(avg_ampl_list):
                calc_err = 1
            else:
                avg_ampl_list += np.log(np.clip(hist_ampl_list,1e-6, None))   # Sum up all logs, avoiding 0
        if calc_err == 1:
            avg_ampl_list = ampl_list
            self.hist_list = []
            self.hist_add(freq_list, ampl_list)
            logging.info("WARNING: History buffer reset")
        elif len(self.hist_list) > 0:
            avg_ampl_list = np.divide(avg_ampl_list, len(self.hist_list))   # Div by N to get avg log
            avg_ampl_list = np.exp(avg_ampl_list)                           # Then "un-log" again

        # Send Average Amplitude to Guido
        spec_buf = ["avg", freq_list, avg_ampl_list]
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)

    def run(self):
        logging.info("AudioAnalyzer started")
        self._stop_requested = False
        it_cnt = 0
        sweep_freq = 0
        sweep_freq_mult = 0
        next_it_time = time.monotonic()
        while not self._stop_requested:
            # --- Wait for Next Iteration ---
            sleep_dur = next_it_time - time.monotonic()
            if sleep_dur > 0:
                time.sleep(sleep_dur)
            next_it_time = next_it_time + C_SWEEP_DWELL_DUR

            # --- Run the Sweep ---
            if self.sweep_on:
                # --- Get Sweep Started ---
                if not self.sweep_running:
                    logging.info(f"{self.name}: AudioAnalyzer sweep started.")
                    self.sweep_running = True
                    if self.start_freq > self.stop_freq:
                        (self.start_freq, self.stop_freq) = (self.stop_freq, self.start_freq)
                    sweep_freq = self.start_freq
                    sweep_freq_mult = (self.stop_freq / self.start_freq) ** (1/(self.sweep_points-1))

                # --- Generate Sweep Tone ---
                logging.info(f"{self.name}: AudioAnalyzer sweep generating {sweep_freq}Hz.")
                self.buf_man.msgSend("Gen", "play_tone", sweep_freq)

                # --- Determine Next Sweep Tone ---
                # When we're done, we'll generate 0, which stops Gen
                sweep_freq = sweep_freq * sweep_freq_mult
                if sweep_freq >= self.stop_freq:
                    sweep_freq = 0
                    logging.info(f"{self.name}: AudioAnalyzer sweep finished.")
                    self.sweep(False)
                    self.buf_man.msgSend("Guido", "sweep_finished", None)

            # --- Stop the Sweep ---
            elif self.sweep_running:
                logging.info(f"{self.name}: AudioAnalyzer sweep stopped.")
                self.sweep_running = False
                self.buf_man.msgSend("Gen", "play_tone", 0)    # Turn off Gen

        logging.info("AudioAnalyzer finished")
        self.finished.emit()

# ==============================================================================
# MODULE TESTBENCH
#
if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    logging.info(f"Hey User!  This is just testing {__file__}")

    audio_ana1 = AudioAnalyzer("aud1")
    audio_ana2 = AudioAnalyzer("aud2")

    # Create Threads
    thread_list = list()
    thread_list.append(threading.Thread(target=audio_ana1.run, daemon=True))
    thread_list.append(threading.Thread(target=audio_ana2.run, daemon=True))

    # Start Threads
    logging.info("--- START OFF " + "-"*40)
    for thread in thread_list:
        thread.start()

    # Do Some Manual Controls
    time.sleep(5)
    logging.info("--- NOW AUD1 ON " + "-"*40)
    audio_ana1.enable()
    time.sleep(5)
    logging.info("--- NOW AUD2 ON " + "-"*40)
    audio_ana1.enable(False)
    audio_ana2.enable(True)
    time.sleep(5)
    logging.info("--- BOTH ON " + "-"*40)
    audio_ana1.enable()
    time.sleep(5)
    logging.info("--- DONE " + "-"*40)