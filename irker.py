#!/usr/bin/env python
"""
irker - a simple IRC multiplexer daemon

Takes JSON objects of the form {'channel':<channel-url>, 'message':<text>}
and relays to IRC channels.

Requires Python 2.6.

"""
import os, sys, json, irclib, getopt
import threading, Queue

class Session():
    "IRC session and message queue processing."
    def __init__(self, url):
        self.url = url
        # The consumer thread
        self.queue = Queue.Queue()
        self.thread = threading.Thread(target=self.dequeue)
        self.thread.daemon = True
        self.thread.start()
        # The channel specification
        if not url.startswith("irc://") or url.count("/") != 3:
            raise ValueError
        else:
            url = url[6:]
        parts = url.split(":", 1)
        if len(parts) == 2:
            try:
                self.port = int(parts[1])
            except ValueError:
                print "Error: Erroneous port."
                sys.exit(1)
        else:
            self.port = 6667
        (self.server, self.channel) = parts[0].split("/", 1)
        # Client setup
        self.client = irclib.SimpleIRCClient()
    def enqueue(self, message):
        "Enque a message for transmission."
        self.queue.put(message)
    def dequeue(self):
        "Try to ship pending messages from the queue."
        while True:
            message = self.queue.get()
            self.ship(self.channel, message)
            self.queue.task_done()
    def await(self):
        "Block until processing of the queue is done."
        self.queue.join()
    def ship(self, channel, message):
        "Ship a message to the channel."
        print "%s: %s" % (channel, message)

class Irker:
    "Persistent IRC multiplexer."
    def __init__(self):
        self.sessions = {}
    def logerr(self, errmsg):
        "Log a processing error."
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
                self.sessions[channel] = Session(channel)
            self.sessions[channel].enqueue(message)

if __name__ == '__main__':
    irker = Irker()
    irker.run(sys.stdin)
