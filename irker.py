#!/usr/bin/env python
"""
irker - a simple IRC multiplexer daemon

Takes JSON objects of the form {'channel':<channel-url>, 'message':<text>}
and relays messages to IRC channels.

Run this as a daemon in order to maimntain stateful connections to IRC
servers; this will allow it to respond to server pings and minimize
join/leave traffic.

Requires Python 2.6.

"""
import os, sys, json, irclib, exceptions, getopt, urlparse
import threading, Queue

class SessionException(exceptions.Exception):
    def __init__(self, message):
        exceptions.Exception.__init__(self)
        self.message = message

class Session():
    "IRC session and message queue processing."
    count = 1
    def __init__(self, irker, url):
        self.irker = irker
        self.url = url
        # The consumer thread
        self.queue = Queue.Queue()
        self.thread = threading.Thread(target=self.dequeue)
        self.thread.daemon = True
        self.thread.start()
        # Server connection setup
        parsed = urlparse.urlparse(url)
        host, sep, port = parsed.netloc.partition(':')
        if not port:
            port = 6667
        self.servername = host
        self.channel = parsed.path.lstrip('/')
        self.port = int(port)
        self.server = self.irker.irc.server()
        self.irker.debug(1, "connecting: server=%s port=%s name=%s" % (self.servername, self.port, self.name()))
        self.server.connect(self.servername, self.port, self.name())
        Session.count += 1
    def enqueue(self, message):
        "Enque a message for transmission."
        self.queue.put(message)
    def dequeue(self):
        "Try to ship pending messages from the queue."
        while True:
            message = self.queue.get()
            self.ship(self.channel, message)
            self.queue.task_done()
    def name(self):
        "Generate a unique name for this session."
        return "irker" + str(Session.count)
    def await(self):
        "Block until processing of all queued messages is done."
        self.queue.join()
    def ship(self, channel, message):
        "Ship a message to the channel."
        self.irker.debug(1, "%s gets %s" % (channel, repr(message)))
        self.server.join(channel)
        self.server.privmsg(channel, message)

class Irker:
    "Persistent IRC multiplexer."
    def __init__(self, debuglevel=0):
        self.debuglevel = 0
        self.irc = irclib.IRC()
        thread = threading.Thread(target=self.irc.process_forever)
        self.irc._thread = thread
        thread.daemon = True
        thread.start()
        self.sessions = {}
    def logerr(self, errmsg):
        "Log a processing error."
        sys.stderr.write("irker: " + errmsg + "\n")
    def debug(self, level, errmsg):
        "Debugging information."
        if level >= self.debuglevel:
            sys.stderr.write("irker: " + errmsg + "\n")
    def run(self, ifp, await=True):
        "Accept JSON relay requests from specified stream."
        while True:
            inp = ifp.readline()
            if not inp:
                break
            try:
                request = json.loads(inp.strip())
            except ValueError:
                self.logerr("can't recognize JSON on input.")
                break
            self.relay(request)
        if await:
            for session in self.sessions.values():
                session.await()
    def relay(self, request):
        if "channel" not in request or "message" not in request:
            self.logerr("ill-formed reqest")
        else:
            channel = request['channel']
            message = request['message']
            if channel not in self.sessions:
                self.sessions[channel] = Session(self, channel)
            self.sessions[channel].enqueue(message)

if __name__ == '__main__':
    debuglevel = 0
    (options, arguments) = getopt.getopt(sys.argv[1:], "-d:")
    for (opt, val) in options:
        if opt == '-v':
            debuglevel = int(val)
    irker = Irker(debuglevel=debuglevel)
    irker.run(sys.stdin)
