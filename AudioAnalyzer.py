# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging

import BufferManager as BufMan

import numpy as np
from scipy.fft import rfft, rfftfreq


# ==============================================================================
# CLASS DEFINITION
#
class AudioAnalyzer(QObject):
    """ Class: AudioAnalyzer
        Analyzes incoming audio data

        Inherits from:
            QObject     - Allows object to be assigned to QThread to run in the background.
    """

    sig_newdata = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, name="aud_ana"):
        super().__init__()
        self._audio_on = False
        self._stop_requested = False
        self.name = name
        self.buf_man = BufMan.BufferManager("AudioAnalyzer")
        self.hist_dur = 3      # Length [seconds] of history buffer
        self.hist_list = []    # List of recent analysis runs.  [timestamp, freq_list, ampl_list]

    def enable(self, audio_on=True):
        self._audio_on = audio_on
        logging.info(f"AudioAnalyzer enable = {audio_on}")

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

    def analyze(self, mic_buf_id):
        # Retrieve buffer with mic waveform
        [time_list, volt_list] = self.buf_man.free(mic_buf_id)

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
        spec_buf_id = self.buf_man.alloc(spec_buf)
        self.sig_newdata.emit(spec_buf_id)
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
        spec_buf_id = self.buf_man.alloc(spec_buf)
        self.sig_newdata.emit(spec_buf_id)

    def run(self):
        logging.info("AudioAnalyzer started")
        self._stop_requested = False
        it_cnt = 0
        while not self._stop_requested:
            it_cnt += 1
            if self._audio_on:
                logging.info(f"{self.name}({it_cnt:02d}): AudioAnalyzer is running.")
            time.sleep(1)
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