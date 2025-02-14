# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging

import BufferManager as BufMan

import numpy as np
import pyaudio as pa

# ==============================================================================
# CLASS DEFINITION
#
class MicReader(QObject):
    """ Class: MicInput
        Reads in mic data

        Inherits from:
            QObject     - Allows object to be assigned to QThread to run in the background.
    """

    sig_newdata = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, format, channels, rate, name="mic_inp"):
        super().__init__()
        self._audio_on = False
        self._stop_requested = False
        self.name = name
        self.buf_man = BufMan.BufferManager("MicInput")
        # --- FROM RACHAEL'S CODE ---
        self.format = format
        self.channels = channels
        self.rate = rate
        self.framesPerBuffer = 16384     # i.e. 2^14
        #self.inputIndex = 1     # For Rachael's MacBook Pro WITH headphones, computer mic = 2, else mic = 1
        #self.inputIndex = 2     # For Fahthar's MacBook Pro MacBook mic = 2
        self._reopen_stream = False

        # instantiate PyAudio
        p = pa.PyAudio()
        # find number of devices (input and output)
        numDevices = p.get_device_count()

        for i in range(0, numDevices):
            if p.get_device_info_by_index(i).get('maxInputChannels') != 0:
                self.inputIndex = i
                logging.info(f"Default input: {p.get_device_info_by_index(i).get('name')}")
                break

    def enable(self, audio_on=True):
        self._audio_on = audio_on
        logging.info(f"MicInput enable = {audio_on}")

    def stop(self):
        logging.info("MicInput stop requested")
        self._stop_requested = True

    def run(self):
        logging.info("MicInput started")
        self._stop_requested = False

        # instantiate PyAudio
        micInput = pa.PyAudio()
        # set up a stream
        stream = micInput.open(format=self.format, channels=self.channels, rate=self.rate, input=True, input_device_index=self.inputIndex, frames_per_buffer=self.framesPerBuffer)

        # time array
        t = np.linspace(start=0, stop=(self.framesPerBuffer - 1)/self.rate, num=self.framesPerBuffer).astype(np.float32)
        while not self._stop_requested:

            if self._reopen_stream:
                # instantiate PyAudio
                micInput = pa.PyAudio()
                # set up a stream
                stream = micInput.open(format=self.format, channels=self.channels, rate=self.rate, input=True,
                                       input_device_index=self.inputIndex, frames_per_buffer=self.framesPerBuffer)
                self._reopen_stream = False

            if self._audio_on:
                data = stream.read(self.framesPerBuffer, exception_on_overflow=False)
                dataAsVoltage = np.frombuffer(data, dtype=np.float32)
                voltageAndTime = [t, dataAsVoltage]
                buf_id = self.buf_man.alloc(voltageAndTime)
                self.sig_newdata.emit(buf_id)
            else:
                time.sleep(1)

        # release resources
        logging.info("MicInput finished")
        stream.stop_stream()
        stream.close()
        micInput.terminate()
        self.finished.emit()


    def changeInputIndex(self, newInputIndex):
        self.inputIndex = newInputIndex
        self._reopen_stream = True
        logging.info(f"input index: {newInputIndex}")

# ==============================================================================
# MODULE TESTBENCH
#
'''
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
'''