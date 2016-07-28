from pynrfjprog import MultiAPI


DEFAULT_FAMILY = 'NRF52'


# This module only uses one pynrfjprog.API.API object at any given time.
_api = None


def enum_jlinks():
	"""Returns a list of attached J-Link debuggers or None."""
	result = None
	if (_api is None):
		api = MultiAPI.MultiAPI(DEFAULT_FAMILY)
		api.open()
		result = api.enum_emu_snr()
		api.close()
	else:
		result = api.enum_emu_snr()
	return result


def attach_and_reset(serial_number, family=DEFAULT_FAMILY):
	""""""
	global _api
	if (_api is not None):
		raise Exception("Only one debugger can be connected at a time.")
	if (isinstance(serial_number, str)):
		serial_number = int(serial_number)
	_api = MultiAPI.MultiAPI(family)
	_api.open()
	_api.connect_to_emu_with_snr(serial_number)
	_api.sys_reset()


def go():
	""""""
	if (_api is None):
		raise Exception("Can not go without first attaching and resetting.")
	_api.go()


def close():
	global _api
	if (_api is None):
		raise Exception("Close called without first attaching.")

	# For some reason the J-Link driver is happier if rtt_stop is called
	# (even though rtt_start is not used). If it's not called then
	# "*** J-Link V5.12 Internal Error ***" strings are printed to stderr with
	# "NET_WriteRead(): USB communication not locked" and
	# "PID0000129E (python2.7): Lock count error (decrement)" errors.
	_api.rtt_stop()

	_api.close()
	_api = None
