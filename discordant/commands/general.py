import asyncio
import io
import re
import urllib.parse
from datetime import datetime

import aiohttp
import discord.game
import pytz
from lxml import html
from pytz import timezone

import discordant.utils as utils
from discordant import Discordant


@Discordant.register_command("help")
async def _help(self, args, message):
    """!help [command]
    displays command help and information."""
    if args:
        try:
            await utils.send_help(self, message, args)
        except:
            await self.send_message(
                message.channel, "Command could not be found.")
    else:
        sections = {}
        for cmd in self._commands.values():
            if cmd.section in sections:
                sections[cmd.section].append(cmd)
            else:
                sections[cmd.section] = [cmd]
        output = "**commands**:"
        for section, cmd_list in sections.items():
            tab_4 = " " * 4
            output += "\n  __{}__:\n".format(section) + \
                      "\n".join([tab_4 + "*{}* - ".format(cmd.aliases[0]) +
                                 cmd.help.replace("\n", tab_4 + "\n").split(
                                     " - ", 1)[1] for cmd in cmd_list])
        await utils.send_long_message(self, message.author, output)
        await self.send_message(
            message.author,
            "**command help syntax**:\n" +
            "  [] - optional argument\n" +
            "  <> - required argument\n" +
            "  \\* - any number of arguments\n" +
            "  key=value - kwargs style argument (each key-value pair is " +
            "separated by space, and the key and value are separated by the " +
            "\"=\" character).\n" +
            "  \\*\\* - any number of kwargs")
        if message.server:
            msg = await self.send_message(message.channel, "Check your PMs.")
            await _delete_after(self, 5, [message, msg])


@Discordant.register_command("timezone")
async def _convert_timezone(self, args, message):
    """!timezone <time> <from> <\*to> or !timezone <\*timezone>
    displays time in given timezone(s)."""
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

    def is_time(dt_str):
        try:
            read_time(dt_str)
        except ValueError:
            return False
        return True

    def relative_date_str(dt_1, dt_2):
        delta = dt_2.day - dt_1.day
        if delta > 1:
            delta = -1
        elif delta < -1:
            delta = 1
        return "same day" if delta == 0 else "1 day " + (
            "ahead" if delta > 0 else "behind")

    def dt_format(dt, tz_str, relative):
        new_dt = dt.astimezone(get_timezone_by_code(tz_str))
        return new_dt.strftime("%I:%M %p %Z") + (
            ", " + relative_date_str(dt, new_dt) if relative else "")

    if not args:
        await utils.send_help(self, message, "timezone")
        return
    split = args.split()
    try:
        is_t = is_time(split[0])
        if is_t:
            dt = get_timezone_by_code(split[1]).localize(read_time(split[0]))
            tz_strs = split[2:]
            output = "{} is{}".format(
                dt.strftime("%I:%M %p %Z"),
                ":\n" if len(tz_strs) > 1 else " ")
        else:
            dt = pytz.utc.localize(datetime.utcnow())
            tz_strs = split
            output = "It is currently" + (":\n" if len(tz_strs) > 1 else " ")
        output += "\n".join([dt_format(dt, tz_str, is_t) for tz_str in tz_strs])
        await self.send_message(message.channel, output)
    except ValueError:
        await self.send_message(message.channel, split[0] +
                                ": Not a valid time format or time zone code.")


async def _dict_search_args_parse(self, args, message, cmd, keys=None):
    if not args:
        await utils.send_help(self, message, cmd)
        return
    limit = 1
    query = args
    kwargs = {}
    if keys:
        kwargs = utils.get_kwargs(args, keys)
        query = utils.strip_kwargs(args, keys)
    result = re.match(r"^([0-9]+)\s+(.*)$", query)
    if result:
        limit, query = [result.group(x) for x in (1, 2)]
    return (int(limit), query) + ((kwargs,) if keys else ())


@Discordant.register_command("jisho")
async def _jisho_search(self, args, message):
    """!jisho [limit] <query>
    searches japanese-english dictionary ``http://jisho.org``."""
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
            await _delete_after(self, 5, [message, sent])
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
                sense_attr = [x for x in sense[attr] if x]
                if sense_attr:
                    output += ". *" + "*. *".join(sense_attr) + "*"
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
    """!alc [limit] <query>
    searches english-japanese dictionary ``http://alc.co.jp``."""
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
            await _delete_after(self, 5, [message, sent])
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
    await getattr(self, utils.get_cmd(self, cmd).name)(
        urllib.parse.unquote(match.group(group), encoding="utf-8"), message)


@Discordant.register_handler(r"http:\/\/jisho\.org\/(search|word)\/(\S*)")
async def _jisho_link(self, match, message):
    if "%23" not in match.group(2):
        await _dict_search_link(self, match, message, "jisho", 2)


@Discordant.register_handler(r"http:\/\/eow\.alc\.co\.jp\/search\?q=([^\s&]*)")
async def _alc_link(self, match, message):
    await _dict_search_link(self, match, message, "alc", 1)


async def _example_sentence_search(self, args, message, cmd, url):
    search_args = await _dict_search_args_parse(self, args, message, cmd,
                                                ["context"])
    if not search_args:
        return
    limit, query, kwargs = search_args
    context = kwargs["context"].lower() in ("true", "t", "yes", "y", "1") \
        if "context" in kwargs else False
    url = url + urllib.parse.quote(re.sub(r"\s+", "-", query), encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    tree = html.fromstring(data)
    query = '//li[contains(@class, "sentence") and span[@class="the-sentence"]]'
    results = tree.xpath(query)[:limit]
    if not results:
        sent = await self.send_message(message.channel, "No results found.")
        if message.server:
            await _delete_after(self, 5, [message, sent])
        return
    japanese = cmd == "yourei"

    def sentence_text(element, class_prefix="the"):
        lst = element.xpath('span[@class="' + class_prefix + '-sentence"]')
        return ("" if japanese else " ").join(
            lst[0].xpath("text() | */text()")) if lst else ""

    def result_text(element):
        text = sentence_text(element)
        match = re.search(r'"([^"]*)"', tree.xpath("//script[1]/text()")[0])
        pattern = match.group(1).replace("\\\\", "\\")
        text = re.sub(pattern, r"**\1**", text, flags=re.I)
        if context:
            sentences = [x for x in [sentence_text(element, "prev"), text,
                                     sentence_text(element, "next")] if x]
            text = ("" if japanese else " ").join(sentences)
        return text

    await utils.send_long_message(
        self, message.channel,
        "\n".join([(str(index + 1) + ". " if len(
            results) > 1 else "") + result_text(result) for index, result in
                   enumerate(results)]),
        message.server is not None)


@Discordant.register_command("yourei")
async def _yourei_search(self, args, message):
    """!yourei [limit] <query> [context=bool]
    Searches Japanese example sentences from ``http://yourei.jp``."""
    await _example_sentence_search(
        self, args, message, "yourei", "http://yourei.jp/")


@Discordant.register_command("nyanglish")
async def _nyanglish_search(self, args, message):
    """!nyanglish [limit] <query> [context=bool]
    searches english example sentences from ``http://nyanglish.com``."""
    await _example_sentence_search(
        self, args, message, "nyanglish", "http://nyanglish.com/")


@Discordant.register_handler(r"http:\/\/(yourei\.jp|nyanglish\.com)\/(\S+)")
async def _yourei_link(self, match, message):
    await _dict_search_link(
        self, match, message, match.group(1).split(".")[0], 2)

async def _delete_after(self, time, args):
    await asyncio.sleep(time)
    f = getattr(
        self, "delete_message" + ("s" if isinstance(args, list) else ""))
    await f(args)


@Discordant.register_command("strokeorder")
async def _stroke_order(self, args, message):
    """!strokeorder <character>
    shows stroke order for a kanji character."""
    if not args:
        await utils.send_help(self, message, "strokeorder")
        return
    file = str(ord(args[0])) + "_frames.png"
    url = "http://classic.jisho.org/static/images/stroke_diagrams/" + file
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 404:
                    await self.send_message(message.channel,
                                            args[0] + ": Kanji not found.")
                    return
                await self.send_file(message.channel,
                                     io.BytesIO(await response.read()),
                                     filename=file)
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return


@Discordant.register_command("showvc")
async def _show_voice_channels_toggle(self, args, message):
    """!showvc
    toggles visibility to the #voice-\* text channels."""
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
        msg = await self.send_message(message.channel, ":white_check_mark:")
    else:
        if not member.voice_channel:
            await self.remove_roles(member, role)
        msg = await self.send_message(
            message.channel, ":negative_squared_cross_mark:")
    if message.server:
        await _delete_after(self, 5, [message, msg])


@Discordant.register_command("readingcircle")
async def _reading_circle(self, args, message):
    """!readingcircle <beginner/intermediate>
    add/remove yourself to ping notification lists for beginner or intermediate
    reading circles."""
    try:
        author = message.author if message.server \
            else self.default_server.get_member(message.author.id)
        role_name = "Reading Circle " + args[0].upper() + args[1:].lower()
        role = discord.utils.get(author.server.roles, name=role_name)
        if role in author.roles:
            await self.remove_roles(author, role)
            msg = await self.send_message(
                message.channel, ":negative_squared_cross_mark:")
        else:
            await self.add_roles(author, role)
            msg = await self.send_message(message.channel, ":white_check_mark:")
    except (AttributeError, IndexError):
        msg = await self.send_message(
            message.channel, "!readingcircle <beginner/intermediate>")
    if message.server:
        await _delete_after(self, 5, [message, msg])


@Discordant.register_command("tag")
async def _tag(self, args, message):
    """!tag <tag> [content/delete]
    display, add, edit, or delete tags (text stored in the bot's database)."""
    collection = self.mongodb.tags
    if not args:
        await self.send_message(
            message.channel,
            utils.cmd_help_format(utils.get_cmd(self, "tag")) + "\nTags: " +
            ", ".join(
                [x["tag"] for x in await collection.find().to_list(None)]))
        return
    split = args.split(None, 1)
    tag = split[0]
    content = split[1] if len(split) > 1 else None
    query = {"tag": tag}
    cursor = await collection.find(query).to_list(None)
    if not message.server:
        message.author = self.default_server.get_member(message.author.id)

    def has_permission(user):
        return cursor[0]["owner"] == user.id or \
               utils.has_permission(user, "manage_roles")

    if content == "delete":
        if not cursor:
            await self.send_message(message.channel, "Tag could not be found.")
            return
        if not has_permission(message.author):
            await self.send_message(
                message.channel, "You're not allowed to delete this tag.")
            return
        await collection.remove(query)
        await self.send_message(message.channel, "Deleted tag: " + tag)
    elif content:
        if not cursor:
            await collection.insert(
                {"tag": tag, "content": content, "owner": message.author.id})
            await self.send_message(message.channel, "Added tag: " + tag)
        else:
            if not has_permission(message.author):
                await self.send_message(
                    message.channel, "You're not allowed to edit this tag.")
                return
            await collection.update(query, {"$set": {"content": content}})
            await self.send_message(message.channel, "Updated tag: " + tag)
    else:
        await self.send_message(
            message.channel,
            cursor[0]["content"] if cursor else "Tag could not be found")
