"""Data is passed between python and the board via SEGGER's Real Time Transfer
feature of its J-Link debuggers. A simple protocol is used to synchronize these
transfers. Specifically, the following states are used:

    UNKNOWN->INIT->RUNNING->RESULT->FINISHED

The UNKOWN state is assumed until an RTT socket is established and the J-Link's
serial number has been confirmed. As soon as the board has booted it sends the
INIT message to the PC. If any params need to be sent to the board then they are
sent via PARAM messages. When all params have been sent python sends the START
message and waits for the RESULT message. If any results need to be sent from
the board back to the PC then they are sent as PARAM messages at this time.
Finally, the board sends the FINISHED message to notify the PC that it is
finished sending params. All messages are ACK'd due to the lack of flow control.

Messages are sent in the form:

    [LEN][CMD]

where LEN is total packet size including LEN itself. Furthermore, data can be
sent like this:

    [LEN][LYS_OP_PARAM][PARAM_TYPE][DATA] or [LEN][LYS_OP_LOG][PARAM_TYPE][DATA]

Finally, arrays of data can be sent like this:

    [LEN][LYS_OP_PARAM][LYS_PARAM_TYPE_ARRAY][PARAM_TYPE][DATA]

Note that nested arrays are not allowed.

In C terms, the enums look like this:

typedef enum
{
    LYS_OP_UNKNOWN = 0,
    LYS_OP_INIT,
    LYS_OP_START,
    LYS_OP_RESULT,
    LYS_OP_FINISHED,
    LYS_OP_PARAM,
    LYS_OP_ACK,
    LYS_OP_LOG,
    LYS_OP_COUNT
} lys_op_t;

typedef enum
{
    LYS_PARAM_TYPE_UINT32 = 0,
    LYS_PARAM_TYPE_INT32,
    LYS_PARAM_TYPE_UINT8,
    LYS_PARAM_TYPE_INT8,
    LYS_PARAM_TYPE_BOOL,
    LYS_PARAM_TYPE_STRING,
    LYS_PARAM_TYPE_ARRAY,
    LYS_PARAM_TYPE_COUNT
} lys_param_t;

"""
import time
import struct


LYS_MAX_STR_LEN = 64
LYS_MAX_ARRAY_LEN = 64
LYS_MAX_MSG_LEN = 64


class LysError(Exception):
    """Subclass for reporting errors."""
    pass


class LysOp(object):
    """Creates and parses entire Lys messages."""

    OP_TYPES = {
    0: 'LYS_OP_UNKNOWN',
    1: 'LYS_OP_INIT',
    2: 'LYS_OP_START',
    3: 'LYS_OP_RESULT',
    4: 'LYS_OP_FINISHED',
    5: 'LYS_OP_PARAM',
    6: 'LYS_OP_ACK',
    7: 'LYS_OP_LOG'
    }

    OP_TYPES_REVERSE = {
    'LYS_OP_UNKNOWN': 0,
    'LYS_OP_INIT': 1,
    'LYS_OP_START': 2,
    'LYS_OP_RESULT': 3,
    'LYS_OP_FINISHED': 4,
    'LYS_OP_PARAM': 5,
    'LYS_OP_ACK': 6,
    'LYS_OP_LOG': 7
    }

    def __init__(self, op_type=None, data=None):
        """Creates a new Lys message with the given op and data."""
        self.opType = None
        self.data = data

        if (op_type is not None):
            self.set_op_type(op_type)

    def is_op(self, op_type):
        """Returns True if this object has the same op type as the one given."""
        return (self.opType == LysOp.find_op(op_type))

    @classmethod
    def find_op(cls, op_type):
        """Returns the int value for the given op_type."""
        if (isinstance(op_type, int)):
            if (cls.OP_TYPES.has_key(op_type)):
                return op_type
        elif (isinstance(op_type, str)):
            if (cls.OP_TYPES_REVERSE.has_key(op_type)):
                return cls.OP_TYPES_REVERSE[op_type]
        raise LysError('Unknown OP_TYPE: ', op_type)

    @classmethod
    def find_op_str(cls, op_type):
        """Returns the str value for the given op_type."""
        if (isinstance(op_type, str)):
            if (cls.OP_TYPES_REVERSE.has_key(op_type)):
                return op_type
        elif (isinstance(op_type, int)):
            if (cls.OP_TYPES.has_key(op_type)):
                return cls.OP_TYPES[op_type]
        raise LysError('Unknown OP_TYPE: ', op_type)

    def op_type_str(self):
        """Returns the LYS_OP_X value of this object's opType."""
        return self.OP_TYPES[self.opType]

    def set_op_type(self, op_type, data=None):
        """Sets this object's opType."""
        self.opType = LysOp.find_op(op_type)
        self.set_data(data)

    def set_data(self, data):
        """Sets this object's data. Raises an error if the object's opType is
        not allowed to have data.

        """
        if (data is None):
            self.data = data
        else:
            if (self.is_op('LYS_OP_PARAM') or self.is_op('LYS_OP_LOG')):
                self.data = data
            else:
                raise LysError('Can not add data to an op of type %s.' %
                    self.op_type_str())

    def dumps(self):
        """Returns this object's data as a serialized str."""
        if (self.opType is None):
            raise LysError("Can not call dumps on unitialized object.")
        if (self.data is None):
            return LysOp.encode(self.opType)
        else:
            return LysOp.encode(self.opType,
                self.data.paramType,
                self.data.paramData)

    @staticmethod
    def encode(op, param_type=None, param_data=None):
        """Returns the specified op as a serialized str. The param_data may be a
        list of values.

        """
        op = LysOp.find_op_str(op)

        if (param_type is not None):
            param_type = LysData.find_param_type_str(param_type)

        if (('LYS_OP_PARAM' == op) or ('LYS_OP_LOG' == op)):
            if ((param_type is None) or (param_data is None)):
                raise LysError("Both param type and data are required.")
            return LysData.encode(param_type, param_data)

        return (chr(2) + chr(LysOp.find_op(op)))

    @staticmethod
    def decode(data_str):
        """Expects a data_str in the form [LEN][PARAM_TYPE][DATA]. If the
        data_str contains any additional information then the unparsed remainder
        will be returned. Returns a tuple in the form (op, param_type|None,
        param_data|None, remainder|None).

        """
        length = ord(data_str[0])
        op = ord(data_str[1])

        if (LYS_MAX_MSG_LEN < length):
            raise LysError("Message is too long: %d" % length)

        if ((LysOp.find_op('LYS_OP_PARAM') == op) or
            (LysOp.find_op('LYS_OP_LOG') == op)):
            param_type, param_data, remainder = LysData.decode(data_str)
            return (op, param_type, param_data, remainder)
        elif (2 != length):
            raise LysError("Non-param message is too long.")

        remainder = data_str[length:]

        if (remainder):
            return (op, None, None, remainder)
        else:
            return (op, None, None, None)

    def parse_str(self, data_str):
        """Expects a data_str in the form [LEN][PARAM_TYPE][DATA]. If the
        data_str contains any additional information then the unparsed remainder
        will be returned. If the entire data_str is consumed then None will be
        returned.

        """
        op, param_type, data, remaining = LysOp.decode(data_str)

        if (data is not None):
            self.data = LysData(param_type, data)
        else:
            self.data = None

        self.set_op_type(op)

        if (remaining):
            return remaining
        else:
            return None


class LysData(object):
    """A simple class for serializing and deserializing strings of lys_param_t
    data. Does NOT support recursive data types.

    """

    PARAM_TYPES = {
    0: 'LYS_PARAM_TYPE_UINT32',
    1: 'LYS_PARAM_TYPE_INT32',
    2: 'LYS_PARAM_TYPE_UINT8',
    3: 'LYS_PARAM_TYPE_INT8',
    4: 'LYS_PARAM_TYPE_BOOL',
    5: 'LYS_PARAM_TYPE_STRING',
    6: 'LYS_PARAM_TYPE_ARRAY'
    }

    PARAM_TYPES_REVERSE = {
    'LYS_PARAM_TYPE_UINT32': 0,
    'LYS_PARAM_TYPE_INT32': 1,
    'LYS_PARAM_TYPE_UINT8': 2,
    'LYS_PARAM_TYPE_INT8': 3,
    'LYS_PARAM_TYPE_BOOL': 4,
    'LYS_PARAM_TYPE_STRING': 5,
    'LYS_PARAM_TYPE_ARRAY': 6
    }

    PARAM_TYPE_LENS = {
    'LYS_PARAM_TYPE_UINT32': 4,
    'LYS_PARAM_TYPE_INT32': 4,
    'LYS_PARAM_TYPE_UINT8': 1,
    'LYS_PARAM_TYPE_INT8': 1,
    'LYS_PARAM_TYPE_BOOL': 1
    }

    def __init__(self, param_type=None, param_data=None):
        """Creates a new LysData payload."""
        self.paramType = None
        self.paramData = None

        if (param_type is not None):
            self.set_param_type(param_type, param_data)

    def is_param_type(self, param_type):
        """Returns True if this object has the same param type as the
        one given.

        """
        return (self.paramType == LysData.find_param_type(param_type))

    @classmethod
    def find_param_type(cls, param_type):
        """Returns the int value for the given param type."""
        if (isinstance(param_type, int)):
            if (cls.PARAM_TYPES.has_key(param_type)):
                return param_type
        elif (isinstance(param_type, str)):
            if (cls.PARAM_TYPES_REVERSE.has_key(param_type)):
                return cls.PARAM_TYPES_REVERSE[param_type]
        raise LysError('Unknown PARAM_TYPE: ', param_type)

    @classmethod
    def find_param_type_str(cls, param_type):
        """Returns the str value for the given param type."""
        if (isinstance(param_type, int)):
            if (cls.PARAM_TYPES.has_key(param_type)):
                return cls.PARAM_TYPES[param_type]
        elif (isinstance(param_type, str)):
            if (cls.PARAM_TYPES_REVERSE.has_key(param_type)):
                return param_type
        raise LysError('Unknown PARAM_TYPE: ', param_type)

    def param_type_str(self):
        """Returns the LYS_PARAM_TYPE_X value of this object's paramType."""
        return self.PARAM_TYPES[self.paramType]

    def set_param_type(self, param_type, data=None):
        """Sets this object's paramType. The int or str value of the param
        type can be used.

        """
        self.paramType = LysData.find_param_type(param_type)
        self.set_data(data)

    def set_data(self, data):
        """Sets this object's data."""
        self.data = data

    def dumps(self):
        """Returns this object's data as a serialized str."""
        if (self.paramType is None or self.paramData is None):
            raise LysError("Can not call dumps on uninitialized object.")
        return LysData.encode(self.paramType, self.paramData)

    @staticmethod
    def encode(param_type, value):
        """Returns the specified data as a serialized str. The value may be a
        list of values. The param_type can be an int or a str. 

        """
        param_type = LysData.find_param_type_str(param_type)

        result = [chr(LysOp.find_op('LYS_OP_PARAM'))]
        if (isinstance(value, list)):
            result.append(chr(LysData.find_param_type('LYS_PARAM_TYPE_ARRAY')))
        else:
            value = [value]

        result.append(chr(LysData.find_param_type(param_type)))
        for v in value:
            result.append(LysData._encode(param_type, v))

        result = ''.join(result)
        length = len(result) + 1
        if (LYS_MAX_MSG_LEN < length):
            raise LysError("Excessive data length: %d" % length)

        return (chr(length) + result)

    @staticmethod
    def decode(data_str):
        """Expects a data_str in the form [LEN][PARAM_TYPE][DATA] or
        [LEN][LYS_PARAM_ARRAY][PARAM_TYPE][DATA]. If the data_str contains any
        additional information then the unparsed remainder will be returned.
        Returns a tuple in the form (param_type, data, remainder|None).

        """
        length = ord(data_str[0])
        op = ord(data_str[1])

        if (LYS_MAX_MSG_LEN < length):
            raise LysError("Message is too long: %d" % length)

        if (LysOp.find_op('LYS_OP_PARAM') != op):
            if (LysOp.find_op('LYS_OP_LOG') != op):
                raise LysError('Message is not allowed to have data.')

        param_type = ord(data_str[2])
        data = data_str[3:length]
        remainder = data_str[length:]
        param_type_str = LysData.find_param_type_str(param_type)
        parsed_data = None

        if ('LYS_PARAM_TYPE_ARRAY' == param_type_str):
            param_type = ord(data_str[3])
            data = data_str[4:length]
            length -= 4
            param_type_str = LysData.find_param_type_str(param_type)
            parsed_data = []
            while (length > 0):
                result = LysData._parse(param_type_str, data)
                parsed, param_len, data = result
                length -= param_len
                parsed_data.append(parsed)
        elif ('LYS_PARAM_TYPE_STRING' == param_type_str):
            param_len = (length - 3)
            parsed_data = data[:param_len]
            data = data[param_len:]
        else:
            parsed_data, param_len, data = LysData._parse(param_type_str, data)

        if (data):
            remainder += data

        if (remainder):
            return (param_type, parsed_data, remainder)
        else:
            return (param_type, parsed_data, None)

    def parse_str(self, data_str):
        """Expects a data_str in the form [LEN][PARAM_TYPE][DATA] or
        [LEN][LYS_PARAM_TYPE_ARRAY][PARAM_TYPE][DATA]. If the data_str contains any
        additional information then the unparsed remainder will be returned. If
        the entire data_str is consumed then None will be returned.

        """
        param_type, data, remaining = LysData.decode(data_str)

        self.paramData = data
        self.set_param_type(param_type)

        if (remaining):
            return remaining
        else:
            return None

    @staticmethod
    def _encode(param_type_str, value):
        """"""
        result = []
        try:
            if ('LYS_PARAM_TYPE_UINT32' == param_type_str):
                result.append(struct.pack('I', value))
            elif ('LYS_PARAM_TYPE_INT32' == param_type_str):
                result.append(struct.pack('i', value))
            elif ('LYS_PARAM_TYPE_UINT8' == param_type_str):
                result.append(struct.pack('B', value))
            elif ('LYS_PARAM_TYPE_INT8' == param_type_str):
                result.append(struct.pack('b', value))
            elif ('LYS_PARAM_TYPE_BOOL' == param_type_str):
                result.append(struct.pack('?', value))
            elif ('LYS_PARAM_TYPE_STRING' == param_type_str):
                result.append(value)
            else:
                raise LysError("Unimplemented lys_param_t: %s" % param_type_str)
        except struct.error as err:
            raise LysError("Invalid value (0x%X) for type %s." %
                (value, param_type_str))
        return ''.join(result)

    @staticmethod
    def _parse(param_type_str, data):
        """"""
        length = LysData.PARAM_TYPE_LENS[param_type_str]
        if ('LYS_PARAM_TYPE_UINT32' == param_type_str):
            return (struct.unpack('I', data[:length])[0], length, data[length:])
        elif ('LYS_PARAM_TYPE_INT32' == param_type_str):
            return (struct.unpack('i', data[:length])[0], length, data[length:])
        elif ('LYS_PARAM_TYPE_UINT8' == param_type_str):
            return (struct.unpack('B', data[:length])[0], length, data[length:])
        elif ('LYS_PARAM_TYPE_INT8' == param_type_str):
            return (struct.unpack('b', data[:length])[0], length, data[length:])
        elif ('LYS_PARAM_TYPE_BOOL' == param_type_str):
            return (struct.unpack('?', data[:length])[0], length, data[length:])
        else:
            raise LysError("Unimplemented lys_param_t: %s" % param_type_str)


class Lys(object):
    """A high-level interface to the Lys protocol."""

    def __init__(self, write_func, state_cb, input_params=None):
        """The input_params should be a sequence of (param_type, param_data)
        tuples. The state_cb will receive lys_op and desc_str parameters.

        """
        if (write_func is None):
            raise LysError("The write_func can not be None.")
        if (state_cb is None):
            raise LysError("The state_cb can not be None.")

        self.inputParams = input_params
        self.state = LysOp.find_op('LYS_OP_UNKNOWN')

        self._writeFunc = write_func
        self._stateCB = state_cb
        self._remainder = None
        self._waitingForACK = False
        self._msgOutFIFO = []
        self._results = []

    def is_state(self, op_type):
        """Convenience method for determining the state of the Lys object."""
        return (self.state == LysOp.find_op(op_type))

    def parse(self, data_str):
        """"""
        if (self._remainder):
            data_str = ''.join((self._remainder, data_str))

        op, param_type, param_data, remainder = LysOp.decode(data_str)
        self._remainder = remainder

        self._update(op, param_type, param_data)

        if (self._remainder):
            try:
                self.parse(self._remainder)
            except LysError:
                pass

    def reset(self):
        """"""
        self.state = LysOp.find_op('LYS_OP_UNKNOWN')
        self._remainder = None
        self._waitingForACK = False
        self._msgOutFIFO = []
        self._results = []

    def _update(self, op, param_type=None, param_data=None):
        """"""
        if (self._waitingForACK):
            if (LysOp.find_op('LYS_OP_ACK') == op):
                self._waitingForACK = False
                if (not self._msgOutFIFO):
                    if (self.is_state('LYS_OP_INIT')):
                        self.state = LysOp.find_op('LYS_OP_START')
                        self._stateCB(self.state, None)
                else:
                    self._send_next_msg()
            else:
                self.is_state('LYS_OP_UNKNOWN')
                self._stateCB(self.state, "ACK not received.")
                self._waitingForACK = False
            return

        if (LysOp.find_op('LYS_OP_LOG') == op):
            self._stateCB(op, (param_type, param_data))
            self._msgOutFIFO.append((LysOp.find_op('LYS_OP_ACK'),
                None,
                None,
                False))
        elif (LysOp.find_op('LYS_OP_UNKNOWN') == op):
            self.state = op
            self._stateCB(self.state, "The nRF board reported an error.")
        elif (LysOp.find_op('LYS_OP_ACK') == op):
            self.is_state('LYS_OP_UNKNOWN')
            self._stateCB(self.state,
                "Unexpected LYS_OP_ACK message received.")
        elif (LysOp.find_op('LYS_OP_INIT') == op):
            self._msgOutFIFO.append((LysOp.find_op('LYS_OP_ACK'),
                None,
                None,
                False))
            if (self.is_state('LYS_OP_UNKNOWN')):
                self._results = []
                self.state = op
                self._stateCB(self.state, None)
                if (self.inputParams):
                    for param_type, param_data in self.inputParams:
                        self._msgOutFIFO.append((LysOp.find_op('LYS_OP_PARAM'),
                            param_type,
                            param_data,
                            True))
                self._msgOutFIFO.append((LysOp.find_op('LYS_OP_START'),
                    None,
                    None,
                    True))
            else:
                self.is_state('LYS_OP_UNKNOWN')
                self._stateCB(self.state,
                    "Unexpected LYS_OP_INIT message received.")
        elif (LysOp.find_op('LYS_OP_RESULT') == op):
            self._msgOutFIFO.append((LysOp.find_op('LYS_OP_ACK'),
                None,
                None,
                False))
            if (LysOp.find_op('LYS_OP_START') == self.state):
                self.state = op
                self._stateCB(self.state, None)
            else:
                self.state = LysOp.find_op('LYS_OP_UNKNOWN')
                self._stateCB(self.state,
                    "Unexpected LYS_OP_RESULT message received.")
        elif (LysOp.find_op('LYS_OP_PARAM') == op):
            self._msgOutFIFO.append((LysOp.find_op('LYS_OP_ACK'),
                None,
                None,
                False))
            if (LysOp.find_op('LYS_OP_RESULT') == self.state):
                self._results.append((param_type, param_data))
            else:
                self.state = LysOp.find_op('LYS_OP_UNKNOWN')
                self._stateCB(self.state,
                    "Unexpected LYS_OP_FINISHED message received.")
        elif (LysOp.find_op('LYS_OP_FINISHED') == op):
            self._msgOutFIFO.append((LysOp.find_op('LYS_OP_ACK'),
                None,
                None,
                False))
            if (self.is_state('LYS_OP_RESULT')):
                self.state = op
                self._stateCB(self.state, self._results)
            else:
                self.is_state('LYS_OP_UNKNOWN')
                self._stateCB(self.state,
                    "Unexpected LYS_OP_FINISHED message received.")

        self._send_next_msg()

    def _send_next_msg(self):
        """"""
        if (self._waitingForACK):
            raise LysError("Attempt to send message while waiting for ACK.")

        if (self._msgOutFIFO):
            msg = self._msgOutFIFO[0]
            del self._msgOutFIFO[0]
            op, param_type, param_data, ack_reqd = msg

            self._writeFunc(LysOp.encode(op, param_type, param_data))

            if (ack_reqd):
                self._waitingForACK = True
            else:
                self._send_next_msg()
