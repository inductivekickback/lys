#!/usr/bin/env python
"""A simple stack for using the Lys protocol to communicate with firmware via
a SEGGER J-Link debugger. The firmware can be given an array of parameters to
use before it is started. Furthermore, the firmware can send log strings back
to the PC and return an array of results when it is finished.

If the project uses Makefiles then the path to the directory where make can be
run can be specified in order to compile and download the firmware. This only
needs to be done once. The default make target is 'flash_debug'.

For convenience, the LCLI class allows parameters and results to be passed as
tuples in the form (TYPE, VALUE) where TYPE can be one of the following
strings: UINT32, INT32, UINT8, INT8, BOOL, STRING. The VALUE will be converted
to and from the corresponding TYPE. Arrays can be created by supplying an array
of items of the specified TYPE e.g. ('INT8', [-2, -1, 0, 128]). Results will be
reported in a simplified format as well.

Use either -h or --help to print the help menu from a command line.

"""
import os
import sys
import argparse
import threading
import datetime
import ast

import maker
import dbg
import rtt
import lys


EXIT_CODES = {
    'LCLI_EXIT_CODE_SUCCESS': 0,
    'LCLI_EXIT_CODE_INVALID_PARAMS': 1,
    'LCLI_EXIT_CODE_INVALID_INIT_PARAMS': 2,
    'LCLI_EXIT_CODE_JLINK_NOT_FOUND': 3,
    'LCLI_EXIT_CODE_INTERNAL_ERROR': 4,
    'LCLI_EXIT_CODE_MAKE_ERROR': 5
    }


class LCLIError(Exception):
    """Subclass for reporting errors."""

    def __init__(self, err_str, exit_code=None):
        """Creates a new object with the given message and exit code."""
        super(LCLIError, self).__init__(err_str)
        self.exit_code = exit_code


class LCLI(object):
    """Orchestrates communication between the various modules that implement
    the Lys stack.

    """

    TIMESTAMP_FMT = '%Y-%m-%d %H:%M:%S'

    def __init__(self):
        """Creates a new object."""
        self.result = None
        self.error = False
        self.debugLog = []
        self.lysLog = []
        self._lys = None
        self._terminal = None
        self._timer = None

    def run(self,
                sn,
                init_params=None,
                makefile_dir=None,
                no_result=False,
                timeout_s=None):
        """A serial number is always required. The init_params may or may not
        be required depending on the firmware. If a makefile_dir is specified
        then make will be called in that directory to compile and download the
        firmware. If no_result is set to True then the firmware will be started
        and then the RTT terminal will be closed instead of waiting for it to
        finish. The timeout_s is similar to no_result except it waits the
        specified number of seconds after the firmware is started before
        closing. Returns a dictionary with the following keys:
            'INIT_PARAMS',
            'LOG',
            'RESULT',
            'TIMESTAMP',
            'ERROR',
            'TIMEOUT_S' (optional)
        If present, the LOG data will be an array of log strings.
        """
        if (no_result and timeout_s):
            raise LCLIError('The no_result and timeout_s parameters ' +
                'are mutually exclusive.',
                EXIT_CODES['LCLI_EXIT_CODE_INVALID_PARAMS'])

        self._no_result = no_result
        self._timeout_s = timeout_s

        # Step 0: Ensure J-Link is attached (otherwise make could fail).
        jlinks = dbg.enum_jlinks()
        if (jlinks is None):
            raise LCLIError('No J-Link debuggers found.',
                EXIT_CODES['LCLI_EXIT_CODE_JLINK_NOT_FOUND'])

        if (not sn in jlinks):
            raise LCLIError('The specified J-Link was not found (SN=%d).' % sn,
                EXIT_CODES['LCLI_EXIT_CODE_JLINK_NOT_FOUND'])

        # Step 1 (optional): Compile and download.
        if (makefile_dir):
            self.debugLog.append("[lcli] Building and flashing project.")
            maker.build_and_flash(makefile_dir, sn)

        # Step 2: Connect, halt, reset.
        self.debugLog.append("[lcli] Connecting to J-Link and resetting target.")
        dbg.attach_and_reset(sn)

        # Step 3: Open RTT socket.
        self.debugLog.append("[lcli] Opening RTT.")
        self._terminal_interact(sn, init_params)

        dbg.close()

        result_dict = {}
        result_dict['INIT_PARAMS'] = init_params
        result_dict['LOG'] = self.lysLog
        result_dict['RESULT'] = self.result
        result_dict['ERROR'] = self.error

        if (self._timer):
            result_dict['TIMEOUT_S'] = self._timer.interval

        now = datetime.datetime.now()
        result_dict['TIMESTAMP'] = now.strftime(self.TIMESTAMP_FMT)
        return result_dict

    def close(self):
        """Closes the terminal regardless of whether or not the firwmare has
        finished.

        """
        if (self._timer):
            self._timer.cancel()

        if (self._lys):
            self._lys.reset()

        if (self._terminal):
            self._terminal.close()

        self.debugLog.append('[lcli] Closing.')

    @staticmethod
    def parse_condensed_params(condensed_params_str):
        """Expects an array in the form "[(param_type, value),...]" where
        each param_type is a key in LysData.PARAM_TYPES,
        LysData.PARAM_TYPES_REVERSE, or a shortened form of an entry in
        LysData.PARAM_TYPES_REVERSE (e.g. 'STRING' instead of
        'LYS_PARAM_TYPE_STRING'). The array can be raw string that is read from
        a file. Returns the str parsed as a python object.

        """
        # Parse the params if they are given as a str.
        result = condensed_params_str
        if (isinstance(condensed_params_str, str)):
            try:
                result = ast.literal_eval(condensed_params_str)
            except SyntaxError, ValueError:
                raise LCLIError("Malformed init params str (SyntaxError).")

        if (not isinstance(result, list)):
            if (not isinstance(result, tuple)):
                raise LCLIError('Init params must be contained in an array ' +
                    'or tuple.',
                    EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])
            else:
                result = list(result)

        for i in range(0, len(result)):
            t = result[i]
            if (not isinstance(t, tuple)):
                raise LCLIError("Init params str must be an array of tuples.",
                    EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])
            elif (2 != len(t)):
                raise LCLIError("Init params str tuples must be in the form " +
                    "(param_type_str, value).",
                    EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])

            k, v = t
            if (isinstance(k, int)):
                if (not k in lys.LysData.PARAM_TYPES):
                    raise LCLIError("Unknown param_type: %d" % k,
                        EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])
            elif (isinstance(k, str)):
                if (not k in lys.LysData.PARAM_TYPES_REVERSE):
                    # Try again with the LYS_PARAM_TYPE_ prefix.
                    exp = ('LYS_PARAM_TYPE_' + k)
                    if (not lys.LysData.PARAM_TYPES_REVERSE.has_key(exp)):
                        raise LCLIError("Unknown param_type str: %s" % k,
                            EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])
                    # Replace the existing string with the expanded one.
                    result[i] = (exp, v)
            else:
                raise LCLIError("Unknown param_type: %r" % k,
                    EXIT_CODES['LCLI_EXIT_CODE_INVALID_INIT_PARAMS'])
        return result

    @staticmethod
    def expand_param_types(params_array, short_form=True):
        """Expects an array of tuples in the form (param_type, value) and
        returns a new array where the param_type items have been converted to
        their str form. If short_form is True then the LYS_PARAM_TYPE_ prefix
        will be dropped.

        """
        result = []

        prefix_len = 0
        if short_form:
            prefix_len = len('LYS_PARAM_TYPE_')

        for t in params_array:
            if (2 != len(t)):
                raise LCLIError('Params array tuples must have two items.',
                    EXIT_CODES['LCLI_EXIT_CODE_INTERNAL_ERROR'])
            key, value = t
            if (isinstance(key, int)):
                result.append((lys.LysData.PARAM_TYPES[key][prefix_len:],value))
            elif (isinstance(key, str)):
                if (key.startswith('LYS_PARAM_TYPE_')):
                    result.append((key[prefix_len:], value))
                else:
                    result.append((key, value))
            else:
                raise LCLIError("Unknown param_type: %r" % key,
                    EXIT_CODES['LCLI_EXIT_CODE_INTERNAL_ERROR'])
        return result

    def _terminal_interact(self, sn, init_params):
        """Uses a queue to pass data between this thread and the thread that is
        communicating with the RTT socket.

        """
        self._terminal = rtt.RTT(sn, self.debugLog)
        while (not self._terminal.closed):
            rtt_event = self._terminal.read()
            if (rtt_event.is_type('RTT_EVENT_STARTUP')):
                self.debugLog.append("[lcli] RTT starting up...")
            elif (rtt_event.is_type('RTT_EVENT_CONNECTED')):
                self.debugLog.append("[lcli] Initializing Lys...")
                self._lys = lys.Lys(self._terminal.write,
                    self._state_changed,
                    init_params)
                dbg.go()
            elif (rtt_event.is_type('RTT_EVENT_RX')):
                printable_data = [ord(x) for x in rtt_event.data]
                if (self._lys is not None):
                    self.debugLog.append('[lcli] Data received: %r' %
                        printable_data)
                    self._lys.parse(rtt_event.data)
                else:
                    self.debugLog.append("[lcli] Ignoring stale data: %r" %
                        printable_data)
            elif (rtt_event.is_type('RTT_EVENT_IDLE')):
                if (self._lys):
                    if (self._lys.is_state('LYS_OP_FINISHED')):
                        self.debugLog.append('[lcli] Finished, shutting down.')
                        self.close()
            elif (rtt_event.is_type('RTT_EVENT_ERROR')):
                self.error = True
                self.debugLog.append("[lcli] Error: %s" % rtt_event.err_str)
                self.close()
            else:
                raise LCLIError('Unknown RTTEvent type: %d' %
                    rtt_event.event_type,
                    EXIT_CODES['LCLI_EXIT_CODE_INTERNAL_ERROR'])

    def _state_changed(self, lys_op, data):
            self.debugLog.append('[lcli] State_changed:' +
                lys.LysOp.OP_TYPES[lys_op] + ": %s" % str(data))
            if (lys.LysOp.OP_TYPES_REVERSE['LYS_OP_UNKNOWN'] == lys_op):
                self.error = True
                self.debugLog.append('[lcli] Error reported, shutting down.')
                self.close()
            elif (lys.LysOp.OP_TYPES_REVERSE['LYS_OP_FINISHED'] == lys_op):
                self.debugLog.append("[lcli] Finished, saving result.")
                self.result = data
            elif (lys.LysOp.OP_TYPES_REVERSE['LYS_OP_LOG'] == lys_op):
                self.lysLog.append(data)
            elif (lys.LysOp.OP_TYPES_REVERSE['LYS_OP_START'] == lys_op):
                if (self._no_result):
                    self.debugLog.append("[lcli] Firmware started, exiting.")
                    self.close()
                if (self._timeout_s):
                    self.debugLog.append('[lcli] Setting timer for %s seconds.'%
                        self._timeout_s)
                    self._timer = threading.Timer(self._timeout_s, self.close)
                    self._timer.start()


def _run(args_obj):
    try:
        _lcli = LCLI()

        if (args.init_params):
            args.init_params = LCLI.parse_condensed_params(args.init_params)

        result_dict = _lcli.run(args_obj.serial_number,
            args_obj.init_params,
            args_obj.makefile_dir,
            args_obj.no_result,
            args_obj.timeout_s)

        if (result_dict['RESULT']):
            expanded = LCLI.expand_param_types(result_dict['RESULT'])
            result_dict['RESULT'] = expanded

        if (result_dict['INIT_PARAMS']):
            expanded = LCLI.expand_param_types(result_dict['INIT_PARAMS'])
            result_dict['INIT_PARAMS'] = expanded

        if (result_dict['LOG']):
            expanded = LCLI.expand_param_types(result_dict['LOG'])
            result_dict['LOG'] = expanded

        if (args_obj.log_file):
            if (args_obj.verbose):
                result_dict['VERBOSE_OUTPUT'] = _lcli.debugLog
            with open(args_obj.log_file, 'ab') as log:
                log.write(str(result_dict) + os.linesep)
        else:
            if (args_obj.verbose):
                print os.linesep.join(_lcli.debugLog)
            print result_dict
        return EXIT_CODES['LCLI_EXIT_CODE_SUCCESS']
    except LCLIError as err:
        print os.linesep + 'ERROR: ' + err.message + os.linesep
        return err.exit_code
    except maker.MakerError as err:
        print os.linesep + 'ERROR: ' + err.message + os.linesep
        return EXIT_CODES['LCLI_EXIT_CODE_MAKE_ERROR']


if __name__ == "__main__":
    """Parses the command line arguments when the program is run from a shell.
    The program can also be run by instantiating an LCLI object and calling its
    run method directly.

    """
    parser = argparse.ArgumentParser(description='Execute a Lys experiment.')
    parser.add_argument('-s',
        '--serial_number',
        required=True,
        dest='serial_number',
        type=int,
        help='the serial number of the J-Link debugger')
    parser.add_argument('-d',
        '--makefile_dir',
        dest='makefile_dir',
        type=str,
        help='path to directory where make can be used to compile and ' + 
        'download the firmware')
    parser.add_argument('-i',
        '--init_params',
        dest='init_params',
        type=str,
        help='a python array of input params to send to the firmware')
    parser.add_argument('-v',
        dest='verbose',
        action='store_true',
        help='include verbose output')
    parser.add_argument('-f',
        '--log_file',
        dest='log_file',
        type=str,
        help='a path where a log file can be created (suppresses stdout)')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('-t',
        '--timeout',
        dest='timeout_s',
        type=int,
        help='exit this number of seconds after starting the firmware')
    group.add_argument('-n',
        '--no_result',
        dest='no_result',
        action='store_true',
        help='exit immediately after starting the firmware')

    args = parser.parse_args()
    sys.exit(_run(args))
