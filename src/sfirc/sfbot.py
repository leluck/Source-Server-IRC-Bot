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

import re
import time
import socket
import logging.handlers
import Queue
import threading

import irclib.ircbot as ircbot
import irclib.irclib as irclib

class SFRconIdentifierError(Exception):
    pass

class SFBot(ircbot.SingleServerIRCBot):
    def __init__(self, nick, channel, server, port = 6667):
        ircbot.SingleServerIRCBot.__init__(self, [(server, port)], nick, nick)
        self.channel = channel
        self.nick = nick
        self.fallbackconnect = None
        
        self.log = logging.Logger('SFBot')
        self.log.setLevel(logging.INFO)
        fHandler = logging.handlers.WatchedFileHandler('../log/sfbot.log')
        fHandler.setLevel(logging.INFO)
        fHandler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
        self.log.addHandler(fHandler)
        
        self.log.info('## Joined as %s in: %s@%s:%d' % (nick, channel, server, port))
        
        self.ircqueue = Queue.Queue(30)
        self.ircsender = threading.Thread(target = SFBot._worker_irc, args = (self,))
        self.ircsender.daemon = True
        self.ircsender.start()
        
        self.chatqueue = Queue.Queue(10)
        self.udplistener = threading.Thread(target = SFBot._udp_listen, args = (self, '0.0.0.0', 26999))
        self.udplistener.daemon = True
        self.udplistener.start()
        self.chatworker = threading.Thread(target = SFBot._worker_chat, args = (self,))
        self.chatworker.daemon = True
        self.chatworker.start()
        
        self.watches = []
        self.rcon = dict()
        self.auths = dict()
        self.users = {
            'LeLuck':       {'passphrase': '2f@P?A', 'aclid': 2},
            'fanta':        {'passphrase': 'rjk02<', 'aclid': 1},
            'Bluthund':     {'passphrase': '_;fNiI', 'aclid': 1},
            'JohnRambo':    {'passphrase': 'w37bY0', 'aclid': 1},
            'Trypha':       {'passphrase': 'IqTJK=', 'aclid': 1},
            'nTraum':       {'passphrase': 'phil', 'aclid': 3}
        }
        self.cmdlist = {
            'help':             [0],
            'public': {
                'status':       [0],
                'players':      [0],
                'map':          [2],
                'kick':         [2],
                'restart':      [],
                'say':          [1,2],
                'watch':        [1,2,3],
                'unwatch':      [1,2,3],
                'watchlist':    [1,2,3]
            },
            'match': {
                'status':       [0],
                'players':      [0],
                'map':          [1,2],
                'switchteams':  [1,2],
                'kick':         [1,2],
                'password':     [1,2],
                'exec':         [1,2],
                'restart':      [],
                'say':          [1,2]
            }
        }
    
    def set_rcon(self, identifier, rc):
        self.rcon[identifier] = rc
    
    def on_pubmsg(self, connection, event):
        cmdParts = event.arguments()[0].split()
        if cmdParts[0] == '!sf':
            target = self.cmdlist
            key = None
            last = 1
            for arg in cmdParts[1:]:
                try:
                    target = target[arg]
                    key = arg
                    last += 1
                except KeyError:
                    break
                except TypeError:
                    break
            try:
                if key is not None and hasattr(self, 'cmd_%s' % (key)):
                    authed = 'OK'
                    account = ''
                    if event.source() in self.auths:
                        account = self.auths[event.source()]['account']
                    
                    if not self._check_acl(event, cmdParts[1:last]):
                        connection.notice(irclib.nm_to_n(event.source()), 'You do not have access to this command.')
                        authed = 'DENIED'
                    else:
                        getattr(self, 'cmd_%s' % (key))(connection, event, cmdParts[1:last], cmdParts[last:])
                    
                    self.log.info('"%s" (%s): (%s) %s' % (irclib.nm_to_n(event.source()), account, authed, ' '.join(cmdParts[1:])))
                    return
            except TypeError as te:
                print(te)
                return
            except SFRconIdentifierError:
                connection.notice(irclib.nm_to_n(event.source()), 'No rcon available for \'%s\'.' % (cmdParts[1]))
                return
            connection.notice(irclib.nm_to_n(event.source()), 'No such command. Try \'!sf help\' for an overview of available commands.')
    
    def on_nick(self, connection, event):
        old = event.source()
        new = '%s!%s' % (event.target(),irclib.nm_to_uh(event.source()))
        
        if old in self.auths:
            self.auths[new] = self.auths[old]
            del self.auths[old]
    
    def on_part(self, connection, event):
        if event.source() in self.auths:
            del self.auths[event.source()]
    
    def on_privmsg(self, connection, event):
        args = event.arguments()[0].split()
        if len(args) == 3 and args[0].lower() == 'auth':
            account = args[1]
            passphrase = args[2]
            self._auth_user(connection, event, account, passphrase)
        
        if len(args) == 1 and args[0].lower() == 'whoami':
            if event.source() in self.auths:
                account = self.auths[event.source()]['account']
                seconds = time.time() - self.auths[event.source()]['time']
                connection.notice(irclib.nm_to_n(event.source()), 'You are authed as %s (%s).' % (account, self._prettyfy_time(seconds)))
            else:
                connection.notice(irclib.nm_to_n(event.source()), 'You are not authed.')
    
    def on_welcome(self, connection, event):
        connection.join(self.channel)
        self.ircqueue.put((connection, 'Ohai'))
        self.fallbackconnect = connection
    
    def cmd_exec(self, connection, event, command, args):
        if len(args) == 1:
            file = args[0]
            result = self._rcon(command[0], 'exec %s' % (file))
            if result.split(';')[0] == '\'%s\' not present' % (file):
                self.ircqueue.put((connection, 'Config not present; not executing.'))
            else:
                self.ircqueue.put((connection, 'Config \'%s\' executed.' % (file)))
    
    def cmd_help(self, connection, event, command, args):
        acl_id = 0
        if event.source() in self.auths and self.auths[event.source()]['authed']:
            acl_id = self.users[self.auths[event.source()]['account']]['aclid']
        
        cmdlist = []
        for cmd in self.cmdlist:
            if type(self.cmdlist[cmd]) is type([]):
                if 0 in self.cmdlist[cmd] or acl_id in self.cmdlist[cmd] \
                and hasattr(self, 'cmd_%s' % (cmd)):
                    cmdlist.append(cmd)
            else:
                for subcmd in self.cmdlist[cmd]:
                    if 0 in self.cmdlist[cmd][subcmd] or acl_id in self.cmdlist[cmd][subcmd] \
                    and hasattr(self, 'cmd_%s' % (subcmd)):
                        cmdlist.append('%s %s' % (cmd, subcmd))
        
        cmdlist.sort()
        connection.notice(irclib.nm_to_n(event.source()), 'You have access to:')
        connection.notice(irclib.nm_to_n(event.source()), ', '.join(cmdlist))
    
    def cmd_kick(self, connection, event, command, args):
        if len(args) == 1:
            players = self._parse_rcon_players(self._rcon(command[0], 'status'))
            kicked = []
            
            arg_is_id = False
            try:
                arg_is_id = str(int(args[0])) == args[0]
            except ValueError:
                pass
            
            if arg_is_id:
                id = int(args[0])
                for p in players:
                    if p['id'] == id:
                        self._rcon(command[0], 'kickid %d' % (p['id']))
                        kicked.append(p['name'])
            else:
                try:
                    pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
                except Exception:
                    self.ircqueue.put((connection, 'Invalid regular expression.'))
                    return
                for p in players:
                    if pattern.search(p['name']):
                        self._rcon(command[0], 'kickid %d' % (p['id']))
                        kicked.append(p['name'])
            
            if len(kicked):
                self.ircqueue.put((connection, 'Kicked %s' % (', '.join(kicked))))
            else:
                self.ircqueue.put((connection, 'No matching player.'))
    
    def cmd_map(self, connection, event, command, args):
        message = ''
        if len(args) == 0:
            status = self._parse_rcon_status(self._rcon(command[0], 'status'))
            message = 'Current map is: %s' % (status['map'].split()[0])
        elif len(args) == 1:
            result = self._rcon(command[0], 'changelevel %s' % (args[0]))
            if len(result) > 0:
                message = 'Map change failed: No such map.'
            else:
                message = 'Changing map to %s' % (args[0])
        self.ircqueue.put((connection, message))

    def cmd_password(self, connection, event, command, args):
        message = ''
        if len(args) == 0:
            result = self._parse_var(self._rcon(command[0], 'sv_password'))
            message = 'Current password is: %s' % (result)
        elif len(args) == 1:
            result = self._rcon(command[0], 'sv_password %s' % (args[0]))
            message = 'Password set to: %s' % (args[0])
        self.ircqueue.put((connection, message))

    def cmd_players(self, connection, event, command, args):
        pattern = None
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.ircqueue.put((connection, 'Invalid regular expression.'))
                return
                
        players = self._parse_rcon_players(self._rcon(command[0], 'status'))
        
        if pattern is not None:
            matches = []
            for p in players:
                if pattern.search(p['name']):
                    matches.append(p)
            players = matches
        
        if len(players) == 0:
            self.ircqueue.put((connection, 'No players.'))
            return
        
        players.sort(key = lambda p: p['name'].lower())
        self.ircqueue.put((connection, '(%d): %s' % (len(players), ', '.join(['%s' % (p['name']) for p in players]))))

    def cmd_restart(self, connection, event, command, args):
        self.ircqueue.put((connection, 'Restarting server "%s".' % (command[0])))
        self._rcon(command[0], '_restart')

    def cmd_say(self, connection, event, command, args):
        if len(args) >= 1:
            self._rcon(command[0], 'say %s' % (' '.join(args)))

    def cmd_status(self, connection, event, command, args):
        status = self._parse_rcon_status(self._rcon(command[0], 'status'))
        self.ircqueue.put((connection, '%s' % (status['hostname'])))
        self.ircqueue.put((connection, '%s, players: %s' % (status['map'].split()[0], status['players'])))
    
    def cmd_unwatch(self, connection, event, command, args):
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.ircqueue.put((connection, 'Invalid regular expression.'))
                return
            
            matches = []
            for p in self._parse_rcon_players(self._rcon(command[0], 'status')):
                if pattern.search(p['name']) and p['steam'] in self.watches:
                    self.watches.remove(p['steam'])
                    matches.append(p['name'])
            if len(matches) > 0:
                matches.sort(key = lambda p: p.lower())
                self.ircqueue.put((connection, 'Players removed from watchlist (%d): %s' % (len(matches), ', '.join(matches))))
            else:
                self.ircqueue.put((connection, 'No matching players.'))
    
    def cmd_watch(self, connection, event, command, args):
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.ircqueue.put((connection, 'Invalid regular expression.'))
                return
            
            matches = []
            for p in self._parse_rcon_players(self._rcon(command[0], 'status')): 
                if pattern.search(p['name']) and p['steam'] not in self.watches:
                    self.watches.append(p['steam'])
                    matches.append(p['name'])
            if len(matches) > 0:
                matches.sort(key = lambda p: p.lower())
                self.ircqueue.put((connection, 'Players put on watchlist (%d): %s' % (len(matches), ', '.join(matches))))
            else:
                self.ircqueue.put((connection, 'No matching players.'))
    
    def cmd_watchlist(self, connection, event, command, args):
        players = self._parse_rcon_players(self._rcon(command[0], 'status'))
        
        remove = []
        active = []
        for steamid in self.watches:
            if steamid not in [p['steam'] for p in players]:
                remove.append(steamid)
            else:
                active.append(filter(lambda p: p['steam'] == steamid, players)['name'])
        
        for steamid in remove:
            self.watches.remove(steamid)
        
        if len(active) > 0:
            active.sort(key = lambda p: p.lower())
            self.ircqueue.put((connection, 'Players on watchlist (%d): %s' % (len(active), ', '.join(active))))
        else:
            self.ircqueue.put((connection, 'No players on watchlist.'))
    
    def _auth_user(self, connection, event, account, passphrase):
        if account not in self.users:
            self.log.info('"%s" tried to auth with non-existant account "%s"' % (irclib.nm_to_n(event.source()), account))
            return False
        
        if self.users[account]['passphrase'] == passphrase:
            self.auths[event.source()] = {'account': account, 'authed': True, 'time': time.time()}
            connection.notice(irclib.nm_to_n(event.source()), 'Authentication successful.')
            self.log.info('"%s" authed as "%s" (acl level %d)' % (irclib.nm_to_n(event.source()), account, self.users[account]['aclid']))
    
    def _check_acl(self, event, command):
        target = self.cmdlist
        for c in command:
            target = target[c]
        
        # 0 is free for all
        if 0 in target:
            return True
        
        if event.source() not in self.auths:
            return False
            
        if self.auths[event.source()]['authed'] \
        and self.users[self.auths[event.source()]['account']]['aclid'] in target:
            return True
        return False
    
    def _parse_rcon_players(self, result):
        playerformat = re.compile(r'^#\s+?(\d+)\s+?"(.+?)"\s+?(STEAM_\S+).+?([\d.:]+)$', re.MULTILINE)
        players = playerformat.findall(result)
        pList = []
        for p in players:
            pList.append({'id': int(p[0]), 'name': p[1].encode('utf-8'), 'steam': p[2].encode('utf-8'), 'ip': p[3].encode('utf-8')})
        return pList
    
    def _parse_rcon_status(self, result):
        propertyformat = re.compile(r'^(\S+)\s*:\s+(.+?)$', re.MULTILINE)
        properties = propertyformat.findall(result)
        pList = dict()
        for p in properties:
            pList[p[0]] = p[1]
        return pList
    
    def _parse_var(self, result):
        varformat = re.compile(r'"\S+" = "(.+?)"')
        return varformat.search(result).groups()[0]

    def _rcon(self, identifier, command):
        if identifier not in self.rcon:
            raise SFRconIdentifierError
        
        return self.rcon[identifier].send(command)
    
    def _prettyfy_time(self, diff):
        diff = int(diff)
        
        if diff < 10:
            return 'just now'
        if diff < 60:
            return str(diff) + ' seconds ago'
        if diff < 120:
            return  'a minute ago'
        if diff < 3600:
            return str( diff / 60 ) + ' minutes ago'
        if diff < 7200:
            return 'an hour ago'
        if diff < 86400:
            return str( diff / 3600 ) + ' hours ago'
    
    def _udp_listen(self, host, port):
        log = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        log.bind((socket.gethostbyname(host), port))
        
        lineformat = re.compile('^"(?P<name>.+?)<\d+><(?P<steam>STEAM_.+?)><(?P<team>Spectator|Blue|Red)>"\s(?P<type>say|say_team)\s"(?P<message>.+?)"', 
                                re.MULTILINE|re.VERBOSE)
        mapchangeformat = re.compile('^Loading map "(?P<map>.+?)"')
        while True:
            data = log.recv(1024)
            chat = lineformat.search(data[30:-2].encode('utf-8'))
            if chat:
                self.chatqueue.put({'name': chat.group('name').strip(),
                                    'steam': chat.group('steam').strip(),
                                    'team': chat.group('team').strip(),
                                    'type': chat.group('type').strip(),
                                    'message': chat.group('message').strip()})
                continue
            mapchange = mapchangeformat.search(data[30:-2].encode('utf-8'))
            if mapchange:
                self.ircqueue.put((self.fallbackconnect, '[MAPCHANGE]: %s' % (mapchange.group('map').strip())))
            
    
    def _worker_chat(self):
        while True:
            line = self.chatqueue.get()
            if line['steam'] in self.watches or line['message'].lower().find('admin') != -1:
                self.ircqueue.put((self.fallbackconnect, '[CHAT] %s: %s' % (line['name'], line['message'])))
                self.log.info('[CHAT] %s: %s' % (line['name'], line['message']))
            self.chatqueue.task_done()
    
    def _worker_irc(self):
        lines = 0
        while True:
            if lines % 8 == 0:
                time.sleep(2)
            (conn, line) = self.ircqueue.get()
            if not conn and self.fallbackconnect:
                conn = self.fallbackconnect
            if not conn and not self.fallbackconnect:
                self.ircqueue.task_done()
                continue
            conn.privmsg(self.channel, line)
            lines += 1
            self.ircqueue.task_done()
            time.sleep(0.2)
    
    