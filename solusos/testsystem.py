import sys
try:
	from configobj import ConfigObj
except:
	print "python-configObj missing!"
	sys.exit (1)
import os.path
from solusos.console import *

from solusos.system import UnderlayManager, SystemManager, execute_hide
import commands
import shutil
import time
import glob

# Global configuration file for SolusOS 2
CONFIG_FILE = "/etc/solusos/2.conf"
TEST_SYSTEM_URI = "http://ng.solusos.com/root_32.squashfs"
RESOURCE_DIR = "/usr/share/solusos/resources_2"

class TestSystem:
	
	def __init__(self):		
		if not os.path.exists (CONFIG_FILE):
			print "Configuration file missing"
			sys.exit (1)
		self.config = ConfigObj (CONFIG_FILE)
		
		self.underlay = self.config ["BuildKit"]["Image"]
		if not os.path.exists (self.underlay):
			print "The SolusOS 2 underlay has not been installed"
			if yes_no ("Download the SolusOS 2 test kit?"):
				dire = "/".join (self.underlay.split ("/")[:-1])
				if not os.path.exists (dire):
					os.makedirs (dire)
				UnderlayManager.DownloadUnderlay (TEST_SYSTEM_URI, self.underlay)
			else:
				print
				print_error ("Aborting due to missing underlay system")
				sys.exit (1)
		# Now check for our loopback file
		self.loopback_file = self.config ["Storage"]["LoopbackFile"]
		self.generate_loopback = self.config ["Storage"]["AutoGenerate"]
		self.loopback_size = int(self.config ["Storage"]["Size"])
		self.loopback_filesystem = self.config ["Storage"]["Filesystem"]
		self.system_root = self.config ["Storage"]["SystemRoot"]
		
		if not os.path.exists (self.loopback_file):
			# Do we create one ?
			if not self.generate_loopback:
				print_error ("Couldn\'t find the loopback filesystem: %s" % self.loopback_file)
				sys.exit (1)
			if yes_no ("A %sMiB loopback filesystem will be created for storage\nDo you want to create the %s loopback file?" % (self.loopback_size, self.loopback_file)):
				UnderlayManager.CreateLoopbackFile (self.loopback_file, self.loopback_size, self.loopback_filesystem)
			else:
				print_error ("Aborting due to missing loopback file")
		# Check this is a valid filesystem
		filetype = commands.getoutput ("file \"%s\""  % self.loopback_file)
		if not "filesystem" in filetype.lower():
			print_error ("\"%s\" does not contain a valid filesystem" % self.loopback_file)
			sys.exit (1)
		
		self.cache_dir = os.path.join (self.system_root, "cache")
		self.underlay_dir = os.path.join (self.system_root, "buildkit")
		self.union_dir = os.path.join (self.system_root, "union")
		
		# Now we ideally want to mount this baby.
		dirs = [ "cache", "buildkit", "union" ]
		for dire in dirs:
			fpath = os.path.join (self.system_root, dire)
			if not os.path.exists (fpath):
				os.makedirs (fpath)

	def enter_system (self, bind_home=False):
		''' Enter the system '''	
		# Mount the cache file (i.e. the 500MB filesystem)
		options = "loop"
		if self.loopback_filesystem == "btrfs":
			# Automatically compress a btrfs loopback file
			options += ",compress"
		
		self.bind_home = bind_home	
		SystemManager.mount (self.loopback_file, self.cache_dir, filesystem=None, options=options)
		
		# Mount our root buildkit filesystem
		SystemManager.mount (self.underlay, self.underlay_dir, filesystem="squashfs", options="loop,ro")
		
		options = "dirs=%s:%s=ro" % (self.cache_dir, self.underlay_dir)
		SystemManager.mount ("none", self.union_dir, filesystem="unionfs", options=options)
		
		# D-BUS.
		self.dbus_pid = os.path.join (self.union_dir, "var/run/dbus/pid")
		if os.path.exists (self.dbus_pid):
			print_info ("Deleting stale D-BUS PID file..")
			os.unlink (self.dbus_pid)

		
		# Always ensure the dbus start files exist
		lsb_init = os.path.join (self.union_dir, "lib/lsb")
		dbus_rc = os.path.join (self.union_dir, "etc/rc.d/init.d")
		if not os.path.exists (lsb_init):
			source_lsb = os.path.join (RESOURCE_DIR, "data/lsb")
			dest_lsb = os.path.join (self.union_dir, "lib/lsb")
			print_info ("Copying lsb init functions")
			shutil.copytree (source_lsb, dest_lsb)
		
		if not os.path.exists (dbus_rc):
			source_dbus = os.path.join (RESOURCE_DIR, "data/init.d")
			dest_dbus = os.path.join (self.union_dir, "etc/rc.d/init.d")
			print_info ("Copying dbus startup files")
			shutil.copytree (source_dbus, dest_dbus)
		
		# Startup dbus
		self.dbus_service = "/etc/rc.d/init.d/dbus"
		print_info ("Starting the D-Bus systemwide message bus")
		execute_hide ("chroot \"%s\" \"%s\" start" % (self.union_dir, self.dbus_service))
		
		# Set up devices + stuff
		self.dev_shm_path = os.path.join (self.union_dir, "dev/shm")
		if not os.path.exists (self.dev_shm_path):
			os.makedirs (self.dev_shm_path)
		
		self.proc_dir = os.path.join (self.union_dir, "proc")
		SystemManager.mount ("tmpfs", self.dev_shm_path, filesystem="tmpfs")
		SystemManager.mount ("proc", self.proc_dir, filesystem="proc")
		
		# Finally, bind home
		if bind_home:
			self.home_dir = os.path.join (self.union_dir, "home")
			if not os.path.exists (self.home_dir):
				os.makedirs (self.home_dir)
			SystemManager.mount_home (self.home_dir)

	def murder_death_kill (self, be_gentle=False):
		''' Completely and utterly murder all processes in the chroot :) '''
		for root in glob.glob ("/proc/*/root"):
			try:
				link = os.path.realpath (root)
				if os.path.abspath (link) == os.path.abspath (self.union_dir):
					pid = root.split ("/")[2]
					if be_gentle:
						os.system ("kill %s" % pid)
					else:
						os.system ("kill -9 %s" % pid)
			except:
				pass
			
	def exit_system (self):
		''' Exit the system '''
		# Clean up by unmounting for now
		
		if self.bind_home:
			print_info ("Unmounting home...")
			SystemManager.umount (self.home_dir)

		dbus_pid = os.path.join (self.union_dir, "var/run/dbus/pid")
		print_info ("Stopping D-BUS...")
		
		with open (dbus_pid, "r") as pid_file:
			pid = pid_file.read().strip()
			os.system ("kill -9 %s" % pid)
		# Safety, gives dbus enough time to die
		time.sleep (3)
		
		# Murder the remaining processes
		print_info ("Asking all remaining processes to stop...")
		self.murder_death_kill (be_gentle=True)
		print_info ("Force-kill any remaining processes...")
		self.murder_death_kill ()
		
		print_info ("Unmounting virtual filesystems...")				
		SystemManager.umount (self.dev_shm_path)
		SystemManager.umount (self.proc_dir)

		print_info ("Unmounting SolusOS 2 system...")
		SystemManager.umount (self.union_dir)
		SystemManager.umount (self.cache_dir)
		SystemManager.umount (self.underlay_dir)
