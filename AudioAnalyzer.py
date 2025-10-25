
# ==============================================================================
# IMPORTS
#
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
import threading
import time
import logging
import re

from datetime import datetime

import BufferManager as BufMan

import numpy as np
from scipy.fft import rfft, rfftfreq

import csv

# ==============================================================================
# CONSTANTS AND GLOBALS
#
C_FREQ_MAX = 20000
C_FREQ_MIN = 50

C_GAIN_MAX_DB = 200
C_GAIN_MIN_DB = 0

C_SWEEP_POINTS_MAX = 100
C_SWEEP_POINTS_MIN = 1

C_HIST_DUR_MAX = 10    # Same as C_AVG_DUR_MAX in Guido
C_HIST_DUR_MIN = 0     # Same as C_AVG_DUR_MIN in Guido

C_SWEEP_DWELL_DUR = 0.1    # Time for each sweep tone [s]

C_SWEEP_BASELINE_VOL = 10 ** (-12/20)   # -12dB

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
        self.gain_db  = 60
        self.hist_dur = 3      # Length [seconds] of history buffer
        self.hist_list = []    # List of recent analysis runs.  [timestamp, freq_list, ampl_list]

        self.apply_cal = False    # False = Don't use.  True = Use.  None = Remove.  String = Capture plot line
        self.cal_freq_list = []
        self.cal_ampl_list = []

        self.sweepFreqs = [np.nan] * self.sweep_points
        self.sweepAmpls = [np.nan] * self.sweep_points
        self.numSweepFreqs = 0
        self.found = True
        self.freqFromMic = 0
        self.pastPeaks = [np.nan] * 2
        self.rejects = 0

        self.analysis_num = 0    # Just a running counter of times analyze() is called, for debug
        self.threshold = 0.90

        # Set Up Debug File
        self.dbg_ana_file = None
        #self.dbg_ana_file = 'dbg_ana' + datetime.now().strftime("_%y%m%d_%H%M%S") + '.csv'  # Set to None to disable

    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        ###logging.info(f"{self.name} received {msg_type} from {snd_name} : {msg_data}")
        ack_data = None

        # Process Message
        if msg_type == "mic_data":
            self.analyze(msg_data)

        elif msg_type == "sweep":
            self.sweep(msg_data)

        elif msg_type == "apply_cal":
            self.apply_cal = msg_data

        elif msg_type == "change_start_freq":
            self.changeStartFreq(msg_data)

        elif msg_type == "change_stop_freq":
            self.changeStopFreq(msg_data)

        elif msg_type == "change_gain_db":
            self.changeGainDb(msg_data)

        elif msg_type == "change_sweep_points":
            self.changeSweepPoints(msg_data)

        elif msg_type == "change_hist_dur":
            self.changeHistDur(msg_data)

        elif msg_type == "cfg_load":
            pass

        elif msg_type == "REQ_cfg_save":
            pass

        elif msg_type == "clear_sweep":
            print("clearing")
            self.sweepFreqs = [np.nan] * self.sweep_points
            self.sweepAmpls = [np.nan] * self.sweep_points

        elif msg_type == "mic_data_sweep":
            self.freqFromMic = msg_data[1]
            self.analyze(msg_data[0])
        elif msg_type == "change_threshold":
            #print("THRESHOLD!!!")
            self.threshold = msg_data
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

    def changeGainDb(self, newGainDb):
        if newGainDb <= C_GAIN_MIN_DB:
            self.gain_db = C_GAIN_MIN_DB
            #logging.info(f"AudioAna gain_db = {self.gain_db}dB = MIN")
        elif newGainDb >= C_GAIN_MAX_DB:
            self.gain_db = C_GAIN_MAX_DB
            #logging.info(f"AudioAna gain_db = {self.gain_db}dB = MAX")
        else:
            self.gain_db = newGainDb
            #logging.info(f"AudioAna gain_db = {self.gain_db}dB")

    def changeSweepPoints(self, newSweepPoints):
        if re.search('^[+-]?\d+(\.\d+)?$', newSweepPoints):
            newSweepPoints = int(newSweepPoints)   # Translate string to number
            if newSweepPoints <= C_SWEEP_POINTS_MIN:
                self.sweep_points = C_SWEEP_POINTS_MIN
                #logging.info(f"AudioAna sweep_points = {self.sweep_points} = MIN")
            elif newSweepPoints >= C_SWEEP_POINTS_MAX:
                self.sweep_points = C_SWEEP_POINTS_MAX
                #logging.info(f"AudioAna sweep_points = {self.sweep_points} = MAX")
            else:
                self.sweep_points = newSweepPoints
                #logging.info(f"AudioAna sweep_points = {self.sweep_points}")

    def changeHistDur(self, newHistDur):
        if newHistDur <= C_HIST_DUR_MIN:
            self.hist_dur = C_HIST_DUR_MIN
            #logging.info(f"AudioAna hist_dur = {self.hist_dur}s = MIN")
        elif newHistDur >= C_HIST_DUR_MAX:
            self.hist_dur = C_HIST_DUR_MAX
            #logging.info(f"AudioAna hist_dur = {self.hist_dur}s = MAX")
        else:
            self.hist_dur = newHistDur
            #logging.info(f"AudioAna hist_dur = {self.hist_dur}s")

    def stop(self):
        logging.info("AudioAnalyzer stop requested")
        self._stop_requested = True

    def hist_clean(self):
        cur_time = time.monotonic()
        age_out_time = cur_time - self.hist_dur
        ind = 0   # Index of oldest entry that has not aged out
        while ind < len(self.hist_list):
            [timestamp, freq_list, ampl_list, swp_data_list] = self.hist_list[ind]
            if timestamp >= age_out_time:
                break
            ind += 1
        if ind >= len(self.hist_list):   # All entries have aged out
            self.hist_list = []
        elif ind > 0:                    # Some entries have aged out
            del self.hist_list[:ind]

    def hist_add(self, freq_list, ampl_list, swp_data_list):
        self.hist_clean()
        self.hist_list.append([time.monotonic(), freq_list, ampl_list, swp_data_list])

    # Translates an amplitude spectrum with one set of frequencies to a different set of frequencies.
    # We'll do this by interpolating in a log-log sense, so that a new point at a new frequency
    #     would appear linearly interpolated between two points of the reference when viewed on a
    #     dB vs. log(f) plot.
    # For new frequencies which lie outside the reference range, we have no other information
    #     so we'll just extend the closest frequency of the reference.
    def refreq_ampl(self, ref_freq_list, ref_ampl_list, new_freq_list):
        # Translate incoming lists to log
        ref_log_freq_list = np.log(np.clip(ref_freq_list, 1e-12, None))
        ref_log_ampl_list = np.log(np.clip(ref_ampl_list, 1e-12, None))
        new_log_freq_list = np.log(np.clip(new_freq_list, 1e-12, None))

        # Build list of ref indices for each new freq such that the ref freq <= new freq
        #     Example:
        #         ref_ind        0     1     2     3
        #         ref_freq      10    20    30    40
        #         new_freq    5 10 15 20 25 30 35 40 45
        #         srch_ind    0  0  1  1  2  2  3  3  4
        # With this, we can linearly interpolate at the new frequency between the ref points at
        #     index srch_ind-1 and srch_ind, handling the special cases at the boundaries separately.
        srch_ind_list = np.searchsorted(ref_freq_list, new_freq_list)

        # Prepend and append values to handle boundary conditions
        # When we do the linear interpolation/extrapolation, we need to use srch_ind and srch_ind-1.
        # To handle srch_ind == 0, we'll prepend a dummy entry and shift the srch_ind values by 1
        #     so we use indices 1 & 0 rather than 0 & -1.
        # To handle srch_ind > length of list, we'll append a dummy entry.
        # These dummy entries will just replicate the first/last y values (log_ampl)
        #     at one freq step before/after the first/last x value (freq).
        # This way, performing the same linear interpolation calc on the arrays results in just
        #     extending the first/last y value for any new x values left/right of the first/last ref x value.
        ref_freq_step = ref_freq_list[1] - ref_log_freq_list[0]
        ref_log_freq_list = np.insert(ref_log_freq_list, 0, ref_log_freq_list[0] - ref_freq_step)
        ref_log_ampl_list = np.insert(ref_log_ampl_list, 0, ref_log_ampl_list[0])
        srch_ind_list = srch_ind_list + 1    # Search results shift because of np.insert
        ref_log_freq_list = np.append(ref_log_freq_list, ref_log_freq_list[-1] + ref_freq_step)
        ref_log_ampl_list = np.append(ref_log_ampl_list, ref_log_ampl_list[-1])

        # Now, calc log amplitude at each new frequency
        ref2_ind_list = srch_ind_list
        x2_list = ref_log_freq_list[ref2_ind_list]
        y2_list = ref_log_ampl_list[ref2_ind_list]

        ref1_ind_list = srch_ind_list - 1
        x1_list = ref_log_freq_list[ref1_ind_list]
        y1_list = ref_log_ampl_list[ref1_ind_list]

        x_list = new_log_freq_list

        new_log_ampl_list = y1_list + ((y2_list - y1_list) / (x2_list - x1_list)) * (x_list - x1_list)

        """
            new_log_ampl_list = np.array([0] * len(new_freq_list)).astype(np.float64)
            for new_ind in range(0, len(new_freq_list)):
            ref2_ind = srch_ind_list[new_ind]
            ref1_ind = ref2_ind - 1

            if ref2_ind == 0:
                new_log_ampl_list[new_ind] = ref_log_ampl_list[ref2_ind]
            elif ref2_ind == len(new_freq_list):
                new_log_ampl_list[new_ind] = ref_log_ampl_list[ref1_ind]
            else:
                x = new_log_freq_list[new_ind]
                x2 = ref_log_freq_list[ref2_ind]
                x1 = ref_log_freq_list[ref1_ind]
                y2 = ref_log_ampl_list[ref2_ind]
                y1 = ref_log_ampl_list[ref1_ind]

                new_log_ampl_list[new_ind] = y1 + ((y2-y1)/(x2-x1))*(x-x1)
        """
        # Un-log the result
        new_ampl_list = np.exp(new_log_ampl_list)

        return new_ampl_list

    def analyze(self, voltageAndTime):
        # keep track of current sweep frequency
        ###print("getting new frequency from mic")
        currSweepFreq = self.freqFromMic
        #currBuffSize = self.framesPerBuff

        # Retrieve buffer with mic waveform
        [time_list, volt_list] = voltageAndTime

        self.analysis_num += 1
        write_dbg = False

        num_samp = len(volt_list)               # Number of audio samples
        t_samp = time_list[1] - time_list[0]    # Audio sampling period

        # Calculate Frequency Spectrum
        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)              # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)            # Amplitude spectrum of measurement

        # Remove DC element
        freq_list = np.delete(freq_list,0)
        ampl_list = np.delete(ampl_list,0)
        ampl_list = ampl_list*2/num_samp * 10**(self.gain_db/20)

        # Apply Calibration
        apply_cal = self.apply_cal
        if apply_cal == True:
            cal_ampl_list = self.cal_ampl_list
            if len(self.cal_ampl_list) != len(ampl_list):
                cal_ampl_list = self.refreq_ampl(self.cal_freq_list, self.cal_ampl_list, freq_list)
            ampl_list = np.divide(ampl_list, cal_ampl_list)

        ###print("sending to guido")
        # Send Amplitude Spectrum to Guido
        spec_buf = ["Live", freq_list, ampl_list]
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)

        #AInd = int(440/(freq_list[1]-freq_list[0])) - 1

        #power = ampl_list[AInd-1] + ampl_list[AInd] + ampl_list[AInd+1]
        #powerTot = np.sum(ampl_list ** 2)

        #print(f"Power BOI: {power} --- Power Total: {[powerTot]} --- {power/powerTot}")

        powerInBOI = None
        freq_found = False
        if (self.sweep_running == True):

            # compute total power
            powerTotal = np.sum(ampl_list ** 2)

            # figure out in which bucket the frequency should be
            distBtwnFreq = freq_list[1] - freq_list[0]
            i = int(currSweepFreq/distBtwnFreq) - 1

            # compute power in BOI (i.e. buckets of interest)
            ###powerInBOI = ((ampl_list[i-1]) ** 2) + ((ampl_list[i]) ** 2) + ((ampl_list[i+1]) ** 2)
            powerInBOI = 0
            window_width = 1
            for ind in range(i-window_width, i+window_width+1):
                powerInBOI += ampl_list[ind] ** 2

            print(f"Power BOI: {powerInBOI} = {20*np.log(powerInBOI)} dB --- Power Total: {[powerTotal]} --- {powerInBOI/powerTotal}")

            conv_ampl_list = np.convolve(ampl_list, ampl_list)
            max_ind = np.argmax(conv_ampl_list)
            det_freq = ((max_ind/2) + 1) * distBtwnFreq
            #print(f"Sweep Freq = {currSweepFreq} Hz.  Detected Freq = {det_freq} Hz.  Freq Resolution = {distBtwnFreq} Hz.")


            if powerInBOI/powerTotal > self.threshold and self.found == False:
                #print(f">> Found pure tone")
                freq_found = True

                for k in range(0, len(self.sweepFreqs)):

                    if self.sweepFreqs[k] == currSweepFreq:
                        break
                    elif np.isnan(self.sweepFreqs[k]):
                        #print("NaN Found")
                        self.sweepFreqs[k] = currSweepFreq
                        volume = self.buf_man.msgSend("Gen", "REQ_volume")
                        print(f"{volume}")
                        self.sweepAmpls[k] = np.sqrt(powerInBOI)/volume * C_SWEEP_BASELINE_VOL
                        self.found = True
                        spec_buf = ["Sweep", self.sweepFreqs, self.sweepAmpls]
                        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
                        break

            if abs(det_freq - currSweepFreq) < (distBtwnFreq/4):
                #print(f">> Found frequency")
                freq_found = True
        swp_data_list = [currSweepFreq, freq_found, powerInBOI]

        # Add to History
        self.hist_add(freq_list, ampl_list, swp_data_list)

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
        avg_freq_list = freq_list
        avg_ampl_list = np.array([0] * len(avg_freq_list)).astype(np.float64)
        for [hist_timestamp, hist_freq_list, hist_ampl_list, swp_data_list] in self.hist_list:
            adj_hist_ampl_list = hist_ampl_list
            if not np.array_equal(hist_freq_list, freq_list):
                adj_hist_ampl_list = self.refreq_ampl(hist_freq_list, hist_ampl_list, freq_list)
            avg_ampl_list += np.log(np.clip(adj_hist_ampl_list,1e-12, None))   # Sum up all logs, avoiding 0
        if len(self.hist_list) > 0:
            avg_ampl_list = np.divide(avg_ampl_list, len(self.hist_list))   # Div by N to get avg log
            avg_ampl_list = np.exp(avg_ampl_list)                           # Then "un-log" again

        # Send Average Amplitude to Guido
        spec_buf = ["Avg", avg_freq_list, avg_ampl_list]
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)

        # Detect Successful Sweep Point
        if (self.sweep_running == True):

            # Consider the Current Sweep Point Good if History Buffer
            #     is filled with valid frequency and amplitude within 3dB
            sweep_ready = False
            avg_powerInBOI = 0
            if freq_found:
                sweep_ready = True
                max_powerInBOI = None
                min_powerInBOI = None
                for [hist_timestamp, hist_freq_list, hist_ampl_list, swp_data_list] in self.hist_list:
                    [hist_currSweepFreq, hist_freq_found, hist_powerInBOI] = swp_data_list
                    if not hist_freq_found:
                        sweep_ready = False
                        break
                    avg_powerInBOI += hist_powerInBOI
                    if max_powerInBOI == None or max_powerInBOI < hist_powerInBOI:
                        max_powerInBOI = hist_powerInBOI
                    if min_powerInBOI == None or min_powerInBOI > hist_powerInBOI:
                        min_powerInBOI = hist_powerInBOI

                if max_powerInBOI == None:
                    max_powerInBOI = min_powerInBOI
                if min_powerInBOI == None:
                    min_powerInBOI = max_powerInBOI

                if min_powerInBOI == None:   # Both are None
                    sweep_ready = False
                elif 10*np.log(max_powerInBOI/min_powerInBOI) > 3 :
                    print(f">> Power Not Stable over {len(self.hist_list)} buffers")
                    print(f">>>>   min = {min_powerInBOI} = {10*np.log(min_powerInBOI)} dB, max = {max_powerInBOI} = {10*np.log(max_powerInBOI)} dB")
                    sweep_ready = False

            if sweep_ready:
                print("TRUE!!")
                if len(self.hist_list) > 0:
                    avg_powerInBOI = avg_powerInBOI / len(self.hist_list)

                for k in range(0, len(self.sweepFreqs)):
                    if np.isnan(self.sweepFreqs[k]):
                        print("NaN Found")
                        self.sweepFreqs[k] = currSweepFreq
                        self.sweepAmpls[k] = np.sqrt(avg_powerInBOI)
                        self.found = True
                        spec_buf = ["Sweep", self.sweepFreqs, self.sweepAmpls]
                        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
                        break


        # Capture Calibration Data to Apply Next Time
        if apply_cal == None:
            self.buf_man.msgSend("Guido", "remove_plot", "Cal")
            self.apply_cal = False

        elif type(apply_cal) is list:
            self.cal_freq_list = apply_cal[0]
            self.cal_ampl_list = apply_cal[1]
            self.buf_man.msgSend("Guido", "plot_data", ["Cal", apply_cal[0], apply_cal[1]])
            self.apply_cal = True

        # Log Debug Info
        if write_dbg:
            if not self.dbg_ana_file is None:
                with open(self.dbg_ana_file, mode='a') as csv_file:
                    csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    ana_pass = f'PASS_{self.analysis_num}'
                    csv_writer.writerow([ana_pass, 'Capture Time', datetime.now().timestamp()])
                    csv_writer.writerow([ana_pass])
                    csv_writer.writerow([ana_pass, 'MicData', 'Time', 'Voltage'])
                    for ind in range(num_samp):
                        csv_writer.writerow([ana_pass, 'MicData', time_list[ind], volt_list[ind]])
                    csv_writer.writerow([ana_pass])
                    csv_writer.writerow([ana_pass, 'FFT', 'Freq', 'Ampl'])
                    for ind in range(len(freq_list)):
                        csv_writer.writerow([ana_pass, 'FFT', freq_list[ind], ampl_list[ind]])
                    csv_writer.writerow([ana_pass])

    def run(self):
        logging.info("AudioAnalyzer started")
        self._stop_requested = False
        self.sweep_freq = 0
        sweep_freq_mult = 0
        next_it_time = time.monotonic()
        sweep_freq_cnt = 0
        while not self._stop_requested:
            # --- Wait for Next Iteration ---
            sleep_dur = next_it_time - time.monotonic()
            if sleep_dur > 0:
                time.sleep(sleep_dur)
            next_it_time = next_it_time + C_SWEEP_DWELL_DUR

            # --- Run the Sweep ---
            if self.sweep_on:

                if self.found == True:
                    self.numSweepFreqs = 0
                    self.pastPeaks = [np.nan] * 2

                    # --- Get Sweep Started ---
                    if not self.sweep_running:
                        logging.info(f"{self.name}: AudioAnalyzer sweep started.")
                        self.sweep_running = True
                        if self.start_freq > self.stop_freq:
                            (self.start_freq, self.stop_freq) = (self.stop_freq, self.start_freq)
                        sweep_freq_cnt = 0
                    else:
                        sweep_freq_cnt = sweep_freq_cnt + 1

                    self.sweep_freq = self.start_freq * (self.stop_freq / self.start_freq) ** (sweep_freq_cnt / (self.sweep_points - 1))

                    # --- Generate Sweep Tone ---
                    logging.info(f"{self.name}: AudioAnalyzer sweep generating {self.sweep_freq}Hz.")



                    # --- Determine Next Sweep Tone ---
                    # When we're done, we'll generate 0, which stops Gen

                    if sweep_freq_cnt >= self.sweep_points:
                        self.sweep_freq = 0
                        logging.info(f"{self.name}: AudioAnalyzer sweep finished.")
                        self.sweep(False)
                        self.buf_man.msgSend("Guido", "sweep_finished", None)
                    else:
                        # --- SEND MESSAGE TO GEN TO PLAY TONE
                        self.buf_man.msgSend("Gen", "play_tone", self.sweep_freq)
                        self.found = False

            # --- Stop the Sweep ---
            elif self.sweep_running:
                logging.info(f"{self.name}: AudioAnalyzer sweep stopped.")
                self.sweep_running = False
                self.buf_man.msgSend("Gen", "play_tone", 0)    # Turn off Gen
                self.pastPeaks = [np.nan] * 2
                self.sweepFreqs = [np.nan] * self.sweep_points
                self.sweepAmpls = [np.nan] * self.sweep_points
                self.found = True

        logging.info("AudioAnalyzer finished")
        self.finished.emit()

# ==============================================================================
# MODULE TESTBENCH
#
if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    rate = 44100
    t_samp = 1/rate
    freq = 1000
    t_per = 1/freq

    logging.info(  f"{'NUM_SAMP':10s} {'PEAK_AMPL':10s}")
    for num_samp in range(512,16385):
        time_list = np.linspace(start=0, stop=t_samp*(num_samp-1), num=num_samp, endpoint=False)
        volt_list = np.sin(2 * np.pi * freq * time_list)

        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)              # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)            # Amplitude spectrum of measurement

        max_ampl=max(ampl_list)
        logging.info(  f"{num_samp:10d} {max_ampl:10.6f}")

elif __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    rate = 44100
    t_samp = 1/rate
    freq = 1000
    t_per = 1/freq

#    num_samp_list = [2**9]                    # 512
#    num_samp_list = [int(20*t_per/t_samp)]    # 880
    num_samp_list = [2**10-1]                   # 1023
#    num_samp_list = [2**10]                   # 1024
#    num_samp_list = [int(200*t_per/t_samp)]   # 8800
#    num_samp_list = [2**14]                   # 16384

    for num_samp_ind in range(0, len(num_samp_list)):
        num_samp = num_samp_list[num_samp_ind]

        logging.info(f"Analyzing freq = {freq}, num_samp = {num_samp}")

        time_list = np.linspace(start=0, stop=t_samp*(num_samp-1), num=num_samp, endpoint=False)
        volt_list = np.sin(2 * np.pi * freq * time_list)

        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)              # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)            # Amplitude spectrum of measurement

        logging.info(f"    {'INDEX':5s} {'TIME_'+str(num_samp):9s} {'VOLTS_'+str(num_samp):9s} {'FREQ_'+str(num_samp):9s} {'AMPLITUDE_'+str(num_samp):9s}")
        for i in range(0,len(volt_list)):
            if i < len(ampl_list):
                logging.info(f"    {i:5d} {time_list[i]:9.6f} {volt_list[i]:9.6f} {freq_list[i]:9.6f} {ampl_list[i]:9.6f}")
            else:
                logging.info(f"    {i:5d} {time_list[i]:9.6f} {volt_list[i]:9.6f}")

elif __name__ == "__main__":
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
