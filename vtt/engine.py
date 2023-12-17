"""
https://github.com/cgloeckner/pyvtt/

Copyright (c) 2020-2022 Christian Glöckner
License: MIT (see LICENSE for details)
"""

__author__ = 'Christian Glöckner'
__licence__ = 'MIT'

import hashlib
import json
import os
import pathlib
import re
import requests
import shutil
import subprocess
import sys
import time
import uuid

import bottle

import vtt.utils as utils
from vtt.tools.buildnumber import BuildNumber
from vtt.cache import EngineCache
from vtt.orm.register import db_session, createMainDatabase
from vtt.server import VttServer


class Engine(object):

    def __init__(self, app_root=pathlib.Path('.'), argv=list(), pref_dir=None):
        appname = 'pyvtt'
        self.log_level = 'INFO'
        for arg in argv:
            if arg.startswith('--appname='):
                appname = arg.split('--appname=')[1]

            elif arg.startswith('--prefdir='):
                pref_dir = arg.split('--prefdir=')[1]

            elif arg.startswith('--loglevel='):
                self.log_level = arg.split('--loglevel=')[1]

        self.paths = utils.PathApi(appname=appname, pref_root=pref_dir, app_root=app_root)
        self.paths.ensure(self.paths.get_export_path())

        self.app = bottle.default_app()

        # setup per-game stuff
        self.checksums = dict()
        self.locks = dict()
        
        # webserver stuff
        self.listen = '0.0.0.0'
        self.hosting = {
            'domain'  : 'localhost',
            'port'    : 8080,
            'socket'  : '',
            'ssl'     : False,
            'reverse' : False
        }
        self.shards = list()
        
        self.main_db = None
        
        # blacklist for GM names and game URLs
        self.gm_blacklist = ['', 'static', 'asset', 'vtt', 'game']
        self.url_regex    = '^[A-Za-z0-9_\-.]+$'
        
        # maximum file sizes for uploads (in MB)
        self.file_limit = {
            "token"      : 2,
            "background" : 10,
            "game"       : 30,
            "music"      : 10,
            "num_music"  : 5
        }
        self.playercolors = ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF']
        
        self.title          = appname
        self.links          = list()
        self.cleanup = {
            'expire': 3600 * 24 * 30, # default: 30d
            'daytime': '03:00'
        }
        self.login          = dict() # login settings
        self.login['type']  = ''
        self.login_api      = None   # login api instance
        self.notify         = dict() # crash notify settings
        self.notify['type'] = ''
        self.notify_api     = None   # notify api instance
        
        self.cache         = None   # later engine cache

        # handle commandline arguments
        self.localhost = '--localhost' in argv
        self.debug     = '--debug' in argv
        self.quiet     = '--quiet' in argv
        self.no_logs   = '--no-logs' in argv
        
        self.logging = utils.LoggingApi(
            quiet        = self.quiet,
            info_file    = self.paths.get_log_path('info'),
            error_file   = self.paths.get_log_path('error'),
            access_file  = self.paths.get_log_path('access'),
            warning_file = self.paths.get_log_path('warning'),
            logins_file  = self.paths.get_log_path('logins'),
            auth_file    = self.paths.get_log_path('auth'),
            stdout_only  = self.no_logs,
            loglevel     = self.log_level
        )
        
        self.logging.info(f'Started Modes: {sys.argv}')
        
        # load fancy url generator api ... lol
        self.url_generator = utils.FancyUrlApi(self.paths)

        # handle settings
        settings_path = self.paths.get_settings_path()
        if not os.path.exists(settings_path):
            # create default settings
            settings = {
                'title'        : self.title,
                'cleanup'      : self.cleanup,
                'links'        : self.links,
                'file_limit'   : self.file_limit,
                'playercolors' : self.playercolors,
                'shards'       : self.shards,
                'hosting'      : self.hosting,
                'login'        : self.login,
                'notify'       : self.notify
            }
            with open(settings_path, 'w') as h:
                json.dump(settings, h, indent=4)
                self.logging.info('Created default settings file')
        else:
            # load settings
            with open(settings_path, 'r') as h:
                settings = json.load(h)
                self.title        = settings['title']
                self.cleanup      = settings['cleanup']
                self.links        = settings['links']
                self.file_limit   = settings['file_limit']
                self.playercolors = settings['playercolors']
                self.shards       = settings['shards']
                self.hosting      = settings['hosting']
                self.login        = settings['login']
                self.notify       = settings['notify']
            self.logging.info('Settings loaded')

        # add this server to the shards list
        self.shards.append(self.getUrl())
        
        # show argv help
        if '--help' in argv:
            print('Commandline options:')
            print('    --localhost  Restrict server to 127.0.0.1')
            print('    --debug      Suppress notification API, enable catching all')
            print('                 exceptions')
            print('    --quiet      Suppress logging to stdout.')
            print('    --no-logs    Suppress logging to files.')
            print('    --appname=<title>')
            print('                 Use <title> in html title and as foldername for')
            print('                 preference directory, e.g. ~/.local/share/<title>')
            print('    --prefdir=<path>')
            print('                 Use <path> as root path for preference directory.')
            print('                 Default ~/.local/share')
            print('    --loglevel=<level>')
            print('                 Use <level> as logging level')
            print('')
            print('See {0} for custom settings.'.format(settings_path))
            sys.exit(0)

        if self.localhost:
            # use localhost as domain
            self.listen = '127.0.0.1'
            self.hosting['domain'] = 'localhost'
            self.logging.info('Restricting to localhost')

        else:
            if self.hosting['domain'] == '':
                # run via public ip
                ip = self.getPublicIp()
                self.hosting['domain'] = ip
                self.logging.info(f'Using Public IP {ip} as Domain')

            # FIXME: use factory pattern
            if self.notify['type'] == 'webhook' and not self.debug:
                if self.notify['provider'] == 'discord':
                    self.notify_api = utils.DiscordWebhookNotifier(self, appname=appname, **self.notify)

            if self.notify['type'] == 'email' and not self.debug:
                # create email notify API
                self.notify_api = utils.EmailApi(self, appname=appname, **self.notify)

            if self.login['type'] == 'oauth':
                self.login_api = utils.OAuthLogin(engine=self, **self.login)

        self.logging.info('Loading main database...')
        # create main database
        self.main_db = createMainDatabase(self)
        
        # setup db_session to all routes
        self.app.install(db_session)
        
        # setup error catching
        if self.debug:
            # let bottle catch exceptions
            self.app.catchall = True
        
        else:
            # use custom middleware
            self.error_reporter = utils.ErrorReporter(self)
            self.app.install(self.error_reporter.plugin)
        
        # dice roll specific timers
        self.recent_rolls = 30 # rolls within past 30s are recent
        self.latest_rolls = 60 * 10 # rolls within the past 10min are up-to-date

        # load version number
        bn = BuildNumber()
        bn.load_from_file(self.paths.get_static_path(default=True) / 'client' / 'version.js')
        self.version = str(bn)
        
        # query latest git hash
        self.git_hash = None
        try:
            with open('sha.txt') as h:
                self.git_hash = h.read().split('\n')[0]
        except:
            self.logging.warning('Cannot load git SHA from sha.txt.')
            # fallback
            p = subprocess.run('git rev-parse --short HEAD', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode != 0:
                error = p.stderr.decode('utf-8')
                self.logging.error(f'Cannot query git SHa from commandline: {error}')
            else:
                self.git_hash = p.stdout.decode('utf-8').split('\n')[0]

        # generate debug hash
        self.debug_hash = None
        if self.debug:
            self.debug_hash = uuid.uuid4().hex

        # export server constants to javascript-file
        self.constants = utils.ConstantExport()
        self.constants(self)

        # game cache
        self.cache = EngineCache(self)

    def run(self):
        certfile = ''
        keyfile  = ''
        if self.hasSsl():
            # enable SSL
            ssl_dir = self.paths.get_ssl_path()
            certfile = ssl_dir / 'cacert.pem'
            keyfile  = ssl_dir / 'privkey.pem'
            assert(os.path.exists(certfile))
            assert(os.path.exists(keyfile))
        
        ssl_args = {'certfile': certfile, 'keyfile': keyfile} if self.hasSsl() else {}
        
        if self.notify_api is not None:
            self.notify_api.on_start()

        bottle.run(
            host       = self.listen,
            port       = self.hosting['port'],
            debug      = self.debug,
            quiet      = self.quiet,
            server     = VttServer,
            # VttServer-specific
            unixsocket = self.hosting['socket'],
            # SSL-specific
            **ssl_args
        )
        
    def getDomain(self):
        if self.localhost:
            # because of forced localhost mode
            return 'localhost'
        else:
            # use domain (might be replaced by public ip)
            return self.hosting['domain']
        
    def getPort(self):
        return self.hosting['port']
   
    def getUrl(self):
        suffix = 's' if self.hasReverseProxy() or self.hasSsl() else ''
        port   = '' if self.hasReverseProxy() else f':{self.getPort()}'
        return f'http{suffix}://{self.getDomain()}{port}'

    def getWebsocketUrl(self):
        protocol = 'wss' if self.hasReverseProxy() or self.hasSsl() else 'ws'
        port     = '' if self.hasReverseProxy() else f':{self.getPort()}'
        return f'{protocol}://{self.getDomain()}{port}/vtt/websocket'

    def getAuthCallbackUrl(self):
        protocol = 'https' if self.hasReverseProxy() or self.hasSsl() else 'http'
        port     = '' if self.hasReverseProxy() else f':{self.getPort()}'
        return f'{protocol}://{self.getDomain()}{port}/vtt/callback'

    def getBuildSha(self):
        if self.debug_hash is not None:
            return self.debug_hash

        v = self.version
        if self.git_hash is not None:
            v += '-' + self.git_hash
        
        return v

    def hasReverseProxy(self):
        return self.hosting['reverse']

    def hasSsl(self):
        return self.hosting['ssl']

    def verifyUrlSection(self, s):
        return bool(re.match(self.url_regex, s))
        
    def getClientIp(self, request):
        # use different header if through unix socket or reverse proxy
        if self.hosting['socket'] != '' or self.hasReverseProxy():
            return request.environ.get('HTTP_X_FORWARDED_FOR')
        else:
            return request.environ.get('REMOTE_ADDR')

    def getClientAgent(self, request):
        return request.environ.get('HTTP_USER_AGENT')
        
    def getCountryFromIp(self, ip, timeout=3):
        result = '?' # fallback case
        try:
            html = requests.get('http://ip-api.com/json/{0}'.format(ip), timeout=timeout)
            d = json.loads(html.text)
            if 'countryCode' in d:
                result = d['countryCode'].lower()
        except requests.exceptions.ReadTimeout as e:
            self.logging.warning('Cannot query location of IP {0}'.format(ip))
        return result
        
    def getPublicIp(self):
        try:
            return requests.get('https://api.ipify.org').text
        except requests.exceptions.ReadTimeout as e:
            self.logging.warning('Cannot query server\'s ip')
            return 'localhost'

    def parseLoginLog(self):

        class LoginRecord(object):
            def __init__(self, timeid, country, ip, agent):
                self.timeid  = timeid
                self.country = country
                self.ip      = ip
                self.agent   = agent
        
        records = list()
        with open(self.paths.get_log_path('logins'), 'r') as h:
            content = h.read()
            for line in content.split('\n'):
                if line == '':
                    continue
                args = json.loads(line)
                records.append(LoginRecord(*args))
        return records

    
    @staticmethod
    def getMd5(handle):
        hash_md5 = hashlib.md5()
        offset = handle.tell()
        for chunk in iter(lambda: handle.read(4096), b""):
            hash_md5.update(chunk)
        # rewind after reading
        handle.seek(offset)
        return hash_md5.hexdigest()
        
    def getSize(self, file_upload):
        """ Determine size of a file upload.
        """
        offset = file_upload.file.tell()
        size = len(file_upload.file.read())
        file_upload.file.seek(offset)
        return size
        
    def getSupportedDice(self):
        return [2, 4, 6, 8, 10, 12, 20, 100]
        
    def cleanupAll(self):
        """ Deletes all export games' zip files, unused images and
        outdated dice roll results from all games.
        Inactive games or even GMs are deleted
        (see engine.cleanup['expire']).
        """
        now = time.time()
        gms   = list()
        games = list()
        num_bytes  = 0
        num_rolls  = 0
        num_tokens = 0
        num_md5s   = 0
        
        with db_session:
            for gm in self.main_db.GM.select():
                gm_cache = self.cache.get(gm)

                # check if GM expired
                if gm.hasExpired(now): 
                    # remove expired GM
                    num_bytes += gm.preDelete()
                    gms.append(gm.url)
                    gm.delete()
                    continue

                # cleanup GM's games
                g, b, r, t, m = gm.cleanup(gm_cache.db, now)
                games.extend(g)
                num_bytes  += b
                num_rolls  += r
                num_tokens += t
                num_md5s   += m
        
        # remove all exported games' zip files
        export_path = self.paths.get_export_path()
        num_zips = len(os.listdir(export_path))
        if num_zips > 0:
            num_bytes += os.path.getsize(export_path)
            shutil.rmtree(export_path)
            self.paths.ensure(export_path)

        return gms, games, num_zips, num_bytes, num_rolls, num_tokens, num_md5s

    def saveToDict(self):
        """ Export all GMs and their games (including scenes and tokens)
        to a single dict. Images and music are NOT included.
        This method's purpose is to allow database schema migration:
        export the database, purge and rebuild, import data.
        """
        gms = list()

        # dump GM data (name, session id etc.)
        with db_session:
            for gm in self.main_db.GM.select():
                gms.append(gm.to_dict())
        
        # dump each GM's games
        for gm in gms:         
            gm_cache = self.cache.getFromUrl(gm['url'])
            gm['games'] = dict()
            with db_session:
                for game in gm_cache.db.Game.select():
                    # fetch all(!) data
                    gm['games'][game.url] = game.toDict()

        return gms

    def loadFromDict(self, gms):
        """ Import all GMs and their games (including scenes and tokens)
        from a single dict. Images and music are NOT included.
        This method's purpose is to allow database schema migration.
        ONLY CALL THIS WITH EMPTY DATABASES.
        """
        # create GM data (name, session id etc.)
        with db_session:
            for gm_data in gms:
                gm = self.main_db.GM(name=gm_data['name'], url=gm_data['url'],
                                     identity=gm_data['identity'], sid=gm_data['sid'],
                                     metadata=gm_data['metadata'])
                gm.postSetup() # NOTE: timeid is overwritten here
                self.cache.insert(gm)

        # create Games
        for gm_data in gms:
            gm_cache = self.cache.getFromUrl(gm_data['url'])
            gm_cache.connect_db()
            with db_session:
                for url in gm_data['games']:
                    game = gm_cache.db.Game(url=url, gm_url=gm_data['url'])
                    game.postSetup()
                    gm_cache.db.commit()
                    game.fromDict(gm_data['games'][url])
                    gm_cache.db.commit()
                    