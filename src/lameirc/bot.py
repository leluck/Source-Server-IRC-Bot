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

import hashlib
import json
import re
import sys
import time

import lameirc.rcon as rcon
import lameirc.assets as assets
import irclib.ircbot as ircbot
import irclib.irclib as irclib

class SourceServerIRCBot(ircbot.SingleServerIRCBot):
    def __init__(self):
        self.basecfg = '../config/settings.cfg'
        self.settings = self._read_config(self.basecfg)
        if self.settings is None:
            print('Failed to load settings file \'%s\'.' % (self.basecfg))
            sys.exit(1)

        try:
            logfile = self.settings['base']['logfile']
            self.log = assets.LogWrapper(logfile)
        except IOError:
            print('Unable to initialize log target %s.' % (logfile))
            sys.exit(1)
        except KeyError as ke:
            print('Missing entry in settings file: \'%s\'.' % (ke))
            sys.exit(1)

        self.log.system('### Bot launched.')

        try:
            nick = self.settings['irc']['nick']
            host = self.settings['irc']['host']
            port = self.settings['irc']['port']
            chan = self.settings['irc']['chan']
            
            ircbot.SingleServerIRCBot.__init__(self, [(host, port)], nick, nick)
            self.channel = chan
            self.nick = nick
            self.log.system('IRC setup loaded.')
        except KeyError as ke:
            print('Missing entry in settings file: \'%s\'.' % (ke))
            sys.exit(1)
            
        try:
            self.users = self.settings['users']
        except KeyError as ke:
            self.log.system('Missing entry in settings file: \'%s\'. No users available.' % (ke))

        try:
            aclfile = self.settings['base']['aclfile']
            self.acl = self._read_config(aclfile)
            self.log.system('ACL loaded.')
        except KeyError as ke:
            print('Missing entry in settings file: \'%s\'.' % (ke))
            sys.exit(1)
        
        try:
            helpfile = self.settings['base']['helpfile']
            self.help = self._read_config(helpfile)
            self.log.system('Help file loaded.')
        except KeyError as ke:
            print('Missing entry in settings file: \'%s\'. No help available.' % (ke))
            self.help = {}
        
        try:
            udpport = self.settings['base']['udplogport']
        except KeyError:
            udpport = 26999
            self.log.system('Falling back to default UDP log port.')
        self.communicate = assets.Communicator(self, udp_log_port = udpport)
        
        self.watches = []
        self._init_rcons()
        self.auths = dict()
    
    def _auth_user(self, connection, event, account, passwdhash):
        if account not in self.users:
            self.log.system('"%s" tried to auth with non-existant account "%s"' % (irclib.nm_to_n(event.source()), account))
            return False
        
        try:
            if self.users[account]['pass'] == passwdhash:
                self.auths[event.source()] = {'account': account, 'authed': True, 'time': time.time()}
                self.communicate.notice(connection, event, 'Authentication successful.')
                self.log.system('"%s" authed as "%s" (acl level %d)' % (irclib.nm_to_n(event.source()), account, self.users[account]['aclid']))
        except KeyError as ke:
            self.log.system('Missing entry in settings file: \'%s\'. Could not authenticate user.' % (ke))
            self.communicate.notice(connection, event, 'Your account information is incomplete. Ask an admin to check the config file.')
            
    
    def _check_acl(self, event, command):
        target = self.acl
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
    
    def _init_rcons(self):
        self.rcon = dict()
        for identifier in self.settings['rcon']:
            try:
                host = self.settings['rcon'][identifier]['host']
                port = self.settings['rcon'][identifier]['port']
                passwd = self.settings['rcon'][identifier]['pass']
                self.rcon[identifier] = rcon.Rcon(host, port, passwd, log = self.log)
                self.log.system('Initialized RCON for \'%s\'.' % (identifier))
            except rcon.RconException as re:
                self.log.system('RCON exception in \'%s\': %s' % (identifier, re))
            except KeyError as ke:
                self.log.system('Missing entry in settings file: \'%s\'. Could not initialize RCON for \'%s\'.' % (ke, identifier))
    
    def _parse_rcon_players(self, result):
        playerformat = re.compile(r'^#\s+?(\d+)\s+?"(.+?)"\s+?(STEAM_\S+).+?([\d.:]+)$', re.MULTILINE)
        players = playerformat.findall(result)
        pList = []
        for p in players:
            pList.append({'id': int(p[0]), 'name': p[1], 'steam': p[2], 'ip': p[3]})
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
    
    def _prettify_time(self, diff):
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
    
    def _rcon(self, identifier, command):
        if identifier not in self.rcon:
            raise assets.RconIdentifierError
        
        return self.rcon[identifier].send(command)
     
    def _read_config(self, file):
        try:
            with open(file, 'r') as cfgfile:
                contents = json.load(cfgfile)
            return contents
        except ValueError:
            self.log.system('Unable to read config \'%s\': Check syntax.')
        return None

    def on_pubmsg(self, connection, event):
        cmdParts = event.arguments()[0].split()
        if len(cmdParts) > 0 and cmdParts[0] == '.':
            target = self.acl
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
                        self.communicate.notice(connection, event, 'Yout lack access to this command.')
                        authed = 'DENIED'
                    else:
                        getattr(self, 'cmd_%s' % (key))(connection, event, cmdParts[1:last], cmdParts[last:])
                    
                    self.log.command('"%s" (%s): (%s) %s' % (irclib.nm_to_n(event.source()), account, authed, ' '.join(cmdParts[1:])))
                    return
            except TypeError as te:
                print(te)
                return
            except assets.RconIdentifierError:
                self.communicate.notice(connection, event, 'No rcon available for \'%s\'.' % (cmdParts[1]))
                return
            self.communicate.notice(connection, event, 'No such command. Try \'!sf help\' for an overview of available commands.')
    
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
            passwdhash = hashlib.sha256(args[2]).hexdigest()
            self._auth_user(connection, event, account, passwdhash)
        
        if len(args) == 1 and args[0].lower() == 'whoami':
            if event.source() in self.auths:
                account = self.auths[event.source()]['account']
                seconds = time.time() - self.auths[event.source()]['time']
                self.communicate.notice(connection, event, 'You are authed as %s (%s).' % (account, self._prettify_time(seconds)))
            else:
                self.communicate.notice(connection, event, 'You are not authed.')

    def on_welcome(self, connection, event):
        connection.join(self.channel)
        self.communicate.set_fallback_connect(connection)
        self.log.system('Joined %s as %s.' % (self.channel, self.nick))

    def cmd_exec(self, connection, event, command, args):
        if len(args) == 1:
            file = args[0]
            result = self._rcon(command[0], 'exec %s' % (file))
            if result.split(';')[0] == '\'%s\' not present' % (file):
                self.communicate.public(connection, 'Config not present; not executing.')
            else:
                self.communicate.public(connection, 'Config \'%s\' executed.' % (file))
    
    def cmd_help(self, connection, event, command, args):
        if len(args) == 0:
            acl_id = 0
            if event.source() in self.auths and self.auths[event.source()]['authed']:
                acl_id = self.users[self.auths[event.source()]['account']]['aclid']
            
            cmdlist = []
            for cmd in self.acl:
                if type(self.acl[cmd]) is type([]):
                    if 0 in self.acl[cmd] or acl_id in self.acl[cmd] \
                    and hasattr(self, 'cmd_%s' % (cmd)):
                        cmdlist.append(cmd)
                else:
                    for subcmd in self.acl[cmd]:
                        if 0 in self.acl[cmd][subcmd] or acl_id in self.acl[cmd][subcmd] \
                        and hasattr(self, 'cmd_%s' % (subcmd)):
                            cmdlist.append('%s %s' % (cmd, subcmd))
            
            cmdlist.sort()
            self.communicate.notice(connection, event, 'You have access to:')
            self.communicate.notice(connection, event, ', '.join(cmdlist))
        else:
            if args[-1] in self.help:
                self.communicate.notice(connection, event, self.help[args[-1]])
            else:
                self.communicate.notice(connection, event, 'No help available for command \'%s\'.' % (args[-1]))
    
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
                    self.communicate.public(connection, 'Invalid regular expression.')
                    return
                for p in players:
                    if pattern.search(p['name']):
                        self._rcon(command[0], 'kickid %d' % (p['id']))
                        kicked.append(p['name'])
            
            if len(kicked):
                self.communicate.public(connection, 'Kicked %s' % (', '.join(kicked)))
            else:
                self.communicate.public(connection, 'No matching player.')
    
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
        self.communicate.public(connection, message)

    def cmd_password(self, connection, event, command, args):
        message = ''
        if len(args) == 0:
            result = self._parse_var(self._rcon(command[0], 'sv_password'))
            message = 'Current password is: %s' % (result)
        elif len(args) == 1:
            result = self._rcon(command[0], 'sv_password %s' % (args[0]))
            message = 'Password set to: %s' % (args[0])
        self.communicate.public(connection, message)

    def cmd_players(self, connection, event, command, args):
        pattern = None
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.communicate.public(connection, 'Invalid regular expression.')
                return
                
        players = self._parse_rcon_players(self._rcon(command[0], 'status'))
        
        if pattern is not None:
            matches = []
            for p in players:
                if pattern.search(p['name']):
                    matches.append(p)
            players = matches
        
        if len(players) == 0:
            self.communicate.public(connection, 'No players.')
            return
        
        players.sort(key = lambda p: p['name'].lower())
        self.communicate.public(connection, '(%d): %s' % (len(players), ', '.join(['%s' % (p['name']) for p in players])))

    def cmd_reloadrcon(self, connection, event, command, args):
        self.log.system('Reloading RCON configurations.')
        try:
            self.rcon = self._read_config(self.basecfg)['rcon']
        except KeyError as ke:
            self.log.system('Missing entry in settings file: \'%s\'. No RCON available.' % (ke))
    
    def cmd_reloadusers(self, connection, event, command, args):
        self.log.system('Reloading user configurations.')
        for user in self.auths:
            self.communicate.notice(connection, user, 'Users are being reloaded. Please re-confirm your authentication.')
        self.auths = dict()
        try:
            self.users = self._read_config(self.basecfg)['users']
        except KeyError as ke:
            self.log.system('Missing entry in settings file: \'%s\'. No users available.' % (ke))

    def cmd_restart(self, connection, event, command, args):
        self.communicate.public(connection, 'Restarting server "%s".' % (command[0]))
        self._rcon(command[0], '_restart')

    def cmd_say(self, connection, event, command, args):
        if len(args) >= 1:
            self._rcon(command[0], 'say %s' % (' '.join(args)))

    def cmd_servers(self, connection, event, command, args):
        self.communicate.public(connection, 'Known servers are: %s' % (', '.join(self.rcon)))

    def cmd_status(self, connection, event, command, args):
        status = self._parse_rcon_status(self._rcon(command[0], 'status'))
        self.communicate.public(connection, '%s' % (status['hostname']))
        self.communicate.public(connection, '%s, players: %s' % (status['map'].split()[0], status['players']))
    
    def cmd_unwatch(self, connection, event, command, args):
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.communicate.public(connection, 'Invalid regular expression.')
                return
            
            matches = []
            for p in self._parse_rcon_players(self._rcon(command[0], 'status')):
                if pattern.search(p['name']) and p['steam'] in self.watches:
                    self.watches.remove(p['steam'])
                    matches.append(p['name'])
            if len(matches) > 0:
                matches.sort(key = lambda p: p.lower())
                self.communicate.public(connection, 'Players removed from watchlist (%d): %s' % (len(matches), ', '.join(matches)))
            else:
                self.communicate.public(connection, 'No matching players.')
    
    def cmd_watch(self, connection, event, command, args):
        if len(args) == 1:
            try:
                pattern = re.compile(r'%s' % (args[0]), re.IGNORECASE)
            except Exception:
                self.communicate.public(connection, 'Invalid regular expression.')
                return
            
            matches = []
            for p in self._parse_rcon_players(self._rcon(command[0], 'status')): 
                if pattern.search(p['name']) and p['steam'] not in self.watches:
                    self.watches.append(p['steam'])
                    matches.append(p['name'])
            if len(matches) > 0:
                matches.sort(key = lambda p: p.lower())
                self.communicate.public(connection, 'Players put on watchlist (%d): %s' % (len(matches), ', '.join(matches)))
            else:
                self.communicate.public(connection, 'No matching players.')
    
    def cmd_watchlist(self, connection, event, command, args):
        players = self._parse_rcon_players(self._rcon(command[0], 'status'))
        
        remove = []
        active = []
        for steamid in self.watches:
            if steamid not in [p['steam'] for p in players]:
                remove.append(steamid)
            else:
                active.append(filter(lambda p: p['steam'] == steamid, players)[0]['name'])
        
        for steamid in remove:
            self.watches.remove(steamid)
        
        if len(active) > 0:
            active.sort(key = lambda p: p.lower())
            self.communicate.public(connection, 'Players on watchlist (%d): %s' % (len(active), ', '.join(active)))
        else:
            self.communicate.public(connection, 'No players on watchlist.')
