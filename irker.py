#!/usr/bin/env python
"""
irker - a simple IRC multiplexer daemon

Takes JSON objects of the form {'channel':<channel-url>, 'privmsg':<text>}
and relays messages to IRC channels.

Run this as a daemon in order to maintain stateful connections to IRC
servers; this will allow it to respond to server pings and minimize
join/leave traffic.

Requires Python 2.6.

TO-DO: Is there any way to cope if servers drop connections?
TO-DO: Round-robin as in http://code.google.com/p/cia-vc/source/browse/trunk/cia/LibCIA/IRC/Network.py
TO-DO: Register the port?
"""
# These things might need tuning

HOST = "localhost"
PORT = 4747

TTL = (3 * 60 * 60)	# Connection time to live in seconds
CONNECT_MAX = 18	# Maximum connections per bot (freenet limit)
NAMESTYLE = "irker%03d"	# IRC nick template - must contain '%d'

# No user-serviceable parts below this line

import sys, json, exceptions, getopt, urlparse, time, socket
import threading, Queue, SocketServer
import irclib

class SessionException(exceptions.Exception):
    def __init__(self, message):
        exceptions.Exception.__init__(self)
        self.message = message

class Session():
    "IRC session and message queue processing."
    def __init__(self, irker, url):
        self.irker = irker
        self.url = url
        self.server = None
        # Server connection setup
        parsed = urlparse.urlparse(url)
        host, _, port = parsed.netloc.partition(':')
        if not port:
            port = 6667
        self.servername = host
        self.channel = parsed.path.lstrip('/')
        self.port = int(port)
        # The consumer thread
        self.queue = Queue.Queue()
        self.thread = threading.Thread(target=self.dequeue)
        self.thread.daemon = True
        self.thread.start()
        self.last_active = None
    def enqueue(self, message):
        "Enque a message for transmission."
        self.queue.put(message)
    def dequeue(self):
        "Try to ship pending messages from the queue."
        while True:
            # We want to be kind to the IRC servers and not hold unused
            # sockets open forever, so they have a time-to-live.  The
            # loop is coded this particular way so that we can drop
            # the actual server connection when its time-to-live
            # expires, then reconnect and resume transmission if the
            # queue fills up again.
            if not self.server:
                self.server = self.irker.open(self.servername,
                                                         self.port)
                self.irker.debug(1, "TTL bump (connection) at %s" % time.asctime())
                self.last_active = time.time()
            elif self.queue.empty():
                if time.time() > self.last_active + TTL:
                    self.irker.debug(1, "timing out inactive connection at %s" % time.asctime())
                    self.irker.close(self.servername,
                                                 self.port)
                    self.server = None
                    break
            else:
                message = self.queue.get()
                self.server.join("#" + self.channel)
                self.server.privmsg("#" + self.channel, message)
                self.last_active = time.time()
                self.irker.debug(1, "TTL bump (transmission) at %s" % time.asctime())
                self.queue.task_done()
    def terminate(self):
        "Terminate this session"
        self.server.quit("#" + self.channel)
        self.server.close()
    def await(self):
        "Block until processing of all queued messages is done."
        self.queue.join()

class Irker:
    "Persistent IRC multiplexer."
    def __init__(self, debuglevel=0, namesuffix=None):
        self.debuglevel = debuglevel
        self.namesuffix = namesuffix or socket.getfqdn().replace(".", "-")
        self.irc = irclib.IRC(debuglevel=self.debuglevel-1)
        thread = threading.Thread(target=self.irc.process_forever)
        self.irc._thread = thread
        thread.daemon = True
        thread.start()
        self.sessions = {}
        self.countmap = {}
        self.servercount = 0
    def logerr(self, errmsg):
        "Log a processing error."
        sys.stderr.write("irker: " + errmsg + "\n")
    def debug(self, level, errmsg):
        "Debugging information."
        if self.debuglevel >= level:
            sys.stderr.write("irker[%d]: %s\n" % (self.debuglevel, errmsg))
    def nickname(self, n):
        "Return a name for the nth server connection."
        # The purpose of including the namme suffix (defaulting to the
        # host's FQDN) is to ensure that the nicks of bots managed by
        # instances running on different hosts can never collide.
        return (NAMESTYLE % n) + "-" + self.namesuffix
    def open(self, servername, port):
        "Allocate a new server instance."
        if not (servername, port) in self.countmap:
            self.countmap[(servername, port)] = (CONNECT_MAX+1, None)
        count = self.countmap[(servername, port)][0]
        if count > CONNECT_MAX:
            self.servercount += 1
            newserver = self.irc.server()
            newserver.connect(servername,
                              port,
                              self.nickname(self.servercount))
            self.countmap[(servername, port)] = (1, newserver)
        return self.countmap[(servername, port)][1]
    def close(self, servername, port):
        "Release a server instance and all sessions using it."
        del self.countmap[(servername, port)]
        for val in self.sessions.values():
            if (val.servername, val.port) == (servername, port):
                self.sessions[servername].terminate()
                del self.sessions[servername]
    def handle(self, line):
        "Perform a JSON relay request."
        try:
            request = json.loads(line.strip())
            if "channel" not in request or "privmsg" not in request:
                self.logerr("ill-formed reqest")
            else:
                channel = request['channel']
                message = request['privmsg']
                if channel not in self.sessions:
                    self.sessions[channel] = Session(self, channel)
                self.sessions[channel].enqueue(message)
        except ValueError:
            self.logerr("can't recognize JSON on input.")
    def terminate(self):
        "Ship all pending messages before terminating."
        for session in self.sessions.values():
            session.await()

class IrkerTCPHandler(SocketServer.StreamRequestHandler):
    def handle(self):
        while True:
            irker.handle(self.rfile.readline().strip())

class IrkerUDPHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        data = self.request[0].strip()
        #socket = self.request[1]
        irker.handle(data)

if __name__ == '__main__':
    host = HOST
    port = PORT
    namesuffix = None
    debuglevel = 0
    tcp = False
    (options, arguments) = getopt.getopt(sys.argv[1:], "d:p:n:t")
    for (opt, val) in options:
        if opt == '-d':
            debuglevel = int(val)
        elif opt == '-p':
            port = int(val)
        elif opt == '-n':
            namesuffix = val
        elif opt == '-t':
            tcp = True
    irker = Irker(debuglevel=debuglevel, namesuffix=namesuffix)
    if tcp:
        server = SocketServer.TCPServer((host, port), IrkerTCPHandler)
    else:
        server = SocketServer.UDPServer((host, port), IrkerUDPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

# end
