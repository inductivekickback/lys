import threading
import Queue
import socket
import select

# TODO: Probably needs to be opened and closed if two debuggers are present.

class RTTError(Exception):
    """Subclass for reporting errors."""
    pass


class RTTEvent(object):
    """A simple object for use when passing data between threads in a queue."""

    EVENT_TYPES = {
    0: 'RTT_EVENT_STARTUP',
    1: 'RTT_EVENT_CONNECTED',
    2: 'RTT_EVENT_RX',
    3: 'RTT_EVENT_IDLE',
    4: 'RTT_EVENT_ERROR'
    }

    EVENT_TYPES_REVERSE = {
    'RTT_EVENT_STARTUP': 0,
    'RTT_EVENT_CONNECTED': 1,
    'RTT_EVENT_RX': 2,
    'RTT_EVENT_IDLE': 3,
    'RTT_EVENT_ERROR': 4
    }

    def __init__(self, event_type):
        """Creates a new object with the given event type."""
        if (isinstance(event_type, str)):
            self.event_type = self.EVENT_TYPES_REVERSE[event_type]
        else:
            self.event_type = event_type
        self.err_str = None
        self.data = None

    def is_type(self, event_type_str):
        """A convenience method for comparing types."""
        return (self.event_type == self.EVENT_TYPES_REVERSE[event_type_str])


class RTT(object):
    """A higher-level interface to an RTT socket. Provides a thread-friendly
    interface for reading and writing to the socket.

    """

    def __init__(self, sn, debug_log=None):
        """Constructs a new RTT object and starts an RTT thread."""
        self.sn = sn

        self._debugLog = debug_log
        self.rxQueue = Queue.Queue()
        self.txQueue = Queue.Queue()
        self.snConfirmed = False
        self.startupIdleCount = 0
        self.closed = False

        self._thread = RTTThread(self.rxQueue, self.txQueue)
        self._thread.start()

    def write(self, data_str):
        """Adds the specified str to write queue."""
        if (self.closed):
            raise RTTError("Can not write to a closed terminal.")
        if (self._debugLog):
            self._debugLog.append('[RTT] Writing: ' + str([ord(x) for x in data_str]))
        self.txQueue.put(data_str)

    def close(self):
        """Instructs the RTT thread to shutdown."""
        self.closed = True
        self._thread.close()

    def read(self, block=True, timeout_s=None):
        """Reads an item from the queue."""
        event = self.rxQueue.get(block, timeout_s)
        if (event.is_type('RTT_EVENT_RX')):
            if (self.snConfirmed):
                if (not event.data.startswith('Process: ')):
                    return event
                else:
                    return RTTEvent('RTT_EVENT_STARTUP')
            else:
                sn = self._parse_sn(event.data)
                if (sn is not None):
                    if (sn == self.sn):
                        self.snConfirmed = True
                        return RTTEvent('RTT_EVENT_CONNECTED')
                    else:
                        self.close()
                        event = RTTEvent('RTT_EVENT_ERROR')
                        event.err_str = ("Incorrect serial number found: %d"%sn)
                        return event
                else:
                    return RTTEvent('RTT_EVENT_STARTUP')
        elif (event.is_type('RTT_EVENT_IDLE')):
            if (self.snConfirmed):
                return event
            else:
                self.close()
                event = RTTEvent('RTT_EVENT_ERROR')
                event.err_str = ("J-Link serial number could not be confirmed.")
                return event
        elif (event.is_type('RTT_EVENT_ERROR')):
            self.close()
            return event
        else:
            raise RTTError("Unknown RTTEvent type: %d" % event.event_type)
        self.rxQueue.task_done()

    def _parse_sn(self, r_str):
        # NOTE: If this is the first time the socket has been read then it will
        #       start by printing a few lines:
        #         "SEGGER J-Link V5.02k - Real time terminal output\r\n"
        #         "J-Link OB-SAM3U128-V2-NordicSemi compiled Mar 15 2016 " \
        #                                        "18:03:17 V1.0, SN=XXXXXX\r\n"
        #         "Process: python2.7.7\r\n"
        for line in r_str.split("\r\n"):
            if (line.startswith("J-Link ")):
                i = line.find("SN=")
                if (i >= 0):
                    try:
                        return int(line[i+3:].strip())
                    except ValueError:
                        pass


class RTTThread(threading.Thread):
    """Creates a simple interface to the telnet socket that is created by
    SEGGER's RTT-enabled J-Link drivers. See
    https://www.segger.com/jlink-rtt.html for more information.

    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 19021
    DEFAULT_READ_LEN = 1024
    DEFAULT_TIMEOUT_S = 0.1

    def __init__(self, rx_queue, tx_queue, host=DEFAULT_HOST, port=DEFAULT_PORT):
        """Creates a new object but does not start the thread."""
        super(RTTThread, self).__init__()
        self.daemon = True

        self.rxQueue = rx_queue
        self.txQueue = tx_queue

        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._stop = threading.Event()

    def run(self):
        """Interacts with the socket until the semaphore is set."""
        try:
            self._sock.connect((self._host, self._port))

            read_socks = ([self._sock],
                [],
                [self._sock],
                self.DEFAULT_TIMEOUT_S)
            all_socks = ([self._sock],
                [self._sock],
                [self._sock],
                self.DEFAULT_TIMEOUT_S)

            while(not self._stop.is_set()):
                idle = True
                if (self.txQueue.empty()):
                    readable, writable, errored = select.select(*read_socks)
                else:
                    readable, writable, errored = select.select(*all_socks)

                if readable:
                    idle = False
                    r_str = self._sock.recv(self.DEFAULT_READ_LEN)
                    if (r_str):
                        event = RTTEvent('RTT_EVENT_RX')
                        event.data = r_str
                        self.rxQueue.put(event)

                if writable:
                    if (self.txQueue.not_empty):
                        if (0 == self._sock.send(self.txQueue.get())):
                            event = RTTEvent('RTT_EVENT_ERROR')
                            event.err_str = 'Socket connection broken.'
                            self.rxQueue.put(event)
                            self.close()

                if (idle):
                   self.rxQueue.put(RTTEvent('RTT_EVENT_IDLE'))

                if (errored):
                    event = RTTEvent('RTT_EVENT_ERROR')
                    event.err_str = 'Select exception'
                    self.rxQueue.put(event)

        except socket.error as err:
            event = RTTEvent('RTT_EVENT_ERROR')
            event.err_str = err.strerror
            self.rxQueue.put(event)
            self.close()

        self._sock.close()

    def close(self):
        """Sets the semaphore to instruct the thread to close."""
        self._stop.set()
