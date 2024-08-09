# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging

import BufferManager as BufMan

import numpy as np


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

    def enable(self, audio_on=True):
        self._audio_on = audio_on
        logging.info(f"AudioAnalyzer enable = {audio_on}")

    def stop(self):
        logging.info("AudioAnalyzer stop requested")
        self._stop_requested = True

    def run(self):
        logging.info("AudioAnalyzer started")
        self._stop_requested = False
        it_cnt = 0
        while not self._stop_requested:
            it_cnt += 1
            if self._audio_on:
                logging.info(f"{self.name}({it_cnt:02d}): Analyzed something.")
                buf = np.random.randint(0, 10, 1000)
                buf_id = self.buf_man.alloc(buf)
                self.sig_newdata.emit(buf_id)
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
