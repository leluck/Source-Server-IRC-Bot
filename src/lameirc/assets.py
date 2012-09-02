# -*- coding: utf-8 -*-

# Copyright (c) 2012 Johannes Bendler
# Licensed under the MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining 
# a copy of this software and associated documentation files (the "Software"), 
# to deal in the Software without restriction, including without limitation 
# the rights to use, copy, modify, merge, publish, distribute, sublicense, 
# and/or sell copies of the Software, and to permit persons to whom the 
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included 
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER 
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING 
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS 
# IN THE SOFTWARE.

import logging.handlers
import Queue
import re
import socket
import threading
import time

import irclib.irclib as irclib

class RconIdentifierError(Exception):
    pass

class LogWrapper:
    CHAT_PREFIX =    'CHT'
    COMMAND_PREFIX = 'CMD'
    RCON_PREFIX =    'RCN'
    SYSTEM_PREFIX =  'SYS'
    
    def __init__(self, logfile):
        self.instance = logging.Logger('SourceServerIRCBot')
        self.instance.setLevel(logging.INFO)
        
        handle = logging.handlers.WatchedFileHandler(logfile)
        handle.setLevel(logging.INFO)
        handle.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
        self.instance.addHandler(handle)
    
    def chat(self, message):
        self._log(self.CHAT_PREFIX, message)
    
    def command(self, message):
        self._log(self.COMMAND_PREFIX, message)
    
    def system(self, message):
        self._log(self.SYSTEM_PREFIX, message)
    
    def rcon(self, message):
        self._log(self.RCON_PREFIX, message)
    
    def _log(self, prefix, message):
        self.instance.info('[%s] %s' % (prefix, message))
        

class Communicator:
    def __init__(self, bot, udp_log_port = 26999):
        self.bot = bot
        self.fallbackconnect = None
        
        self.ircqueue = Queue.Queue(30)
        self.ircsender = threading.Thread(target = Communicator._worker_irc, args = (self,))
        self.ircsender.daemon = True
        self.ircsender.start()
        
        self.chatqueue = Queue.Queue(10)
        self.chatworker = threading.Thread(target = Communicator._worker_chat, args = (self,))
        self.chatworker.daemon = True
        self.chatworker.start()
        
        self.udplistener = threading.Thread(target = Communicator._udp_listen, args = (self, '0.0.0.0', udp_log_port))
        self.udplistener.daemon = True
        self.udplistener.start()
        
        self.bot.log.system('Communicator loaded.')
    
    def _udp_listen(self, host, port):
        udplog = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udplog.bind((socket.gethostbyname(host), port))
        
        lineformat = re.compile('^"(?P<name>.+?)<\d+><(?P<steam>STEAM_.+?)><(?P<team>Spectator|Blue|Red)>"\s(?P<type>say|say_team)\s"(?P<message>.+?)"', 
                                re.MULTILINE|re.VERBOSE)
        
        while True:
            data = udplog.recvfrom(1024)
            chat = lineformat.search(data[0][30:-2])
            if chat:
                self.chatqueue.put({'name': chat.group('name').strip(),
                                    'steam': chat.group('steam').strip(),
                                    'team': chat.group('team').strip(),
                                    'type': chat.group('type').strip(),
                                    'message': chat.group('message').strip()})
                continue
    
    def _worker_chat(self):
        while True:
            line = self.chatqueue.get()
            if line['steam'] in self.bot.watches or line['message'].lower().find('admin') != -1:
                self.public(self.fallbackconnect, '[CHAT] %s: %s' % (line['name'], line['message']))
                self.bot.log.chat('%s: %s' % (line['name'], line['message']))
            self.chatqueue.task_done()
    
    def _worker_irc(self):
        lines = 0
        while True:
            (conn, line) = self.ircqueue.get()
            if not conn:
                if self.fallbackconnect:
                    conn = self.fallbackconnect
                else:
                    self.ircqueue.task_done()
                    continue
            if lines % 8 == 0:
                time.sleep(2)
            conn.privmsg(self.bot.channel, line)
            lines += 1
            self.ircqueue.task_done()
            time.sleep(0.2)
    
    def set_fallback_connect(self, connect):
        self.fallbackconnect = connect

    def notice(self, connection, event, message):
        connection.notice(irclib.nm_to_n(event.source()), message)
    
    def public(self, connection, message):
        self.ircqueue.put((connection, message))
