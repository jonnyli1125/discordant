import re
import shlex
from datetime import datetime

import discord


def split_every(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)]


def is_url(s):  # good enough for now lmao
    return re.match(r'^https?:\/\/.*', s)


def long_message(output, truncate=False, max_lines=15):
    output = output.strip()
    return ["\n".join(output.split("\n")[:max_lines]) +
            "\n... *Search results truncated. " +
            "Send me a command over PM to show more!*"] \
        if truncate and output.count("\n") > max_lines \
        else split_every(output, 2000)

async def send_long_message(self, channel, message, truncate=False,
                            max_lines=15):
    for msg in long_message(message, truncate, max_lines):
        await self.send_message(channel, msg)


def get_kwargs(args_str, keys=None):
    return dict(
        x.split("=") for x in shlex.split(args_str)
        if "=" in x and
        (True if keys is None else x.split("=")[0] in keys))


def strip_kwargs(args_str, keys=None):
    return " ".join(
        [x for x in shlex.split(args_str)
         if not ("=" in x and
         (True if keys is None else x.split("=")[0] in keys))])


def get_from_kwargs(key, kwargs, default):
    return kwargs[key] if key in kwargs else default


def get_user(search, seq):
    def f(x):
        nonlocal search
        if search == x.mention:
            return True
        if search == x.name + "#" + x.discriminator:
            return True
        if search == x.name or search == x.nick:
            return True
        search = search.lower()
        if x.name.lower().startswith(search):
            return True
        if x.nick and x.nick.lower().startswith(search):
            return True
        return False

    return discord.utils.find(f, seq)


async def is_punished(self, member, action):
    cursor = await self.mongodb.punishments.find(
        {"user_id": member.id}).to_list(None)
    cursor.reverse()
    if not cursor:
        return False
    if action == "ban":
        return bool(discord.utils.find(lambda x: x["action"] == "ban", cursor))
    else:
        def f(x):
            return x["action"] == action and \
                   (datetime.utcnow() - x["date"]).seconds / float(3600) < x[
                       "duration"]
        active = discord.utils.find(f, cursor)
        if not active:
            return False

        def g(x):
            nonlocal active
            xd = x["date"]
            ad = active["date"]
            return x["action"] == "remove " + action and \
                (xd > ad and (xd - ad).seconds / float(3600) < active[
                    "duration"])
        return discord.utils.find(g, cursor) is None


def has_permission(user, permission):
    return len(
        [x for x in user.roles if getattr(x.permissions, permission)]) > 0
