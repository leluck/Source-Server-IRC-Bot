# -*- coding: utf-8 -*-

# Copyright (c) 2012 Alexander Kuhrt, Johannes Bendler
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

import socket
import struct
import select
import time

class SFRconException(Exception):
    pass


class Rcon:
    SERVERDATA_AUTH = 3
    SERVERDATA_AUTH_RESPONSE = 2
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_RESPONSE_VALUE = 0
    
    def __init__(self, host, port = 27015, rcon_password = None, timeout = 120):
        self.socket = None
        self.ip = socket.gethostbyname(host)
        self.port = port
        self.rcon_password = rcon_password
        self.timeout = timeout
        self.request_id = 0
        self.authenticated = False
        
        self._connect()
    
    def __del__(self):
        self._disconnect()
    
    def _connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(self.timeout)
        self.lastConnect = time.time()
        self.socket.connect((self.ip, self.port))
        
        if self.rcon_password:
            self._authenticate()
        else:
            raise SFRconException('No RCON password given')
    
    def _disconnect(self):
        if self.socket:
            self.socket.close()
    
    def _authenticate(self):
        self._send(self.rcon_password, type = self.SERVERDATA_AUTH)
        
        if self._recv() != '' and self.authenticated == False:
            raise SFRconException('IP is banned')
        
        self._recv() # Whatever...
    
    def _send(self, command, type = SERVERDATA_EXECCOMMAND):
        self.request_id += 1
        
        cmd_string = (command + '\x00\x00').encode('latin-1')
        packet = struct.pack('<LLL', len(cmd_string) + 4 + 4, self.request_id, type) + cmd_string
        
        if time.time() - self.lastConnect >= 30:
            self.request_id -= 1
            self._disconnect()
            self._connect()
        
        self.socket.send(packet)
        
    def _recv(self):
        response = b''
        
        while True:
            recv_buffer = b''
            
            size = struct.unpack('<L', self.socket.recv(4))[0]
            
            while len(recv_buffer) < size:
                recv_buffer += self.socket.recv(size - len(recv_buffer))
            
            if len(recv_buffer) != size:
                raise SFRconException('Received RCON response with bad length (%d of %d bytes)' % (len(recv_buffer), size))
            
            request_id, response_code = struct.unpack('<LL', recv_buffer[0:8])
            
            if hex(request_id) == '0xffffffff':
                raise SFRconException('Bad RCON password')
            elif request_id != self.request_id:
                raise SFRconException('Received bad request id: %d (expected %d)' % (request_id, self.request_id))
            
            if response_code == self.SERVERDATA_AUTH_RESPONSE:
                self.authenticated = True
            elif response_code != self.SERVERDATA_RESPONSE_VALUE:
                raise SFRconException('Invalid RCON response code: %d' % (response_code))

            response += recv_buffer[8:size - 8 - 2]
            
            # Socket still has data to read?
            poll = select.select([self.socket], [], [], 0)
            
            if not len(poll[0]) and size < 3700:
                break
            
        return response
    
    def send(self, command):
        if self.authenticated == False:
            raise SFRconException('Not authenticated, cannot perform RCON command')
        
        self._send('%s' % command)
        return self._recv()