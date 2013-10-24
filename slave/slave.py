#!/usr/bin/env python
import xmlrpclib
from SimpleXMLRPCServer import SimpleXMLRPCServer
from configobj import ConfigObj
from solusos.console import *
from solusos.system import SystemManager

from SocketServer import ThreadingMixIn

import sys
import socket
import platform
import os
import os.path
import multiprocessing
import urllib2
import subprocess
import re
import shutil

from worker import Worker, WorkerState, work_environment

FORK = False

class AsyncXMLRPCServer(ThreadingMixIn,SimpleXMLRPCServer): pass

def redirect_io (stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
    stdin_ = open (stdin, "r")
    stdout_ = open (stdout, "a+")
    stderr_ = open (stderr, "a+")
    
    os.dup2 (stdin_.fileno(), sys.stdin.fileno())
    os.dup2 (stdout_.fileno(), sys.stdout.fileno())
    os.dup2 (stderr_.fileno(), sys.stderr.fileno())
    
class SlaveController:
    
    # Temporary, pending setup.py creation
    DATA_DIR = os.path.abspath ("./data")
    
    def __init__(self):
        self.config = ConfigObj ("slave.conf")
        
        self.server = AsyncXMLRPCServer ((self.config["Controller"]["Address"], int(self.config["Controller"]["Port"])))
        self.server.register_introspection_functions()
        # Register functions
        self.server.register_function (self.get_host_info, "get_host_info")
        self.server.register_function (self.get_storage_info, "get_storage_info")
        self.server.register_function (self.update_media, "update_media")
        
        self.fs_image = os.path.join (self.config["Builder"]["Storage"], "storage.image")
        self.fs_info = os.path.join (self.config["Builder"]["Storage"], "storage.info")
        
        self.loop_point = os.path.join (self.config["Builder"]["Storage"], "loopback")
        self.mount_point = os.path.join (self.config["Builder"]["Storage"], "mountpoint")
        
        self.imaging_progress = 0
        
        self.worker = Worker (self.config)
        self.server.register_instance (self.worker)
        
        storage_dir = self.config ["Builder"]["Storage"]
        if not os.path.exists (storage_dir):
            os.makedirs (storage_dir)
        
    def serve (self):
        self.server.serve_forever ()
    
    def sync_new_media (self):
        for item in [self.mount_point, self.loop_point]:
            if not os.path.exists (item):
                os.mkdir (item)
                
        # Mount loopback
        SystemManager.mount (self.image_source, self.loop_point, options="loop")
        
        # Mount fresh filesystem
        SystemManager.mount (self.fs_image, self.mount_point, options="loop")
        
        # Find the actual total number of files
        dry_run = "rsync -az --stats --dry-run \"%s/\" \"%s/\"" % (self.loop_point, self.mount_point)
        p = subprocess.Popen (dry_run, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        remainder = p.communicate() [0]
        mn = re.findall(r'Number of files: (\d+)', remainder)
        total_files = int(mn[0])
        
        # Really run rsync now
        cmd = "rsync -avz \"%s/\" \"%s/\" --progress" % (self.loop_point, self.mount_point)
        p = subprocess.Popen (cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        
        while True:
            output = p.stdout.readline()
            if 'to-check' in output:
                m = re.findall(r'to-check=(\d+)/(\d+)', output)
                progress = (100 * (int(m[0][1]) - int(m[0][0]))) / total_files
                self.imaging_progress = progress
                if int(m[0][0]) == 0:
                    break
            if output is None or p.poll() is not None:
                break
        
        self.imaging_progress = 0
        
        # Quickly install dbus
        self.install_dbus ()
                
        # Unmount it
        SystemManager.umount (self.mount_point)
        SystemManager.umount (self.loop_point)
    
    def install_dbus (self):
        source_lib = os.path.join (self.DATA_DIR, "lsb")
        target_lib = os.path.join (self.mount_point, "lib/lsb")
        
        source_etc = os.path.join (self.DATA_DIR, "init.d")
        target_etc = os.path.join (self.mount_point, "etc/rc.d/init.d")
        
        # Copy lsb-functions, etc.
        try:
            shutil.copytree (source_lib, target_lib)
            shutil.copytree (source_etc, target_etc)
        except:
            # Already installed
            pass
        
    def get_storage_info (self):
        config = ConfigObj (self.fs_info)
        if not os.path.exists (self.fs_info):
            return None
        try:
            size = config["DiskInfo"]["Size"]
            filesystem = config["DiskInfo"]["Filesystem"]
            backing_store = config["DiskInfo"]["BackingStore"]
            return (filesystem, size, backing_store)
        except:
            return None
    
    def get_backing_source (self):
        # Ensure we have the backing source.
        backing_store = self.get_storage_info ()[2]
        backing_uri = "http://ng.solusos.com/root_32.squashfs" if backing_store == "32" else None
        
        self.image_source = os.path.join (self.config["Builder"]["Storage"], "system%s.image" % backing_store)
        if not os.path.exists (self.image_source):
            self.download_file (backing_uri, self.image_source)
        
    def download_file (self, url, target):
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
                if not FORK:
                    progress (file_size_dl, file_size)
                
    def update_media (self, filesystem, size, backing_store):
        ''' Rebuild the backing media '''
        #### WE NEED PRE CHECKS, mounts, etc ######
        if size >= (self.get_host_info()[1]):
            # Don't attempt to create larger files than free space.
            return False
        
        current_info = self.get_storage_info ()
        noImage = False
        if current_info != None:
            if int(current_info [1]) == size:
                noImage = True    

        cmd = "dd if=/dev/zero of=\"%s\" bs=1MB count=%d" % (self.fs_image, size)
        if not noImage:
            if os.path.exists (self.fs_image):
                os.unlink (self.fs_image)             
            os.system (cmd)
       
        if filesystem.startswith ("ext"):
            cmd = "mkfs.%s -F \"%s\"" % (filesystem, self.fs_image)
        else:
            print "FILESYSTEM NOT IMPLEMENTED: %s" % filesystem
            return False
        os.system (cmd)

        # Write our currently known config (for get_storage_info)
        conf = ConfigObj ()
        conf.filename = self.fs_info
        config = {}
        config["Filesystem"] = filesystem
        config["Size"] = size
        config["BackingStore"] = backing_store
        conf["DiskInfo"] = config
        conf.write ()
        
        self.get_backing_source ()
        self.sync_new_media ()
        return True
            
    def get_host_info (self):
        '''
        Retrieve basic information about the host
        '''
        disk_free = commands.getoutput ("df")
        for line in disk_free.split ("\n"):
            line = line.strip ()
            splits = line.split ()
            mount_point = splits[5]
            if mount_point == "/":
                available = splits[3]
                total = splits[1]
                break
        hostname = socket.gethostname ()
        uname = platform.uname ()
        kernel = uname [2]
        arch = uname [4]
        max_jobs = multiprocessing.cpu_count () + 1
        return (total, available, hostname, kernel, arch, max_jobs, self.imaging_progress)

def main():
    control = SlaveController ()
    print_header ("SlaveController", "Slave")
    
    
    try:
        control.serve ()
    except KeyboardInterrupt:
        print_info ("Shutdown requested")
        sys.exit (0)
    except Exception, e:
        print e        
                
if __name__ == "__main__":
    # Should check whether we want to fork :)
    if FORK:
        try:
            pid = os.fork ()
            if pid > 0: sys.exit(0) # Exit first parent.
        except OSError, e:
            print e
            sys.exit (1)
        
        os.umask (0)
        os.setsid ()
        
        # Fork again, daemonize
        try:
            pid = os.fork ()
            if pid > 0:
                print_info ("SLAVE_PID=%d" % pid)
                sys.exit(0) # Exit second parent.
        except OSError, e:
            print e
            sys.exit (1)
            
        # All setup to go
        redirect_io ()
        main()
    else:
        main()
