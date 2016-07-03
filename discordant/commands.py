import asyncio
import os
import os.path
import re
import shlex
import time
import urllib.parse
from datetime import datetime

import aiohttp
import discord.game
import psutil
import pytz
from lxml import html
from pytz import timezone

import discordant.utils as utils
from .discordant import Discordant


#region general
@Discordant.register_command("help")
async def _help(self, args, message):
    section = args
    default = "general"
    if not section:
        section = default
    cmds = [cmd.aliases[0] for cmd in self._commands.values()
            if cmd.section == section]
    output = ""
    if cmds:
        output += "Commands: " + ", ".join(cmds) + "\n"
    if not args or not cmds:
        sections = list({cmd.section + (" *(default)*"
                        if cmd.section == default else "")
                        for cmd in self._commands.values()})
        output += "!help [section]\nSections: " + ", ".join(sections)
    await self.send_message(message.channel, output.strip())


@Discordant.register_command("timezone")
async def _convert_timezone(self, args, message):
    def get_timezone_by_code(code):
        code = code.upper()
        for tz_str in pytz.all_timezones:
            tz = timezone(tz_str)
            if tz.tzname(datetime.now()) == code:
                return tz
        raise ValueError(code + ": not a valid time zone code")

    def read_time(dt_str):
        formats = ["%I%p", "%I:%M%p", "%H", "%H:%M"]
        for f in formats:
            try:
                read_dt = datetime.strptime(dt_str, f)
                return datetime.now().replace(hour=read_dt.hour,
                                              minute=read_dt.minute)
            except ValueError:
                pass
        raise ValueError(dt_str + ": not a valid time format")

    def relative_date_str(dt_1, dt_2):
        delta = (dt_2 - dt_1).days
        if delta == 0:
            return "same day"
        else:
            return "{} day{} {}".format(abs(delta),
                                        "s" if abs(delta) != 1 else "",
                                        "ahead" if delta > 0 else "behind")

    split = args.split()
    if len(split) != 3 and len(split) != 1:
        await self.send_message(
            message.channel,
            "!timezone <time> <from> <to>\n!timezone <timezone>")
        return
    try:
        if len(split) == 1:
            dt = pytz.utc.localize(datetime.utcnow())
            new_dt = dt.astimezone(get_timezone_by_code(args))
            await self.send_message(
                message.channel,
                "It is currently " + new_dt.strftime("%I:%M %p %Z") + ".")
        else:
            dt = get_timezone_by_code(split[1]).localize(read_time(split[0]))
            new_dt = dt.astimezone(get_timezone_by_code(split[2]))
            await self.send_message(message.channel, "{} is {}, {}".format(
                dt.strftime("%I:%M %p %Z"),
                new_dt.strftime("%I:%M %p %Z"),
                relative_date_str(dt, new_dt))
                                )
    except ValueError as e:
        await self.send_message(message.channel, str(e))


async def _dict_search_args_parse(self, args, message, cmd):
    if not args:
        await self.send_message(message.channel, "!" + cmd + " [limit] <query>")
        return
    limit = 1
    query = args
    result = re.match(r"^([0-9]+)\s+(.*)$", args)
    if result:
        limit, query = [result.group(x) for x in (1, 2)]
    return int(limit), query
    # keys = ["limit"]
    # kwargs = utils.get_kwargs(args, keys)
    # try:
    #     limit = int(kwargs["limit"])
    #     if limit <= 0:
    #         raise ValueError
    # except (ValueError, KeyError):
    #     limit = 1
    # query = utils.strip_kwargs(args, keys)


@Discordant.register_command("jisho")
async def _jisho_search(self, args, message):
    search_args = await _dict_search_args_parse(self, args, message, "jisho")
    if not search_args:
        return
    limit, query = search_args
    url = "http://jisho.org/api/v1/search/words?keyword=" + \
          urllib.parse.quote(query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    results = data["data"][:limit]
    if not results:
        sent = await self.send_message(message.channel, "No results found.")
        if message.server:
            await _delete_after(self, 5, message, sent)
        return
    output = ""

    def display_word(obj, *formats):
        f = formats[len(obj) - 1]
        return f.format(*obj.values()) if len(obj) == 1 else f.format(**obj)

    for result in results:
        japanese = result["japanese"]
        output += display_word(japanese[0], "**{}**",
                               "**{word}** {reading}") + "\n"
        new_line = ""
        if "is_common" in result and result["is_common"]:
            new_line += "Common word. "
        if result["tags"]:  # it doesn't show jlpt tags, only wk tags?
            new_line += "Wanikani level " + ", ".join(
                [tag[8:] for tag in result["tags"]]) + ". "
        if new_line:
            output += new_line + "\n"
        senses = result["senses"]
        for index, sense in enumerate(senses):
            # jisho returns null sometimes for some parts of speech... k den
            parts = [x for x in sense["parts_of_speech"] if x is not None]
            if parts == ["Wikipedia definition"] and len(senses) > 1:
                continue
            if parts:
                output += "*" + ", ".join(parts) + "*\n"
            output += str(index + 1) + ". " + "; ".join(
                sense["english_definitions"])
            for attr in ["tags", "info"]:
                if sense[attr]:
                    output += ". *" + "*. *".join(sense[attr]) + "*"
            if sense["see_also"]:
                output += ". *See also*: " + ", ".join(sense["see_also"])
            output += "\n"
            output += "\n".join(
                ["{text}: {url}".format(**x) for x in sense["links"]])
        if len(japanese) > 1:
            output += "Other forms: " + ", ".join(
                [display_word(x, "{}", "{word} ({reading})") for x in
                 japanese[1:]]) + "\n"
        # output += "\n"
    await utils.send_long_message(
        self, message.channel, output, message.server is not None)


@Discordant.register_command("alc")
async def _alc_search(self, args, message):
    search_args = await _dict_search_args_parse(self, args, message, "alc")
    if not search_args:
        return
    limit, query = search_args
    url = "http://eow.alc.co.jp/search?q=" + \
          urllib.parse.quote(re.sub(r"\s+", "+", query), encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    output = ""
    tree = html.fromstring(data)
    results = tree.xpath('//div[@id="resultsList"]/ul/li')[:limit]
    if not results:
        sent = await self.send_message(message.channel, "No results found.")
        if message.server:
            await _delete_after(self, 5, message, sent)
        return
    for result in results:
        words = [x for x in result.xpath('./span') if
                 x.attrib["class"].startswith("midashi")][0]
        highlight = " ".join(words.xpath('./span[@class="redtext"]/text()'))
        output += re.sub("(" + highlight + ")", r"**\1**",
                         words.text_content()) + "\n"
        div = result.xpath('./div')[0]
        if div.xpath('./text()') or div.xpath('./span[@class="refvocab"]'):
            output += div.text_content()
        else:
            for br in div.xpath("*//br"):
                br.tail = "\n" + br.tail if br.tail else "\n"
            for element in div.xpath('./*'):
                if element.tag == "span":
                    if element.attrib["class"] == "wordclass":
                        output += element.text[1:-1] + "\n"
                    elif element.attrib["class"] == "attr":
                        # alc pls lmao.
                        output += element.text_content().strip().replace(
                            "＠", "カナ") + "\n"
                elif element.tag == "ol" or element.tag == "ul":
                    lis = element.xpath('./li')
                    if lis:
                        for index, li in enumerate(lis):
                            output += "{}. {}\n".format(
                                index + 1, li.text_content().strip())
                    else:
                        output += "1. " + element.text_content().strip() + "\n"
                # output += "\n"
        # cheap ass fuckers dont actually give 文例's
        # also removes kana things
        output = re.sub(r"(｛[^｝]*｝)|(【文例】)", "", output.strip()) + "\n"
    await utils.send_long_message(
        self, message.channel, output, message.server is not None)


async def _dict_search_link(self, match, message, cmd, group):
    await getattr(self, self._commands[self._aliases[cmd]].name)(
        urllib.parse.unquote(match.group(group), encoding="utf-8"), message)


@Discordant.register_handler(
    r"https?:\/\/(www\.)?jisho\.org\/(search|word)\/(\S*)")
async def _jisho_link(self, match, message):
    await _dict_search_link(self, match, message, "jisho", 3)


@Discordant.register_handler(
    r"https?:\/\/eow\.alc\.co\.jp\/search\?q=([^\s&]*)")
async def _alc_link(self, match, message):
    await _dict_search_link(self, match, message, "alc", 1)
#endregion


#region bot
@Discordant.register_command("client", section="bot")
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


async def _delete_after(self, time, *args):
    await asyncio.sleep(time)
    for msg in args:
        await self.delete_message(msg)


@Discordant.register_command("showvc", section="bot")
async def _show_voice_channels_toggle(self, args, message):
    query = {"user_id": message.author.id}
    collection = self.mongodb.always_show_vc
    cursor = await collection.find(query).to_list(None)
    if not cursor:
        show = True
        await collection.insert({"user_id": message.author.id, "value": show})
    else:
        show = not cursor[0]["value"]
        await collection.update(query, {"$set": {"value": show}})
    role = discord.utils.get(self.default_server.roles, name="VC Shown")

    member = message.author if message.server \
        else self.default_server.get_member(message.author.id)
    if show:
        await self.add_roles(member, role)
        msg = await self.send_message(
            message.channel,
            "Now always showing voice channels for " + message.author.name +
            ". Type this command again to toggle.")
    else:
        if not member.voice_channel:
            await self.remove_roles(member, role)
        msg = await self.send_message(
            message.channel,
            "Now hiding voice channels for " + message.author.name +
            ". Type this command again to toggle.")
    if message.server:
        await _delete_after(self, 5, message, msg)


@Discordant.register_command("say", section="bot")
async def _say(self, args, message):
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


@Discordant.register_command("edit", section="bot")
async def _say(self, args, message):
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


@Discordant.register_command("stats", section="bot")
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

#endregion


#region moderation
def _punishment_format(self, server, document):
    server = server if server else self.default_server
    if "user" not in document:
        user_id = document["user_id"]
        user = server.get_member(user_id)
        document["user"] = user.name + "#" + user.discriminator \
            if user else user_id
    if "moderator" not in document:
        moderator = server.get_member(document["moderator_id"])
        document["moderator"] = moderator.name + "#" + moderator.discriminator
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
    if await utils.is_punished(self, member, "warning"):
        current.append("**warning**")
    if await utils.is_punished(self, member, "mute"):
        current.append("**mute**")
    if current:
        output += "currently active punishments: " + ", ".join(current) + "\n"
    output += "\n".join(
        [_punishment_format(self, member.server, x) for x in cursor])
    return output


@Discordant.register_command("modhistory", section="mod")
async def _moderation_history(self, args, message):
    if not args:
        await self.send_message(message.channel, "!modhistory <user>")
        return
    server = message.server if message.server else self.default_server
    user = utils.get_user(args, server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    collection = self.mongodb.punishments
    cursor = await collection.find({"user_id": user.id}).to_list(None)
    await self.send_message(
        message.channel,
        await _punishment_history(self, user, cursor)
        if cursor else user.name + " has no punishment history.")


async def _mod_cmd(self, args, message, cmd, action, role_name):
    server = message.server if message.server else self.default_server
    member = server.get_member(message.author.id)
    if not utils.has_permission(member, "manage_roles"):
        await self.send_message(member,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(
            message.channel,
            ("!" + cmd + " <user> [reason]" +
             " or !" + cmd + " <user> [duration=hours] [reason=str]"))
        return
    keys = ["duration", "reason"]
    kwargs = utils.get_kwargs(args, keys)
    split = shlex.split(args)
    if not kwargs and len(split) > 1:
        # has more than one pos arg, no kwargs
        args = split[0] + ' reason="' + " ".join(split[1:]) + '"'
        kwargs = utils.get_kwargs(args, keys)
    user_search = utils.strip_kwargs(args, keys)
    user = utils.get_user(user_search, server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    if utils.has_permission(user, "manage_roles"):
        await self.send_message(message.channel,
                                "Cannot " + cmd + " another moderator.")
        return
    duration = utils.get_from_kwargs(
        "duration", kwargs, self.config["moderation"][cmd + "_duration"])
    try:
        duration = float(duration)
    except ValueError:
        await self.send_message(message.channel, "Invalid duration.")
        return
    reason = utils.get_from_kwargs("reason", kwargs, "No reason given.")
    role = discord.utils.get(server.roles, name=role_name)
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
            if reply is None or reply.content.lower() == "n":
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
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(self, message.server, document))
    await self.add_punishment_timer(user, action, role)


@Discordant.register_command("warn", section="mod")
async def _warn(self, args, message):
    await _mod_cmd(self, args, message, "warn", "warning", "Warned")


@Discordant.register_command("mute", section="mod")
async def _mute(self, args, message):
    await _mod_cmd(self, args, message, "mute", "mute", "Muted")


async def _mod_remove_cmd(self, args, message, cmd, action, role_name):
    server = message.server if message.server else self.default_server
    member = server.get_member(message.author.id)
    if not utils.has_permission(member, "manage_roles"):
        await self.send_message(member,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(message.channel, "!" + cmd + " <user> [reason]")
        return
    user_search = args.split()[0]
    reason = args[len(user_search) + 1:] if " " in args else "No reason given."
    user = utils.get_user(user_search, server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    role = discord.utils.get(server.roles, name=role_name)
    collection = self.mongodb.punishments
    orig_action = action.replace("remove ", "")
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
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(self, message.server, document))


@Discordant.register_command("unwarn", section="mod")
async def _unwarn(self, args, message):
    await _mod_remove_cmd(
        self, args, message, "unwarn", "remove warning", "Warned")


@Discordant.register_command("unmute", section="mod")
async def _unmute(self, args, message):
    await _mod_remove_cmd(
        self, args, message, "unmute", "remove mute", "Muted")


@Discordant.register_command("ban", section="mod")
async def _ban(self, args, message):
    server = message.server if message.server else self.default_server
    member = server.get_member(message.author.id)
    if not utils.has_permission(member, "ban_members"):
        await self.send_message(member,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(message.channel, "!ban <user> [reason]")
        return
    user_search = args.split()[0]
    reason = args[len(user_search) + 1:] if " " in args else "No reason given."
    user = utils.get_user(user_search, server.members)
    if user is None:
        await self.send_message(
            message.channel,
            "User could not be found.\nIf this is a user ID, type y/n.")
        reply = await self.wait_for_message(
            check=lambda m: m.author == message.author and
                            (m.content.lower() == "y" or
                             m.content.lower() == "n"),
            timeout=60)
        if reply is None or reply.content.lower() == "n":
            await self.send_message(message.channel, "Cancelled ban.")
            return
        else:
            user_id = user_search
    else:
        if utils.has_permission(user, "ban_members"):
            await self.send_message(message.channel,
                                    "Cannot ban another moderator.")
            return
        user_id = user.id
    collection = self.mongodb.punishments
    doc = await collection.find_one({"user_id": user_id, "action": "ban"})
    if doc:
        await self.send_message(
            message.channel, user.name + " is already banned.")
        return
    document = {
        "user_id": user_id,
        "action": "ban",
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": 0,
        "reason": reason
    }
    await collection.insert(document)
    await self.send_message(
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(self, message.server, document))
    await self.ban(user)  # run after the output or else user data is lost
#endregion
