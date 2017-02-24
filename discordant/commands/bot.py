import inspect
import os
import os.path
import time

import aiohttp
import discord.game
import psutil

import discordant.utils as utils
from discordant import Discordant


@Discordant.register_command("client", ["settings"],
                             perm_func=utils.is_controller,
                             arg_func=utils.has_args)
async def _client_settings(self, args, message):
    """!client [\*\*key=value]
    updates the bot's discord client settings."""
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


@Discordant.register_command("say", context=True, perm_func=utils.is_controller,
                             arg_func=lambda a: utils.len_split(a, 2, None, 1))
async def _say(self, args_split, message, context):
    """!say <channel> <message>
    sends a message to a channel through the bot."""
    channel = utils.get_channel(
        args_split[0], context.server.channels, message) or utils.get_user(
        args_split[0], context.server.members, message)
    if not channel:
        await self.send_message(message.channel, "Channel or user not found.")
        return
    await self.send_message(channel, args_split[1])


@Discordant.register_command("edit", context=True,
                             perm_func=utils.is_controller,
                             arg_func=lambda a: utils.len_split(a, 3, None, 2))
async def _edit(self, args_split, message, context):
    """!edit <channel> <message id> <message>
    edits a message with that id in the given channel to a new message."""
    if not utils.is_controller(self, message.author):
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    channel = utils.get_channel(args_split[0], context.server.channels, message)
    if not channel:
        user = utils.get_user(args_split[0], context.server.members, message)
        if not user:
            await self.send_message(
                message.channel, "Channel or user not found.")
            return
        channel = discord.utils.get(self.private_channels, user=user)
        if not channel:
            await self.send_message(
                message.channel, "No private messages with " + user.name + ".")
            return
    msg = await self.get_message(channel, args_split[1])
    if not msg:
        await self.send_message(message.channel, "Message not found.")
        return
    await self.edit_message(msg, args_split[2])


@Discordant.register_command("uptime")
async def _stats(self, args, message):
    """!uptime
    displays bot process uptime."""
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


@Discordant.register_command("userinfo", ["uinfo", "u", "ui"], context=True,
                             arg_func=utils.has_args)
async def _userinfo(self, args, message, context):
    """!userinfo <user>
    displays discord user info for a user."""
    user = utils.get_user(args, context.server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    await self.send_message(
        message.channel,
        ("**name**: {0}\n" +
         "**id**: {0.id}\n" +
         "**account created**: {0.created_at} UTC\n" +
         "**joined server**: {0.joined_at} UTC\n" +
         "**avatar**: {1}").format(user, utils.get_avatar_url(user)))


@Discordant.register_command("eval", context=True,
                             perm_func=utils.is_controller,
                             arg_func=utils.has_args)
async def _eval(self, args, message, context):
    """!eval <expression>
    evaluates a python expression in the discordant command context."""
    # taken from Rapptz/RoboDanny's eval command, edited for Discordant
    try:
        result = eval(args)
        if inspect.isawaitable(result):
            result = await result
    except Exception as e:
        await self.send_message(
            message.channel,
            utils.python_format(type(e).__name__ + ": " + str(e)))
        return
    await self.send_message(message.channel, utils.python_format(result))


@Discordant.register_command("usercmd", ["ucmd"], context=True,
                             perm_func=utils.is_controller,
                             arg_func=lambda a: utils.len_split(a, 2, None, 1))
async def _usercmd(self, args_split, message, context):
    """!usercmd <user> <command>
    executes a command as another user."""
    user = utils.get_user(args_split[0], context.server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    message.author = user
    message.content = "!" + args_split[1]
    await self.run_command(message)
