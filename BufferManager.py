# ==============================================================================
# BUFFER AND MESSAGE MANAGER
#     Objects communicate with each other by pass messages between each other
#         via inter-process communication (IPC) channels.
#
#     Each message is a list comprised of:
#         msg_type   - A string understood by the receiver as the type of message
#                      If the type begins with "REQ", it is a request message which will
#                          block until the receiver responds with an acknowledgment.
#                      Otherwise, it is a posted message which will not block.
#         name       - A string which identifies the receiver or the sender
#         msg_data   - An object containing data for the receiver.
#                      Beware of passing a reference to anything which might change
#                      after sending.
#     Messages are sent to a receiving object using msgSend().
#     Receivers must implement a msgHandler() which would contain something like:
#         def msgHandler(self, buf_id):
#             # Retrieve Message
#             [msg_type, snd_name, msg_data] = self.buf_man.msgReceive(buf_id)
#             ack_data = None
#         
#             # Process Message
#             if msg_type == <some posted message type>:
#                 <do something useful>
#             elif msg_type == "REQ<...>":
#                 <perhaps do something useful>
#                 ack_data = <requested data>
#             else:
#                 logging.info(f"ERROR: {self.name} received unsupported {msg_type} message from {snd_name} : {msg_data}")
#         
#             # Acknowledge/Release Message
#             self.buf_man.msgAcknowledge(buf_id, ack_data)
#     Here, msgReceive() is used to retrieve the message contents, while msgAcknowledge() is used to either
#         free the message's buffer (for posted messages) or return requested data (for request messages).
#
#     Each message is stored in a "buffer", allocated from a shared global pool
#     A buffer can be any object, although we are mostly using lists here as a buffer.
#     The buffer ID is a unique identifier for that buffer, allocated
#         and freed from the global pool by alloc() and free().
#     Access to the buffers is strictly controlled by a mutex to prevent collisions.
#
#     Every sending object must create a dictionary keyed off a potential receiver's name
#         and containing a pyqtSignal which is connected to the that receiver's msgHandler().
#     The dictionary is passed to the constructor here so that BufMan knows which
#         signal to emit when a message is sent to a receiver.
#

# ==============================================================================
# IMPORTS
#
from PyQt5.QtCore import QMutex, QSemaphore
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import logging

# ==============================================================================
# CONSTANTS AND GLOBALS
#

C_BUF_CNT = 10                         # Number of buffers in pool
g_buf_pool_list = [None] * C_BUF_CNT   # An unused buffer contains None

g_sem = QSemaphore(C_BUF_CNT)     # Semaphore to block on if there are no available buffers
g_mutex = QMutex()                # Mutex to control access to buffer list


# ==============================================================================
# CLASS DEFINITION
#
class BufferManager:

    # --------------------------------------------------------------------------
    # CONSTRUCTOR
    #
    def __init__(self, name="BuffMan", ipc_dict={}):
        self.ipc_dict = ipc_dict      # Key: Receiver Name; Value: Signal for Message, connected to receiver's msgHandler()
        self.name = name

    # --------------------------------------------------------------------------
    # BUFFER ACCESS METHODS
    #
    
    # Adds provided buffer to global pool and returns buffer ID
    # Waits if there isn't a slot available
    def alloc(self, buf):
        # Wait for a buffer location to become available
        g_sem.acquire(1)

        # Choose Which Buffer Location to Use
        g_mutex.lock()
        buf_id = None
        for ind, val in enumerate(g_buf_pool_list):
            if val is None:
                buf_id = ind
                g_buf_pool_list[ind] = buf
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
        buf = g_buf_pool_list[buf_id]
        g_buf_pool_list[buf_id] = None
        g_mutex.unlock()
        g_sem.release(1)
        #logging.info(f"Released buffer #{buf_id} for {self.name}")
        return buf

    # Returns number of free buffers available
    def freeCount(self):
        return g_sem.available()

    # Returns the specified buffer without removing it from the buffer list
    def get(self, buf_id):
        buf = g_buf_pool_list[buf_id]
        #logging.info(f"Retrieved buffer #{buf_id} for {self.name}")
        return buf

    # Stuffs data into specified buffer
    #     Only call this if you have already allocated the buffer with alloc()
    def set(self, buf_id, buf):
        g_mutex.lock()
        g_buf_pool_list[buf_id] = buf
        g_mutex.unlock()

    # --------------------------------------------------------------------------
    # INTER-PROCESS COMMUNICATION METHODS
    #     These are used to set up communication channels between objects
    #     through which messages can be passed.
    #

    def ipcSignal(self, rx_name):
        if rx_name not in self.ipc_dict:
            logging.info(f"ERROR: No IPC signal found for {rx_name}")
            return None
        return self.ipc_dict[rx_name]

    def ipcReceivers(self):
        return self.ipc_dict.keys()
    def ipcSig(self, rx_name):
        return self.ipc_dict[rx_name]

    def msgSend(self, rx_name, msg_type, msg_data=None):
        # Detect REQuest Messages
        #     Non-REQuest messages will be "posted" (ie. sent without expecting any response)
        #         Those messages are then freed when the msgHandler calls msgReceive below.
        #     For REQuest messages, the receiver's msgHandler does not free the buffer but changes it into
        #         and ACKnowledge message, whose data is the requested result.
        req_sem = None
        if msg_type[:3] == "REQ":
            req_sem = QSemaphore(0)

        # Retrieve Signal for Communication
        if rx_name not in self.ipc_dict:
            logging.info(f"ERROR: {self.name} is unable to send message to {rx_name}")
            return None
        ipc_sig = self.ipc_dict[rx_name]

        # Build Message Buffer
        msg_buf = [msg_type, self.name, msg_data, req_sem]

        # Allocate Buffer and Send It
        buf_id = self.alloc(msg_buf)
        ipc_sig.emit(buf_id)

        # We're Done if Posted Message
        if req_sem == None:
            return True

        # Block and Wait for Response
        req_sem.acquire(1)

        # Return Result
        [ack_msg_type, ack_name, ack_msg_data, ack_sem] = self.get(buf_id)
        return ack_msg_data

    def msgReceive(self, buf_id):
        msg_buf = self.get(buf_id)
        return msg_buf[:3]

    def msgAcknowledge(self, buf_id, ack_data=None):
        [msg_type, rcv_name, msg_data, req_sem] = self.get(buf_id)

        # Free Buffer for Posted Messages
        if req_sem == None:
            self.free(buf_id)

        # Return Result
        else:
            ack_msg_buf = ["ACK"+msg_type[3:], self.name, ack_data, None]
            self.set(buf_id, ack_msg_buf)
            req_sem.release(1)