import subprocess


BUILD_TYPES = ['debug', 'release']


class MakerError(Exception):
	"""Subclass for reporting errors."""
	pass


def build_and_flash(armgcc_path, sn, version="debug"):
	"""Calls make in the specified directory to build and download the project
	to the debugger with the given serial number.

	"""
	version = version.lower()
	if (not version in BUILD_TYPES):
		raise MakerError("Invalid version param: ", version)

	process = subprocess.Popen(['make', 'flash_%s' % version, 'SN=%d' % sn],
		cwd=armgcc_path,
		stdout=subprocess.PIPE, 
		stderr=subprocess.PIPE)
	out, err = process.communicate()
	errcode = process.returncode

	if (errcode != 0):
		raise MakerError('Make exited with error number %d.' % errcode)
