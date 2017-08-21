import asyncio
import re
import shlex
from datetime import datetime

import discord


def split_every(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)]


def is_url(s):  # good enough for now lmao
    return bool(re.match(r'^https?:\/\/.*', s))


def long_message(output, truncate=False, max_chars=2000,
                 err_msg="... *Message truncated. PM me to show more!"):
    if not truncate:
        return split_every(output, max_chars)
    elif len(output) > max_chars:
        output = output[:max_chars - len(err_msg)]
        return output[:output.rindex("\n") + 1] + err_msg
    else:
        return output

async def send_long_message(self, channel, message, truncate=False,
                            max_lines=15):
    for msg in long_message(message, truncate, max_lines):
        await self.send_message(channel, msg)


def get_kwargs(args_str, keys=None):
    return dict(
        x.split("=") for x in try_shlex(args_str)
        if "=" in x and
        (True if keys is None else x.split("=")[0] in keys))


def strip_kwargs(args_str, keys=None):
    return " ".join(
        [x for x in try_shlex(args_str)
         if not ("=" in x and
         (True if keys is None else x.split("=")[0] in keys))])


def get_from_kwargs(key, kwargs, default):
    return kwargs[key] if key in kwargs else default


def get_user(search, seq, message=None, strict=False):
    if re.match(r"<@!?\d+>", search):
        return discord.utils.get(
            message.mentions if message else seq, mention=search)
    elif re.match(r".+#\d{4}$", search):
        return discord.utils.find(lambda x: search == str(x), seq)
    elif not strict:
        return _general_search(search, seq)


def get_channel(search, seq, message=None):
    if re.match(r"<#\d+>", search):
        return discord.utils.get(
            message.channel_mentions if message else seq, mention=search)
    else:
        while search.startswith("#"):
            search = search[1:]
        return _general_search(search, seq)


def _general_search(search, seq):
    temp = search.lower()
    searches = [lambda x: search == x.name,
                lambda x: hasattr(x, "nick") and x.nick and search == x.nick,
                lambda x: temp == x.name.lower(),
                lambda x: hasattr(x, "nick") and x.nick and
                          temp == x.nick.lower(),
                lambda x: x.name.startswith(temp),
                lambda x: hasattr(x, "nick") and x.nick and
                          x.nick.startswith(temp),
                lambda x: temp in x.name.lower(),
                lambda x: hasattr(x, "nick") and x.nick and
                          temp in x.nick.lower()]
    for fn in searches:
        result = discord.utils.find(fn, seq)
        if result:
            return result
    return None


async def is_punished(self, member, *actions):
    punishments = ["ban", "warning", "mute"]
    if not set(actions) <= set(punishments):
        raise ValueError("Invalid action, must be one of: " +
                         ", ".join(punishments))
    cursor = await self.mongodb.punishments.find(
        {"user_id": member.id}).to_list(None)
    cursor.reverse()
    if not cursor:
        return False
    actions = actions if actions else punishments
    for action in actions:
        if await _is_punished(cursor, action):
            return True
    return False

async def _is_punished(cursor, action):
    if action == "ban":
        return bool(discord.utils.find(lambda x: x["action"] == "ban", cursor))
    else:
        def f(x):
            td = datetime.utcnow() - x["date"]
            return x["action"] == action and td.seconds / float(
                3600) + td.days * 24 < x["duration"]
        active = discord.utils.find(f, cursor)
        if not active:
            return False

        def g(x):
            nonlocal active
            xd = x["date"]
            ad = active["date"]
            td = xd - ad
            return x["action"] == "remove " + action and \
                (xd > ad and td.seconds / float(3600) + td.days * 24 < active[
                    "duration"])
        return discord.utils.find(g, cursor) is None


async def add_punishment_timer(self, member, action):
    role = action_to_role(self, action)
    while True:
        punished = await is_punished(self, member, action)
        if not punished:
            print("Removing punishment for " + str(member))
            if role:
                await self.remove_roles(member, role)
            break
        await asyncio.sleep(
            self.config["moderation"]["punishment_check_rate"])


def action_to_role(self, action):
    dct = {
        # "warning": "Warned",
        "mute": "Muted"
    }
    if action not in dct:
        return None
        # raise ValueError("Invalid action {}, must be one of: {}".format(
        #     action, ", ".join(dct.keys())))
    return discord.utils.get(self.default_server.roles, name=dct[action])


def get_cmd(self, cmd_name):
    try:
        return self._commands[self._aliases[cmd_name]]
    except KeyError:
        return None


def cmd_help_format(cmd):
    if isinstance(cmd, str):
        split = [s.strip() for s in cmd.split("\n")]
        return split[0] + " - " + " ".join(split[1:]).replace("\\n", "\n")
    else:
        return cmd.help


async def send_help(self, message, cmd_name):
    await self.send_message(message.channel, cmd_help_format(get_cmd(
        self, cmd_name)))


def is_controller(self, user):
    return user.id in self.controllers


def python_format(code):
    zwsp = "​"  # zero width space
    return "```py\n{}\n```".format(str(code).replace("`", "`" + zwsp))


def get_avatar_url(user):
    return user.avatar_url if user.avatar else user.default_avatar_url


def datetime_floor_microseconds(dt, digits=3):
    n = 10 ** digits
    return dt.replace(microsecond=dt.microsecond // n * n)


def geq_role(self, user, author):
    self_user = self.default_server.get_member(self.user.id)
    return user.top_role >= min(self_user.top_role, author.top_role)


def gt_role(self, author, user, include_self=False):
    def rank(x):
        return x.top_role.position

    author_rank = rank(author)
    if include_self:
        self_user = self.default_server.get_member(self.user.id)
        author_rank = min(rank(self_user), author_rank)
    return author_rank > rank(user)


def has_args(s):
    return bool(s)


def len_split(s, n, *args):
    split = s.split(*args)
    return len(split) == n, split


def has_permission(member, perm):
    return getattr(member.server_permissions, perm)


def remove_spaces(s, all=False):
    return re.sub(r"\s?", "", s) if all else re.sub(r"\s+", " ", s).strip()


def try_shlex(s):
    try:
        split = shlex.split(s)
    except ValueError:
        split = s.split()
    return split
