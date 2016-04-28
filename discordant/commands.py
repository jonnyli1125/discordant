from .discordant import Discordant
import asyncio
import re
import requests


@Discordant.register_handler(r'\bayy+$', re.I)
async def _ayy_lmao(self, match, message):
    if is_controller(self, message.author):
        await self.send_message(message.channel, 'lmao')

_stats = {}
# {str (server_id):
#     {str (user_id):
#         {message_count:int,
#          word_count:int,
#          word_frequency: {str (word):int}
#         }
#     }
# }


@Discordant.register_handler(r'.*', re.I)
async def _record_stats(self, match, message):
    if message.server.id not in self.config["Servers"].values():
        return
    global _stats
    if message.server.id not in _stats:
        _stats[message.server.id] = {}
    if message.author.id not in _stats[message.server.id]:
        _stats[message.server.id][message.author.id] = dict(message_count=0,
                                                            word_count=0,
                                                            word_frequency={})
    user_stat = _stats[message.server.id][message.author.id]
    user_stat['message_count'] += 1
    # regex for japanese, halfwidth katakana, cjk unified
    p = re.compile(r'[\u3040-\u30ff\uff65-\uff9f\u4e00-\u9fcc]|\w+')
    m = re.findall(p, message.content)
    user_stat['word_count'] += len(m)
    for word in m:
        user_stat['word_frequency'][word.lower()] += 1


def is_controller(self, user):
    return user.id in self.config['Controllers'].values()


def get_user_by_id(self, user_id):
    l = [m for s in self.servers for m in s.members if m.id == user_id]
    return l[0] if l else None


def get_server_by_id(self, server_id):
    l = [s for s in self.servers if s.id == server_id]
    return l[0] if l else None


@Discordant.register_command('stats')
async def _stats_command(self, args, message):
    if not is_controller(self, message.author):
        return
    global _stats
    if args == 'messages' or args == 'wordcount':
        output = ''
        counter = 0
        server_stat = _stats[message.server.id]

        def which():
            global args
            return 'message_count' if args == 'messages' else 'word_count'
        for user_id in sorted(server_stat,
                              key=lambda x: server_stat[x][which()],
                              reverse=True):
            user_name = get_user_by_id(self, user_id).name
            user_stat = server_stat[user_id][which()]
            output += '{}. {}: {}\n'.format(counter, user_name, user_stat)
            counter += 1
        await self.send_message(message.channel, output)
    elif args == 'wordfreq':  # TODO
        pass
    elif args == 'clear':
        _stats = {}
    else:
        await self.send_message(self.config.get('Commands', 'command_char') +
                                'stats <messages/wordcount/clear>')


# @Discordant.register_command('youtube')
async def _youtube_search(self, args, message):
    base_req_url = 'https://www.googleapis.com/youtube/v3/search'
    req_args = {
        'key': self.config.get('API-Keys', 'youtube'),
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


@Discordant.register_command('remember')
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


@Discordant.register_command('recall')
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
