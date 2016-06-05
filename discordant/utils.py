from datetime import datetime
from pytz import timezone
import pytz
import re


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
            return datetime.now().replace(hour=read_dt.hour, minute=read_dt.minute)
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


def split_every(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)]


def is_url(s):  # good enough for now lmao
    return re.match(r'^https?:\/\/.*', s)

