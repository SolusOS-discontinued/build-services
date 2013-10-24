#!/usr/bin/env python
import xmlrpclib
from configobj import ConfigObj
from solusos.console import *

config_host = ConfigObj ("slave.conf")["Controller"]

proxy = xmlrpclib.ServerProxy('http://%s:%s' % (config_host["Address"], config_host["Port"]) )

methods = proxy.system.listMethods ()
print_info ("Discovering known methods..\n")

for method in methods:
    if not method.startswith ("system."):
        help = proxy.system.methodHelp (method)
        print "%s -- %s" % (method, help)

print        
print_info ("Trying: get_host_info")        
host_info = proxy.get_host_info ()
print host_info

print
