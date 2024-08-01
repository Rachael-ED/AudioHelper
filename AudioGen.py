# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging
import pyaudio as pa
import numpy as np


# ==============================================================================
# CLASS DEFINITION
#
class AudioGen(QObject):
    """ Class: AudioGen
        Generates tones on audio output

        Inherits from:
            QObject     - Allows object to be assigned to QThread to run in the background.
    """

    finished = pyqtSignal()

    def __init__(self, format, channels, rate, framesPerBuffer, freq, name="aud_gen"):
        super().__init__()
        self._audio_on = False
        self._stop_requested = False
        self.name = name
        # --- FROM RACHAEL'S CODE ---
        self.format = format
        self.channels = channels
        self.rate = rate
        self.framesPerBuffer = framesPerBuffer
        self.freq = freq
        self.vol = 1
        self.outputIndex = 3  # for Rachael, 1 = headphones, 3 = speakers
        #self.outputIndex = 0  # for Fahthar, 0 = monitor, 3 = MacBook Pro
        self.numSamples = 1000
        self.t_start = 0
        self.t_end = self.numSamples / self.rate
        self.currFreq = freq

    def enable(self, audio_on=True):
        self._audio_on = audio_on
        logging.info(f"AudioGen enable = {audio_on}")

    def stop(self):
        logging.info("AudioGen stop requested")
        self._stop_requested = True

    def run(self):
        logging.info("AudioGen started")
        self._stop_requested = False

        # instantiate PyAudio
        sound = pa.PyAudio()
        # set up a stream
        # output_device_index: For Rachael's MacBook Pro, headphones = 1, speakers = 3
        stream = sound.open(format=self.format, channels=self.channels, rate=self.rate, output=True,
                            output_device_index=self.outputIndex, frames_per_buffer=self.framesPerBuffer)

        while not self._stop_requested:
            if self._audio_on:
                # keep track of current frequency
                self.currFreq = self.freq
                # print(self.currFreq)
                # equation: y = volume * sin(2 * pi * freq * time)
                # np.linspace(start, stop, num samples, don't include last sample)
                pitch = (self.vol * np.sin(2 * np.pi * self.currFreq * (np.linspace(start=self.t_start, stop=self.t_end, num=self.numSamples, endpoint=False)))).astype(np.float32)
                stream.write(pitch, num_frames=self.numSamples)
                # define t_start
                self.t_start = self.t_startAtValt_end()
                self.t_end = self.t_start + (self.numSamples / self.rate)
                # print(pitch)
                # print("\n\n\n")
            else:
                self.t_start = 0
                self.t_end = self.numSamples/self.rate

        logging.info("AudioGen finished")
        # release resources
        stream.close()
        sound.terminate()
        self.finished.emit()

    def t_startAtValt_end(self):
        # find what time on the new wave the y-val = valAt_t_end
        tAt_t_end = (2 * np.pi * self.currFreq * self.t_end)/(2 * np.pi * self.freq)
        return tAt_t_end

    def changeFreq(self, newFreq):
        self.freq = newFreq


# ==============================================================================
# MODULE TESTBENCH
#

'''
if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    logging.info(f"Hey User!  This is just testing {__file__}")

    FORMAT = pa.paFloat32
    CHANNELS = 1
    RATE = 44100
    FRAMES_PER_BUFFER = 1024

    audio_gen1 = AudioGen(FORMAT, CHANNELS, RATE, FRAMES_PER_BUFFER, "aud1")
    audio_gen2 = AudioGen(FORMAT, CHANNELS, RATE, FRAMES_PER_BUFFER,"aud2")

    # Create Threads
    thread_list = list()
    thread_list.append(threading.Thread(target=audio_gen1.run, daemon=True))
    thread_list.append(threading.Thread(target=audio_gen2.run, daemon=True))

    # Start Threads
    logging.info("--- START OFF " + "-"*40)
    for thread in thread_list:
        thread.start()

    # Do Some Manual Controls
    time.sleep(5)
    logging.info("--- NOW AUD1 ON " + "-"*40)
    audio_gen1.enable()
    time.sleep(5)
    logging.info("--- NOW AUD2 ON " + "-"*40)
    audio_gen1.enable(False)
    audio_gen2.enable(True)
    time.sleep(5)
    logging.info("--- BOTH ON " + "-"*40)
    audio_gen1.enable()
    time.sleep(5)
    logging.info("--- DONE " + "-"*40)
'''

