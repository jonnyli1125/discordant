import asyncio
import json
import re
import sys
import traceback
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
        self.commands_parsed = 0
        self.log_channel = None
        self.staff_channel = None

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

    async def discordme_bump(self):
        cfg = self.config["api-keys"]["discordme"]
        while True:
            with aiohttp.ClientSession() as session:
                async with session.post(
                        "https://discord.me/signin",
                        data=cfg["login"]
                ) as response:
                    if not response.status == 200:
                        print("DiscordMe login request failed.")
                        return
                    if '<li><a href="/logout">LOGOUT</a></li>' not in \
                            await response.text():
                        print("DiscordMe login credentials incorrect.")
                        return
                async with session.get(
                                "https://discord.me/server/bump/" +
                                cfg["bump_id"]
                ) as response:
                    if not response.status == 200:
                        print("DiscordMe bump request failed.")
                        return
                    output = "failed: Already bumped within the last 6 hours." \
                        if "you need to wait 6 hours between bumps!" in \
                           await response.text() else "successful."
                    print("DiscordMe server bump " + output)
            await asyncio.sleep(60 * 60 * 6 + 60)  # add 1m cuz its not perfect

    async def on_ready(self):
        self.log_channel = self.get_channel(
            self.config["moderation"]["log_channel"])
        self.staff_channel = self.get_channel(
            self.config["moderation"]["staff_channel"])
        self.default_server = self.log_channel.server
        await self.change_status(
            game=discord.Game(name=self.config["client"]["game"])
            if self.config["client"]["game"] else None)
        await self.load_voice_roles()
        coros = [self.load_punishment_timers()]
        if self.config["api-keys"]["discordme"]["login"]["username"]:
            coros.append(self.discordme_bump())
        await asyncio.gather(*coros)

    async def on_error(self, event_method, *args, **kwargs):
        await super().on_error(event_method, *args, **kwargs)
        for uid in self.controllers:
            await self.send_message(
                self.default_server.get_member(uid),
                "```{}```".format(traceback.format_exc()))

    async def load_punishment_timers(self):
        cursor = await self.mongodb.punishments.find().to_list(None)
        to_remove = {}
        timers = []
        for document in reversed(cursor):
            action = document["action"]
            if action == "ban" or action.startswith("removed"):
                continue
            member = self.default_server.get_member(document["user_id"])
            if not member:
                continue
            role = utils.action_to_role(self, action)
            if await utils.is_punished(self, member, action):
                print("Adding punishment timer for {}#{}".format(
                    member.name, member.discriminator))
                timers.append(self.add_punishment_timer(
                    member, action))
            elif role in member.roles:
                if member.id not in to_remove:
                    to_remove[member.id] = []
                to_remove[member.id].append(role)
        await asyncio.gather(*timers)
        for uid, roles in to_remove.items():
            member = self.default_server.get_member(uid)
            await asyncio.sleep(1)
            await self.remove_roles(member, *roles)
            print("Removed punishments for {}#{}: {}".format(
                member.name,
                member.discriminator,
                ", ".join([x.name for x in roles])))

    async def add_punishment_timer(self, member, action):
        role = utils.action_to_role(self, action)
        while True:
            punished = await utils.is_punished(self, member, action)
            if not punished:
                print("Removing punishment for {}#{}".format(
                    member.name, member.discriminator))
                await self.remove_roles(member, role)
                break
            await asyncio.sleep(
                self.config["moderation"]["punishment_check_rate"])

    async def on_member_join(self, member):
        if await utils.is_punished(self, member):
            await self.send_message(
                self.staff_channel,
                "Punished user {}#{} ({}) joined the server.".format(
                    member.name, member.discriminator, member.id))
            if await utils.is_punished(self, member, "ban"):
                await self.ban(member)
            else:
                to_add = []
                timers = []
                for action in ["warning", "mute"]:
                    if await utils.is_punished(self, member, action):
                        to_add.append(utils.action_to_role(self, action))
                        timers.append(self.add_punishment_timer(member, action))
                if to_add:
                    await asyncio.gather(self.add_roles(member, *to_add),
                                         *timers)

    async def on_member_leave(self, member):
        if await utils.is_punished(self, member):
            await self.send_message(
                self.staff_channel,
                "Punished user {}#{} ({}) left the server.".format(
                    member.name, member.discriminator, member.id))

    async def load_voice_roles(self):
        voice_role = discord.utils.get(self.default_server.roles, name="Voice")
        for member in [x for x in self.default_server.members
                       if x.voice_channel or voice_role in x.roles]:
            await asyncio.sleep(1)  # avoid rate limit
            await self._update_voice_roles(member, voice_role)
        cursor = await self.mongodb.always_show_vc.find().to_list(None)
        for doc in cursor:
            member = self.default_server.get_member(doc["user_id"])
            if not member:
                continue
            show_vc_role = discord.utils.get(
                self.default_server.roles, name="VC Shown")
            f = getattr(self, ("add" if doc["value"] else "remove") + "_roles")
            await asyncio.sleep(1)
            await f(member, show_vc_role)

    async def _update_voice_roles(self, member, *roles):
        in_voice = bool(member.voice_channel) and \
                   member.voice_channel != member.server.afk_channel
        f = getattr(self, ("add" if in_voice else "remove") + "_roles")
        await f(member, *roles)

    async def on_voice_state_update(self, before, after):
        if before.voice_channel != after.voice_channel:
            roles = [discord.utils.get(after.server.roles, name="Voice")]
            doc = await self.mongodb.always_show_vc.find_one(
                {"user_id": after.id})
            if not doc or not doc["value"]:
                roles.append(
                    discord.utils.get(after.server.roles, name="VC Shown"))
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
            self.commands_parsed += 1
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
