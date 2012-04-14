#!/usr/bin/python

import sfirc.sfbot
import sfirc.rcon
import ConfigParser

def launch():
    cfg = ConfigParser.RawConfigParser()
    cfg.read('../config/rcon.cfg')

    try:
        nick = cfg.get('irc', 'nick')
        host = cfg.get('irc', 'host')
        port = cfg.getint('irc', 'port')
        chan = cfg.get('irc', 'chan')
        
        rcons = {}
        for identifier in cfg.sections():
            if identifier != 'irc':
                rcons[identifier] = {
                    'host': cfg.get(identifier, 'host'),
                    'port': cfg.getint(identifier, 'port'),
                    'pass': cfg.get(identifier, 'pass')}
    except ConfigParser.NoSectionError as nse:
        print(nse)
        return
    except ConfigParser.NoOptionError as noe:
        print(noe)
        return
    
    bot = sfirc.sfbot.SFBot(nick, chan, host, port)
    for identifier in rcons:
        bot.set_rcon(identifier, sfirc.rcon.Rcon(rcons[identifier]['host'], rcons[identifier]['port'], rcons[identifier]['pass']))
    bot.start()

if __name__ == '__main__':
    launch()