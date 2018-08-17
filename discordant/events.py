import asyncio
import sys

import aiohttp
import discord

import discordant.utils as utils
from discordant import Discordant


@Discordant.register_event("ready")
async def load_voice_roles(self):
    server = self.default_server
    voice_role = discord.utils.get(server.roles, name="Voice")
    voiced = [x for x in server.members
              if x.voice_channel or voice_role in x.roles]
    for user in voiced:
        await update_voice_roles(self, user)


async def _update_voice_roles(self, member, *roles):
    in_voice = bool(member.voice_channel) and \
               member.voice_channel != member.server.afk_channel
    f = getattr(self, ("add" if in_voice else "remove") + "_roles")
    await f(member, *roles)


async def update_voice_roles(self, member):
    voice_role = discord.utils.get(member.server.roles, name="Voice")
    vc_role = discord.utils.get(member.server.roles, name="VC Shown")
    roles = [voice_role]
    doc = await self.mongodb.always_show_vc.find_one({"user_id": member.id})
    if not doc or not doc["value"]:
        roles.append(vc_role)
    await _update_voice_roles(self, member, *roles)


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
        if action == "ban" or action.startswith("remove"):
            continue
        member = self.default_server.get_member(document["user_id"])
        if not member:
            continue
        role = utils.action_to_role(self, action)
        if await utils.is_punished(self, member, action):
            print("Adding punishment timer for " + str(member))
            timers.append(utils.add_punishment_timer(self, member, action))
        elif role and role in member.roles:
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


# discord.me added captcha so rip this
# @Discordant.register_event("ready")
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
    punishments = []
    for action in ["ban", "warning", "mute"]:
        if await utils.is_punished(self, member, action):
            punishments.append(action)
    if punishments:
        await self.send_message(
            self.staff_channel,
            "Punished user {0} ({0.id}) joined the server.".format(member))
        if "ban" in punishments:
            await self.ban(member)
            return
        else:
            to_add = []
            timers = []
            for action in punishments:
                role = utils.action_to_role(self, action)
                if role:
                    to_add.append(role)
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
        await update_voice_roles(self, after)


@Discordant.register_event("ready")
async def stats_update(self):
    if not self.user.bot:
        print("Stats logs cannot be fetched: please run through a bot account.")
        return
    server = self.default_server
    logs = []
    channels = []
    for channel in server.channels:
        if channel in [self.staff_channel, self.testing_channel] \
                or channel.type != discord.ChannelType.text \
                or not channel.permissions_for(server.get_member(
                    self.user.id)).read_messages:
            continue
        channels.append({"channel_id": channel.id, "name": channel.name})
        search = await self.mongodb.logs.find({
            "$query": {"channel_id": channel.id},
            "$orderby": {"$natural": -1}
        }).to_list(None)
        last_msg = None
        for res in search:
            try:
                last_msg = await self.get_message(channel, res["message_id"])
                break
            except discord.NotFound:
                pass
        limit, after = (sys.maxsize, last_msg) if last_msg else (100, None)
        async for message in self.logs_from(channel, limit, after=after):
            logs.append({
                "message_id": message.id,
                "author_id": message.author.id,
                "channel_id": message.channel.id,
                "timestamp": message.timestamp,
                "content": message.clean_content
            })
    members = [{"user_id": x.id,
                "name": x.name,
                "discriminator": x.discriminator,
                "nick": x.nick,
                "created_at": utils.datetime_floor_microseconds(x.created_at),
                "joined_at": utils.datetime_floor_microseconds(x.joined_at),
                "avatar": utils.get_avatar_url(x)}
               for x in server.members]
    if logs:
        await self.mongodb.logs.insert_many(
            sorted(logs, key=lambda x: x["timestamp"]))
    dct = {"channels": "channel_id", "members": "user_id"}
    for name, id_name in dct.items():
        count_name = name + "_updated"
        locals()[count_name] = 0
        for obj in locals()[name]:
            query = {id_name: obj[id_name]}
            collection = self.mongodb[name]
            document = await collection.find_one(query)
            if document:
                del document["_id"]
            if document != obj:
                await collection.update_one(query, {"$set": obj}, upsert=True)
                locals()[count_name] += 1
    print("Updated stats: {} messages, {} channels, {} users updated.".format(
        len(logs), locals()["channels_updated"], locals()["members_updated"]))
