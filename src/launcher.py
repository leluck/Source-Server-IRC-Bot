#!/usr/bin/python
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

import lameirc.lamebot
import ConfigParser

def launch():
    
    cfg = ConfigParser.RawConfigParser()
    cfg.read('../config/irc.cfg')
    
    try:
        nick = cfg.get('irc', 'nick')
        host = cfg.get('irc', 'host')
        port = cfg.getint('irc', 'port')
        chan = cfg.get('irc', 'chan')
    except ConfigParser.NoSectionError as nse:
        print(nse)
        return
    except ConfigParser.NoOptionError as noe:
        print(noe)
        return
    
    bot = lameirc.lamebot.LameBot(nick, chan, host, port)
    bot.start()

if __name__ == '__main__':
    launch()