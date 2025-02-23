# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QMutex, QSemaphore
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import logging

# ==============================================================================
# CONSTANTS AND GLOBALS
#

C_BUF_CNT = 10       # Number of buffers in pool
g_buf_list = [None] * C_BUF_CNT   # An unused

g_sem = QSemaphore(C_BUF_CNT)     # Semaphore to block on if there are no available buffers
g_mutex = QMutex()                # Mutex to control access to buffer list


# ==============================================================================
# CLASS DEFINITION
#
class BufferManager:

    def __init__(self, name="BuffMan", ipc_dict={}):
        self.ipc_dict = ipc_dict      # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
        self.name = name

    # Adds provided buffer to global pool and returns buffer ID
    # Waits if there isn't a slot available
    def alloc(self, buf):
        # Wait for a buffer location to become available
        g_sem.acquire(1)

        # Choose Which Buffer Location to Use
        g_mutex.lock()
        buf_id = None
        for ind, val in enumerate(g_buf_list):
            if val is None:
                buf_id = ind
                g_buf_list[ind] = buf
                break
        g_mutex.unlock()

        if buf_id is None:
            logging.error(f"Unable to find buffer for {self.name}")
        #else:
        #    logging.info(f"Added buffer #{buf_id} for {self.name}")
        return buf_id

    # Releases the specified buffer location, allowing it to be used again
    # Returns the buffer, in case the caller wants to use it
    def free(self, buf_id):
        g_mutex.lock()
        buf = g_buf_list[buf_id]
        g_buf_list[buf_id] = None
        g_mutex.unlock()
        g_sem.release(1)
        #logging.info(f"Released buffer #{buf_id} for {self.name}")
        return buf

    def freeCount(self):
        return g_sem.available()

    # Returns the specified buffer without removing it from the buffer list
    def get(self, buf_id):
        buf = g_buf_list[buf_id]
        #logging.info(f"Retrieved buffer #{buf_id} for {self.name}")
        return buf

    def ipcSignal(self, rx_name):
        if rx_name not in self.ipc_dict:
            logging.info(f"ERROR: No IPC signal found for {rx_name}")
            return None
        return self.ipc_dict[rx_name]

    def ipcReceivers(self):
        return self.ipc_dict.keys()
    def ipcSig(self, rx_name):
        return self.ipc_dict[rx_name]

    def msgSend(self, rx_name, msg_type, msg_data):
        # Retrieve Signal for Communication
        if rx_name not in self.ipc_dict:
            logging.info(f"ERROR: {self.name} is unable to send message to {rx_name}")
            return False
        ipc_sig = self.ipc_dict[rx_name]

        # Build Message Buffer
        msg_buf = [msg_type, self.name, msg_data]

        # Allocate Buffer and Send It
        buf_id = self.alloc(msg_buf)
        ipc_sig.emit(buf_id)

    def msgReceive(self, buf_id):
        return self.free(buf_id)