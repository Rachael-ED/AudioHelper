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

    sig_micdata = pyqtSignal(int)

    def __init__(self, name="aud_ana"):
        super().__init__()
        self._audio_on = False
        self._stop_requested = False
        self.name = name
        self.buf_man = BufMan.BufferManager("AudioAnalyzer")

    def enable(self, audio_on=True):
        self._audio_on = audio_on
        logging.info(f"AudioAnalyzer enable = {audio_on}")

    def stop(self):
        logging.info("AudioAnalyzer stop requested")
        self._stop_requested = True

    def analyze(self, mic_buf_id):
        mic_buf = self.buf_man.free(mic_buf_id)
        meas_t = mic_buf[0]
        meas_v = mic_buf[1]

        num_samp = len(meas_v)            # Number of audio samples
        t_samp = meas_t[1] - meas_t[0]  # Audio sampling period

        meas_f = rfftfreq(num_samp, t_samp)   # Frequency of measurement spectrum
        meas_fft = rfft(meas_v)                 # FFT of measurement
        meas_p = np.abs(meas_fft)

        spec_buf = [meas_f, meas_p]
        spec_buf_id = self.buf_man.alloc(spec_buf)
        self.sig_newdata.emit(spec_buf_id)
        logging.info(f"{self.name}: Analyzed spectrum.")


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
