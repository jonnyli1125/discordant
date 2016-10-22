import re
import shlex
import sys
from datetime import datetime

import discord.game

import discordant.utils as utils
from discordant import Discordant


def _punishment_format(self, server, document):
    server = server if server else self.default_server
    if "user" not in document:
        user_id = document["user_id"]
        user = server.get_member(user_id)
        document["user"] = str(user) if user else user_id
    if "moderator" not in document:
        moderator = server.get_member(document["moderator_id"])
        document["moderator"] = str(moderator)
    document["date"] = document["date"].strftime("%Y/%m/%d %I:%M %p UTC")
    document["duration"] = "indefinite" \
        if not document["duration"] \
        else str(document["duration"]) + " hours"
    return ("**{action}**\n" +
            "*date*: {date}\n" +
            "*user*: {user}\n" +
            "*mod*: {moderator}\n" +
            "*duration*: {duration}\n" +
            "*reason*: {reason}").format(
        **document)


async def _punishment_history(self, member, cursor):
    output = ""
    current = []
    if await utils._is_punished(cursor, "warning"):
        current.append("**warning**")
    if await utils._is_punished(cursor, "mute"):
        current.append("**mute**")
    if current:
        output += "currently active punishments: " + ", ".join(current) + "\n"
    output += "\n".join(
        [_punishment_format(self, member.server, x) for x in cursor])
    return output


def _can_kick(self, user):
    return utils.has_permission(user, "kick_members")


def _can_ban(self, user):
    return utils.has_permission(user, "ban_members")


@Discordant.register_command("modhistory", ["modh"], context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _moderation_history(self, args, message, context):
    """!modhistory <user>
    displays punishment history for a user."""
    user = utils.get_user(args, context.server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    collection = self.mongodb.punishments
    cursor = await collection.find({"user_id": user.id}).to_list(None)
    await self.send_message(
        message.channel,
        await _punishment_history(self, user, cursor)
        if cursor else user.name + " has no punishment history.")


_mod_cmd_to_action = {"warn": "warning",
                      "mute": "mute",
                      "ban": "ban",
                      "unwarn": "remove warning",
                      "unmute": "remove mute"}


async def _mod_cmd(self, args, message, context):
    keys = ["duration", "reason"]
    kwargs = utils.get_kwargs(args, keys)
    split = shlex.split(args)
    if not kwargs and len(split) > 1:
        # has more than one pos arg, no kwargs
        args = split[0] + ' reason="' + " ".join(split[1:]) + '"'
        kwargs = utils.get_kwargs(args, keys)
    user_search = utils.strip_kwargs(args, keys)
    user = utils.get_user(user_search, context.server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    if not utils.gt_role(self, context.author, user, True):
        await self.send_message(
            message.channel, "Cannot {} {}".format(context.cmd_name, user.name))
        return
    duration = utils.get_from_kwargs(
        "duration", kwargs,
        self.config["moderation"][context.cmd_name + "_duration"])
    try:
        duration = float(duration)
    except ValueError:
        await self.send_message(message.channel, "Invalid duration.")
        return
    reason = utils.get_from_kwargs("reason", kwargs, "No reason given.")
    action = _mod_cmd_to_action[context.cmd_name]
    role = utils.action_to_role(self, action)
    collection = self.mongodb.punishments
    if await utils.is_punished(self, user, action):
        await self.send_message(
            message.channel,
            user.name + " already has an active " + action + ".")
        return
    else:
        cursor = await collection.find({"user_id": user.id}).to_list(None)
        if cursor:
            await self.send_message(
                message.channel,
                user.name + " has a history of:\n" + await _punishment_history(
                    self, user, cursor) + "\n\nType y/n to continue.")
            reply = await self.wait_for_message(
                check=lambda m: m.author == message.author and
                                (m.content.lower() == "y" or
                                 m.content.lower() == "n"),
                timeout=60)
            if not reply or reply.content.lower() == "n":
                await self.send_message(
                    message.channel, "Cancelled " + action + ".")
                return
    document = {
        "user_id": user.id,
        "action": action,
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": duration,
        "reason": reason
    }
    await collection.insert(document)
    await self.add_roles(user, role)
    await self.send_message(
        self.log_channel,
        _punishment_format(self, message.server, document))
    await utils.add_punishment_timer(self, user, action)


@Discordant.register_command("warn", context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _warn(self, args, message, context):
    """!warn <user> [reason] or !warn <user> [duration=hours] [reason=str]
    warns a user."""
    await _mod_cmd(self, args, message, context)


@Discordant.register_command("mute", context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _mute(self, args, message, context):
    """!mute <user> [reason] or !mute <user> [duration=hours] [reason=str]
    mutes a user."""
    await _mod_cmd(self, args, message, context)


async def _mod_remove_cmd(self, args, message, context):
    split = shlex.split(args)
    user_search = split[0]
    reason = " ".join(split[1:]) if len(split) > 1 else "No reason given."
    user = utils.get_user(user_search, context.server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    if not utils.gt_role(self, context.author, user, True):
        await self.send_message(
            message.channel, "Cannot {} {}".format(context.cmd_name, user.name))
        return
    collection = self.mongodb.punishments
    action = _mod_cmd_to_action[context.cmd_name]
    orig_action = action.replace("remove ", "")
    role = utils.action_to_role(self, orig_action)
    if not await utils.is_punished(self, user, orig_action):
        await self.send_message(
            message.channel, user.name + " has no active " + orig_action + ".")
        return
    document = {
        "user_id": user.id,
        "action": action,
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": 0,
        "reason": reason
    }
    await collection.insert(document)
    await self.remove_roles(user, role)
    await self.send_message(
        self.log_channel,
        _punishment_format(self, message.server, document))


@Discordant.register_command("unwarn", context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _unwarn(self, args, message, context):
    """!unwarn <user> [reason]
    removes a warning for a user."""
    await _mod_remove_cmd(self, args, message, context)


@Discordant.register_command("unmute", context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _unmute(self, args, message, context):
    """!unmute <user> [reason]
    removes a mute for a user."""
    await _mod_remove_cmd(self, args, message, context)


@Discordant.register_command("ban", context=True,
                             arg_func=utils.has_args, perm_func=_can_ban)
async def _ban(self, args, message, context):
    """!ban <user/user id> [reason]
    bans a user."""
    split = shlex.split(args)
    user_search = split[0]
    reason = " ".join(split[1:]) if len(split) > 1 else "No reason given."
    user = utils.get_user(user_search, context.server.members, message, True)
    if not user:
        await self.send_message(
            message.channel,
            "User could not be found. "
            "Please use an @ mention string or name#id.\n"
            "Search logs? Type y/n.")
        reply = await self.wait_for_message(
            check=lambda m: m.author == message.author and (
                m.content.lower() == "y" or m.content.lower() == "n"),
            timeout=60)
        if not reply:  # if no reply, cancel silently to avoid confusion
            return
        if reply.content.lower() == "n":
            await self.send_message(message.channel, "Cancelled ban.")
            return
        authors = set()
        for channel in context.server.channels:
            if channel in [self.staff_channel, self.testing_channel,
                           self.log_channel] or \
                            channel.type != discord.ChannelType.text:
                continue
            async for msg in self.logs_from(channel, limit=500):
                authors.add(msg.author)
        user = utils.get_user(user_search, authors)
        if not user:
            await self.send_message(
                message.channel, "User could not be found.")
            return
    elif not utils.gt_role(self, context.author, user, True):
        await self.send_message(message.channel, "Cannot ban " + user.name)
        return
    collection = self.mongodb.punishments
    doc = await collection.find_one({"user_id": user.id, "action": "ban"})
    if doc or user in await self.get_bans(context.server):
        await self.send_message(
            message.channel, user.name + " is already banned.")
        return
    document = {
        "user_id": user.id,
        "action": "ban",
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": 0,
        "reason": reason
    }
    await collection.insert(document)
    await self.send_message(
        self.log_channel,
        _punishment_format(self, message.server, document))
    await self.ban(user)


#@Discordant.register_command("unban", context=True,
#                             arg_func=utils.has_args, perm_func=_can_ban)
async def _unban(self, args, message, context):
    """!unban <user>
    unbans a user."""
    pass


@Discordant.register_command("bans", context=True, perm_func=_can_ban)
async def _bans(self, args, message, context):
    """!bans [page]
    lists the bans in this server."""
    page_length = 10
    bans = await self.get_bans(context.server)
    len_bans = len(bans)
    pages = -(-len_bans // page_length)  # ceil division
    page = int(args) - 1 if args.isdigit() else pages - 1
    if page >= pages or page < 0:
        await self.send_message(
            message.channel, "There are only {} pages available.".format(pages))
        return
    start = page * page_length
    end = (page + 1) * page_length
    await self.send_message(
        message.channel,
        utils.python_format(
            "\n".join(["{0}. {1} ({1.id})".format(start + index + 1, user)
                       for index, user in enumerate(bans[start:end])]) +
            "\npage {} out of {}".format(page + 1, pages)))


@Discordant.register_command("reason", context=True,
                             arg_func=utils.has_args, perm_func=_can_kick)
async def _reason(self, args, message, context):
    """!reason <user> <reason>
    edits the reason of the given user's most recent punishment."""
    split = shlex.split(args)
    if len(split) < 2:
        await self.send_message(message.channel, context.cmd.help)
        return
    user_search = split[0]
    reason = " ".join(split[1:])
    user = utils.get_user(user_search, context.server.members, message) or \
        utils.get_user(user_search, await self.get_bans(context.server))
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    collection = self.mongodb.punishments
    query = {"user_id": user.id}
    cursor = await collection.find(query).sort(
        "$natural", -1).limit(1).to_list(None)
    if not cursor:
        await self.send_message(
            message.channel, user.name + " has no punishment history.")
        return
    doc = cursor[0]
    moderator = context.server.get_member(doc["moderator_id"])
    if utils.gt_role(self, moderator, context.author):
        await self.send_message(
            message.channel,
            "Cannot edit punishment issued by moderator of higher role.")
        return
    doc["reason"] = reason
    await collection.save(doc)
    async for msg in self.logs_from(self.log_channel, limit=sys.maxsize):
        if "\n*user*: {}\n".format(user) in msg.content:
            await self.edit_message(
                msg, re.sub(r"(\*reason\*: ).*", "\g<1>" + reason, msg.content))
            return
