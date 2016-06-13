import re
import shlex
import sys
import pymongo


def split_every(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)]


def is_url(s):  # good enough for now lmao
    return re.match(r'^https?:\/\/.*', s)


def long_message(output, truncate, max_lines=15):
    output = output.strip()
    return ["\n".join(output.split("\n")[:max_lines]) +
            "\n... *Search results truncated. " +
            "Send me a command over PM to show more!*"] \
        if truncate and output.count("\n") > max_lines \
        else split_every(output, 2000)


def get_kwargs(args_str, keys=None):
    return dict(
        x.split("=") for x in shlex.split(args_str)
        if "=" in x and
        (True if keys is None else x[:x.find("=")] in keys))


def strip_kwargs(args_str, keys=None):
    return " ".join(
        [x for x in shlex.split(args_str)
         if not ("=" in x and
         (True if keys is None else x[:x.find("=")] not in keys))])


