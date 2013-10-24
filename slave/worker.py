#!/usr/bin/env python

import subprocess
from solusos.system import SystemManager
import os.path

import shutil
from contextlib import contextmanager

from remote_api import QueueAPI, QueueRequest, QueueResponse, QueueStatusRequest
from piston_mini_client.auth import BasicAuthorizer

import glob
import hashlib

import multiprocessing

''' We haven't got enum support in python 2.x '''
def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.iteritems())
    enums['reverse_mapping'] = reverse
    return type('Enum', (), enums)
    
'''
Possible build states
'''
BuildState = enum ('STARTED', 'FETCHING', 'UNPACKING', 'PATCHING', 'CONFIGURING', 'BUILDING', 'TESTING')

from buildlog import BuildLogger

@contextmanager
def work_environment (worker):
    if worker._enter_system ():
        yield
        worker._exit_system ()
    else:
        worker.errors = "Could not enter system"
        

    
'''
The possible states of a worker
'''
WorkerState = enum ('IDLE', 'OFF', 'FAILED', 'BUILDING', 'SYNCING', 'BUSY')
RepoType = enum ('GIT', 'MERCURIAL')


''' The actual Worker '''
class Worker:
    
    DATA_DIR = os.path.abspath ("./data")
    
    state = WorkerState.OFF
    
    config = None
    
    def _hashsum_for_queue (self, queue):
        hash_sum = hashlib.md5()
        for item in queue:
            up = "%s-%s" % (item.name, item.version)
            hash_sum.update (up)
        digest = hash_sum.hexdigest ()
        return digest
    
    def _get_last_queue_hashsum (self):
        queue_location = os.path.join (self.mount_point, "work_dir/.queue")
        if os.path.exists (queue_location):
            queue_file = open (queue_location, "r")
            hashsum = queue_file.read().strip()
            queue_file.close ()
            return hashsum
        return None
    
    def _store_queue_hashsum (self, queue):
        queue_location = os.path.join (self.mount_point, "work_dir/.queue")
        with open (queue_location, "w") as hashsum:
            hexe = self._hashsum_for_queue (queue)
            hashsum.write (hexe)
            hashsum.flush ()

    def _run_command_in_system (self, command, workDir=None):
        '''
        Run a command in the workingDir of our system (not chroot!)
        '''
        if workDir is None:
            workDir = self.mount_point
        p = subprocess.Popen (command, shell=True, cwd=workDir, stdin=subprocess.PIPE)
        p.wait ()
        return p.returncode == 0
        
    def _run_chroot_command_in_system (self, command):
        '''
        Run a CHROOT'd command in our system
        '''
        cmd = "chroot \"%s\" %s" % (self.mount_point, command)
        p = subprocess.Popen (cmd, shell=True)
        p.wait ()
        return p.returncode == 0
    
    def _run_logged_chroot_command_in_system (self, command, filename, callback):
        '''
        Run a CHROOT'd command in our system, and log
        it to a file
        '''
        cmd = "chroot \"%s\" %s" % (self.mount_point, command)
        p = subprocess.Popen (cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_file = open (filename, "w")
        logger = BuildLogger (p, log_file, callback)
        p.communicate()
        p.wait ()
        log_file.close ()
        return p.returncode == 0
        
    def __init__(self, config):
        '''
        Create a new Worker
        '''
        self.config = config
        self.mount_point = os.path.join (self.config["Builder"]["Storage"], "mountpoint")
        self.fs_image = os.path.join (self.config["Builder"]["Storage"], "storage.image")
        self.repo_dir = os.path.join (self.mount_point, "repositories")
        self.auto_clean = True if str(self.config["Settings"]["Autoclean"]).lower() == "true" else False
        self.errors = None
        
    def _can_continue (self):
        return (self.state == WorkerState.IDLE or self.state != WorkerState.BUSY)
        

    def worker_busy (self):
        '''
        Public method to determine whether the worker is busy or not
        '''
        return not self._can_continue ()
        
    def add_source_repo (self, uri, vcs, username=None, password=None):
        '''
        Clone the repository into our system
        '''
        if not self._can_continue ():
            return False
        self.errors = None
        with work_environment (self):
            self.state = WorkerState.BUSY
            if os.path.exists (self.repo_dir):
                shutil.rmtree (self.repo_dir)
            os.makedirs (self.repo_dir)
            
            parts = uri.split ("//")
            repo = uri
            if username is not None and password is not None:
                repo = "%s//%s:%s@%s" % (parts[0], username, password, parts[1])
            if vcs == "mercurial":
                clone = "hg clone %s" % repo
                if self._run_command_in_system (clone, workDir=self.repo_dir):
                    self.repo_subdir = os.listdir (self.repo_dir)[0]
                    subdir = os.path.join (self.repo_dir, self.repo_subdir)
                    self._run_command_in_system ("hg update", workDir=subdir)
                else:
                    self.errors = "Failed to clone"
            self.state = WorkerState.IDLE
            
        return self.errors is None
    
    def sync_packages (self, host_address, target, username, password):
        '''
        Sync our logs with the selected server
        '''
        if not self._can_continue ():
            return False
        self.errors = None
        
        with work_environment (self):
            self.state = WorkerState.SYNCING
            
            env = os.environ.copy ()
            env["RSYNC_PASSWORD"] = password
            
            work_dir = os.path.join (self.mount_point, "work_dir")
            upload_dir = os.path.join (self.mount_point, "upload_dir")
            if os.path.exists (upload_dir):
                shutil.rmtree (upload_dir)
            os.mkdir (upload_dir)
            
            for root,dirs,files in os.walk (work_dir):
                for file in files:
                    if file.endswith (".pisi"):
                        fpath = os.path.join (root, file)
                        shutil.copy2 (fpath, upload_dir)
                        
            mapping = {
                'UploadDir': upload_dir,
                'User' : username,
                'Host' : host_address,
                'Target': target,
            }
            cmd = "rsync -avz %(UploadDir)s/  %(User)s@%(Host)s::%(Target)s" % mapping
            p = subprocess.Popen (cmd, shell=True, stdin=subprocess.PIPE, env=env)
            p.wait ()
            
            if not p.returncode == 0:
                self.errors = "Failed to sync"
            self.state = WorkerState.IDLE
        return self.errors is not None
                                    
    def sync_logs (self, host_address, target, username, password):
        '''
        Sync our logs with the selected server
        '''
        if not self._can_continue ():
            return False
        self.errors = None
        
        with work_environment (self):
            self.state = WorkerState.SYNCING
            
            env = os.environ.copy ()
            env["RSYNC_PASSWORD"] = password
            
            log_dir = os.path.join (self.mount_point, "log_dir")
            
            mapping = {
                'LogDir': log_dir,
                'User' : username,
                'Host' : host_address,
                'Target': target,
            }
            cmd = "rsync -avz %(LogDir)s/ %(User)s@%(Host)s::%(Target)s" % mapping
            p = subprocess.Popen (cmd, shell=True, stdin=subprocess.PIPE, env=env)
            p.wait ()
            if not p.returncode == 0:
                self.errors = "Failed to sync"
            self.state = WorkerState.IDLE
        return self.errors is not None
        
    def begin_build (self, queue_id, sandboxed):
        '''
        Build everything in the queue
        '''
        if not self._can_continue ():
            return False
        # Reset errors
        self.errors = None
        
        max_jobs = multiprocessing.cpu_count () + 1
        
        with work_environment (self):
            self.state = WorkerState.BUSY
            
            # Prechecks: Get a work dir ready
            work_dir = "work_dir/"
            work_dir_external = os.path.join (self.mount_point, work_dir)
            
            # Log dirs
            log_dir = "log_dir/"
            log_dir_external = os.path.join (self.mount_point, log_dir)
            
            pisi_local = os.path.join (self.DATA_DIR, "pisi-template")
            pisi_target = os.path.join (self.mount_point, "etc/pisi/pisi.conf")
            with open (pisi_local, "r") as local_pisi_template:
                lines = local_pisi_template.readlines ()
                with open (pisi_target, "w") as target_pisi_file:
                    for line in lines:
                        line = line.replace ("\r","").replace("\n","")
                        line = line.replace ("[[[JOBCOUNT]]]", "-j%s" % str(max_jobs))
                        target_pisi_file.write ("%s\n" % line)
                    target_pisi_file.flush ()
                    
            ## Add our building and queue processing here
            try:
                web_user = self.config["Frontend"]["Username"]
                web_pass = self.config["Frontend"]["Password"]
                auth = BasicAuthorizer (web_user, web_pass)
                remote = QueueAPI (remote_uri="http://%s/api" % self.config["Frontend"]["URL"], auth=auth)
                
                queue = remote.build_queue (queue_id)
                
                def log_callback (state, extra=None):
                    request = None
                    if state == BuildState.CONFIGURING:
                        request = QueueRequest (name=item.name, build_status='config')
                    elif state == BuildState.FETCHING:
                        request = QueueRequest (name=item.name, build_status='download')
                    elif state == BuildState.BUILDING:
                        request = QueueRequest (name=item.name, build_status='build')
                    
                    '''      
                    Not Yet Implemented in UI
                    -------------------                      
                    elif state == BuildState.UNPACKING:
                        request = QueueRequest (name=item.name, build_status='unpack')                                                
                    elif state == BuildState.STARTED:
                        request = QueueRequest (name=item.name, build_status='start')
                    elif state == BuildState.PATCHING:
                        request = QueueRequest (name=item.name, build_status='patch')
                    elif state == BuildState.TESTING:
                        request = QueueRequest (name=item.name, build_status='test')    
                    '''     
                    if request is not None:
                        remote.update_status (queue_id, request=request)
                    
                purge = True
                # Check last queue
                if self._get_last_queue_hashsum () is not None:
                    if self._get_last_queue_hashsum () == self._hashsum_for_queue (queue):
                        print "Encountered repeat queue"
                        purge = False
                
                if purge:
                    # Clean up for new jobs
                    if os.path.exists (work_dir_external):
                        shutil.rmtree (work_dir_external)
                    if os.path.exists (log_dir_external):
                        shutil.rmtree (log_dir_external)
                    os.makedirs (work_dir_external)
                    os.makedirs (log_dir_external)
                    
                # HACK!!!
                if not os.path.exists (log_dir_external):
                    os.makedirs (log_dir_external)
                    
                # Always store current queue hashsum
                self._store_queue_hashsum (queue)
                            
                current = 0
                total = len(queue)
                for item in queue:
                    current += 1
                    print "%s - %s" % (item.name, item.version)
                    
                    # Update queue immediately, otherwise the wrong package name is displayed
                    q = QueueStatusRequest (current=current, package_name=item.name, length=total)
                    remote.update_queue (queue_id, request=q)
                    
                    # full path
                    fpath_internal = "repositories/%s/%s" % (self.repo_subdir, item.spec_uri)
                    fpath_external = os.path.join (self.mount_point, fpath_internal)
                    
                    if not os.path.exists (fpath_external):
                        self.errors = "%s not found!" % fpath_internal
                        # Note: This would happen if the user doesn't reindex.. :)
                        print self.errors
                        break
                    if item.build_status == 'built' and not purge:
                        print "Skipping already built package"
                        continue
                    # Now we're ready to prepare a build :)
                    package_work = "%s/%s" % (work_dir, item.name)
                    package_work_external = os.path.join (self.mount_point, package_work)
                    package_work = "/%s" % package_work
                    
                    # Make our temporary working dirs
                    if not os.path.exists (package_work_external):
                        os.makedirs (package_work_external)
                    
                    ## TODO: Add --ignore-sandbox if specified by controller
                    if sandboxed:
                        cmd = "pisi build -y \"%s\" -O \"%s\"" % (fpath_internal, package_work)
                    else:
                        cmd = "pisi build --ignore-sandbox -y \"%s\" -O \"%s\"" % (fpath_internal, package_work)                        
                    log_file = os.path.join (log_dir_external, "%s-%s.txt" % (item.name, item.version))
                    
                    # Eventually need callbacks 
                    if self._run_logged_chroot_command_in_system (cmd, log_file, log_callback):
                        potential_packages_list = list()
                        for potential in os.listdir (package_work_external):
                            potential_packages_list.append ("%s/%s" % (package_work, potential))
                            
                        potential_packages = " " .join (potential_packages_list)
                        if not self._run_chroot_command_in_system ("pisi install %s" % potential_packages):
                            request = QueueRequest (name=item.name, build_status='fail')
                            print "Failed to install packages: %s " % potential_packages
                            self.errors = "Failed to install package"
                        else:
                            # Installed and working.
                            request = QueueRequest (name=item.name, build_status='built')
                    else:
                        request = QueueRequest (name=item.name, build_status='fail')
                        self.errors = "Failed to build package"
                    remote.update_status (queue_id, request=request)
                    
                    # Clean up if requested
                    if self.auto_clean:
                        self._run_chroot_command_in_system ("pisi delete-cache")
                    
            except Exception, e:
                self.errors = e
                print self.errors
            self.state = WorkerState.IDLE
        return self.errors is None
        
    def add_binary_repo (self, name, uri):
        '''
        Add a binary (pisi-index.xml) repository to the build system
        '''
        if not self._can_continue():
            return False
        self.errors = None
        with work_environment (self):
            self.state = WorkerState.BUSY
            
            ret = self._run_chroot_command_in_system ("pisi add-repo \"%s\" \"%s\"" % (name, uri))
            # We will need to pay attention to whether add-repo works soon. Repos must be removed
            # in imaging
            if not self._run_chroot_command_in_system ("pisi update-repo"):
                self.errors = "Failed to update repo"
            self._run_chroot_command_in_system ("pisi upgrade -y")    
            self.state = WorkerState.IDLE
            
        return self.errors is None
        
    def _enter_system (self, enableServices=False):
        '''
        Setup and enter our new system (i.e. mountpoints and such)
        '''
        SystemManager.mount (self.fs_image, self.mount_point, options="loop")
        
        self.dbus_pid = os.path.join (self.mount_point, "var/run/dbus/pid")
        if os.path.exists (self.dbus_pid):
            os.unlink (self.dbus_pid)
            
        self.dbus_service = "/etc/rc.d/init.d/dbus"
        if not self._run_chroot_command_in_system ("%s start" % self.dbus_service):
            SystemManager.umount (self.mount_point)
            self.errors = "Could not start D-BUS"
        else:
            # Let's get some stuff mounted shall we?
            self.dev_shm_path = os.path.join (self.mount_point, "dev/shm")
            self.proc_dir = os.path.join (self.mount_point, "proc")
            SystemManager.mount ("tmpfs", self.dev_shm_path, filesystem="tmpfs")
            SystemManager.mount ("proc", self.proc_dir, filesystem="proc")
                
        return self.errors is None

    def murder_death_kill (self, be_gentle=False):
        ''' Completely and utterly murder all processes in the chroot :) '''
        for root in glob.glob ("/proc/*/root"):
            try:
                link = os.path.realpath (root)
                if os.path.abspath (link) == os.path.abspath (self.mount_point):
                    pid = root.split ("/")[2]
                    if be_gentle:
                        os.system ("kill %s" % pid)
                    else:
                        os.system ("kill -9 %s" % pid)
            except:
                pass
                        
    def _exit_system (self):
        '''
        Tear down the environment and kill anything running
        '''
        if hasattr(self, "dev_shm_path"):
            SystemManager.umount (self.dev_shm_path)
        if hasattr (self, "proc_dir"):
            SystemManager.umount (self.proc_dir)
        
        self._run_chroot_command_in_system ("%s stop" % self.dbus_service)
            
        with open (self.dbus_pid, "r") as pid_file:
            pid = pid_file.read().strip()
            try:
                os.system ("kill -9 %s" % pid)  
            except:
                pass
        
        self.murder_death_kill (be_gentle=True)
        self.murder_death_kill ()
                      
        SystemManager.umount (self.mount_point)
