import sys
import re

import fcntl
import os

from worker import BuildState

def non_blocking_read (output):
    fd = output.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        return output.read()
    except:
        return ''
        
class BuildLogger:
    
    ESCAPE = '%s[' % chr(27)
    FORMAT = '1;%dm'
    
    def strip_ansi_codes(self, s):
        return re.sub(r'\x1b\[([0-9,A-Z]{1,2}(;[0-9]{1,2})?(;[0-9]{3})?)?[m|K]?', '', s)
        
    def __init__(self,process, logfile, callback):
        started = False
        canWrite = True
        while True:
            stdout = process.stdout.readline()
            if process.poll() != None:
                break

            stderr = non_blocking_read (process.stderr)
                        
            if self.ESCAPE in stdout:
                if "Setting up source" in stdout:
                    print "CONFIGURING"
                    callback (BuildState.CONFIGURING)
                    
                elif "Unpacking archive(" in stdout:
                    print "UNPACKING"
                    started = True
                    canWrite = True
                    callback (BuildState.UNPACKING)
                    
                elif "Applying patch" in stdout:
                    patch = stdout.split (":")[1].strip()
                    print "PATCHING: %s" % patch
                    callback (BuildState.PATCHING, patch)
                    
                elif "Building source." in stdout:
                    print "BUILDING"
                    callback (BuildState.BUILDING)
                    
                elif "Testing package" in stdout:
                    print "TESTING"
                    callback (BuildState.TESTING)
                    
                elif "Building source package:" in stdout:
                    print "STARTING"
                    callback (BuildState.STARTED)
                    
            else:
                if "Fetching source from:" in stdout and not started:
                    archive = ":".join (stdout.split (":")[1:]).strip()
                    stripped = self.strip_ansi_codes (stdout)
                    logfile.write (stripped)
                    print "DOWNLOADING: %s" % archive
                    canWrite = False
                    callback (BuildState.FETCHING, archive)
                    
            stdout = self.strip_ansi_codes (stdout)
            stderr = self.strip_ansi_codes (stderr)
            
            if canWrite:
                logfile.write (stdout)
            
            if stderr != '':
                logfile.write (stderr)
            
            logfile.flush ()
