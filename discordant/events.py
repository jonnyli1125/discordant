import asyncio
import sys

import aiohttp
import discord

import discordant.utils as utils
from discordant import Discordant


async def _update_voice_roles(self, member, *roles):
    in_voice = bool(member.voice_channel) and \
               member.voice_channel != member.server.afk_channel
    f = getattr(self, ("add" if in_voice else "remove") + "_roles")
    await f(member, *roles)


_load_punishment_timers = False


@Discordant.register_event("ready")
async def load_punishment_timers(self):
    global _load_punishment_timers
    if not _load_punishment_timers:
        _load_punishment_timers = True
    else:
        return
    cursor = await self.mongodb.punishments.find().to_list(None)
    to_remove = {}
    timers = []
    for document in reversed(cursor):
        action = document["action"]
        if action == "ban" or action.startswith("removed"):
            continue
        member = self.default_server.get_member(document["user_id"])
        if not member:
            continue
        role = utils.action_to_role(self, action)
        if await utils.is_punished(self, member, action):
            print("Adding punishment timer for " + str(member))
            timers.append(utils.add_punishment_timer(self, member, action))
        elif role in member.roles:
            if member.id not in to_remove:
                to_remove[member.id] = []
            to_remove[member.id].append(role)
    await asyncio.gather(*timers)
    for uid, roles in to_remove.items():
        member = self.default_server.get_member(uid)
        await asyncio.sleep(1)
        await self.remove_roles(member, *roles)
        print("Removed punishments for {}: {}".format(
            str(member),
            ", ".join([x.name for x in roles])))


_discordme_bump = False


@Discordant.register_event("ready")
async def discordme_bump(self):
    global _discordme_bump
    if not _discordme_bump:
        _discordme_bump = True
    else:
        return
    cfg = self.config["api-keys"]["discordme"]
    if not cfg["login"]["username"]:
        return
    while True:
        with aiohttp.ClientSession() as session:
            async with session.post(
                    "https://discord.me/signin",
                    data=cfg["login"]
            ) as response:
                if not response.status == 200:
                    print("DiscordMe login request failed.")
                    return
                if '<li><a href="/logout">LOGOUT</a></li>' not in \
                        await response.text():
                    print("DiscordMe login credentials incorrect.")
                    return
            async with session.get(
                            "https://discord.me/server/bump/" +
                            cfg["bump_id"]
            ) as response:
                if not response.status == 200:
                    print("DiscordMe bump request failed.")
                    return
                output = "failed: Already bumped within the last 6 hours." \
                    if "you need to wait 6 hours between bumps!" in \
                       await response.text() else "successful."
                print("DiscordMe server bump " + output)
        await asyncio.sleep(60 * 60 * 6 + 60 * 5)  # 5m delay just in case


@Discordant.register_event("member_join")
async def on_member_join(self, member):
    if await utils.is_punished(self, member):
        await self.send_message(
            self.staff_channel,
            "Punished user {0} ({0.id}) joined the server.".format(member))
        if await utils.is_punished(self, member, "ban"):
            await self.ban(member)
        else:
            to_add = []
            timers = []
            for action in ["warning", "mute"]:
                if await utils.is_punished(self, member, action):
                    to_add.append(utils.action_to_role(self, action))
                    timers.append(utils.add_punishment_timer(
                        self, member, action))
            if to_add:
                await asyncio.gather(self.add_roles(member, *to_add),
                                     *timers)


@Discordant.register_event("member_leave")
async def on_member_leave(self, member):
    if await utils.is_punished(self, member):
        await self.send_message(
            self.staff_channel,
            "Punished user {0} ({0.id}) left the server.".format(member))


@Discordant.register_event("voice_state_update")
async def on_voice_state_update(self, before, after):
    if before.voice_channel != after.voice_channel:
        roles = [discord.utils.get(after.server.roles, name="Voice")]
        doc = await self.mongodb.always_show_vc.find_one({"user_id": after.id})
        if not doc or not doc["value"]:
            roles.append(discord.utils.get(after.server.roles, name="VC Shown"))
        await _update_voice_roles(self, after, *roles)


@Discordant.register_event("ready")
async def stats_fetch_logs(self):
    if not self.user.bot:
        print("Stats logs cannot be fetched: please run through a bot account.")
        return
    collection = self.mongodb.logs
    logs = []
    for channel in self.default_server.channels:
        if channel == self.staff_channel or channel == self.testing_channel:
            continue
        search = await collection.find_one({
            "$query": {"channel_id": channel.id},
            "$orderby": {"$natural": -1}
        })
        limit, after = (sys.maxsize, await self.get_message(
            channel, search["message_id"])) if search else (100, None)
        async for message in self.logs_from(channel, limit, after=after):
            logs.append({
                "message_id": message.id,
                "author_id": message.author.id,
                "channel_id": message.channel.id,
                "timestamp": message.timestamp,
                "content": message.clean_content
            })
    if logs:
        await collection.insert(sorted(logs, key=lambda x: x["timestamp"]))
    print("Updated stats logs: {} messages inserted.".format(len(logs)))


async def stats_fetch_type(self, name, collection, keys):
    collection = self.mongodb[name + "s"]
    data = []
    for obj in collection:
        if obj == self.staff_channel or obj == self.testing_channel:
            continue


@Discordant.register_event("ready")
async def stats_fetch_members(self):
    pass