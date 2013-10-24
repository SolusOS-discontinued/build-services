from solusos.bcolors import *
import sys
import os
import commands

def yes_no (question):
	try:
		response = raw_input ("%s (%syes%s, %sno%s): " % (question, bcolors.OKGREEN, bcolors.ENDC, bcolors.FAIL, bcolors.ENDC))
		response = response.lower ().strip ()
		if response == "yes" or response == "y":
			return True
		return False
	except KeyboardInterrupt:
		print
		print_error ("Aborting due to CTRL+C")
		sys.exit (1)
		

def print_header (toptext, subtext):
	lines = (len(toptext) + 2) * "_"
	print ".%s." % lines
	print "| %s%s%s |" % (bcolors.HEADER, toptext, bcolors.ENDC)
	lines = (len(toptext) + 2) * "-"
	print "+%s+" % lines
	print

def print_error (textual, errname="!"):
	print "[ %s%s%s ] %s%s%s" % (bcolors.FAIL, errname, bcolors.ENDC, bcolors.FAIL, textual, bcolors.ENDC)

def print_info (textual, infoname="@"):
	print "[ %s%s%s ] %s%s%s" % (bcolors.OKBLUE, infoname, bcolors.ENDC, bcolors.OKBLUE, textual, bcolors.ENDC)

def getTerminalSize():
    import os
    env = os.environ
    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct, os
            cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ,
        '1234'))
        except:
            return
        return cr
    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass
    if not cr:
        cr = (env.get('LINES', 25), env.get('COLUMNS', 80))
    return int(cr[1]), int(cr[0])
    
def progress (current, total, border_width=10):
	fraction =  float (float(total) / float(current))

	percent_i =  (float(current)/float(total)) * 100
	width,height = getTerminalSize ()
	original_width = width
	width -= border_width * 2
	progress_i = int (width / fraction) 
	progress = progress_i * "="
	remainder = (width - progress_i) * " "
	border = border_width * " "

	percent = "%0.2f%% " % percent_i
	width_percent = len(percent)
	border = (border_width - width_percent ) * " "
	print "\r%s%s[%s%s%s%s]" % (border, percent, bcolors.OKBLUE, progress, bcolors.ENDC, remainder),

def xterm_title(message):
    """Set message as console window title."""
    if os.environ.has_key("TERM") and sys.stderr.isatty():
        terminalType = os.environ["TERM"]
        for term in ["xterm", "Eterm", "aterm", "rxvt", "screen", "kterm", "rxvt-unicode"]:
            if terminalType.startswith(term):
                sys.stderr.write("\x1b]2;"+str(message)+"\x07")
                sys.stderr.flush()
                break

def xterm_title_reset():
    """Reset console window title."""
    if os.environ.has_key("TERM"):
        xterm_title("")
