import asyncio
import io
import math
import re
import urllib.parse
from datetime import datetime

import aiohttp
import discord.game
import pytz
from PIL import Image
from lxml import html
from pytz import timezone

import discordant.utils as utils
from discordant import Discordant


@Discordant.register_command("help", ["info", "h", "cmds", "commands"],
                             context=True)
async def _help(self, args, message, context):
    """!help [command/section]
    displays command help and information."""
    sections = {}
    for cmd in self._commands.values():
        if cmd.perm_func and not cmd.perm_func(self, context.author):
            continue
        if cmd.section in sections:
            sections[cmd.section].append(cmd)
        else:
            sections[cmd.section] = [cmd]
    cmd = utils.get_cmd(self, args) if args else None
    if cmd:
        if cmd.perm_func and not cmd.perm_func(self, context.author):
            await self.send_message(
                message.channel, "You are not authorized to use this command.")
            return
        await self.send_message(message.channel, cmd.help)
        return
    if args:
        if args in sections:
            sections = {args: sections[args]}
        else:
            await self.send_message(message.channel,
                                    "Command could not be found.")
            return
    msg = None
    try:
        await utils.send_long_message(self, message.author, _help_menu(
            sections))
        await self.send_message(
            message.author,
            "type !help [command/section] to display more information "
            "about a certain command or section.")
        await self.send_message(
            message.author,
            "**command help syntax**:\n"
            "[]     optional argument\n"
            "<>    required argument\n"
            "\\*       any number of arguments\n"
            "k=v  kwargs style argument (each key-value pair is "
            "separated by space, and the key and value are separated by the"
            " \"=\" character).\n"
            "\\*\\*     any number of kwargs")
    except discord.errors.Forbidden:
        msg = await self.send_message(
            message.channel, "Please enable your PMs.")
    if message.server:
        if not msg:
            msg = await self.send_message(
                message.channel, "Check your PMs.")
        await _delete_after(self, 5, [message, msg])


def _help_menu(sections):
    output = "**commands**:"
    for section, cmd_list in sections.items():
        tab_4 = " " * 4
        output += "\n  __{}__:\n".format(section) + \
                  "\n".join([tab_4 + "*{}* - ".format(cmd.aliases[0]) +
                             cmd.help.replace("\n", tab_4 + "\n").split(
                                 " - ", 1)[1] for cmd in cmd_list])
    return output


def _tz_args(args):
    if not args:
        return False
    split = args.split()
    len_s = len(split)
    return len_s == 1 or len_s >= 3, split


@Discordant.register_command("timezone", ["tz"], arg_func=_tz_args)
async def _convert_timezone(self, args_split, message):
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

    try:
        is_t = is_time(args_split[0])
        if is_t:
            dt = get_timezone_by_code(args_split[1]).localize(read_time(
                args_split[0]))
            tz_strs = args_split[2:]
            output = "{} is{}".format(
                dt.strftime("%I:%M %p %Z"),
                ":\n" if len(tz_strs) > 1 else " ")
        else:
            dt = pytz.utc.localize(datetime.utcnow())
            tz_strs = args_split
            output = "It is currently" + (":\n" if len(tz_strs) > 1 else " ")
        output += "\n".join([dt_format(dt, tz_str, is_t) for tz_str in tz_strs])
        await self.send_message(message.channel, output)
    except ValueError:
        await self.send_message(message.channel, args_split[0] +
                                ": Not a valid time format or time zone code.")


def _search_args(args, keys=None):
    if not utils.has_args(args):
        return False
    limit = 1
    query = args
    kwargs = {}
    if keys:
        kwargs = utils.get_kwargs(args, keys)
        query = utils.strip_kwargs(args, keys)
    result = re.match(r"^([0-9]+)\s+(.*)$", query)
    if result:
        limit, query = [result.group(x) for x in (1, 2)]
    args_tuple = (int(limit), query) + ((kwargs,) if keys else ())
    return True, args_tuple


@Discordant.register_command("jisho", ["j", "kanji", "k"],
                             arg_func=_search_args, context=True)
async def _jisho_search(self, args_tuple, message, context):
    """!jisho [limit] <query>
    searches japanese-english dictionary <http://jisho.org>.
    see <http://jisho.org/docs> for search options."""
    limit, query = args_tuple
    if context.cmd_name[0] == "k":
        query += "#kanji"
    if "#kanji" in query:
        await _jisho_kanji(self, limit, query, message)
        return
    if "#sentences" in query:
        await _jisho_sentences(self, limit, query, message)
        return
    if "#names" in query:
        await _jisho_names(self, limit, query, message)
        return
    url = "http://jisho.org/api/v1/search/words?keyword=" + \
          urllib.parse.quote(query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    #results = data["data"][:limit] cant embed multiple
    results = data["data"][:1]
    if not results:
        await self.send_message(message.channel, "No results found.")
        return

    def display_word(obj, *formats):
        f = formats[len(obj) - 1]
        return f.format(*obj.values()) if len(obj) == 1 else f.format(**obj)

    embed = discord.Embed(
        colour=self.default_server.get_member(self.user.id).colour,
        url="http://jisho.org/search/" + query)

    for result in results:
        jp = result["japanese"]
        embed.title = display_word(jp[0], "{}", "{word}")
        embed.description = display_word(
            jp[0], "**{}**", "**{word}** {reading}") + "\n"
        if "is_common" in result and result["is_common"]:
            embed.description += "Common word. "
        if result["tags"]:  # it doesn't show jlpt tags, only wk tags?
            embed.description += "Wanikani level " + ", ".join(
                [tag[8:] for tag in result["tags"]]) + ". "
        senses = [x for x in result["senses"] if "english_definitions" in x]
        defns = ""
        for index, sense in enumerate(senses):
            # jisho returns null sometimes for some parts of speech... k den
            parts = [x for x in sense["parts_of_speech"] if x is not None]
            if parts == ["Wikipedia definition"] and len(senses) > 1:
                continue
            if parts:
                embed.description += "\n*" + ", ".join(parts) + "*"
            defns += str(index + 1) + ". " + "; ".join(
                sense["english_definitions"])
            for attr in ["tags", "info"]:
                sense_attr = [x for x in sense[attr] if x]
                if sense_attr:
                    defns += ". *" + "*. *".join(sense_attr) + "*"
            if sense["see_also"]:
                defns += ". *See also*: " + ", ".join(
                    ["[{0}](http://jisho.org/search/{0})".format(x)
                     for x in sense["see_also"]])
            defns += "\n"
            defns += "\n".join(
                ["{text}: {url}".format(**x) for x in sense["links"]])
        embed.add_field(
            name="Definitions:",
            value=utils.long_message(
                defns, truncate=True,
                err_msg="... *Message truncated. " +
                        "Please access directly on jisho.*",
                max_chars=1024))
        if len(jp) > 1:
            embed.add_field(name="Other forms:", value=", ".join(
                [display_word(x, "{}", "{word} ({reading})") for x in
                 jp[1:]]) + "\n")
    await self.send_message(message.channel, embed=embed)
    # await utils.send_long_message(
    #     self, message.channel, output, message.server is not None)


async def _jisho_kanji(self, limit, query, message):
    url = "http://jisho.org/search/" + urllib.parse.quote(
        query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    tree = html.fromstring(data)
    info_div = tree.xpath('//div[@class="kanji details"]')
    if info_div:
        await self.send_message(
            message.channel, embed=_jisho_kanji_info(self, tree))
        return
    results_div = tree.xpath('//div[@class="kanji_light_block"]')
    if not results_div:
        await self.send_message(message.channel, "No results found.")
        return
    results_divs = results_div[0].xpath(
        './div[@class="entry kanji_light clearfix"]')[:limit]
    for result_div in results_divs:
        k_url = result_div.xpath(
            'a[@class="light-details_link"]')[0].attrib["href"]
        try:
            with aiohttp.ClientSession() as session:
                async with session.get(k_url) as response:
                    k_data = await response.text()
        except Exception as e:
            await self.send_message(
                message.channel, "Request failed: {}, {}".format(k_url, e))
            continue
        await self.send_message(
            message.channel,
            embed=_jisho_kanji_info(self, html.fromstring(k_data)))
    # await utils.send_long_message(
    #     self, message.channel, output, message.server is not None)


def _jisho_kanji_info(self, tree):
    details = tree.xpath('//div[@class="kanji details"]')[0]
    character = utils.remove_spaces(
        details.xpath('//h1[@class="character"]')[0].text_content())
    meanings = utils.remove_spaces(details.xpath(
        '//div[@class="kanji-details__main-meanings"]')[0].text_content())
    strokes = utils.remove_spaces(details.xpath(
        '//div[@class="kanji-details__stroke_count"]')[0].text_content())
    stats_div = details.xpath('//div[@class="kanji_stats"]')[0]
    stats = " ".join([utils.remove_spaces(x.text_content()) + "."
                      for x in stats_div.xpath('./div')])
    readings_div = details.xpath(
        '//div[@class="kanji-details__main-readings"]')[0]
    readings = "\n".join([utils.remove_spaces(x.text_content()).replace(
        "、", ",") for x in readings_div])
    radicals_divs = [x[0] for x in details.xpath('//div[@class="radicals"]')]
    radical = utils.remove_spaces(radicals_divs[0].text_content())
    parts_div = radicals_divs[1]
    parts = "Parts: " + ", ".join(
        utils.remove_spaces(parts_div.xpath("./dd")[0].text_content(), True))
    embed = discord.Embed(
        title=character,
        url="http://jisho.org/search/" + character + "%23kanji",
        colour=self.default_server.get_member(self.user.id).colour,
        description="**{}**\n{}. {}".format(character, strokes, stats),
        image="")
    embed.add_field(name="Meanings:", value=meanings, inline=False)
    embed.add_field(name="Readings:", value=readings, inline=False)
    embed.add_field(
        name="Radical/Parts:",
        value="{}\n{}".format(radical, parts), inline=False)
    return embed
    # return "**{}** {}\n*{}. {}*\n{}\n{}\n{}".format(
    #     character, meanings, strokes, stats, readings, radical, parts)

async def _jisho_sentences(self, limit, query, message, sentence_url=None):
    url = sentence_url or "http://jisho.org/search/" + urllib.parse.quote(
        query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    tree = html.fromstring(data)
    sentences = tree.xpath('//ul[@class="sentences"]') or tree.xpath(
        '//article[@class="sentences columns small-8"]')
    if not sentences:
        await self.send_message(message.channel, "No results found.")
        return
    sentences = sentences[0][:limit]
    fmt = ("**{i}.** " if len(sentences) > 1 else "") + "{jp}。{en}\n"
    output = ""
    for i, li in enumerate(sentences):
        div = li.xpath('div[@class="sentence_content"]')[0]
        japanese = "".join(div.xpath('ul/li/span[@class="unlinked"]/text()'))
        english = div[1][0].text_content()
        output += fmt.format(jp=japanese, en=english, i=i+1)
    await utils.send_long_message(
        self, message.channel, output, message.server is not None)


async def _jisho_names(self, limit, query, message):
    url = "http://jisho.org/search/" + urllib.parse.quote(
        query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    tree = html.fromstring(data)
    names = tree.xpath('//div[@class="names"]')
    if not names:
        await self.send_message(message.channel, "No results found.")
        return
    names = names[0].xpath("div")[:limit]
    output = ""
    for div in names:
        name_split = div[0].text_content().split()
        name = "**{}** {}".format(name_split[1][1:-1], name_split[0]) \
            if len(name_split) > 1 else "**{}**".format(name_split[0])
        info_div = div[1][0]
        tags = utils.remove_spaces(info_div[0].text_content())
        meaning = utils.remove_spaces(info_div[1].text_content())
        output += "{}\n*{}.*\n{}\n".format(name, tags, meaning)
    await utils.send_long_message(
        self, message.channel, output, message.server is not None)


@Discordant.register_command("alc", arg_func=_search_args)
async def _alc_search(self, args_tuple, message):
    """!alc [limit] <query>
    searches english-japanese dictionary <http://alc.co.jp>."""
    limit, query = args_tuple
    url = "http://eow.alc.co.jp/search?q=" + \
          urllib.parse.quote(
              re.sub(r"\s+", "+", query), encoding="utf-8", safe="+")
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
        await self.send_message(message.channel, "No results found.")
        return
    for result in results:
        words = [x for x in result.xpath('./span') if
                 x.attrib["class"].startswith("midashi")][0]
        highlight = " ".join(words.xpath('./h2/span[@class="redtext"]/text()'))
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
    query = urllib.parse.unquote(match.group(group), encoding="utf-8")
    args_tuple = (1, query) + (([],) if cmd in ("yourei", "nyanglish") else ())
    await getattr(self, utils.get_cmd(self, cmd).name)(args_tuple, message)


# @Discordant.register_handler(
#     r"http:\/\/jisho\.org\/(search|word|sentences)\/(\S*)")
async def _jisho_link(self, match, message):
    if match.group(1) == "sentences":
        await _jisho_sentences(self, 1, "", message, match.group(0))
    else:
        await _dict_search_link(self, match, message, "jisho", 2)


# @Discordant.register_handler(r"http:\/\/eow\.alc\.co\.jp\/search\?q=([^\s&]*)")
async def _alc_link(self, match, message):
    await _dict_search_link(self, match, message, "alc", 1)


async def _example_sentence_search(self, args_tuple, message, cmd, url):
    limit, query, kwargs = args_tuple
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
        await self.send_message(message.channel, "No results found.")
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


def _search_args_context(args):
    return _search_args(args, ["context"])


@Discordant.register_command("yourei", arg_func=_search_args_context)
async def _yourei_search(self, args_tuple, message):
    """!yourei [limit] <query> [context=bool]
    searches japanese example sentences from <http://yourei.jp>."""
    await _example_sentence_search(
        self, args_tuple, message, "yourei", "http://yourei.jp/")


# @Discordant.register_command("nyanglish", arg_func=_search_args_context)
#async def _nyanglish_search(self, args_tuple, message):
#    """!nyanglish [limit] <query> [context=bool]
#    searches english example sentences from <http://nyanglish.com>."""
#    await _example_sentence_search(
#        self, args_tuple, message, "nyanglish", "http://nyanglish.com/")


# @Discordant.register_handler(r"http:\/\/(yourei\.jp|nyanglish\.com)\/(\S+)")
async def _yourei_link(self, match, message):
    await _dict_search_link(
        self, match, message, match.group(1).split(".")[0], 2)


async def _delete_after(self, time, args):
    await asyncio.sleep(time)
    f = getattr(
        self, "delete_message" + ("s" if isinstance(args, list) else ""))
    await f(args)


@Discordant.register_command("strokeorder", ["so"], arg_func=utils.has_args)
async def _stroke_order(self, args, message):
    """!strokeorder <character>
    shows stroke order for a kanji character."""
    file = str(ord(args[0])) + "_frames.png"
    url = "http://classic.jisho.org/static/images/stroke_diagrams/" + file
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 404:
                    await self.send_message(message.channel,
                                            args[0] + ": Kanji not found.")
                    return
                raw_response = await response.read()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    orig_image = Image.open(io.BytesIO(raw_response))
    image = _crop_and_shift_img(orig_image)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    await self.send_file(message.channel, buffer, filename=file)


def _crop_and_shift_img(img):
    char_width = 109  # width/height of one character
    chars_per_line = 4  # max before discord starts resizing it
    max_width = char_width * chars_per_line
    slices = int(math.ceil(img.width / max_width))
    total_height = char_width * slices
    width = min(max_width, img.width)
    new_img = Image.new("RGBA", (width, total_height), color=(0, 0, 0, 0))
    for i in range(slices):
        left = i * max_width
        right = min(left + max_width, img.width)
        _slice = img.crop((left, 0, right, char_width))
        new_img.paste(_slice, (0, char_width * i))
    return new_img


@Discordant.register_command("pronounce", ["p", "audio", "a"], arg_func=utils.has_args)
async def _stroke_order(self, args, message):
    """!pronounce <word>
    gives audio pronunciation for a word."""
    query = args
    url = "http://jisho.org/api/v1/search/words?keyword=" + \
          urllib.parse.quote(query, encoding="utf-8")
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    data_arr = data["data"]
    if not data_arr:
        await self.send_message(message.channel, "No results found.")
        return
    japanese = data_arr[0]["japanese"][0]
    url = "http://assets.languagepod101.com/dictionary/japanese/audiomp3.php?"
    params = "kana=" + urllib.parse.quote(japanese["reading"], encoding="utf-8")
    if len(japanese) > 1:
        params += "&kanji=" + urllib.parse.quote(
            japanese["word"], encoding="utf-8")
    url += params
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 404:
                    await self.send_message(message.channel,
                                            query + ": Audio file not found")
                    return
                buffer = io.BytesIO(await response.read())
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    await self.send_file(
        message.channel, buffer, filename=query + ".mp3")


@Discordant.register_command("showvc", ["hidevc"], context=True)
async def _show_voice_channels_toggle(self, args, message, context):
    """!showvc
    toggles visibility to the #voice-\* text channels."""
    query = {"user_id": message.author.id}
    collection = self.mongodb.always_show_vc
    cursor = await collection.find(query).to_list(None)
    show = not cursor[0]["value"] if cursor else True
    await collection.update(
        query,
        dict(query, value=show),
        upsert=True)
    role = discord.utils.get(self.default_server.roles, name="VC Shown")
    if show:
        await self.add_roles(context.author, role)
        msg = await self.send_message(message.channel, ":white_check_mark:")
    else:
        if not context.author.voice_channel:
            await self.remove_roles(context.author, role)
        msg = await self.send_message(
            message.channel, ":negative_squared_cross_mark:")
    if message.server:
        await _delete_after(self, 5, [message, msg])


# @Discordant.register_command("readingcircle", ["rc"], context=True)
async def _reading_circle(self, args, message, context):
    """!readingcircle <beginner/intermediate>
    add/remove yourself to ping notification lists for beginner or intermediate
    reading circles."""
    try:
        role_name = "Reading Circle " + args[0].upper() + args[1:].lower()
        role = discord.utils.get(context.server.roles, name=role_name)
        if role in context.author.roles:
            await self.remove_roles(context.author, role)
            msg = await self.send_message(
                message.channel, ":negative_squared_cross_mark:")
        else:
            await self.add_roles(context.author, role)
            msg = await self.send_message(message.channel, ":white_check_mark:")
    except (AttributeError, IndexError):
        msg = await self.send_message(message.channel, context.cmd.help)
    if message.server:
        await _delete_after(self, 5, [message, msg])


@Discordant.register_command("tag", ["t", "tags"], context=True)
async def _tag(self, args, message, context):
    """!tag <tag> [content/delete]
    display, add, edit, or delete tags (text stored in the bot's database)."""
    collection = self.mongodb.tags
    if not args:
        await self.send_message(
            message.channel,
            context.cmd.help + "\nTags: " + ", ".join(
                [x["tag"] for x in await collection.find().to_list(None)]))
        return
    split = args.split(None, 1)
    tag = split[0]
    content = split[1] if len(split) > 1 else None
    query = {"tag": re.compile(tag, re.I)}
    cursor = await collection.find_one(query)

    def has_permission(user):
        return cursor["owner"] == user.id or \
               context.server.default_channel.permissions_for(
                   user).manage_messages

    if content == "delete":
        if not cursor:
            await self.send_message(message.channel, "Tag could not be found.")
            return
        if not has_permission(context.author):
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
            if not has_permission(context.author):
                await self.send_message(
                    message.channel, "You're not allowed to edit this tag.")
                return
            await collection.update(query, {"$set": {"content": content}})
            await self.send_message(message.channel, "Updated tag: " + tag)
    else:
        await self.send_message(
            message.channel,
            cursor["content"] if cursor else "Tag could not be found")


@Discordant.register_command("studying", context=True)
async def _studying(self, args, message, context):
    """!studying <resource>
    add/remove a studying resource role to yourself."""
    collection = self.mongodb.studying_resources
    obj = await collection.find_one()
    if obj:
        role_names = obj["value"]
    else:
        await collection.insert({"value": []})
        role_names = []
    if not args:
        await self.send_message(
            message.channel,
            context.cmd.help + "\nResources: " + ", ".join(role_names))
        return
    split = args.split(None, 1)
    if len(split) > 1:
        subcmd = split[0]
        resource = split[1]
        role = discord.utils.get(context.server.roles, name=resource)
        if subcmd == "add":
            if not utils.is_controller(self, context.author):
                await self.send_message(
                    message.channel, "You're not allowed to do that.")
                return
            await collection.update({}, {"$push": {"value": resource}})
            if not role:
                await self.create_role(
                    context.server,
                    name=resource,
                    permissions=context.server.default_role.permissions,
                    mentionable=True)
            await self.send_message(
                message.channel, "Added studying resource: " + resource)
            return
        if subcmd == "del":
            if not utils.is_controller(self, context.author):
                await self.send_message(
                    message.channel, "You're not allowed to do that.")
                return
            await collection.update({}, {"$pull": {"value": resource}})
            if role:
                await self.delete_role(context.server, role)
            await self.send_message(
                message.channel, "Deleted studying resource: " + resource)
            return

    def search_str(s):
        return "".join(s.lower().split())

    def find_role(r):
        n = search_str(r.name)
        a = search_str(args)
        return n == a or n.startswith(a) or n in a

    roles = [discord.utils.get(context.server.roles, name=x) for x in role_names]
    role = discord.utils.find(find_role, roles)
    if not role:
        await self.send_message(message.channel, "Resource could not be found.")
        return
    if role in context.author.roles:
        await self.remove_roles(context.author, role)
        msg = await self.send_message(
            message.channel, ":negative_squared_cross_mark:")
    else:
        await self.add_roles(context.author, role)
        msg = await self.send_message(message.channel, ":white_check_mark:")
    if message.server:
        await _delete_after(self, 5, [message, msg])


async def _google_search(self, args_tuple, message, cse_key):
    api_key = self.config["api-keys"]["google"]
    cse_id = self.config["api-keys"]["cse"][cse_key]
    limit, query = args_tuple
    url = ("https://www.googleapis.com/customsearch/v1"
           "?key={}&cx={}&q={}&fields=items(title,link)".format(
              api_key, cse_id, urllib.parse.quote(query, encoding="utf-8")))
    try:
        with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
    except Exception as e:
        await self.send_message(message.channel, "Request failed: " + str(e))
        return
    if not data:
        await self.send_message(message.channel, "No results found.")
        return
    items = data["items"][:limit]
    fmt = "**{index}.** {title} - <{link}>" \
        if len(items) > 1 else "{title} - {link}"
    results = [fmt.format(**x, index=i+1) for i, x in enumerate(items)]
    await self.send_message(message.channel, "\n".join(results))


@Discordant.register_command("taekim", ["tk"], arg_func=_search_args)
async def _taekim_search(self, args_tuple, message):
    """!taekim [limit] <query>
    searches <http://guidetojapanese.org>."""
    await _google_search(self, args_tuple, message, "taekim")


@Discordant.register_command("google", ["g"], arg_func=_search_args)
async def _web_search(self, args_tuple, message):
    """!google [limit] <query>
    searches the web through google."""
    await _google_search(self, args_tuple, message, "google")
