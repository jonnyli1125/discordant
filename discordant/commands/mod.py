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
            "*moderator*: {moderator}\n" +
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


@Discordant.register_command("modhistory", ["modh"])
async def _moderation_history(self, args, message):
    """!modhistory <user>
    displays punishment history for a user."""
    if not args:
        await utils.send_help(self, message, "modhistory")
        return
    server = message.server or self.default_server
    user = utils.get_user(args, server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    collection = self.mongodb.punishments
    cursor = await collection.find({"user_id": user.id}).to_list(None)
    await self.send_message(
        message.channel,
        await _punishment_history(self, user, cursor)
        if cursor else user.name + " has no punishment history.")


async def _mod_cmd(self, args, message, cmd, action):
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).kick_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await utils.send_help(self, message, cmd)
        return
    keys = ["duration", "reason"]
    kwargs = utils.get_kwargs(args, keys)
    split = shlex.split(args)
    if not kwargs and len(split) > 1:
        # has more than one pos arg, no kwargs
        args = split[0] + ' reason="' + " ".join(split[1:]) + '"'
        kwargs = utils.get_kwargs(args, keys)
    user_search = utils.strip_kwargs(args, keys)
    user = utils.get_user(user_search, server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    if not utils.gt_role(self, member, user, True):
        await self.send_message(message.channel,
                                "Cannot {} {}".format(cmd, user.name))
        return
    duration = utils.get_from_kwargs(
        "duration", kwargs, self.config["moderation"][cmd + "_duration"])
    try:
        duration = float(duration)
    except ValueError:
        await self.send_message(message.channel, "Invalid duration.")
        return
    reason = utils.get_from_kwargs("reason", kwargs, "No reason given.")
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


@Discordant.register_command("warn")
async def _warn(self, args, message):
    """!warn <user> [reason] or !warn <user> [duration=hours] [reason=str]
    warns a user."""
    await _mod_cmd(self, args, message, "warn", "warning")


@Discordant.register_command("mute")
async def _mute(self, args, message):
    """!mute <user> [reason] or !mute <user> [duration=hours] [reason=str]
    mutes a user."""
    await _mod_cmd(self, args, message, "mute", "mute")


async def _mod_remove_cmd(self, args, message, cmd, action):
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).kick_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await utils.send_help(self, message, cmd)
        return
    split = shlex.split(args)
    user_search = split[0]
    reason = " ".join(split[1:]) if len(split) > 1 else "No reason given."
    user = utils.get_user(user_search, server.members, message)
    if not user:
        await self.send_message(message.channel, "User could not be found.")
        return
    if not utils.gt_role(self, member, user, True):
        await self.send_message(message.channel,
                                "Cannot {} {}".format(cmd, user.name))
        return
    collection = self.mongodb.punishments
    orig_action = action.replace("remove ", "")
    role = utils.action_to_role(self, orig_action)
    if not await utils.is_punished(self, user, orig_action):
        await self.send_message(
            message.channel, user.name + " has no active " + action + ".")
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


@Discordant.register_command("unwarn")
async def _unwarn(self, args, message):
    """!unwarn <user> [reason]
    removes a warning for a user."""
    await _mod_remove_cmd(self, args, message, "unwarn", "remove warning")


@Discordant.register_command("unmute")
async def _unmute(self, args, message):
    """!unmute <user> [reason]
    removes a mute for a user."""
    await _mod_remove_cmd(self, args, message, "unmute", "remove mute")


@Discordant.register_command("ban")
async def _ban(self, args, message):
    """!ban <user/user id> [reason]
    bans a user."""
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).ban_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await utils.send_help(self, message, "ban")
        return
    split = shlex.split(args)
    user_search = split[0]
    reason = " ".join(split[1:]) if len(split) > 1 else "No reason given."
    user = utils.get_user(user_search, server.members, message)
    if not user:
        await self.send_message(
            message.channel,
            "User could not be found.\nIf this is a user ID, type y/n.")
        reply = await self.wait_for_message(
            check=lambda m: m.author == message.author and
                            (m.content.lower() == "y" or
                             m.content.lower() == "n"),
            timeout=60)
        if not reply or reply.content.lower() == "n":
            await self.send_message(message.channel, "Cancelled ban.")
            return
        else:
            user = discord.Member(
                id=user_search,
                name=user_search,
                discriminator="",
                server=server)
    else:
        if not utils.gt_role(self, member, user, True):
            await self.send_message(message.channel,
                                    "Cannot ban " + user.name)
            return
    collection = self.mongodb.punishments
    doc = await collection.find_one({"user_id": user.id, "action": "ban"})
    if doc or user in await self.get_bans(server):
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


#@Discordant.register_command("unban")
async def _unban(self, args, message):
    """!unban <user>
    unbans a user."""
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).ban_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await utils.send_help(self, message, "unban")
        return


@Discordant.register_command("bans")
async def _bans(self, args, message):
    """!bans
    lists the bans in this server."""
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).ban_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    bans = await self.get_bans(server)
    await self.send_message(
        message.channel,
        utils.python_format(
            "\n".join(["{0}. {1} ({1.id})".format(index + 1, user)
                       for index, user in enumerate(bans)])))


@Discordant.register_command("reason")
async def _reason(self, args, message):
    """!reason <user> <reason>
    edits the reason of the given user's most recent punishment."""
    server = message.server or self.default_server
    member = server.get_member(message.author.id)
    if not server.default_channel.permissions_for(member).kick_members:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    split = shlex.split(args)
    if len(split) < 2:
        await utils.send_help(self, message, "reason")
        return
    user_search = split[0]
    reason = " ".join(split[1:])
    user = utils.get_user(user_search, server.members, message) or \
        utils.get_user(user_search, await self.get_bans(server))
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
    moderator = server.get_member(doc["moderator_id"])
    if utils.gt_role(self, moderator, member):
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
