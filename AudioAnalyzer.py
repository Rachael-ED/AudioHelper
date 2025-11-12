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

C_HIST_DUR_MAX = 10  # Same as C_AVG_DUR_MAX in Guido
C_HIST_DUR_MIN = 0  # Same as C_AVG_DUR_MIN in Guido

C_SWEEP_DWELL_DUR = 0.1  # Time for each sweep tone [s]

C_SWEEP_BASELINE_VOL = 10 ** (-12 / 20)  # -12dB


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
        ipc_dict = {  # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
            "Gen": self.sig_ipc_gen,
            "Mic": self.sig_ipc_mic,
            "Guido": self.sig_ipc_guido
        }

        # Create Buffer Manager
        self.name = name
        self.buf_man = BufMan.BufferManager(name, ipc_dict)

        self.sweep_on = False
        self.sweep_running = False
        self.state = "IDLE"
        self._stop_requested = False
        self.start_freq = C_FREQ_MIN
        self.stop_freq = C_FREQ_MAX
        self.sweep_freq = 0
        self.sweep_points = 100
        self.gain_db = 60
        self.hist_dur = 3  # Length [seconds] of history buffer
        self.hist_list = []  # List of recent analysis runs.  [timestamp, freq_list, ampl_list]

        self.apply_cal = False  # False = Don't use.  True = Use.  None = Remove.  String = Capture plot line
        self.cal_freq_list = []
        self.cal_ampl_list = []

        self.sweepFreqs = [np.nan] * self.sweep_points
        self.sweepAmpls = [np.nan] * self.sweep_points
        self.numSweepFreqs = 0
        self.found = True
        self.freqFromMic = 0
        self.rejects = 0

        self.analysis_num = 0  # Just a running counter of times analyze() is called, for debug
        self.threshold = 0.90

        # Set Up Debug File
        self.dbg_ana_file = None
        # self.dbg_ana_file = 'dbg_ana' + datetime.now().strftime("_%y%m%d_%H%M%S") + '.csv'  # Set to None to disable

    def msgHandler(self, buf_id):
        # Retrieve Message
        [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
        # logging.info(f"{self.name} received {msg_type} from {snd_name} : {msg_data}")
        ack_data = None

        # Process Message
        if msg_type == "mic_data":
            self.analyze(msg_data, -1)

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
            self.sweepFreqs = [np.nan] * self.sweep_points
            self.sweepAmpls = [np.nan] * self.sweep_points

        elif msg_type == "mic_data_sweep":
            voltageAndTime = msg_data[0]
            currSweepFreq = msg_data[1]
            self.analyze(voltageAndTime, currSweepFreq)
        elif msg_type == "change_threshold":
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
            newFreq = float(newFreq)  # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.start_freq = C_FREQ_MIN
                # logging.info(f"AudioAna start_freq = {self.start_freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.start_freq = C_FREQ_MAX
                # logging.info(f"AudioAna start_freq = {self.start_freq}Hz = MAX")
            else:
                self.start_freq = newFreq
                # logging.info(f"AudioAna start_freq = {self.start_freq}Hz")

    def changeStopFreq(self, newFreq):
        if re.search('^\d+(\.\d+)?$', newFreq):
            newFreq = float(newFreq)  # Translate string to number
            if newFreq <= C_FREQ_MIN:
                self.stop_freq = C_FREQ_MIN
                # logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz = MIN")
            elif newFreq >= C_FREQ_MAX:
                self.stop_freq = C_FREQ_MAX
                # logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz = MAX")
            else:
                self.stop_freq = newFreq
                # logging.info(f"AudioAna stop_freq = {self.stop_freq}Hz")

    def changeGainDb(self, newGainDb):
        if newGainDb <= C_GAIN_MIN_DB:
            self.gain_db = C_GAIN_MIN_DB
            # logging.info(f"AudioAna gain_db = {self.gain_db}dB = MIN")
        elif newGainDb >= C_GAIN_MAX_DB:
            self.gain_db = C_GAIN_MAX_DB
            # logging.info(f"AudioAna gain_db = {self.gain_db}dB = MAX")
        else:
            self.gain_db = newGainDb
            # logging.info(f"AudioAna gain_db = {self.gain_db}dB")

    def changeSweepPoints(self, newSweepPoints):
        if re.search('^[+-]?\d+(\.\d+)?$', newSweepPoints):
            newSweepPoints = int(newSweepPoints)  # Translate string to number
            if newSweepPoints <= C_SWEEP_POINTS_MIN:
                self.sweep_points = C_SWEEP_POINTS_MIN
                # logging.info(f"AudioAna sweep_points = {self.sweep_points} = MIN")
            elif newSweepPoints >= C_SWEEP_POINTS_MAX:
                self.sweep_points = C_SWEEP_POINTS_MAX
                # logging.info(f"AudioAna sweep_points = {self.sweep_points} = MAX")
            else:
                self.sweep_points = newSweepPoints
                # logging.info(f"AudioAna sweep_points = {self.sweep_points}")

    def changeHistDur(self, newHistDur):
        if newHistDur <= C_HIST_DUR_MIN:
            self.hist_dur = C_HIST_DUR_MIN
            # logging.info(f"AudioAna hist_dur = {self.hist_dur}s = MIN")
        elif newHistDur >= C_HIST_DUR_MAX:
            self.hist_dur = C_HIST_DUR_MAX
            # logging.info(f"AudioAna hist_dur = {self.hist_dur}s = MAX")
        else:
            self.hist_dur = newHistDur
            # logging.info(f"AudioAna hist_dur = {self.hist_dur}s")

    def stop(self):
        logging.info("AudioAnalyzer stop requested")
        self._stop_requested = True

    def hist_clean(self):
        cur_time = time.monotonic()
        age_out_time = cur_time - self.hist_dur
        ind = 0  # Index of oldest entry that has not aged out
        while ind < len(self.hist_list):
            [timestamp, freq_list, ampl_list, buf_data_list] = self.hist_list[ind]
            if timestamp >= age_out_time:
                break
            ind += 1
        if ind >= len(self.hist_list):  # All entries have aged out
            self.hist_list = []
        elif ind > 0:  # Some entries have aged out
            del self.hist_list[:ind]

    def hist_add(self, freq_list, ampl_list, buf_data_list):
        self.hist_clean()
        self.hist_list.append([time.monotonic(), freq_list, ampl_list, buf_data_list])

    # Translates an amplitude spectrum with one set of frequencies to a different set of frequencies.
    # We'll do this by interpolating in a log-log sense, so that a new point at a new frequency
    #     would appear linearly interpolated between two points of the reference when viewed on a
    #     dB vs. log(f) plot.
    # For new frequencies which lie outside the reference range, we have no other information,
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
        # To handle srch_ind == 0, we'll prepend a dummy entry and shift the srch_ind values by 1,
        #     so we use indices 1 & 0 rather than 0 & -1.
        # To handle srch_ind > length of list, we'll append a dummy entry.
        # These dummy entries will just replicate the first/last y values (log_ampl)
        #     at one freq step before/after the first/last x value (freq).
        # This way, performing the same linear interpolation calc on the arrays results in just
        #     extending the first/last y value for any new x values left/right of the first/last ref x value.
        ref_freq_step = ref_freq_list[1] - ref_log_freq_list[0]
        ref_log_freq_list = np.insert(ref_log_freq_list, 0, ref_log_freq_list[0] - ref_freq_step)
        ref_log_ampl_list = np.insert(ref_log_ampl_list, 0, ref_log_ampl_list[0])
        srch_ind_list = srch_ind_list + 1  # Search results shift because of np.insert
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

    def analyze(self, voltageAndTime, currSweepFreq):
        # --------------------------------------------------------------------------------
        # FETCH STATE & DATA BUFFER TO ANALYZE
        #
        start_time = time.monotonic()
        dbg_out_en = True
        [time_list, volt_list] = voltageAndTime

        ana_state = self.state
        self.analysis_num += 1
        write_dbg = False

        num_samp = len(volt_list)             # Number of audio samples
        t_samp = time_list[1] - time_list[0]  # Audio sampling period
        bufDuration = num_samp * t_samp       # Time covered by buffer

        # --------------------------------------------------------------------------------
        # CALCULATE AMPLITUDE SPECTRUM OF BUFFER
        #

        # Calculate Frequency Spectrum
        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)  # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)  # Amplitude spectrum of measurement

        distBtwnFreq = freq_list[1] - freq_list[0]

        # Remove DC element
        freq_list = np.delete(freq_list, 0)
        ampl_list = np.delete(ampl_list, 0)
        ampl_list = ampl_list * 2 / num_samp * 10 ** (self.gain_db / 20)

        # Apply Calibration
        apply_cal = self.apply_cal
        if apply_cal:
            cal_ampl_list = self.cal_ampl_list
            if len(self.cal_ampl_list) != len(ampl_list):
                cal_ampl_list = self.refreq_ampl(self.cal_freq_list, self.cal_ampl_list, freq_list)
            ampl_list = np.divide(ampl_list, cal_ampl_list)

        # Compute total power
        powerTotal = np.sum(ampl_list ** 2)

        # Send Amplitude Spectrum to Guido
        spec_buf = ["Live", freq_list, ampl_list]
        plot_live_send_time = time.monotonic()
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
        plot_live_ret_time = time.monotonic()

        # --------------------------------------------------------------------------------
        # CALCULATE OTHER METRICS OF BUFFER
        #

        # Calc Power in Buckets Of Interest (BOI)
        #     Only if we're analyzing a buffer captured during a sweep (which includes currSweepFreq)
        powerInBOI = None
        if currSweepFreq > 0:

            # figure out in which bucket the frequency should be
            currSweepFreqInd = int(currSweepFreq / distBtwnFreq) - 1

            # compute power in BOI (i.e. buckets of interest)
            powerInBOI = 0
            window_width = 1
            for ind in range(currSweepFreqInd - window_width, currSweepFreqInd + window_width + 1):
                powerInBOI += ampl_list[ind] ** 2

            #logging.info(f"Power in BOI: {powerInBOI:.3f} = {10 * np.log(powerInBOI):.3f} dB --- Power Total: {powerTotal:.3f} --- {powerInBOI / powerTotal:.3f}")

        # See if Expected Sweep Frequency is Dominant in Buffer
        #     Only if we're analyzing a buffer captured during a sweep (which includes currSweepFreq)
        foundSweepFreq = None
        if currSweepFreq > 0:
            conv_ampl_list = np.convolve(ampl_list, ampl_list)
            max_ind = np.argmax(conv_ampl_list)
            det_freq = ((max_ind / 2) + 1) * distBtwnFreq

            if abs(det_freq - currSweepFreq) < (distBtwnFreq / 4):
                foundSweepFreq = currSweepFreq
                #logging.info(f"Detected freq : {det_freq:.3f} Hz")
        buf_data_list = [bufDuration, foundSweepFreq, powerTotal, powerInBOI]

        # --------------------------------------------------------------------------------
        # CURRENT BUFFER TO HISTORY LIST
        #
        self.hist_add(freq_list, ampl_list, buf_data_list)

        # --------------------------------------------------------------------------------
        # ANALYZE HISTORY LIST
        #

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

        hist_len = len(self.hist_list)
        allTS_list = np.array([0] * hist_len).astype(np.float64)
        allBufDuration_list = np.array([0] * hist_len).astype(np.float64)
        allPowerTotal_list = np.array([0] * hist_len).astype(np.float64)

        freqFoundTS_list = np.array([0] * hist_len).astype(np.float64)
        freqFoundBufDuration_list = np.array([0] * hist_len).astype(np.float64)
        freqFoundPowerInBOI_list = np.array([0] * hist_len).astype(np.float64)

        hist_ind = -1
        cntFreqFound = 0
        for [hist_timestamp, hist_freq_list, hist_ampl_list, buf_data_list] in self.hist_list:
            [hist_bufDuration, hist_foundSweepFreq, hist_powerTotal, hist_powerInBOI] = buf_data_list
            hist_ind += 1

            # Remap Amplitudes to Common Frequency List for Averaging
            adj_hist_ampl_list = hist_ampl_list
            if not np.array_equal(hist_freq_list, freq_list):
                adj_hist_ampl_list = self.refreq_ampl(hist_freq_list, hist_ampl_list, freq_list)

            # Retrieve Buffer Metrics
            allTS_list[hist_ind] = hist_timestamp
            allBufDuration_list[hist_ind] = hist_bufDuration
            allPowerTotal_list[hist_ind]= hist_powerTotal
            if hist_foundSweepFreq == currSweepFreq:
                freqFoundTS_list[cntFreqFound] = hist_timestamp
                freqFoundBufDuration_list[cntFreqFound] = hist_bufDuration
                freqFoundPowerInBOI_list[cntFreqFound] = hist_powerInBOI
                cntFreqFound += 1

            # Accumulate Metrics
            avg_ampl_list += np.log(np.clip(adj_hist_ampl_list, 1e-12, None))  # Sum up all logs, avoiding 0

        avg_powerTotal = 0
        totalBufElapsed = 0
        totalBufDuration = 0
        if hist_len > 0:
            avg_ampl_list = np.divide(avg_ampl_list, hist_len)  # Div by N to get avg log
            avg_ampl_list = np.exp(avg_ampl_list)  # Then "un-log" again

            avg_powerTotal = np.average(allPowerTotal_list)
            totalBufElapsed = allTS_list[hist_len-1] - allTS_list[0] + allBufDuration_list[hist_len-1]
            totalBufDuration = np.sum(allBufDuration_list)

        sweepBufElapsed = 0
        sweepBufDuration = 0
        avg_powerInBOI = 0
        avg_powerInBOI_db = 0
        min_powerInBOI_db = 0
        max_powerInBOI_db = 0
        if cntFreqFound > 0:
            sweepBufElapsed = freqFoundTS_list[cntFreqFound-1] - freqFoundTS_list[0] + freqFoundBufDuration_list[cntFreqFound-1]
            sweepBufDuration = np.sum(freqFoundBufDuration_list)

            f=0
            l=cntFreqFound

            avg_powerInBOI = np.average(freqFoundPowerInBOI_list[f:l])

            avg_powerInBOI_db = 10 * np.log( np.average(freqFoundPowerInBOI_list[f:l]) )
            min_powerInBOI_db = 10 * np.log( np.min(freqFoundPowerInBOI_list[f:l]) )
            max_powerInBOI_db = 10 * np.log( np.max(freqFoundPowerInBOI_list[f:l]) )

        if cntFreqFound > 3:
            avg_powerInBOI = np.average(freqFoundPowerInBOI_list[f:l])

            l=cntFreqFound
            f=l-3

            avg_powerInBOI_db = 10 * np.log( np.average(freqFoundPowerInBOI_list[f:l]) )
            min_powerInBOI_db = 10 * np.log( np.min(freqFoundPowerInBOI_list[f:l]) )
            max_powerInBOI_db = 10 * np.log( np.max(freqFoundPowerInBOI_list[f:l]) )


        # Send Average Amplitude to Guido
        spec_buf = ["Avg", avg_freq_list, avg_ampl_list]
        plot_avg_send_time = time.monotonic()
        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
        plot_avg_ret_time = time.monotonic()

        # --------------------------------------------------------------------------------
        # DETECT SUCCESSFUL SWEEP POINT
        #
        if self.sweep_running and (currSweepFreq > 0):

            # Consider the Current Sweep Point Good if History Buffer
            #     is filled with valid frequency and amplitude within 3dB
            sweep_ready = False
            sweep_timeout = 0.8*totalBufElapsed
            if foundSweepFreq == currSweepFreq:
                sweep_ready = True
                if sweepBufElapsed >= sweep_timeout:
                    pass
                elif cntFreqFound < 3:
                    sweep_ready = False
                elif (max_powerInBOI_db - min_powerInBOI_db) > 3:
                    sweep_ready = False

            plot_sweep_send_time = 0
            plot_sweep_ret_time = 0
            if sweep_ready:
                for k in range(0, len(self.sweepFreqs)):
                    if np.isnan(self.sweepFreqs[k]):
                        self.sweepFreqs[k] = currSweepFreq
                        self.sweepAmpls[k] = np.sqrt(avg_powerInBOI)
                        self.found = True
                        spec_buf = ["Sweep", self.sweepFreqs, self.sweepAmpls]
                        plot_sweep_send_time = time.monotonic()
                        self.buf_man.msgSend("Guido", "plot_data", spec_buf)
                        plot_sweep_ret_time = time.monotonic()
                        break

            if dbg_out_en:
                dbg_out_start_time = time.monotonic()
                if sweep_ready:
                    logging.info(f"History List: READY for {currSweepFreq:.3f} Hz")
                else:
                    logging.info(f"History List: NOT READY for {currSweepFreq:.3f} Hz")
                logging.info(f"    Total Buffers:        {hist_len} = {totalBufDuration:.3f}s over {totalBufElapsed:.3f}s elapsed")
                logging.info(f"    Timeout:              {sweep_timeout:.3f}s")
                logging.info(f"    Sweep Freq Buffers:   {cntFreqFound} = {sweepBufDuration:.3f}s over {sweepBufElapsed:.3f}s elapsed")
                if cntFreqFound > 0:
                    logging.info(f"    Power in BOI:         {min_powerInBOI_db:.3f}dB min, {avg_powerInBOI_db:.3f}dB avg, {max_powerInBOI_db:.3f}dB max ")

                '''
                logging.info(f"Benchmarking:")
                logging.info(f"    Plot Live      : {(plot_live_ret_time - plot_live_send_time):.6f} seconds")
                logging.info(f"    Plot Avg       : {(plot_avg_ret_time - plot_avg_send_time):.6f} seconds")
                logging.info(f"    Plot Sweep     : {(plot_sweep_ret_time - plot_sweep_send_time):.6f} seconds")
                dbg_out_end_time = time.monotonic()
                logging.info(f"    Logging        : {(dbg_out_end_time - dbg_out_start_time):.6f} seconds")
                total_io_dur = plot_live_ret_time - plot_live_send_time + plot_avg_ret_time - plot_avg_send_time + plot_sweep_ret_time - plot_sweep_send_time + dbg_out_end_time - dbg_out_start_time
                logging.info(f"    Total I/O      : {total_io_dur:.6f} seconds")
                end_time = time.monotonic()
                logging.info(f"    Total Analysis : {(end_time - start_time):.6f} seconds")
                '''

        # --------------------------------------------------------------------------------
        # FINISH UP ANALYSIS PASS
        #

        # Capture Calibration Data to Apply Next Time
        if apply_cal is None:
            self.buf_man.msgSend("Guido", "remove_plot", "Cal")
            self.apply_cal = False

        elif type(apply_cal) is list:
            self.cal_freq_list = apply_cal[0]
            self.cal_ampl_list = apply_cal[1]
            self.buf_man.msgSend("Guido", "plot_data", ["Cal", apply_cal[0], apply_cal[1]])
            self.apply_cal = True

        # Log Debug Info
        if write_dbg:
            if self.dbg_ana_file is not None:
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

                if self.found:
                    self.numSweepFreqs = 0

                    # --- Get Sweep Started ---
                    if not self.sweep_running:
                        logging.info(f"{self.name}: AudioAnalyzer sweep started.")
                        self.sweep_running = True
                        if self.start_freq > self.stop_freq:
                            (self.start_freq, self.stop_freq) = (self.stop_freq, self.start_freq)
                        sweep_freq_cnt = 0
                    else:
                        sweep_freq_cnt = sweep_freq_cnt + 1

                    self.sweep_freq = self.start_freq * (self.stop_freq / self.start_freq) ** (
                                sweep_freq_cnt / (self.sweep_points - 1))

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
                self.buf_man.msgSend("Gen", "play_tone", 0)  # Turn off Gen
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
    t_samp = 1 / rate
    freq = 1000
    t_per = 1 / freq

    logging.info(f"{'NUM_SAMP':10s} {'PEAK_AMPL':10s}")
    for num_samp in range(512, 16385):
        time_list = np.linspace(start=0, stop=t_samp * (num_samp - 1), num=num_samp, endpoint=False)
        volt_list = np.sin(2 * np.pi * freq * time_list)

        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)  # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)  # Amplitude spectrum of measurement

        max_ampl = max(ampl_list)
        logging.info(f"{num_samp:10d} {max_ampl:10.6f}")

elif __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    rate = 44100
    t_samp = 1 / rate
    freq = 1000
    t_per = 1 / freq

    #    num_samp_list = [2**9]                    # 512
    #    num_samp_list = [int(20*t_per/t_samp)]    # 880
    num_samp_list = [2 ** 10 - 1]  # 1023
    #    num_samp_list = [2**10]                   # 1024
    #    num_samp_list = [int(200*t_per/t_samp)]   # 8800
    #    num_samp_list = [2**14]                   # 16384

    for num_samp_ind in range(0, len(num_samp_list)):
        num_samp = num_samp_list[num_samp_ind]

        logging.info(f"Analyzing freq = {freq}, num_samp = {num_samp}")

        time_list = np.linspace(start=0, stop=t_samp * (num_samp - 1), num=num_samp, endpoint=False)
        volt_list = np.sin(2 * np.pi * freq * time_list)

        freq_list = rfftfreq(num_samp, t_samp)  # Frequency of measurement spectrum
        fft_list = rfft(volt_list)  # FFT of measurement (complex values)
        ampl_list = np.abs(fft_list)  # Amplitude spectrum of measurement

        logging.info(
            f"    {'INDEX':5s} {'TIME_' + str(num_samp):9s} {'VOLTS_' + str(num_samp):9s} {'FREQ_' + str(num_samp):9s} {'AMPLITUDE_' + str(num_samp):9s}")
        for i in range(0, len(volt_list)):
            if i < len(ampl_list):
                logging.info(
                    f"    {i:5d} {time_list[i]:9.6f} {volt_list[i]:9.6f} {freq_list[i]:9.6f} {ampl_list[i]:9.6f}")
            else:
                logging.info(f"    {i:5d} {time_list[i]:9.6f} {volt_list[i]:9.6f}")

elif __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    logging.info(f"Hey User!  This is just for testing {__file__}.  Run from AudioHelper.py instead.")
