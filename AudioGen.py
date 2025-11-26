# ==============================================================================
# IMPORTS
#
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
import time
import logging
import re
import pyaudio as pa
import numpy as np

from datetime import datetime

import BufferManager as BufMan

import csv

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
        self._new_tone = False
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
        self.run_time = None           # Running time

        self.delayMeasPeak_TS = None   # Timestamp of last generated delay measurement peak

        # Set Up Debug File
        self.dbg_gen_file = None
        #self.dbg_gen_file = 'dbg_gen' + datetime.now().strftime("_%y%m%d_%H%M%S") + '.csv'  # Set to None to disable
        if not self.dbg_gen_file is None:
            with open(self.dbg_gen_file, mode='a') as csv_file:
                csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                csv_writer.writerow(['Time', 'Amplitude', 'Buf_Index', 'Buf_Time'])

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

        elif msg_type == "gen_pulse":
            self.genPulse(msg_data)

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

        elif msg_type == "REQ_mode":
            ack_data = self.mode
        elif msg_type == "REQ_vol":
            ack_data = 20*np.log10(self.vol)   # dB
        elif msg_type == "REQ_delay_meas_peak_ts":
            ack_data = self.delayMeasPeak_TS

        else:
            logging.error(f"{self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")

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

        pulse_state = "IDLE"
        prev_pulse_state = "IDLE"
        while not self._stop_requested:
            # Determine Volume We'll Finish the Buffer With
            #     If the volume changes, we'll bleed that out over the course of the buffer
            #     to avoid audible pops when changing the volume
            end_vol = self.vol
            mode = self.mode

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
                self.run_time = None
                pulse_state = "IDLE"

            # Otherwise, Generate Output
            else:
                # Start Run Time
                buf_time = datetime.now().timestamp()
                if self.run_time is None:
                    self.run_time = buf_time

                # Generate Delay Measurement Pulse
                if mode == "Delay Meas":
                    if pulse_state == "IDLE":                # Step 1: Ramp down to 0
                        end_vol = 0
                        pulse_state = "RAMP_QUIET"
                    elif pulse_state == "RAMP_QUIET":       # Step 2: Ramp up to volume
                        pulse_state = "PULSE_RAMP_UP"
                    elif pulse_state == "PULSE_RAMP_UP":     # Step 3: Ramp back down to 0
                        end_vol = 0
                        pulse_state = "PULSE_DONE"
                    elif pulse_state == "PULSE_DONE":
                        end_vol = 0
                        pulse_state = "IDLE"
                        self.mode = "Delay Meas DONE"
                        self.enable(False)
                    else:
                        logging.error("Invalid pulse state")
                        pulse_state = "IDLE"
                else:
                    pulse_state = "IDLE"

                # Debug Pulse Generation
                if False and pulse_state != prev_pulse_state:
                    logging.info(f"Generator pulse state = {pulse_state}")
                    prev_pulse_state = pulse_state

                # Start with Tone of Unit Amplitude
                if (mode == "Single Tone") or (mode == "Sweep") or (mode == "Delay Meas"):
                    # keep track of current frequency
                    prevFreq = self.currFreq
                    self.currFreq = self.freq
                    self.t_start = self.t_end * prevFreq / self.currFreq
                    self.t_end = self.t_start + (self.numSamples / self.rate)
                    time_array = np.linspace(start=self.t_start, stop=self.t_end, num=self.numSamples, endpoint=False)

                    # equation: y = volume * sin(2 * pi * freq * time)
                    # np.linspace(start, stop, num samples, don't include last sample)
                    pitch_array = np.sin(2 * np.pi * self.currFreq * time_array)

                elif mode == "Noise":
                    pitch_array = (self.currVol * np.random.rand(self.numSamples)).astype(np.float32)

                else:
                    pitch_array = (np.array([0] * self.numSamples)).astype(np.float32)

                # Scale Tone with Volume
                #     Here, we'll bleed out any changes in volume over the course of the output buffer
                vol_array = np.linspace(start=self.currVol, stop=end_vol, num=self.numSamples, endpoint=False)
                self.currVol = end_vol
                out_array = np.multiply(pitch_array, vol_array).astype(np.float32)

                # Write to Output
                out_time = datetime.now()
                out_time_TS = out_time.timestamp()
                stream.write(out_array, num_frames=self.numSamples)
                if not self.dbg_gen_file is None:
                    with open(self.dbg_gen_file, mode='a') as csv_file:
                        csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                        for buf_nind, buf_ampl in np.ndenumerate(out_array):
                            buf_ind = buf_nind[0]   # ndenumerate() gives us an n-dimensional index.  We want 1st dimension
                            csv_writer.writerow([self.run_time + (buf_ind / self.rate), buf_ampl, buf_ind, buf_time])
                self.run_time += self.numSamples / self.rate

                # Send a message to Mic to indicate which sweep freq he should be reading
                if self._new_tone:
                    self.buf_man.msgSend("Mic", "curr_sweep_freq", [self.freq, out_time_TS])
                    self._new_tone = False

                if pulse_state == "PULSE_DONE":
                    logging.info(f"Delay measurement {self.currFreq:.1f}Hz peak generated at T = {out_time_TS:.9f} = {out_time}")
                    self.delayMeasPeak_TS = out_time_TS

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
                #logging.info(f"AudioGen freq = {newFreq}Hz ==> {self.freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.freq = C_FREQ_MAX
                #logging.info(f"AudioGen freq = {newFreq}Hz ==> {self.freq}Hz = MAX")
            else:
                self.freq = newFreq
                #logging.info(f"AudioGen freq = {self.freq}Hz")

    def changeVol(self, newVolDB):
        logging.info(f"DBG: Changing volume to {newVolDB}")
        if isinstance(newVolDB, int):
            newVolDB = float(newVolDB)
        elif isinstance(newVolDB, str) and re.search('^[+-]?\d+(\.\d+)?$', newVolDB):
            newVolDB = float(newVolDB)

        if isinstance(newVolDB, float):
            if (newVolDB >= 1):
                self.vol = 1
                logging.info(f"AudioGen volume = 1.0 = 0dB = ABS MAX")
            elif (newVolDB >= C_VOL_MAX_DB):
                self.vol = float(10**(C_VOL_MAX_DB/20))
                logging.info(f"AudioGen volume = {self.vol} = {20*np.log10(self.vol)}dB = MAX")
            elif (newVolDB <= C_VOL_MIN_DB):
                self.vol = 0
                logging.info(f"AudioGen volume = 0.0 = OFF")
            else:
                self.vol = float(10**(newVolDB/20))
                logging.info(f"AudioGen volume = {self.vol} = {20*np.log10(self.vol)}dB ")

    def changeMode(self, newMode):
        logging.info(f"Gen changing mode to {newMode}")
        self.mode = newMode

    def playTone(self, playFreq):
        # First tell Mic that any previous tone has stopped, and confirm that it was seen
        out_time_TS = datetime.now().timestamp()
        self.buf_man.msgSend("Mic", "curr_sweep_freq", [0, out_time_TS])
        self.buf_man.msgSend("Mic", "REQ_curr_sweep_freq")

        # Check for Out of Bounds
        if (playFreq < C_FREQ_MIN) or (playFreq > C_FREQ_MAX):
            self._audio_on = False

        # Start the Tone
        else:
            self.freq = playFreq
            self._audio_on = True
            self._new_tone = True    # Set flag so run() will tell Mic after tone starts

    def genPulse(self, pulseFreq):
        # Check for Out of Bounds
        if (pulseFreq >= C_FREQ_MIN) and (pulseFreq <= C_FREQ_MAX):
            self.freq = pulseFreq

        if self.mode == "Delay Meas DONE":
            self.mode = "Delay Meas"

        if self.mode == "Delay Meas":
            logging.info("Clearing delayMeasPeak_TS")
            self.delayMeasPeak_TS = None
            self.enable(True)
        else:
            logging.error(f"Attempting to generate pulse while in {self.mode} mode, not in Delay Meas mode.  Aborting attempt.")

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