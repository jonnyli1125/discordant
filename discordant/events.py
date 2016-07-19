import asyncio

import aiohttp
import discord

import discordant.utils as utils
from discordant import Discordant


async def _update_voice_roles(self, member, *roles):
    in_voice = bool(member.voice_channel) and \
               member.voice_channel != member.server.afk_channel
    f = getattr(self, ("add" if in_voice else "remove") + "_roles")
    await f(member, *roles)


@Discordant.register_event("ready")
async def load_voice_roles(self):
    voice_role = discord.utils.get(self.default_server.roles, name="Voice")
    for member in [x for x in self.default_server.members
                   if x.voice_channel or voice_role in x.roles]:
        await asyncio.sleep(1)  # avoid rate limit
        await _update_voice_roles(self, member, voice_role)
    cursor = await self.mongodb.always_show_vc.find().to_list(None)
    for doc in cursor:
        member = self.default_server.get_member(doc["user_id"])
        if not member:
            continue
        show_vc_role = discord.utils.get(
            self.default_server.roles, name="VC Shown")
        f = getattr(self, ("add" if doc["value"] else "remove") + "_roles")
        await asyncio.sleep(1)
        await f(member, show_vc_role)


async def add_punishment_timer(self, member, action):
    role = utils.action_to_role(self, action)
    while True:
        punished = await utils.is_punished(self, member, action)
        if not punished:
            print("Removing punishment for {}#{}".format(
                member.name, member.discriminator))
            await self.remove_roles(member, role)
            break
        await asyncio.sleep(
            self.config["moderation"]["punishment_check_rate"])


@Discordant.register_event("ready")
async def load_punishment_timers(self):
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
            print("Adding punishment timer for {}#{}".format(
                member.name, member.discriminator))
            timers.append(add_punishment_timer(self, member, action))
        elif role in member.roles:
            if member.id not in to_remove:
                to_remove[member.id] = []
            to_remove[member.id].append(role)
    await asyncio.gather(*timers)
    for uid, roles in to_remove.items():
        member = self.default_server.get_member(uid)
        await asyncio.sleep(1)
        await self.remove_roles(member, *roles)
        print("Removed punishments for {}#{}: {}".format(
            member.name,
            member.discriminator,
            ", ".join([x.name for x in roles])))


@Discordant.register_event("ready")
async def discordme_bump(self):
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
            "Punished user " +
            "{0.name}#{0.discriminator} ({0.id}) joined the server.".format(
                member))
        if await utils.is_punished(self, member, "ban"):
            await self.ban(member)
        else:
            to_add = []
            timers = []
            for action in ["warning", "mute"]:
                if await utils.is_punished(self, member, action):
                    to_add.append(utils.action_to_role(self, action))
                    timers.append(add_punishment_timer(self, member, action))
            if to_add:
                await asyncio.gather(self.add_roles(member, *to_add),
                                     *timers)


@Discordant.register_event("member_leave")
async def on_member_leave(self, member):
    if await utils.is_punished(self, member):
        await self.send_message(
            self.staff_channel,
            "Punished user " +
            "{0.name}#{0.discriminator} ({0.id}) left the server.".format(
                member))


@Discordant.register_event("voice_state_update")
async def on_voice_state_update(self, before, after):
    print("test")
    if before.voice_channel != after.voice_channel:
        roles = [discord.utils.get(after.server.roles, name="Voice")]
        doc = await self.mongodb.always_show_vc.find_one(
            {"user_id": after.id})
        if not doc or not doc["value"]:
            roles.append(
                discord.utils.get(after.server.roles, name="VC Shown"))
        await _update_voice_roles(self, after, *roles)


async def stats_fetch_logs(self):
    pass
