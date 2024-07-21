# ==============================================================================
# IMPORTS
#
import sys
from PyQt5.Qt import *
from PyQt5.QtCore import QObject, pyqtSignal
import AudioHelperGUI as GuiMdl
import AudioGen as AudGenMdl
import logging
import pyaudio as pa
import numpy as np

""" This is just a dummy change to see if I can check something in"""

# ==============================================================================
# MAIN PROGRAM
#

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)

print(f"Hey User!  The program has started.")

# --- Create GUI ---
app = QApplication(sys.argv)
main_win = GuiMdl.AudioHelperGUI()
main_win.show()

# --- Parameters needed for AudioGen class
FORMAT = pa.paFloat32
CHANNELS = 1
RATE = 44100
FRAMES_PER_BUFFER = 1024
FREQ = 440

# --- Create AudioGen ---
audio_gen_thread = QThread()
audio_gen = AudGenMdl.AudioGen(FORMAT, CHANNELS, RATE, FRAMES_PER_BUFFER, FREQ)
audio_gen.enable()

# --- Make Window & AudioGen Connections ---
# It seems that these need to be done before we move the AudioGen to its own thread.
main_win.sig_audio_gen_enable.connect(audio_gen.enable)

main_win.sig_closing.connect(audio_gen.stop)                      # When user closes main window, stop audio generator
audio_gen.finished.connect(audio_gen_thread.quit)                 # ... Once the generator is done, quit the thread
audio_gen.finished.connect(audio_gen.deleteLater)                 # ...     and schedule the generator to be deleted

# --- Move AudioGen to Its Own Thread ---
audio_gen.moveToThread(audio_gen_thread)

# --- Thread Connections ---
# It seems that these need to be set up after AudioGen is Moved to the Thread
audio_gen_thread.started.connect(audio_gen.run)                   # Start audio gen running when its thread is started
audio_gen_thread.finished.connect(audio_gen_thread.deleteLater)   # Once the thread is done, schedule it to be deleted

# --- Start the Threads and the Event Loop ---
audio_gen_thread.start()
app.exec()

# --- Finished ---
print("DONE")
