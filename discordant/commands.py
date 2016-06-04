from .discordant import Discordant
import asyncio
import re
import requests
import urllib.parse
from .utils import *


# @Discordant.register_handler(r'\bayy+$', re.I)
async def _ayy_lmao(self, match, message):
    await self.send_message(message.channel, 'lmao')


# @Discordant.register_command('youtube')
async def _youtube_search(self, args, message):
    base_req_url = 'https://www.googleapis.com/youtube/v3/search'
    req_args = {
        'key': self.config['API-Keys']['youtube'],
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


@Discordant.register_command("timezone")
async def _convert_timezone(self, args, message):
    try:
        split = args.split()
        if len(split) != 3:
            await self.send_message(
                message.channel, "!timezone <time> <from> <to>")
        dt = read_time(split[0])
        tz_from = get_timezone_by_code(split[1], dt)
        tz_to = get_timezone_by_code(split[2], dt)
        new_dt = convert_timezone(dt, tz_from, tz_to)
        await self.send_message(message.channel, "{} is {}, {}".format(
            tz_from.localize(dt).strftime("%I:%M %p %Z"),
            new_dt.strftime("%I:%M %p %Z"),
            relative_date_str(dt, new_dt))
                                )
    except ValueError as e:
        await self.send_message(message.channel,
                                "Timezone conversion failed: " + str(e))


@Discordant.register_command("jisho")
async def _jisho_search(self, args, message):
    if not args:
        await self.send_message(message.channel, "!jisho [limit] <query>")
        return
    limit = 1
    query = args
    result = re.match(r"^([0-9]+)\s+(.*)$", args)
    if result:
        limit, query = [result.group(x) for x in (1, 2)]

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
        await self.send_message(message.channel, "No results found.")
        return
    output = ""
    for result in results:
        japanese = result["japanese"]
        output += ("**{}**" + (" {}" if len(japanese[0]) > 1 else "")).format(
            *japanese[0].values()) + "\n"
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
            parts = sense["parts_of_speech"]
            if parts == ["Wikipedia definition"]:
                continue
            if parts:
                output += "*" + ", ".join(parts) + "*\n"
            output += str(index + 1) + ". " + "; ".join(
                sense["english_definitions"])
            for attr in ["tags", "see_also", "info"]:
                if sense[attr]:
                    output += ". *" + "*. *".join(sense[attr]) + "*"
            output += "\n"
        if len(japanese) > 1:
            def f(x):
                return ("{}" + (" ({})" if len(x) > 1 else "")).format(
                    *x.values())
            output += "Other forms: " + ", ".join(
                [f(x) for x in japanese[1:]]) + "\n"
        output += "\n"
    for msg in split_every(output.strip(), 2000):
        await self.send_message(message.channel, msg)
