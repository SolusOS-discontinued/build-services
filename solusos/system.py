import os
import os.path

from solusos.console import *
import urllib2
import subprocess

def sizeof_fmt(num):
        for x in ['bytes','KB','MB','GB']:
                if num < 1024.0:
                        return "%3.1f%s" % (num, x)
                num /= 1024.0
        return "%3.1f%s" % (num, 'TB')

def execute_hide (command):
	''' Execute a command with no stdout '''
	p = subprocess.Popen (command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	p.wait ()
	        
class UnderlayManager:
	
	@staticmethod
	def DownloadUnderlay (url, target):
		print "\nDownloading underlay..\n"
		xterm_title ("Downloading underlay...")
		progress (10, 120)

		u = urllib2.urlopen(url)
		f = open(target, 'wb')
		meta = u.info()
		file_size = int(meta.getheaders("Content-Length")[0])

		file_size_dl = 0
		block_sz = 8192
		while True:
				buffer = u.read(block_sz)
				if not buffer:
						break

				file_size_dl += len(buffer)
				f.write(buffer)
				progress (file_size_dl, file_size)
		print "\n"
		xterm_title_reset ()

	@staticmethod
	def CreateLoopbackFile (filepath, size, format):
		xterm_title ("Generating loopback filesystem...")
		print_info ("Generating loopback filesystem...")
		cmd = "dd if=/dev/zero of=\"%s\" bs=1M count=%d" % (filepath, size)
		execute_hide (cmd)
		xterm_title ("Formatting loopback filesystem...")
		print_info ("Formatting loopback filesystem...")
		if not "ext" in format:
			cmd = "mkfs.%s \"%s\"" % (format, filepath)
		else:
			cmd = "mkfs -t %s -F \"%s\"" % (format, filepath)
		execute_hide (cmd)
		xterm_title_reset ()
		
class SystemManager:
	
	@staticmethod
	def mount (device, mountpoint, filesystem=None, options=None):
		if filesystem is not None:
			cmd = "mount -t %s %s %s" % (filesystem, device, mountpoint)
		else:
			cmd = "mount %s %s" % (device, mountpoint)
		if options is not None:
			cmd += " -o %s" % options
		os.system (cmd)
		
	@staticmethod
	def umount (device_or_mount):
		cmd = "umount \"%s\"" % device_or_mount
		os.system (cmd)
		
	@staticmethod
	def mount_home (point):
		os.system ("mount --bind /home/ \"%s\"" % point)
