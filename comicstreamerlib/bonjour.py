# coding=utf-8

"""
ComicStreamer bonjour thread class
"""

import threading
import select
import sys
import logging
import socket

try:
    import pybonjour
    have_bonjour = True
except:
    have_bonjour = False

class BonjourThread(threading.Thread):
    def __init__(self, port):
        super(BonjourThread, self).__init__()
        self.name    = socket.gethostname()
        self.regtype = "_comicstreamer._tcp"
        self.port    = port
        self.daemon = True
         
    def register_callback(self, sdRef, flags, errorCode, name, regtype, domain):
        if errorCode == pybonjour.kDNSServiceErr_NoError:
            logging.info("Registered bonjour server: {0}:{1}:(port {2})".format(name,regtype,self.port))
        
    def run(self):
        if not have_bonjour:
            logging.warn("Cannot run bonjour server!  Maybe some packages need to be installed?")
            return
        
        sdRef = pybonjour.DNSServiceRegister(name = self.name,
                                             regtype = self.regtype,
                                             port = self.port,
                                             callBack = self.register_callback)
        try:
            try:
                while True:
                    ready = select.select([sdRef], [], [])
                    if sdRef in ready[0]:
                        pybonjour.DNSServiceProcessResult(sdRef)
            except KeyboardInterrupt:
                pass
        finally:
            sdRef.close()


#-------------------------------------------------

