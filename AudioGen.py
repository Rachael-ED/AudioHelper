# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import time
import logging
import re
import pyaudio as pa
import numpy as np

import BufferManager as BufMan

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

    # Signals for IPC
    sig_ipc_guido = pyqtSignal(int)
    sig_ipc_mic = pyqtSignal(int)
    sig_ipc_ana = pyqtSignal(int)

    # Comment by Rachael

    def __init__(self, format, channels, rate, framesPerBuffer, name="Gen"):
        super().__init__()

        # Set Up Dictionary with IPC Signals for BufMan
        ipc_dict = {       # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
            "Guido": self.sig_ipc_guido,
            "Mic": self.sig_ipc_mic,
            "Ana": self.sig_ipc_ana
        }

        # Create Buffer Manager
        self.name = name
        self.buf_man = BufMan.BufferManager(name, ipc_dict)

        self._audio_on = False
        self._stop_requested = False
        self.mode = "Single Tone"
        self.format = format
        self.channels = channels
        self.rate = rate                         # sampling rate = frame rate
        self.framesPerBuffer = framesPerBuffer   # 1 "frame" = 1 sample on all channels
        self.freq = 440
        self.vol = 0
        self.numSamples = 1000
        self.t_start = 0
        self.t_end = self.numSamples / self.rate
        self.currFreq = self.freq
        self.currVol = 0
        self._reopen_stream = False

        # instantiate PyAudio
        p = pa.PyAudio()
        # find number of devices (input and output)
        numDevices = p.get_device_count()

        self.dev_ind_to_name = {-1: "None"}
        self.dev_name_to_ind = {"None": -1}
        self.outputIndex = -1
        for i in range(0, numDevices):
            if p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
                dev_name = p.get_device_info_by_index(i).get('name')
                self.dev_ind_to_name[i] = dev_name
                self.dev_name_to_ind[dev_name] = i
                if self.outputIndex == -1:
                    self.outputIndex = i
                    logging.info(f"Default output: {dev_name}")

    # Handle Messages from Other Objects
    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        ###logging.info(f"{self.name} received {msg_type} from {snd_name} : {msg_data}")
        ack_data = None

        # Process Message
        if msg_type == "enable":
            self.enable(msg_data)

        elif msg_type == "play_tone":
            self.playTone(msg_data)

        elif msg_type == "silent":
            self.enable(False)
            self.playTone(False)

        elif msg_type == "change_output":
            self.changeOutputIndex(msg_data)

        elif msg_type == "change_mode":
            self.changeMode(msg_data)

        elif msg_type == "change_freq":
            self.changeFreq(msg_data)

        elif msg_type == "change_vol":
            self.changeVol(msg_data)

        elif msg_type == "cfg_load":
            for param in msg_data.keys():
                val = msg_data[param]
                if (param == "outputDevice") and (val in self.dev_name_to_ind):
                    self.changeOutputIndex(self.dev_name_to_ind[val])

        elif msg_type == "REQ_cfg_save":
            ack_data = {
                "outputDevice": self.dev_ind_to_name[self.outputIndex]
            }

        elif msg_type == "REQ_cfg":
            ack_data = {
                "enable": self._audio_on,
                "mode": self.mode,
                "format": self.format,
                "channels": self.channels,
                "rate": self.rate,
                "framesPerBuffer": self.framesPerBuffer ,
                "freq" : self.freq,
                "vol": self.vol,
                "outputIndex": self.outputIndex,
                "numSamples": self.numSamples
            }

        elif msg_type == "REQ_sweep_mode":
            if self.mode == "Sweep":
                ack_data = True
            else:
                ack_data = False

        else:
            logging.info(f"ERROR: {self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")

        # Acknowledge/Release Message
        self.buf_man.msgAcknowledge(buf_id, ack_data)

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

            # if the output device index is changed, the stream needs to be reopened
            if self._reopen_stream:
                # instantiate PyAudio
                sound = pa.PyAudio()
                # set up a stream
                # output_device_index: For Rachael's MacBook Pro, headphones = 1, speakers = 3
                stream = sound.open(format=self.format, channels=self.channels, rate=self.rate, output=True,
                                    output_device_index=self.outputIndex, frames_per_buffer=self.framesPerBuffer)
                self._reopen_stream = False

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
                if (self.mode == "Single Tone") or (self.mode == "Sweep"):
                    # keep track of current frequency
                    prevFreq = self.currFreq
                    self.currFreq = self.freq
                    self.t_start = self.t_end * prevFreq / self.currFreq
                    self.t_end = self.t_start + (self.numSamples / self.rate)
                    time_array = np.linspace(start=self.t_start, stop=self.t_end, num=self.numSamples, endpoint=False)

                    # equation: y = volume * sin(2 * pi * freq * time)
                    # np.linspace(start, stop, num samples, don't include last sample)
                    pitch_array = np.sin(2 * np.pi * self.currFreq * time_array)

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
        if re.search('^\d+(\.\d+)?$', newFreq):
            newFreq = float(newFreq)   # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.freq = C_FREQ_MIN
                #logging.info(f"AudioGen freq = {self.freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.freq = C_FREQ_MAX
                #logging.info(f"AudioGen freq = {self.freq}Hz = MAX")
            else:
                self.freq = newFreq
                #logging.info(f"AudioGen freq = {self.freq}Hz")

    def changeVol(self, newVolDB):
        if re.search('^[+-]?\d+(\.\d+)?$', newVolDB):
            newVolDB = float(newVolDB)   # Translate string to number
            if (newVolDB >= C_VOL_MAX_DB):
                self.vol = 1
                #logging.info(f"AudioGen volume = 1.0 = 0dB = MAX")
            elif (newVolDB <= C_VOL_MIN_DB):
                self.vol = 0
                #logging.info(f"AudioGen volume = 0.0 = OFF")
            else:
                self.vol = float(10**(newVolDB/20))
                #logging.info(f"AudioGen volume = {self.vol} = {20*np.log10(self.vol)}dB ")

    def changeMode(self, newMode):
        self.mode = newMode

    def playTone(self, playFreq):
        if (playFreq < C_FREQ_MIN) or (playFreq > C_FREQ_MAX):
            self._audio_on = False
        else:
            self.freq = playFreq
            self._audio_on = True

        # send a message to Mic to indicate which sweep freq he should be reading
        self.buf_man.msgSend("Mic", "curr_sweep_freq", playFreq)

    def changeOutputIndex(self, newOutputIndex):
        self.outputIndex = newOutputIndex
        self._reopen_stream = True
        logging.info(f"output index: {newOutputIndex}")
        self.buf_man.msgSend("Guido", "default_output", self.outputIndex)

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