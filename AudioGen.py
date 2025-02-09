# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging
import re
import pyaudio as pa
import numpy as np

# ==============================================================================
# CONSTANTS AND GLOBALS
#
C_VOL_MAX_DB = 0
C_VOL_MIN_DB = -60

C_FREQ_MAX = 20000
C_FREQ_MIN = 50

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

    # Comment by Rachael

    def __init__(self, format, channels, rate, framesPerBuffer, freq, vol_db, name="aud_gen"):
        super().__init__()
        self._audio_on = False
        self._stop_requested = False
        self.name = name
        self.mode = "Single Tone"
        self.format = format
        self.channels = channels
        self.rate = rate                         # sampling rate = frame rate
        self.framesPerBuffer = framesPerBuffer   # 1 "frame" = 1 sample on all channels
        self.freq = freq
        self.currVol = 0                     # Start at no volume
        self.vol = 10**(vol_db/20)           # ... and ramp to target when enabled
        #self.outputIndex = 2  # for Rachael WITH headphones, 1 = headphones, 3 = speakers, else speaker = 2
        self.outputIndex = 0  # for Fahthar, 0 = monitor, 3 = MacBook Pro
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
            # Determine Volume We'll Finish the Buffer With
            #     If the volume changes, we'll bleed that out over the course of the buffer
            #     to avoid audible pops when changing the volume
            end_vol = self.vol
            if not self._audio_on:
                end_vol = 0

            # Don't Output Anything if Fully Stopped
            if (self.currVol == 0) and (end_vol == 0):
                self.t_start = 0
                self.t_end = self.numSamples/self.rate
                time.sleep(1)

            # Otherwise, Generate Output
            else:
                # Start with Tone of Unit Amplitude
                if self.mode == "Single Tone":
                    # keep track of current frequency
                    prevFreq = self.currFreq
                    self.currFreq = self.freq
                    self.t_start = self.t_end * prevFreq / self.currFreq
                    self.t_end = self.t_start + (self.numSamples / self.rate)
                    time_array = np.linspace(start=self.t_start, stop=self.t_end, num=self.numSamples, endpoint=False)

                    # print(self.currFreq)
                    # equation: y = volume * sin(2 * pi * freq * time)
                    # np.linspace(start, stop, num samples, don't include last sample)
                    pitch_array = np.sin(2 * np.pi * self.currFreq * time_array)

                    ###pitch = (self.currVol * np.sin(2 * np.pi * self.currFreq * (np.linspace(start=self.t_start, stop=self.t_end, num=self.numSamples, endpoint=False)))).astype(np.float32)
                elif self.mode == "Noise":
                    pitch_array = (self.currVol * np.random.rand(self.numSamples)).astype(np.float32)

                else:
                    pitch_array = (np.array([0] * self.numSamples)).astype(np.float32)

                # Scale Tone with Volume
                #     Here, we'll bleed out any changes in volume over the course of the output buffer
                vol_array = np.linspace(start=self.currVol, stop=end_vol, num=self.numSamples, endpoint=False)
                self.currVol = end_vol
                out_array = np.multiply(pitch_array, vol_array).astype(np.float32)

                # Write to Output
                stream.write(out_array, num_frames=self.numSamples)

        logging.info("AudioGen finished")
        # release resources
        stream.close()
        sound.terminate()
        self.finished.emit()

    def changeFreq(self, newFreq):
        if re.search('^\d+(\.\d+)?', newFreq):
            newFreq = float(newFreq)   # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.freq = C_FREQ_MIN
                logging.info(f"AudioGen freq = {self.freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.freq = C_FREQ_MAX
                logging.info(f"AudioGen freq = {self.freq}Hz = MAX")
            else:
                self.freq = newFreq
                logging.info(f"AudioGen freq = {self.freq}Hz")

    def changeVol(self, newVolDB):
        if re.search('^[+-]?\d+(\.\d+)?', newVolDB):
            newVolDB = float(newVolDB)   # Translate string to number
            if (newVolDB >= C_VOL_MAX_DB):
                self.vol = 1
                logging.info(f"AudioGen volume = 1.0 = 0dB = MAX")
            elif (newVolDB <= C_VOL_MIN_DB):
                self.vol = 0
                logging.info(f"AudioGen volume = 0.0 = OFF")
            else:
                self.vol = float(10**(newVolDB/20))
                logging.info(f"AudioGen volume = {self.vol} = {20*np.log10(self.vol)}dB ")

    def changeMode(self, newMode):
        self.mode = newMode

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

