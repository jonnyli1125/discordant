import asyncio
import json
import re
import sys
import threading
from collections import namedtuple
from inspect import iscoroutinefunction
from os import path

import aiohttp
import discord
import motor.motor_asyncio

import discordant.utils as utils

Command = namedtuple('Command', ['name', 'arg_func', 'aliases', 'section'])


class Discordant(discord.Client):
    _CMD_NAME_REGEX = re.compile(r'[a-z0-9]+')
    _handlers = {}
    _commands = {}
    _aliases = {}
    _triggers = set()

    def __init__(self, config_file='config.json'):
        super().__init__()

        self.__email = ''  # prevent a conflict with discord.Client#email
        self._password = ''
        self._token = ''
        self.command_char = ''
        self.controllers = []
        self.mongodb = None
        self.config = {}
        self.default_server = None

        self.load_config(config_file)

    def run(self):
        if self._token:
            super().run(self._token)
        else:
            super().run(self.__email, self._password)

    def load_config(self, config_file):
        if utils.is_url(config_file):
            async def f():
                nonlocal config_file
                with aiohttp.ClientSession() as session:
                    async with session.get(config_file) as response:
                        self.config = await response.json()

            asyncio.get_event_loop().run_until_complete(f())
        elif not path.exists(config_file):
            print("No config file found (expected '{}').".format(config_file))
            print("Copy config-example.json to", config_file,
                  "and edit it to use the appropriate settings.")
            sys.exit(-1)
        else:
            with open(config_file, "r") as f:
                self.config = json.load(f)
        if 'token' in self.config['login']:
            self._token = self.config['login']['token']
        else:
            self.__email = self.config['login']['email']
            self._password = self.config['login']['password']
        self.command_char = self.config['commands']['command_char']
        self.controllers = self.config["client"]["controllers"]
        self.mongodb = motor.motor_asyncio.AsyncIOMotorClient(
            self.config["api-keys"]["mongodb"]).get_default_database()
        self.load_aliases()

    def load_aliases(self):
        aliases = self.config['aliases']
        for base_cmd, alias_list in aliases.items():
            cmd_name = self._aliases[base_cmd]

            for alias in alias_list:
                self._aliases[alias] = cmd_name
                self._commands[cmd_name].aliases.append(alias)

    async def on_ready(self):
        await self.change_status(
            game=discord.Game(name=self.config["client"]["game"])
            if self.config["client"]["game"] else None)
        self.default_server = self.get_channel(
            self.config["moderation"]["log_channel"]).server
        await self.load_punishment_timers()
        voice_role = discord.utils.get(self.default_server.roles, name="Voice")
        for member in [x for x in self.default_server.members
                       if x.voice_channel or voice_role in x.roles]:
            await self._update_voice_roles(member, voice_role)

    async def load_punishment_timers(self):
        cursor = await self.mongodb.punishments.find().to_list(None)
        for document in reversed(cursor):
            action = document["action"]
            if action == "ban" or action.startswith("removed"):
                continue
            member = self.default_server.get_member(document["user_id"])
            if member is None:
                continue
            if await utils.is_punished(self, member, action):
                await self.add_punishment_timer(member, action)

    async def add_punishment_timer(self, member, action):
        async def f():
            nonlocal member, action
            punishments = {"warning": "Warned", "mute": "Muted"}
            while True:
                if not await utils.is_punished(self, member, action):
                    await self.remove_roles(
                        member,
                        discord.utils.get(
                            member.server.roles, name=punishments[action]))
                    break
                await asyncio.sleep(
                    self.config["moderation"]["punishment_check_rate"])

        def loop_in_thread(l):
            asyncio.set_event_loop(l)
            l.run_until_complete(f())

        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop_in_thread, args=(loop,))
        t.start()

    async def on_member_join(self, member):
        if await utils.is_punished(self, member, "ban"):
            await self.ban(member.server, member)
            return
        if await utils.is_punished(self, member, "warning"):
            await self.add_roles(
                member, discord.utils.get(member.server.roles, name="Warned"))
        if await utils.is_punished(self, member, "mute"):
            await self.add_roles(
                member, discord.utils.get(member.server.roles, name="Muted"))

    async def _update_voice_roles(self, member, *roles):
        in_voice = bool(member.voice_channel) and \
                   member.voice_channel != member.server.afk_channel
        f_name = ("add" if in_voice else "remove") + "_roles"
        await getattr(self, f_name)(member, *roles)

    async def on_voice_state_update(self, before, after):
        if before.voice_channel != after.voice_channel:
            roles = [discord.utils.get(after.server.roles, name="Voice")]
            doc = await self.mongodb.punishments.find_one({"user_id": after.id})
            if not doc or not doc["value"]:
                # discord.py library bug, so prepending to list for now.
                roles.insert(
                    0, discord.utils.get(after.server.roles, name="VC Shown"))
            await self._update_voice_roles(after, *roles)

    async def on_message(self, message):
        # TODO: logging
        if message.content.startswith(self.command_char) and \
                        message.author != self.user:
            await self.run_command(message)
            return

        for handler_name, trigger in self._handlers.items():
            match = trigger.search(message.content)
            if match is not None:
                await getattr(self, handler_name)(match, message)
            # do we return after the first match? or allow multiple matches

    async def run_command(self, message):
        cmd_name, *args = message.content.split(' ')
        cmd_name = cmd_name[1:]
        args = ' '.join(args).strip()

        if cmd_name in self._aliases:
            cmd = self._commands[self._aliases[cmd_name]]
            args = cmd.arg_func(args)
            await getattr(self, cmd.name)(args, message)

    @classmethod
    def register_handler(cls, trigger, regex_flags=0):
        try:
            trigger = re.compile(trigger, regex_flags)
        except re.error as err:
            print('Invalid trigger "{}": {}'.format(trigger, err.msg))
            sys.exit(-1)

        if trigger.pattern in cls._triggers:
            print('Cannot reuse pattern "{}"'.format(trigger.pattern))
            sys.exit(-1)

        cls._triggers.add(trigger.pattern)

        def wrapper(func):
            if not iscoroutinefunction(func):
                print('Handler for trigger "{}" must be a coroutine'.format(
                    trigger.pattern))
                sys.exit(-1)

            func_name = '_trg_' + func.__name__
            # disambiguate the name if another handler has the same name
            while func_name in cls._handlers:
                func_name += '_'

            setattr(cls, func_name, func)
            cls._handlers[func_name] = trigger

        return wrapper

    @classmethod
    def register_command(cls, name, aliases=None, arg_func=lambda args: args,
                         section="general"):
        if aliases is None:
            aliases = []
        aliases.append(name)

        def wrapper(func):
            if not iscoroutinefunction(func):
                print('Handler for command "{}" must be a coroutine'.format(
                    name))
                sys.exit(-1)

            func_name = '_cmd_' + func.__name__
            while func_name in cls._commands:
                func_name += '_'

            setattr(cls, func_name, func)
            cls._commands[func_name] = Command(
                func_name, arg_func, aliases, section)
            # associate the given aliases with the command
            for alias in aliases:
                if alias in cls._aliases:
                    print('The alias "{}"'.format(alias),
                          'is already in use for command',
                          cls._aliases[alias][:5].strip('_'))
                    sys.exit(-1)
                if cls._CMD_NAME_REGEX.match(alias) is None:
                    print('The alias "{}"'.format(alias),
                          ('is invalid. Aliases must only contain lowercase'
                           ' letters or numbers.'))
                    sys.exit(-1)
                cls._aliases[alias] = func_name

        return wrapper
