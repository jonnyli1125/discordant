import asyncio
import os.path
import re
import urllib.parse
from datetime import datetime

import discord.game
import pytz
import requests
from lxml import html
from pytz import timezone

import discordant.utils as utils
from .discordant import Discordant


#region other
# @Discordant.register_handler(r'\bayy+$', re.I)
async def _ayy_lmao(self, match, message):
    await self.send_message(message.channel, 'lmao')


# @Discordant.register_command('youtube')
async def _youtube_search(self, args, message):
    base_req_url = 'https://www.googleapis.com/youtube/v3/search'
    req_args = {
        'key': self.config['api-keys']['youtube'],
        'part': 'snippet',
        'type': 'video',
        'maxResults': 1,
        'q': args
    }

    res = requests.get(base_req_url, req_args)
    if not res.ok:
        await self.send_message(message.channel, 'Error:',
                                res.status_code, '-', res.reason)
        return

    json = res.json()
    if json['pageInfo']['totalResults'] == 0:
        await self.send_message(message.channel, 'No results found.')
    else:
        await self.send_message(message.channel, 'https://youtu.be/' +
                                json['items'][0]['id']['videoId'])


# @Discordant.register_command('urban')
async def _urban_dictionary_search(self, args, message):
    # this entire function is an egregious violation of the DRY
    # principle, so TODO: abstract out the request part of these functions
    base_req_url = 'http://api.urbandictionary.com/v0/define'

    res = requests.get(base_req_url, {'term': args})
    if not res.ok:
        await self.send_message(message.channel, 'Error:',
                                res.status_code, '-', res.reason)
        return

    json = res.json()
    if json['result_type'] == 'no_results':
        await self.send_message(message.channel, 'No results found.')
    else:
        entry = json['list'][0]
        definition = re.sub(r'\[(\w+)\]', '\\1', entry['definition'])

        reply = ''
        reply += definition[:1000].strip()
        if len(definition) > 1000:
            reply += '... (Definition truncated. '
            reply += 'See more at <{}>)'.format(entry['permalink'])
        reply += '\n\n{} :+1: :black_small_square: {} :-1:'.format(
            entry['thumbs_up'], entry['thumbs_down'])
        reply += '\n\nSee more results at <{}>'.format(
            re.sub(r'/\d*$', '', entry['permalink']))

        await self.send_message(message.channel, reply)


_memos = {}


# @Discordant.register_command('remember')
async def _remember(self, args, message):
    global _memos

    key, *memo = args.split()
    if len(memo) == 0:
        if key in _memos:
            del _memos[key]
            await self.send_message(message.channel, 'Forgot ' + key + '.')
        else:
            await self.send_message(message.channel,
                                    'Nothing given to remember.')
        return

    memo = args[len(key):].strip()
    _memos[key] = memo
    await self.send_message(
        message.channel,
        "Remembered message '{}' for key '{}'.".format(memo, key))


# @Discordant.register_command('recall')
async def _recall(self, args, message):
    global _memos
    if args not in _memos:
        await self.send_message(message.channel,
                                'Nothing currently remembered for', args + '.')
        return

    await self.send_message(message.channel, _memos[args])


# @Discordant.register_command('sleep')
async def _sleep(self, args, message):
    await asyncio.sleep(5)
    await self.send_message(message.channel, 'done sleeping')


# @Discordant.register_command('exit')
async def _exit(self, args, message):
    import sys
    sys.exit()
#endregion


#region general
@Discordant.register_command("help")
async def _help(self, args, message):
    if not args:
        args = "general"
    cmds = [self._commands[x].aliases[0] for x in self._commands
            if self._commands[x].section.lower() == args.lower()]
    await self.send_message(
        message.channel, "Commands: " + ", ".join(cmds) if cmds else "*none*")


@Discordant.register_command("timezone")
async def _convert_timezone(self, args, message):
    def get_timezone_by_code(code, date):
        code = code.upper()
        for tz_str in pytz.all_timezones:
            tz = timezone(tz_str)
            if tz.tzname(date) == code:
                return tz
        raise ValueError(code + ": not a valid time zone code")

    def convert_timezone(date, tz_from, tz_to):
        return tz_from.localize(date).astimezone(tz_to)

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
        delta = dt_2.day - dt_1.day
        if delta == 0:
            return "same day"
        else:
            return "{} day{} {}".format(abs(delta),
                                        "s" if abs(delta) != 1 else "",
                                        "ahead" if delta > 0 else "behind")

    try:
        split = args.split()
        if len(split) != 3:
            await self.send_message(
                message.channel, "!timezone <time> <from> <to>")
        dt = read_time(split[0])
        tz_f = get_timezone_by_code(split[1], dt)
        tz_t = get_timezone_by_code(split[2], dt)
        new_dt = convert_timezone(dt, tz_f, tz_t)
        await self.send_message(message.channel, "{} is {}, {}".format(
            tz_f.localize(dt).strftime("%I:%M %p %Z"),
            new_dt.strftime("%I:%M %p %Z"),
            relative_date_str(dt, new_dt))
                                )
    except ValueError as e:
        await self.send_message(message.channel,
                                "Timezone conversion failed: " + str(e))


async def _dict_search_args_parse(self, args, message, cmd):
    if not args:
        await self.send_message(message.channel, "!" + cmd + " [limit] <query>")
        return
    limit = 1
    query = args
    result = re.match(r"^([0-9]+)\s+(.*)$", args)
    if result:
        limit, query = [result.group(x) for x in (1, 2)]
    return limit, query
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
    limit, query = await _dict_search_args_parse(self, args, message, "jisho")
    base_req_url = "http://jisho.org/api/v1/search/words"
    # for some reason, requests.get does not encode the url properly, if i use
    # it with the second parameter as a dict.
    res = requests.get(base_req_url + "?keyword=" + urllib.parse.quote(
        query, encoding="utf-8"))
    if not res.ok:
        await self.send_message(message.channel, 'Error: ',
                                res.status_code, '-', res.reason)
        return

    results = res.json()["data"][:int(limit)]
    if not results:
        sent = await self.send_message(message.channel, "No results found.")
        if message.server is not None:
            await asyncio.sleep(5)
            await self.delete_message(sent)
        return
    output = ""

    def display_word(obj, *formats):
        return formats[len(obj) - 1].format(**obj)

    for result in results:
        japanese = result["japanese"]
        output += display_word(japanese[0], "**{reading}**",
                               "**{word}** {reading}") + "\n"
        new_line = ""
        if result["is_common"]:
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
            if parts == ["Wikipedia definition"]:
                continue
            if parts:
                output += "*" + ", ".join(parts) + "*\n"
            output += str(index + 1) + ". " + "; ".join(
                sense["english_definitions"])
            for attr in ["tags", "info"]:
                if sense[attr]:
                    output += ". *" + "*. *".join(sense[attr]) + "*"
            if sense["see_also"]:
                output += ". *See also: " + ", ".join(sense["see_also"]) + "*"
            output += "\n"
        if len(japanese) > 1:
            output += "Other forms: " + ", ".join(
                [display_word(x, "{reading}", "{word} ({reading})") for x in
                 japanese[1:]]) + "\n"
        # output += "\n"
    for msg in utils.long_message(output, message.server is not None):
        await self.send_message(message.channel, msg)


@Discordant.register_command("alc")
async def _alc_search(self, args, message):
    limit, query = await _dict_search_args_parse(self, args, message, "alc")
    base_req_url = "http://eow.alc.co.jp/search"
    res = requests.get(base_req_url + "?q=" + urllib.parse.quote(
        query, encoding="utf-8"))
    if not res.ok:
        await self.send_message(message.channel, 'Error: ',
                                res.status_code, '-', res.reason)
        return

    output = ""
    tree = html.fromstring(res.content)
    results = tree.xpath('//div[@id="resultsList"]/ul/li')[:int(limit)]
    if not results:
        sent = await self.send_message(message.channel, "No results found.")
        if message.server is not None:
            await asyncio.sleep(5)
            await self.delete_message(sent)
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
    for msg in utils.long_message(output, message.server is not None):
        await self.send_message(message.channel, msg)
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
            kwargs["avatar"] = requests.get(
                kwargs["avatar"], stream=True).raw.read()
        elif os.path.isfile(kwargs["avatar"]):
            kwargs["avatar"] = open(kwargs["avatar"], "rb").read()
        else:
            await self.send_message(message.channel,
                                    "Invalid avatar url or path.")
            return
    await self.edit_profile(self._password, **kwargs)
    await self.send_message(message.channel, "Settings updated.")
#endregion


#region moderation
def _punishment_format(message, document):
    if "user" not in document:
        user = message.server.get_member(document["user_id"])
        document["user"] = user.name + "#" + user.discriminator
    if "moderator" not in document:
        moderator = message.server.get_member(document["moderator_id"])
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


def _punishment_history(message, cursor):
    return "\n".join(reversed([_punishment_format(message, x) for x in cursor]))


@Discordant.register_command("modhistory", section="mod")
async def _moderation_history(self, args, message):
    if not args:
        await self.send_message(message.channel, "!modhistory <user>")
        return
    user = utils.get_user(args, message.server.members)
    db = self.mongodb_client.get_default_database()
    collection = db["punishments"]
    cursor = list(collection.find({"user_id": user.id}))
    cursor.reverse()
    if cursor:
        await self.send_message(
            message.channel, _punishment_history(message, cursor))
    else:
        await self.send_message(
            message.channel, user.name + " has no punishment history.")


async def _mod_cmd(self, args, message, cmd, action, role_name):
    if message.server is None:
        await self.send_message(message.channel,
                                "Do not use this command from PM.")
        return
    if not utils.has_permission(message.author, "manage_roles"):
        await self.send_message(message.channel,
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
    if not kwargs and " " in args:  # has more than one pos arg, no kwargs
        i = args.find(" ") + 1
        args = args[:i] + 'reason="' + args[i:] + '"'
        kwargs = utils.get_kwargs(args, keys)
    user_search = utils.strip_kwargs(args, keys)
    user = utils.get_user(user_search, message.server.members)
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
    role = discord.utils.get(message.server.roles, name=role_name)
    await self.add_roles(user, role)
    db = self.mongodb_client.get_default_database()
    collection = db["punishments"]
    if utils.is_punished(collection, user, action):
        await self.send_message(
            message.channel,
            user.name + " already has an active " + action + ".")
        return
    else:
        cursor = list(collection.find({"user_id": user.id}))
        cursor.reverse()
        if cursor:
            await self.send_message(
                message.channel,
                user.name + " has a history of:\n" + _punishment_history(
                    message, cursor) + "\n\nType y/n to continue.")
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
    collection.insert_one(document)
    await self.add_punishment_timer(user, action)
    await self.send_message(
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(message, document))


@Discordant.register_command("warn", section="mod")
async def _warn(self, args, message):
    await _mod_cmd(self, args, message, "warn", "warning", "Warned")


@Discordant.register_command("mute", section="mod")
async def _mute(self, args, message):
    await _mod_cmd(self, args, message, "mute", "mute", "Muted")


async def _mod_remove_cmd(self, args, message, cmd, action, role_name):
    if message.server is None:
        await self.send_message(message.channel,
                                "Do not use this command from PM.")
        return
    if not [x for x in message.author.roles if x.permissions.manage_roles]:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(message.channel, "!" + cmd + " <user> [reason]")
        return
    user_search = args.split()[0]
    reason = args[len(user_search) + 1:] if " " in args else "No reason given."
    user = utils.get_user(user_search, message.server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    role = discord.utils.get(message.server.roles, name=role_name)
    await self.remove_roles(user, role)
    db = self.mongodb_client.get_default_database()
    collection = db["punishments"]
    orig_action = action.replace("remove ", "")
    if not utils.is_punished(collection, user, orig_action):
        await self.send_message(
            message.channel, user.name + " has no active warning.")
        return
    document = {
        "user_id": user.id,
        "action": action,
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": 0,
        "reason": reason
    }
    collection.insert_one(document)
    await self.remove_roles(user, role)
    await self.send_message(
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(message, document))


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
    if message.server is None:
        await self.send_message(message.channel,
                                "Do not use this command from PM.")
        return
    if not [x for x in message.author.roles if x.permissions.ban_members]:
        await self.send_message(message.channel,
                                "You are not authorized to use this command.")
        return
    if not args:
        await self.send_message(message.channel, "!ban <user> [reason]")
        return
    user_search = args.split()[0]
    reason = args[len(user_search) + 1:] if " " in args else "No reason given."
    user = utils.get_user(user_search, message.server.members)
    if user is None:
        await self.send_message(message.channel, "User could not be found.")
        return
    if utils.has_permission(user, "ban_members"):
        await self.send_message(message.channel,
                                "Cannot ban another moderator.")
        return
    db = self.mongodb_client.get_default_database()
    collection = db["punishments"]
    if utils.is_punished(collection, user, "ban"):
        await self.send_message(
            message.channel, user.name + " has no active ban.")
        return
    document = {
        "user_id": user.id,
        "action": "ban",
        "moderator_id": message.author.id,
        "date": datetime.utcnow(),
        "duration": 0,
        "reason": reason
    }
    collection.insert_one(document)
    await self.send_message(
        self.get_channel(self.config["moderation"]["log_channel"]),
        _punishment_format(message, document))
    await self.ban(user)
#endregion
