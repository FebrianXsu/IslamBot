import asyncio
import discord
import pytz
from aiohttp import ClientSession
from datetime import datetime
from dbhandler import update_server_prayer_times_details, delete_server_prayer_times_details, \
    get_server_prayer_times_details, get_user_calculation_method, update_user_calculation_method
from discord.ext import commands, tasks
from discord.ext.commands import CheckFailure, MissingRequiredArgument, BadArgument
from pytz import timezone

icon = 'https://www.muslimpro.com/img/muslimpro-logo-2016-250.png'

headers = {'content-type': 'application/json'}


class PrayerTimes(commands.Cog):

    def __init__(self, bot):
        self.session = ClientSession(loop = bot.loop)
        self.bot = bot
        self.send_reminders.start()
        self.methods_url = 'https://api.aladhan.com/methods'
        self.prayertimes_url = 'http://api.aladhan.com/timingsByAddress?address={}&method={}&school={}'

    async def get_calculation_methods(self):
        async with self.session.get(self.methods_url, headers=headers) as resp:
            data = await resp.json()
            data = data['data'].values()

            # There's an entry ('CUSTOM') with no 'name' value, so we need to ignore it:
            calculation_methods = {method['id']: method['name'] for method in data if int(method['id']) != 99}
            return calculation_methods

    async def get_prayertimes(self, location, calculation_method):
        url = self.prayertimes_url.format(location, calculation_method, '0')

        async with self.session.get(url, headers=headers) as resp:
            data = await resp.json()
            fajr = data['data']['timings']['Fajr']
            sunrise = data['data']['timings']['Sunrise']
            dhuhr = data['data']['timings']['Dhuhr']
            asr = data['data']['timings']['Asr']
            maghrib = data['data']['timings']['Maghrib']
            isha = data['data']['timings']['Isha']
            imsak = data['data']['timings']['Imsak']
            midnight = data['data']['timings']['Midnight']
            date = data['data']['date']['readable']

        url = self.prayertimes_url.format(location, calculation_method, '1')

        async with self.session.get(url, headers=headers) as resp:
            data = await resp.json()
            hanafi_asr = data['data']['timings']['Asr']

        return fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date

    @commands.command(name="prayertimes")
    async def prayertimes(self, ctx, *, location):

        calculation_method = await get_user_calculation_method(ctx.author.id)

        try:
            fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date = await \
                self.get_prayertimes(location, calculation_method)
        except:
            return await ctx.send("**Location not found**.")

        em = discord.Embed(colour=0x2186d3, title=date)
        em.set_author(name=f'Prayer Times for {location.title()}', icon_url=icon)
        em.add_field(name=f'**Imsak (إِمْسَاك)**', value=f'{imsak}', inline=True)
        em.add_field(name=f'**Fajr (صلاة الفجر)**', value=f'{fajr}', inline=True)
        em.add_field(name=f'**Sunrise (طلوع الشمس)**', value=f'{sunrise}', inline=True)
        em.add_field(name=f'**Ẓuhr (صلاة الظهر)**', value=f'{dhuhr}', inline=True)
        em.add_field(name=f'**Asr (صلاة العصر)**', value=f'{asr}', inline=True)
        em.add_field(name=f'**Asr - Ḥanafī School (صلاة العصر - حنفي)**', value=f'{hanafi_asr}', inline=True)
        em.add_field(name=f'**Maghrib (صلاة المغرب)**', value=f'{maghrib}', inline=True)
        em.add_field(name=f'**Isha (صلاة العشاء)**', value=f'{isha}', inline=True)
        em.add_field(name=f'**Midnight (منتصف الليل)**', value=f'{midnight}', inline=True)

        method_names = await self.get_calculation_methods()
        em.set_footer(text=f'Calculation Method: {method_names[calculation_method]}')
        await ctx.send(embed=em)

    @commands.command(name="setcalculationmethod")
    async def setcalculationmethod(self, ctx):

        def is_user(msg):
            return msg.author == ctx.author

        em = discord.Embed(colour=0x467f05, description="Please select a **calculation method number**.\n\n")
        em.set_author(name='Calculation Methods', icon_url=icon)
        calculation_methods = await self.get_calculation_methods()
        for method, name in calculation_methods.items():
            em.description = f'{em.description}**{method}** - {name}\n'
        await ctx.send(embed=em)

        try:
            message = await self.bot.wait_for('message', timeout=120.0, check=is_user)
            method = message.content
            try:
                method = int(method)
                if method not in calculation_methods.keys():
                    raise TypeError
            except:
                return await ctx.send("❌ **Invalid calculation method number.** ")

            await update_user_calculation_method(ctx.author.id, method)
            await ctx.send(':white_check_mark: **Successfully updated!**')

        except asyncio.TimeoutError:
            await ctx.send("❌ **Timed out**. Please try again.")

    @commands.command(name="addprayerreminder")
    @commands.has_permissions(administrator=True)
    async def addprayerreminder(self, ctx):

        def is_user(msg):
            return msg.author == ctx.author

        em = discord.Embed(colour=0x467f05, title='Prayer Times Reminder Setup (1/4)')
        em.set_author(name=ctx.guild, icon_url=icon)

        try:
            # Ask for channel.
            em.description = "Please mention the **channel** to send prayer time reminders in."
            help_msg = await ctx.send(embed=em)
            message = await self.bot.wait_for('message', timeout=60.0, check=is_user)
            if message.channel_mentions:
                channel = message.channel_mentions[0]
                channel_id = channel.id
            else:
                return await ctx.send("❌ **Invalid channel**. Aborting.")

            # Ask for location.
            em.description = "Please set the **location** to send prayer times for. " \
                             "\n\n**Example**: Burj Khalifa, Dubai, UAE"
            em.title = 'Prayer Times Reminder Setup (2/4)'
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=60.0, check=is_user)
            location = message.content

            # Ask for timezone.
            em.description = "Please select the **__timezone__ of the location**. " \
                             "**[Click here](https://timezonedb.com/time-zones)** for a list of timezones." \
                             "\n\n**Examples**: `Asia/Dubai`, `Europe/London`, `America/Toronto`"
            em.title = 'Prayer Times Reminder Setup (3/4)'
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=180.0, check=is_user)
            if message.content in pytz.all_timezones:
                timezone = message.content
            else:
                return await ctx.send("❌ **Invalid timezone**. Aborting.")

            # Ask for calculation method.
            em.title = 'Prayer Times Reminder Setup (4/4)'
            calculation_methods = await self.get_calculation_methods()
            em.description = "Please select the prayer times **calculation method number**.\n\n"
            for method, name in calculation_methods.items():
                em.description = f'{em.description}**{method}** - {name}\n'
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=180.0, check=is_user)
            method = message.content
            try:
                method = int(method)
                if method not in calculation_methods.keys():
                    raise TypeError
            except TypeError:
                return await ctx.send("❌ **Invalid calculation method number.** ")

            # Update database.
            try:
                await update_server_prayer_times_details(ctx.guild.id, channel_id, location, timezone, method)
            except Exception as e:
                print(e)
                return await ctx.send("❌ **An error occurred**. You may already have a reminder channel on the server.")

            # Send success message.
            em.description = f":white_check_mark: **Setup complete!**" \
                             f"\n\n**Channel**: <#{channel.id}>\n**Location**: {location}\n**Timezone**: {timezone}" \
                             f"\n**Calculation Method**: {method}" \
                             f"\n\nIf you would like to change these details, use `.deletereminderchannel` and run" \
                             f" this command again."
            await help_msg.edit(embed=em)

        except asyncio.TimeoutError:
            await ctx.send("**Timed out.** Please try again.")

    @commands.command(name="removereminder")
    @commands.has_permissions(administrator=True)
    async def removeprayerreminder(self, ctx, channel: discord.TextChannel):
        try:
            await delete_server_prayer_times_details(ctx.guild.id, channel.id)
            await ctx.send(f":white_check_mark: **You will no longer receive prayer times reminders in <#{channel.id}>.**")
        except Exception as e:
            await ctx.send("❌ **An error occurred**.")

    @addprayerreminder.error
    @removeprayerreminder.error
    async def on_error(self, ctx, error):
        if isinstance(error, CheckFailure):
            await ctx.send("🔒 You need the **Administrator** permission to use this command.")
        if isinstance(error, MissingRequiredArgument) or isinstance(error, BadArgument):
            await ctx.send("❌ **Please mention the channel to delete prayer time reminders for**.")

    @tasks.loop(minutes=1)
    async def send_reminders(self):
        em = discord.Embed(colour=0x467f05)
        em.set_author(name='Prayer Times Reminder', icon_url=icon)

        # To be honest, this is a very crude implementation - but it works. I would appreciate PRs for improvement.
        servers = await get_server_prayer_times_details()
        for server in servers:
            channel_id = server[2]
            channel = self.bot.get_channel(int(channel_id))
            calculation_method = server[3]
            location = server[4]
            time_zone = server[5]

            # Get the time at the timezone and convert it into a string.
            tz = timezone(time_zone)
            tz_time = datetime.now(tz).strftime('%H:%M')

            # Get the prayer times for the location.
            fajr, _, dhuhr, asr, hanafi_asr, maghrib, isha, _, _, date = await self.get_prayertimes(
                location, calculation_method)

            maghrib = '21:10'

            em.title = location

            # If the time at the timezone matches the prayer times for the location, we send a reminder:
            try:
                if tz_time == fajr:
                    em.description = f"It is **Fajr** time in **{location}**! (__{fajr}__)" \
                                     f"\n\n**Dhuhr** will be at __{dhuhr}__."
                    await channel.send(embed=em)

                elif tz_time == dhuhr:
                    em.description = f"It is **Dhuhr** time in **{location}**! (__{dhuhr}__)" \
                                     f"\n\n**Asr** will be at __{asr}__."
                    await channel.send(embed=em)

                elif tz_time == asr:
                    await channel.send(f"It is **Asr** time in **{location}**! (__{asr}__)."
                                       f"\n\nFor Hanafis, the Asr will be at __{hanafi_asr}__."
                                       f"\n\n**Maghrib** will be at __{maghrib}__.")

                elif tz_time == maghrib:
                    em.description = f"It is **Maghrib** time in **{location}**! (__{maghrib}__)" \
                                     f"\n\n**Isha** will be at __{isha}__."
                    await channel.send(embed=em)

                elif tz_time == isha:
                    em.description = f"It is **Isha** time in **{location}**! (__{isha}__)"
                    await channel.send(embed=em)
            except:
                pass


def setup(bot):
    bot.add_cog(PrayerTimes(bot))
