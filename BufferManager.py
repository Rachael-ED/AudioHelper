# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QMutex, QSemaphore

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

    def __init__(self, name="BuffMan"):
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

    # Returns the specified buffer without removing it from the buffer list
    def get(self, buf_id):
        buf = g_buf_list[buf_id]
        #logging.info(f"Retrieved buffer #{buf_id} for {self.name}")
        return buf
