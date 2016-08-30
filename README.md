# lys
Lys is a serialization protocol for synchronization and data exchange between a PC and an embedded device. It automates the following steps:

  0. Compile and download the firmware
  1. Reset the device
  2. Send some parameters from the PC to the device
  3. Allow the device to run for some arbitrary amount of time or until it finishes
  4. Allow the device to send log messages back to the PC while it's running
  5. Allow the device to report a result if it has finished

The firmware only needs to be compiled and downloaded once so step zero is optional.

Background
------------------------
A serial port is the obvious choice for passing data between a PC and an embedded device. [SEGGER's RTT](https://www.segger.com/jlink-rtt.html) functionality is even better because it acts like a serial port but doesn't tie up the device's UART peripheral. Furthermore, RTT works with all J-Link devices and it's pretty easy to work with from the PC because the interface is just a socket.

Python is my favorite desktop programming language so, naturally, [pynrfjprog](http://infocenter.nordicsemi.com/index.jsp?topic=%2Fcom.nordic.infocenter.tools%2Fdita%2Ftools%2Fpynrfjprog%2Fpynrfjprog_lpage.html) is my preferred tool for interacting with a J-Link debugger. I knew that I could use pynrfjprog to enumerate the J-Link debuggers that are currently plugged into the PC, select one of the debuggers by serial number, and then use the debugger to reset the device. Upon further experimentation I confirmed that connecting to a J-Link debugger with pynrfjprog causes the J-Link driver to automatically make the RTT socket available until pynrjprog disconnects from the debugger.

In fact, the RTT socket can be read directly from pynrfjprog using friendly functions like `rtt_start` and `rtt_read`. However, I couldn't get pynrfjprog's RTT functionality to work when multiple debuggers were opened concurrently so I decided to roll my own [socket class](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/rtt.py) with the hope that I could use it to ping-pong between multiple RTT connections in the future. The RTT socket is accessable via TCP at 127.0.0.1:19021. It always starts by printing a useful blurb like this one when a new connection is accepted:

    SEGGER J-Link V5.02k - Real time terminal output
    J-Link OB-SAM3U128-V2-NordicSemi compiled Mar 15 2016
    18:03:17 V1.0, SN=XXXXXX
    Process: python2.7.7

I parse this blurb to make sure that the RTT socket is working and that I'm connected to the correct debugger. If the J-Link driver is unhappy then it may accept connections but will not write the blurb.

The Protocol
------------
Every Lys message includes an operation (OP). The OP enumeration is very simple:

    typedef enum
    {
      LYS_OP_UNKNOWN=0,// Signifies that something has gone wrong
      LYS_OP_INIT,     // Sent by the embedded device after a reset
      LYS_OP_START,    // Sent by the PC after all of the initial params have been sent
      LYS_OP_RESULT,   // Sent by the embedded device when result params are available
      LYS_OP_FINISHED, // Sent by the embedded device after all of the result params have been sent
      LYS_OP_PARAM,    // Used to send param data
      LYS_OP_ACK,      // Acknowledges that the previous message was received
      LYS_OP_LOG,      // Used to send a param while the embedded device is running
      LYS_OP_COUNT
    } lys_op_t;

Simple Lys messages are in the form:

    [LEN (1)][OP (1)]

where the LEN is the message length including the LEN byte itself.

LYS_OP_PARAM and LYS_OP_LOG messages are in the form:
    
    [LEN (1)][OP (1)][lys_param_type_t (1)][data (p)]

where p is the length of the specified lys_param_type_t.

NOTE: Strings length zero are not allowed.

LYS_PARAM_TYPE_ARRAY messages are in the form:
    
    [LEN (1)][OP (1)][LYS_PARAM_TYPE_ARRAY (1)][lys_param_type_t (1)][data (n * p)]

where n is the length of the array and p is the length of the specified lys_param_type_t.

NOTE: Nested arrays, arrays of strings, and arrays of length zero are not allowed.

The available parameter types are:

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
    } lys_param_type_t;

Take a look at the [header file](https://github.com/inductivekickback/lys/blob/master/embedded/nRF5_SDK_11.0.0/examples/peripheral/lys/lys.h) for more details.

I decided to be pedantic about the C data types [on the PC side](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/lys.py) in order to avoid surprises. Python's struct class is really useful in situations like this one.

The Implementation
------------------
The C library only requires stdbool.h, stdint.h, string.h, and SEGGER_RTT.h and has the usual structure:

 - lys.h
 - lys.c

[Here](https://github.com/inductivekickback/lys/blob/master/embedded/nRF5_SDK_11.0.0/examples/peripheral/lys/main.c) is a simple example of how Lys can be used to parameterize the classic blinky example.

The Python stack is a little more involved but the individual pieces are pretty simple:

 - [dbg.py](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/dbg.py) - A wrapper around pynrfjprog
 - [rtt.py](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/rtt.py) - A TCP socket in its own thread with a queue-based interface
 - [lys.py](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/lys.py) - Encodes and decodes Lys messages
 - [maker.py](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/maker.py) - A simple wrapper for invoking Make
 - [lcli.py](https://github.com/inductivekickback/lys/blob/master/PC/python/lys/lcli.py) - The Lys Command Line Interface

All of the Python classes are part of a package so they should be kept together in a folder named 'lys'.

I use GCC so it was really easy to add support for compiling and downloading the embedded device's firmware using Make. There is a post regarding my Makefiles [here](https://devzone.nordicsemi.com/blogs/1000/getting-more-out-of-make/).

Usage
-----
DISCLAIMER: I have only ever used the Python stack on a Linux machine using Python v2.7.

Adding the Lys C library to an existing project is easy if you already have RTT working. If not, there is a [Keil tutorial here](https://devzone.nordicsemi.com/tutorials/6/) or you can take a look at [my Makefile](https://github.com/inductivekickback/lys/blob/master/embedded/nRF5_SDK_11.0.0/examples/peripheral/lys/pca10040/blank/armgcc/Makefile) if you are using GCC.

The command line interface is intended to be executed by a script so the init params and result params are specified in Python. For example, the [blinky example](https://github.com/inductivekickback/lys/blob/master/embedded/nRF5_SDK_11.0.0/examples/peripheral/lys/main.c) expects two init params:

    uint32_t m_param_num_loops;
    uint8_t  m_param_blink_delay_type;

These are supplied on the command line as a Python array:

    '[("LYS_PARAM_TYPE_UINT32", 10),("LYS_PARAM_TYPE_UINT8", 1)]'

or the data types can be shortened:

    '[("UINT32", 10),("UINT8", 1)]'

or the lys_param_type_t value can be used:

    '[(0, 10),(2 , 1)]'

The results are expressed using the shortened string representation:

    '[("UINT32", 10)]'

If the firmware can be built and downloaded with Make then the path to the directory containing a Makefile can be specified. If the firmware on the embedded device isn't supposed to finish and return a result then a timeout can be specified (in seconds) or the firmware can be started and then left running. The full help text looks like this:

    python lys/lcli.py --help
    usage: lcli.py [-h] -s SERIAL_NUMBER [-d MAKEFILE_DIR] [-i INIT_PARAMS] [-v]
                   [-f LOG_FILE] [-t TIMEOUT_S | -n]
    
    Execute a Lys experiment.
    
    optional arguments:
      -h, --help            show this help message and exit
      -s SERIAL_NUMBER, --serial_number SERIAL_NUMBER
                            the serial number of the J-Link debugger
      -d MAKEFILE_DIR, --makefile_dir MAKEFILE_DIR
                            path to directory where make can be used to compile
                            and download the firmware
      -i INIT_PARAMS, --init_params INIT_PARAMS
                            a python array of input params to send to the firmware
      -v                    include verbose output
      -f LOG_FILE, --log_file LOG_FILE
                            a path where a log file can be created (suppresses
                            stdout)
      -t TIMEOUT_S, --timeout TIMEOUT_S
                            exit this number of seconds after starting the
                            firmware
      -n, --no_result       exit immediately after starting the firmware

If the [blinky example](https://github.com/inductivekickback/lys/tree/master/embedded/nRF5_SDK_11.0.0/examples/peripheral/lys) has already been downloaded to an embedded device and the J-Link debugger's serial number is XXXXXXX then this is what a simple invocation looks like:

    $ lys/lcli.py -s 682522292 -i '[("UINT32", 10),("UINT8", 1)]' 
        {
            'TIMESTAMP': '2016-07-28 14:31:30',
            'ERROR': False,
            'INIT_PARAMS': [('UINT32', 10), ('UINT8', 1)],
            'LOG': [],
            'RESULT': [('UINT32', 10)]
        }

The output is a Python dictionary and is clearly meant to be parsed by another Python program. The 'TIMESTAMP', 'INIT_PARAMS', and 'RESULT' items should be self-explanatory. The 'LOG' entry will contain any log messages that have been sent by the embedded device. The 'ERROR' entry will be set to True if an error occurred.
