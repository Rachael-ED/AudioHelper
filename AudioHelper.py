# ==============================================================================
# IMPORTS
#
import sys
from PyQt5.Qt import *
from PyQt5.QtCore import QObject, pyqtSignal
import AudioHelperGUI as GuiMdl
import AudioGen as AudGenMdl
import AudioAnalyzer as AudAnaMdl
import MicReader as MicMdl
import logging
import pyaudio as pa
import numpy as np

# ==============================================================================
# CONSTANTS AND GLOBALS
#
#

# --- Parameters needed for AudioGen class
FORMAT = pa.paFloat32
CHANNELS = 1
RATE = 44100
FRAMES_PER_BUFFER = 1024
FREQ = 440
VOL_DB = -12

# ==============================================================================
# MAIN PROGRAM
#

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)

print(f"Hey User!  The program has started.")

# --- Create GUI ---
app = QApplication(sys.argv)
main_win = GuiMdl.AudioHelperGUI()
main_win.show()

# --- Create AudioGen ---
audio_gen_thread = QThread()
audio_gen = AudGenMdl.AudioGen(FORMAT, CHANNELS, RATE, FRAMES_PER_BUFFER, FREQ, VOL_DB)
#audio_gen.enable()

# --- Create AudioAnalyzer ---
audio_ana_thread = QThread()
audio_ana = AudAnaMdl.AudioAnalyzer()
#audio_ana.enable()

# --- Create MicReader ---
mic_reader_thread = QThread()
mic_reader = MicMdl.MicReader(FORMAT, CHANNELS, RATE)
mic_reader.enable()

# --- Make Window & AudioGen Connections ---
# It seems that these need to be done before we move the AudioGen to its own thread.
main_win.sig_audio_gen_enable.connect(audio_gen.enable)
main_win.sig_audio_ana_sweep.connect(audio_ana.sweep)
main_win.sig_mic_reader_enable.connect(mic_reader.enable)

#main_win.sig_changeFreq.connect(audio_gen.changeFreq)
main_win.txt_aud_gen_freq1.textChanged.connect(audio_gen.changeFreq)
main_win.txt_aud_gen_vol.textChanged.connect(audio_gen.changeVol)

main_win.cmb_aud_gen_mode.currentTextChanged.connect(audio_gen.changeMode)

audio_ana.sig_audio_gen_playtone.connect(audio_gen.playTone)

main_win.sig_assignNewOutputIndex.connect(audio_gen.changeOutputIndex)
main_win.sig_assignNewInputIndex.connect(mic_reader.changeInputIndex)

mic_reader.sig_newdata.connect(audio_ana.analyze)                 # Analyze mic data when new data is available
audio_ana.sig_newdata.connect(main_win.update_plot)               # Update the plot when new data is available

main_win.sig_closing.connect(audio_gen.stop)                      # When user closes main window, stop audio generator
audio_gen.finished.connect(audio_ana.stop)                        # ... Once the generator is done, stop analyzer
audio_ana.finished.connect(mic_reader.stop)                       # ... Once the analyzer is done, stop mic reader

mic_reader.finished.connect(audio_gen_thread.quit)                 # ... Once the mic reader is done, quit the generator thread
mic_reader.finished.connect(audio_gen.deleteLater)                 # ...     and schedule the generator to be deleted
mic_reader.finished.connect(audio_ana_thread.quit)                 # ...     and also the analyzer
mic_reader.finished.connect(audio_ana.deleteLater)                 # ...
mic_reader.finished.connect(mic_reader_thread.quit)                # ...     and also the mic reader
mic_reader.finished.connect(mic_reader.deleteLater)

# --- Move Modules to Their Own Threads ---
audio_gen.moveToThread(audio_gen_thread)
audio_ana.moveToThread(audio_ana_thread)
mic_reader.moveToThread(mic_reader_thread)

# --- Thread Connections ---
# It seems that these need to be set up after AudioGen is Moved to the Thread
audio_gen_thread.started.connect(audio_gen.run)                   # Start audio gen running when its thread is started
audio_gen_thread.finished.connect(audio_gen_thread.deleteLater)   # Once the thread is done, schedule it to be deleted

audio_ana_thread.started.connect(audio_ana.run)                   # Start audio ana running when its thread is started
audio_ana_thread.finished.connect(audio_ana_thread.deleteLater)   # Once the thread is done, schedule it to be deleted

mic_reader_thread.started.connect(mic_reader.run)                 # Start mic reader running when its thread is started
mic_reader_thread.finished.connect(mic_reader_thread.deleteLater) # Once the thread is done, schedule it to be deleted

# --- Start the Threads and the Event Loop ---
audio_gen_thread.start()
audio_ana_thread.start()
mic_reader_thread.start()
app.exec()

# --- Finished ---
print("DONE")
