import os
import os.path
import time

import aiohttp
import discord.game
import psutil

import discordant.utils as utils
from discordant import Discordant


@Discordant.register_command("client")
async def _client_settings(self, args, message):
    if message.author.id not in self.controllers:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(message.channel, "!client [*field*=value]")
    kwargs = utils.get_kwargs(args)
    if "game" in kwargs:
        game = discord.Game(name=kwargs["game"]) if kwargs["game"] else None
        await self.change_status(game=game)
        del kwargs["game"]
    if "avatar" in kwargs:
        if utils.is_url(kwargs["avatar"]):
            try:
                with aiohttp.ClientSession() as session:
                    async with session.get(kwargs["avatar"]) as response:
                        kwargs["avatar"] = await response.read()
            except Exception as e:
                await self.send_message(message.channel,
                                        "Request failed: " + str(e))
                return
        elif os.path.isfile(kwargs["avatar"]):
            kwargs["avatar"] = open(kwargs["avatar"], "rb").read()
        else:
            await self.send_message(message.channel,
                                    "Invalid avatar url or path.")
            return
    await self.edit_profile(self._password, **kwargs)
    await self.send_message(message.channel, "Settings updated.")


@Discordant.register_command("say")
async def _say(self, args, message):
    if message.author.id not in self.controllers:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    split = args.split(" ")
    if len(split) <= 1:
        await self.send_message(message.channel, "!say <channel> <message>")
        return
    channel_mention = split[0]
    channel = None
    for c in message.channel_mentions:
        if c.mention == channel_mention:
            channel = c
    if not channel:
        await self.send_message(message.channel, "Channel not found.")
        return
    await self.send_message(channel, args[len(channel_mention) + 1:])


@Discordant.register_command("edit")
async def _edit(self, args, message):
    if message.author.id not in self.controllers:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    split = args.split(" ")
    if len(split) <= 2:
        await self.send_message(message.channel,
                                "!edit <channel> <message id> <message>")
        return
    channel_mention = split[0]
    channel = None
    for c in message.channel_mentions:
        if c.mention == channel_mention:
            channel = c
    if not channel:
        await self.send_message(message.channel, "Channel not found.")
        return
    msg_id = split[1]
    msg = await self.get_message(channel, msg_id)
    if not msg:
        await self.send_message(message.channel, "Message not found.")
        return
    await self.edit_message(msg, args[len(msg_id) + len(channel_mention) + 2:])


@Discordant.register_command("info")
async def _stats(self, args, message):
    process = psutil.Process(os.getpid())
    uptime = time.time() - process.create_time()
    m, s = divmod(uptime, 60)
    h, m = divmod(m, 60)
    await self.send_message(
        message.channel,
        ("uptime: {} hours, {} minutes, {} seconds" +
         "\ncommands parsed: {}" +
         "\nmemory usage: {} MiB").format(
            int(h), int(m), int(s),
            self.commands_parsed,
            process.memory_info().rss / float(2 ** 20)))


@Discordant.register_command("userinfo")
async def _userinfo(self, args, message):
    if not args:
        await self.send_message(message.channel, "!userinfo <user>")
        return
    server = message.server if message.server else self.default_server
    user = utils.get_user(args, server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    await self.send_message(
        message.channel,
        ("**name**: {0.name}#{0.discriminator}\n" +
         "**id**: {0.id}\n" +
         "**account created**: {0.created_at}\n" +
         "**joined server**: {0.joined_at}\n" +
         "**avatar**: {0.avatar_url}").format(user))
