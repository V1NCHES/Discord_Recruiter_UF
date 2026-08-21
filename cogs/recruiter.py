import re
import datetime
import asyncio
import gc
import psutil
import os
import discord
from discord.ext import commands
from discord import app_commands
from urllib.parse import quote
from settings_manager import has_bot_permission, load_settings, increment_stat, save_settings
from scraper import AlbionScraper

def parse_roster_text(raw_text: str) -> list[str]:
    """Parses raw text or tabular data into formatted roster items."""
    lines = raw_text.splitlines()
    if not lines:
        return []
    first_line = lines[0].lower()
    start_idx = 0
    if any(h in first_line for h in ["игрок", "ник", "name", "дата", "date", "последний"]) or "\t" in lines[0]:
        start_idx = 1
    roster = []
    for line in lines[start_idx:]:
        line_str = line.strip()
        if not line_str:
            continue
        parts = [p.strip() for p in re.split(r'\t|\s{2,}', line_str) if p.strip()]
        if len(parts) >= 2:
            name = parts[0].strip('"')
            last_seen = parts[1].strip('"')
            roster.append(f"**{name}** (Последний онлайн: {last_seen})")
        elif len(parts) == 1:
            names = [n.strip('"').strip() for n in re.split(r'[\s,;]+', line_str) if n.strip().strip('"')]
            for name in names:
                if name:
                    roster.append(f"**{name}**")
    return roster

def parse_exits_text(raw_text: str, last_date: str = "") -> tuple[list[tuple[str, str]], str]:
    """Parses raw exit records into a tuple of (new_exits, new_last_date)."""
    lines = raw_text.splitlines()
    if not lines:
        return [], last_date
    first_line = lines[0].lower()
    start_idx = 0
    if any(h in first_line for h in ["игрок", "ник", "name", "дата", "date", "действие", "action"]) or "\t" in lines[0]:
        start_idx = 1
    new_last_date = last_date
    new_exits = []
    for line in lines[start_idx:]:
        line_str = line.strip()
        if not line_str:
            continue
        parts = [p.strip() for p in re.split(r'\t|\s{2,}', line_str) if p.strip()]
        if len(parts) >= 3:
            date_str = parts[0].strip('"')
            name = parts[1].strip('"')
            action = parts[2].strip('"')
            if date_str > last_date and "покинул" in action.lower():
                new_exits.append((date_str, name))
                if date_str > new_last_date:
                    new_last_date = date_str
        elif len(parts) == 1:
            names = [n.strip('"').strip() for n in re.split(r'[\s,;]+', line_str) if n.strip().strip('"')]
            for name in names:
                if name:
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    new_exits.append((now_str, name))
    return new_exits, new_last_date

class RosterModal(discord.ui.Modal, title="Ввод состава гильдии"):
    text_input = discord.ui.TextInput(
        label="Список состава гильдии",
        style=discord.TextStyle.paragraph,
        placeholder="Вставьте список состава (каждый ник на новой строке, или таблицей из файла)...",
        required=True,
        max_length=4000
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            roster = parse_roster_text(self.text_input.value)
            if not roster:
                await interaction.followup.send("⚠️ Не удалось найти корректные данные в переданном тексте.", ephemeral=True)
                return
                
            embed = discord.Embed(title="📜 Текущий состав гильдии", color=discord.Color.blue())

            
            # Разделяем на чанки, чтобы не превысить лимит (4096 символов для description)
            chunks = []
            current_chunk = ""
            for item in roster:
                if len(current_chunk) + len(item) + 2 > 4000:
                    chunks.append(current_chunk)
                    current_chunk = item + "\n"
                else:
                    current_chunk += item + "\n"
            if current_chunk:
                chunks.append(current_chunk)
                
            embed.description = chunks[0]
            embed.set_footer(text=f"Всего игроков: {len(roster)}")
                
            await interaction.followup.send("✅ Список состава гильдии сформирован:", embed=embed, ephemeral=True)
            
            # Отправляем остальные части, если они есть
            for chunk in chunks[1:]:
                chunk_embed = discord.Embed(description=chunk, color=discord.Color.blue())
                await interaction.followup.send(embed=chunk_embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"❌ **Ошибка при обработке состава гильдии:** `{str(e)}`", ephemeral=True)

class ExitsModal(discord.ui.Modal, title="Ввод покинувших гильдию"):
    text_input = discord.ui.TextInput(
        label="Список вышедших игроков",
        style=discord.TextStyle.paragraph,
        placeholder="Вставьте список (каждый ник на новой строке, или таблицу exits.txt)...",
        required=True,
        max_length=4000
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        settings = load_settings()
        ban_channel_id = settings.get("ban_log_channel_id")
        
        if not ban_channel_id:
            await interaction.followup.send("❌ **Канал логов банов не настроен!** Администратор должен сначала задать его командой `/setting_ban_channel`.", ephemeral=True)
            return
            
        ban_channel = interaction.guild.get_channel(int(ban_channel_id))
        if not ban_channel:
            await interaction.followup.send("❌ **Сохраненный канал банов не найден на сервере!** Пожалуйста, перенастройте его с помощью `/setting_ban_channel`.", ephemeral=True)
            return
            
        try:
            last_date = settings.get("last_processed_exit_date", "")
            acceptance_logs = settings.get("acceptance_logs", {})
            new_exits, new_last_date = parse_exits_text(self.text_input.value, last_date)
            
            if not new_exits:
                await interaction.followup.send("⚠️ В переданном источнике нет новых записей о покинувших игроках.", ephemeral=True)
                return
                
            sent_count = 0
            
            # Отправляем новых игроков в бан-канал
            for date_str, ign in reversed(new_exits): # от старых к новым
                ign_lower = ign.lower()
                dsi = "Неизвестно"
                dsn = "Неизвестно"
                
                # Ищем DSI
                log_entry = acceptance_logs.get(ign_lower)
                if log_entry:
                    msg_id = log_entry.get("message_id")
                    for k, v in acceptance_logs.items():
                        if k != ign_lower and k.isdigit() and isinstance(v, dict) and v.get("message_id") == msg_id:
                            dsi = k
                            break
                            
                # Ищем DSN
                if dsi != "Неизвестно":
                    member = interaction.guild.get_member(int(dsi))
                    if member:
                        dsn = member.name
                    else:
                        try:
                            user = await self.cog.bot.fetch_user(int(dsi))
                            dsn = user.name
                        except Exception:
                            pass
                            
                ban_log_text = (
                    f"IGN    {ign}\n"
                    f"DSN    {dsn}\n"
                    f"DSI    {dsi}\n"
                    f"REASON Покинул гильдию ({date_str})"
                )
                
                await ban_channel.send(f"🚪 **Игрок покинул гильдию:**\n```text\n{ban_log_text}\n```")
                sent_count += 1
                
            # Сохраняем новую дату, если мы обрабатывали файл с датами
            if new_last_date > last_date:
                settings["last_processed_exit_date"] = new_last_date
                save_settings(settings)
                
            await interaction.followup.send(f"✅ Обработано **{sent_count}** покинувших гильдию игроков. Логи отправлены в {ban_channel.mention}.", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ **Ошибка при обработке списка выходов:** `{str(e)}`", ephemeral=True)

class Recruiter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.portals = self.load_ava_portals()

    def load_ava_portals(self):
        import json
        import os
        if os.path.exists('ava_portals_cache.json'):
            try:
                with open('ava_portals_cache.json', 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Ошибка при загрузке ava_portals_cache.json: {e}")
                return []
        return []

    @app_commands.command(name="info", description="Показывает информацию о доступных командах игрока.")
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Информация о командах игрока",
            description="Список доступных вам функций и их описание:",
            color=discord.Color.green()
        )
        embed.add_field(name="`/info`", value="Показывает это сообщение.", inline=False)
        embed.add_field(name="`/start <ник>`", value="Поиск выдающихся киллов игрока с MurderLedger (только ссылки).", inline=False)
        embed.add_field(name="`/ava_portal <Локация>`", value="Показывает тир, размер сундуков и лут в локациях Авалона (с автокомплитом).", inline=False)
        embed.add_field(name="`/stats`", value="Показывает использование ОЗУ (памяти), CPU, Uptime и выполняет автоочистку памяти.", inline=False)
        
        embed.set_footer(text="United Force • Игровой помощник")
        await interaction.response.send_message(embed=embed)
        gc.collect()

    @app_commands.command(name="stats", description="Показывает использование оперативной памяти (ОЗУ), системные ресурсы и время работы бота.")
    async def stats(self, interaction: discord.Interaction):
        # Замеряем память ДО очистки
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / (1024 * 1024)
        
        # Выполняем сборку мусора для эффективного освобождения памяти
        collected_objects = gc.collect()
        
        # Замеряем память ПОСЛЕ очистки
        mem_after = process.memory_info().rss / (1024 * 1024)
        freed_mb = mem_before - mem_after
        if freed_mb < 0:
            freed_mb = 0.0
            
        cpu_percent = process.cpu_percent(interval=0.1)
        
        # Расчет Uptime
        uptime_str = "Неизвестно"
        if hasattr(self.bot, 'start_time'):
            delta = datetime.datetime.now(datetime.timezone.utc) - self.bot.start_time
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{days}д {hours}ч {minutes}м {seconds}с"
            
        # Лимит памяти Discloud
        DISCLOUD_RAM_LIMIT_MB = 100.0
        used_percent = (mem_after / DISCLOUD_RAM_LIMIT_MB) * 100
        
        # Статус-индикатор нагрузки на память
        status_emoji = "🟢" if mem_after < 60 else ("🟡" if mem_after < 85 else "🔴")

        embed = discord.Embed(
            title="📊 Системная статистика & Память (ОЗУ)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="💾 Занято оперативной памяти (ОЗУ)",
            value=(
                f"{status_emoji} **{mem_after:.2f} MB** / {DISCLOUD_RAM_LIMIT_MB:.0f} MB ({used_percent:.1f}%)\n"
                f"🧹 **До очистки:** `{mem_before:.2f} MB` | **Освобождено:** `{freed_mb:.2f} MB` (`{collected_objects}` объектов)"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Системные показатели",
            value=(
                f"🖥️ **Загрузка CPU:** `{cpu_percent:.1f}%`\n"
                f"⏱️ **Время работы (Uptime):** `{uptime_str}`\n"
                f"🐍 **Сборщик мусора (GC):** `Автоматическая очистка включена`"
            ),
            inline=False
        )
        
        embed.set_footer(text="United Force System Monitor • Очистка ОЗУ выполняется автоматически")
        await interaction.response.send_message(embed=embed)
        gc.collect()

    @app_commands.command(name="info_rec", description="Показывает информацию о командах рекрутеров и администрации.")
    @has_bot_permission()
    async def info_rec(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Панель управления рекрутингом (United Force)",
            description="Список команд для рекрутеров и администрации гильдии:",
            color=discord.Color.blue()
        )
        embed.add_field(name="`/info_rec`", value="Показывает это сообщение для рекрутеров.", inline=False)
        embed.add_field(name="`/start_db <ник>`", value="Парсит детальную статистику игрока с AlbionDB.", inline=False)
        embed.add_field(name="`/start_murder <ник>`", value="Поиск выдающихся киллов игрока (Гучи киллы) с MurderLedger с подробностями.", inline=False)
        embed.add_field(name="`/search_id <ID>`", value="Ищет упоминания пользователя по его Discord ID на сервере.", inline=False)
        embed.add_field(name="`/close_ticket <ник> @юзер`", value="Закрывает тикет рекрутинга (Принят), отправляет подробный отчет в лог-канал и автоматически удаляет этот канал тикета через 5 секунд.", inline=False)
        embed.add_field(name="`/close_ticket_no <ник> [@юзер]`", value="Закрывает тикет как отклоненный, отправляет подробный отчет в канал отклонений и автоматически удаляет этот канал тикета через 5 секунд.", inline=False)
        embed.add_field(name="`/guild_exit <Ник> [Причина] [@Юзер]`", value="Регистрирует выход игрока в бан-канал в точечном формате с автопоиском Discord ID в логах принятия.", inline=False)
        embed.add_field(name="`/left_guild <Ник> [Причина] [@Юзер]`", value="Записывает уход принятого игрока из гильдии в лог отклонений.", inline=False)
        embed.add_field(name="`/ban <Ник> <Дис_Имя> <Дис_ID> <Причина>`", value="Логирует бан игрока в точечном формате в сохраненный канал банов.", inline=False)
        embed.add_field(name="`/ticket_stats`", value="Показывает общую накопленную статистику рекрутинга и банов.", inline=False)
        embed.add_field(name="`/stats`", value="Мониторинг нагрузки на ОЗУ/память, CPU, время работы бота и запуск автоочистки.", inline=False)
        embed.add_field(name="`/guild_roster [файл / текст]`", value="Показывает состав гильдии из загруженного текстового файла или напрямую из переданного текста.", inline=False)
        embed.add_field(name="`/guild_exits [файл / текст]`", value="Обрабатывает список покинувших гильдию и отправляет уведомления в лог-канал банов.", inline=False)
        embed.add_field(name="`/ping_newcomers`", value="Пингует всех новых участников сервера за последние 3 дня с приветственным сообщением.", inline=False)
        embed.add_field(name="`/setting_role @Роль`", value="Устанавливает авторизованную роль для использования команд бота (Админ).", inline=False)
        embed.add_field(name="`/setting_channel #канал`", value="Устанавливает канал для сохранения логов тикетов (только для админов).", inline=False)
        embed.add_field(name="`/setting_ban_channel #канал`", value="Устанавливает канал для сохранения логов банов (только для админов).", inline=False)
        embed.add_field(name="`/setting_rejected_channel #канал`", value="Устанавливает канал для сохранения логов отклоненных тикетов (только для админов).", inline=False)
        embed.add_field(name="`/setting_ping_message <Текст>`", value="Устанавливает приветственный текст для пинга новых участников (только для админов).", inline=False)
        
        # Получаем и отображаем текущие настройки каналов и ролей
        settings = load_settings()
        role_id = settings.get("authorized_role_id")
        ticket_chan_id = settings.get("ticket_log_channel_id")
        ban_chan_id = settings.get("ban_log_channel_id")
        rejected_chan_id = settings.get("rejected_log_channel_id")
        ping_msg = settings.get("newcomers_ping_message", "❌ Не настроено")
        
        role_mention = f"<@&{role_id}>" if role_id else "❌ Не настроена"
        ticket_chan_mention = f"<#{ticket_chan_id}>" if ticket_chan_id else "❌ Не настроен"
        ban_chan_mention = f"<#{ban_chan_id}>" if ban_chan_id else "❌ Не настроен"
        rejected_chan_mention = f"<#{rejected_chan_id}>" if rejected_chan_id else "❌ Не настроен"
        
        settings_text = (
            f"👑 **Авторизованная роль:** {role_mention}\n"
            f"🟢 **Логи принятия:** {ticket_chan_mention}\n"
            f"🚪 **Логи выходов/банов:** {ban_chan_mention}\n"
            f"🔴 **Логи отклоненных:** {rejected_chan_mention}\n"
            f"💬 **Текст пинга новых:** {ping_msg}"
        )
        embed.add_field(name="⚙️ Текущие настройки каналов и ролей:", value=settings_text, inline=False)
        
        embed.set_footer(text="United Force Recruitment Admin Panel")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping_newcomers", description="Пингует участников сервера, зашедших за последние 3 дня, с настроенным сообщением.")
    @has_bot_permission()
    async def ping_newcomers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            three_days_ago = now - datetime.timedelta(days=3)
            
            # Находим новых участников сервера
            newcomers = []
            for member in interaction.guild.members:
                if member.bot:
                    continue
                if member.joined_at and member.joined_at >= three_days_ago:
                    newcomers.append(member)
            
            if not newcomers:
                await interaction.followup.send("🤷 За последние 3 дня на сервер не заходило новых участников.", ephemeral=True)
                return
                
            settings = load_settings()
            custom_message = settings.get("newcomers_ping_message", "Добро пожаловать на сервер United Force!")
            
            # Сортируем новых участников по дате захода (от старых к новым)
            newcomers.sort(key=lambda m: m.joined_at)
            
            # Формируем пинги
            mentions = [m.mention for m in newcomers]
            
            # Так как лимит сообщения в Discord 2000 символов, разобьем пинги на группы
            chunk_size = 50
            chunks = [mentions[i:i + chunk_size] for i in range(0, len(mentions), chunk_size)]
            
            # Отправляем первое сообщение в текущий канал публично
            first_chunk_text = " ".join(chunks[0])
            full_msg = f"{first_chunk_text}\n\n{custom_message}"
            
            if len(full_msg) > 2000:
                await interaction.channel.send(" ".join(chunks[0]))
                await interaction.channel.send(custom_message)
            else:
                await interaction.channel.send(full_msg)
                
            for chunk in chunks[1:]:
                await interaction.channel.send(" ".join(chunk))
                
            await interaction.followup.send(f"✅ Успешно упомянуто новых участников: **{len(newcomers)}**", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Произошла ошибка при выполнении пинга: `{str(e)}`", ephemeral=True)

    @app_commands.command(name="start_db", description="Fetches and displays detailed statistics for a given player.")
    @has_bot_permission()
    async def start_db(self, interaction: discord.Interaction, nickname: str):
        await interaction.response.defer()

        def format_shorthand(value_str):
            if not value_str or value_str == '0':
                return '0'
            try:
                num = int(value_str.replace(',', ''))
                if num >= 1_000_000_000:
                    return f"{num / 1_000_000_000:.1f} billion"
                if num >= 1_000_000:
                    return f"{num / 1_000_000:.1f} million"
                if num >= 1_000:
                    return f"{num / 1_000:.1f}k"
                return str(num)
            except:
                return value_str

        def fetch_data():
            scraper = AlbionScraper()
            try:
                return scraper.get_player_stats(nickname)
            finally:
                scraper.close()

        try:
            data = await asyncio.to_thread(fetch_data)
            
            if not data:
                error_embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"Не удалось получить данные для игрока **{nickname}**. Возможно, профиль скрыт или сайт недоступен.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed)
                return

            encoded_nick = quote(nickname)
            ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
            adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"

            pve = data.get('pve_fame', {})
            gath = data.get('gathering', {})
            craft = data.get('crafting', {})

            text = f"📊 **Статистика игрока: {nickname}**\n"
            text += f"🔗 [MurderLedger Europe]({ml_link}) | [AlbionDB Europe]({adb_link})\n\n"
            
            kill_sh = format_shorthand(data.get('kill_fame'))
            death_sh = format_shorthand(data.get('death_fame'))
            text += f"**PvP Статистика**\n```⚔️ Kill: {kill_sh:<13} | 💀 Death: {death_sh}```\n"

            t_sh = format_shorthand(pve.get('total'))
            r_sh = format_shorthand(pve.get('royal'))
            o_sh = format_shorthand(pve.get('outlands'))
            a_sh = format_shorthand(pve.get('avalon'))
            text += f"**PvE Fame**\n```Total: {t_sh} | Out: {o_sh} | Roy: {r_sh} | Ava: {a_sh}```\n"

            gath_val = gath.get('all', '0')
            try:
                gath_num = int(str(gath_val).replace(',', ''))
                gath_str = f"{gath_num:,}"
            except Exception:
                gath_str = str(gath_val)

            craft_val = craft.get('total', '0')
            try:
                craft_num = int(str(craft_val).replace(',', ''))
                craft_str = f"{craft_num:,}"
            except Exception:
                craft_str = str(craft_val)

            gath_text = f"```All: {gath_str}```"
            craft_text = f"```Total: {craft_str}```"
            text += f"**Сбор (Gathering)**\n{gath_text}\n**Крафт (Crafting)**\n{craft_text}\n"

            history = data.get('guild_history', [])
            if history:
                import re
                from datetime import datetime

                def parse_date_val(d_str):
                    if not d_str: return None
                    d_lower = d_str.lower()
                    if any(w in d_lower for w in ['current', 'present', 'настоящее', 'текущ']):
                        return datetime.now()
                    if 'T' in d_str and '-' in d_str:
                        try:
                            return datetime.fromisoformat(d_str.replace('Z', '+00:00')).replace(tzinfo=None)
                        except Exception:
                            pass
                    clean = re.sub(r'[^\w\s]', '', d_str).strip()
                    month_map = {
                        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
                        'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'мая': 5, 'июн': 6, 'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
                    }
                    parts = clean.split()
                    if len(parts) >= 3:
                        try:
                            day = int(parts[0])
                            m_str = parts[1].lower()[:3]
                            year = int(parts[2])
                            month = month_map.get(m_str, 1)
                            return datetime(year, month, day)
                        except Exception:
                            pass
                    return None

                hist_text = ""
                for idx, h in enumerate(history):
                    first_str = h.get('first_seen', '')
                    last_str = h.get('last_seen', '')
                    is_current = (idx == 0) or any(w in (first_str + ' ' + last_str).lower() for w in ['current', 'present', 'настоящее', 'текущ'])
                    is_fallback = is_current and not any(c.isdigit() for c in first_str)
                    
                    if is_fallback:
                        hist_text += f"• **{h['guild']}** (Текущая гильдия)\n"
                    else:
                        days_text = ""
                        try:
                            d1 = parse_date_val(first_str)
                            d2 = parse_date_val(last_str)
                            if d1 and d2:
                                days = (d2 - d1).days + 1
                                warning = " ❌" if (days < 14 and not is_current) else ""
                                days_text = f" — **{days} дн.**{warning}"
                        except Exception:
                            pass
                        status_tag = " *(Текущая)*" if is_current else ""
                        hist_text += f"• **{h['guild']}**{status_tag} ({first_str} - {last_str}){days_text}\n"
                
                text += f"📜 **История гильдий (все гильдии)**\n{hist_text}\n"

            text += "_Данные получены с europe.albiondb.net_"
            
            if len(text) > 2000:
                text = text[:1997] + "..."
            
            await interaction.followup.send(content=text)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Произошла ошибка",
                description=f"При обработке данных возникла ошибка: `{str(e)}`",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed)

    @app_commands.command(name="stats_db", description="Парсит детальную статистику игрока с Albion API / AlbionDB.")
    @has_bot_permission()
    async def stats_db(self, interaction: discord.Interaction, nickname: str):
        await self.start_db(interaction, nickname)

    async def _fetch_events(self, nickname):

        def fetch():
            scraper = AlbionScraper()
            try:
                return scraper.get_murderledger_events(nickname)
            finally:
                scraper.close()
        return await asyncio.to_thread(fetch)

    @app_commands.command(name="start", description="Fetches and displays only the links of high value kills for a given player.")
    @has_bot_permission()
    async def start(self, interaction: discord.Interaction, nickname: str):
        encoded_nick = quote(nickname)
        text = (
            f"🔗 [MurderLedger - {nickname}](https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger)\n"
            f"🔗 [AlbionDB - {nickname}](https://europe.albiondb.net/player/{encoded_nick})"
        )
        await interaction.response.send_message(text)

    @app_commands.command(name="close_ticket", description="Закрывает тикет рекрутинга и отправляет отчет в сохраненный лог-канал.")
    @app_commands.describe(
        nickname="Игровой никнейм кандидата",
        member_id="Discord ID или упоминание кандидата"
    )
    @has_bot_permission()
    async def close_ticket(self, interaction: discord.Interaction, nickname: str, member_id: str):
        # Отправляем первичное сообщение (невидимое для других, чтобы не спамить в закрываемом тикете)
        await interaction.response.send_message("⏳ *Обработка закрытия тикета и генерация отчета...*", ephemeral=True)
        
        try:
            # Инкрементируем статистику принятых
            increment_stat('closed_tickets_yes', interaction.user.id)

            # Загружаем настройки и получаем сохраненный канал логов
            settings = load_settings()
            channel_id = settings.get("ticket_log_channel_id")
            
            if not channel_id:
                await interaction.edit_original_response(
                    content="❌ **Канал логов не настроен!** Администратор должен сначала задать его командой `/setting_channel`."
                )
                return
                
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                await interaction.edit_original_response(
                    content="❌ **Сохраненный канал логов не найден на этом сервере!** Пожалуйста, перенастройте его с помощью `/setting_channel`."
                )
                return

            # Получаем ссылку на вызванную команду (наше исходное сообщение ответа)
            orig_msg = await interaction.original_response()
            command_url = orig_msg.jump_url
            
            # Кодируем ник для ссылок
            encoded_nick = quote(nickname)
            ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
            adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"
            
            # Парсим ID
            cleaned_member_id = member_id.replace("<", "").replace(">", "").replace("@", "").replace("!", "").strip()
            
            # Пробуем разрешить участника
            resolved_member = None
            try:
                resolved_member = interaction.guild.get_member(int(cleaned_member_id))
            except Exception:
                pass
                
            member_mention = resolved_member.mention if resolved_member else f"<@{cleaned_member_id}>"
            
            # Формируем красивый Embed для лог-канала
            embed = discord.Embed(
                title="🎫 Отчет о закрытии тикета (Принят)",
                color=discord.Color.green(),
                timestamp=interaction.created_at
            )
            
            # Блок Участника
            embed.add_field(
                name="👤 Участник",
                value=(
                    f"**Ник в игре:** `{nickname}`\n"
                    f"**ID:** `{cleaned_member_id}`\n"
                    f"**Ник в Discord:** {member_mention}"
                ),
                inline=False
            )
            
            # Блок Рекрутера
            embed.add_field(
                name="🔑 Рекрутер",
                value=(
                    f"**ID:** `{interaction.user.id}`\n"
                    f"**Ник в Discord:** {interaction.user.mention}"
                ),
                inline=False
            )
            
            # Блок Ссылок как в /start
            embed.add_field(
                name="🔗 Ссылки (Источники данных: MurderLedger & AlbionDB)",
                value=(
                    f"🔗 [MurderLedger - {nickname}]({ml_link})\n"
                    f"🔗 [AlbionDB - {nickname}]({adb_link})"
                ),
                inline=False
            )
            
            # Ссылка на вызванную команду и канал
            ticket_channel_link = f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}"
            embed.add_field(
                name="📍 Место вызова",
                value=(
                    f"**Канал тикета:** <#{interaction.channel_id}> ([Перейти]({ticket_channel_link}))\n"
                    f"**Ссылка на команду:** [Перейти к сообщению]({command_url})"
                ),
                inline=False
            )
            
            embed.set_footer(text=f"Закрыто через бот United Force")
            
            # Отправляем в заданный канал
            log_msg = await channel.send(embed=embed)
            
            # Сохраняем информацию об этом лог-сообщении для последующего редактирования при выходе
            if "acceptance_logs" not in settings:
                settings["acceptance_logs"] = {}
                
            log_entry = {
                "message_id": log_msg.id,
                "channel_id": log_msg.channel.id,
                "recruiter_id": str(interaction.user.id)  # Сохраняем ID рекрутера, который принял
            }
            
            if cleaned_member_id:
                settings["acceptance_logs"][str(cleaned_member_id)] = log_entry
            if nickname:
                settings["acceptance_logs"][nickname.lower()] = log_entry
                
            save_settings(settings)
            
            # Обновляем ответ рекрутеру с ссылкой на созданный лог
            await interaction.edit_original_response(
                content=f"✅ **Тикет успешно обработан!**\nОтчет отправлен в канал {channel.mention}.\n🔗 [Открыть отчет в логах]({log_msg.jump_url})\n\n🔒 *Пожалуйста, нажмите кнопку **Закрыть** (Close) ниже от бота Tickets.bot, чтобы закрыть тикет и сгенерировать веб-транскрипт (историю переписки)!*"
            )
            
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при отправке отчета:** `{str(e)}`"
            )

    @app_commands.command(name="close_ticket_no", description="Закрывает тикет как отклоненный и отправляет отчет в лог-канал отклоненных.")
    @app_commands.describe(
        nickname="Игровой никнейм кандидата (необязательно)",
        member_id="Discord ID или упоминание кандидата (необязательно)"
    )
    @has_bot_permission()
    async def close_ticket_no(self, interaction: discord.Interaction, nickname: str = None, member_id: str = None):
        # Отправляем первичное сообщение
        await interaction.response.send_message("⏳ *Обработка отклонения тикета и генерация отчета...*", ephemeral=True)
        
        try:
            # Инкрементируем статистику отклоненных
            increment_stat('closed_tickets_no', interaction.user.id)
            
            # Загружаем настройки и получаем сохраненный канал логов
            settings = load_settings()
            channel_id = settings.get("rejected_log_channel_id")
            
            if not channel_id:
                await interaction.edit_original_response(
                    content="❌ **Канал логов отклоненных тикетов не настроен!** Администратор должен сначала задать его командой `/setting_rejected_channel`."
                )
                return
                
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                await interaction.edit_original_response(
                    content="❌ **Сохраненный канал логов отклонений не найден!** Пожалуйста, перенастройте его с помощью `/setting_rejected_channel`."
                )
                return

            orig_msg = await interaction.original_response()
            command_url = orig_msg.jump_url
            
            # Формируем красивый Embed для лог-канала
            embed = discord.Embed(
                title="🎫 Отчет об отклонении тикета",
                color=discord.Color.red(),
                timestamp=interaction.created_at
            )
            
            # Разрешаем ID и упоминание
            cleaned_member_id = None
            member_mention = "Не указан"
            if member_id:
                cleaned_member_id = member_id.replace("<", "").replace(">", "").replace("@", "").replace("!", "").strip()
                try:
                    resolved_member = interaction.guild.get_member(int(cleaned_member_id))
                    if resolved_member:
                        member_mention = resolved_member.mention
                    else:
                        member_mention = f"<@{cleaned_member_id}>"
                except Exception:
                    member_mention = f"<@{cleaned_member_id}>"
                    
            nickname_val = f"`{nickname}`" if nickname else "`Не указан`"
            member_id_str = f"`{cleaned_member_id}`" if cleaned_member_id else "`Не указан`"
            
            # Блок Участника
            embed.add_field(
                name="👤 Участник",
                value=(
                    f"**Ник в игре:** {nickname_val}\n"
                    f"**ID:** {member_id_str}\n"
                    f"**Ник в Discord:** {member_mention}"
                ),
                inline=False
            )
            
            # Блок Рекрутера
            embed.add_field(
                name="🔑 Рекрутер",
                value=(
                    f"**ID:** `{interaction.user.id}`\n"
                    f"**Ник в Discord:** {interaction.user.mention}"
                ),
                inline=False
            )
            
            # Блок Ссылок как в /start (указываем источники данных)
            if nickname:
                encoded_nick = quote(nickname)
                ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
                adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"
                embed.add_field(
                    name="🔗 Ссылки (Источники данных: MurderLedger & AlbionDB)",
                    value=(
                        f"🔗 [MurderLedger - {nickname}]({ml_link})\n"
                        f"🔗 [AlbionDB - {nickname}]({adb_link})"
                    ),
                    inline=False
                )
            
            # Ссылка на вызванную команду и канал
            embed.add_field(
                name="📍 Место вызова",
                value=f"**Канал тикета:** `#{interaction.channel.name}` (Канал удален)",
                inline=False
            )
            
            embed.set_footer(text=f"Отклонено через бот United Force")
            
            # Отправляем в заданный канал
            log_msg = await channel.send(embed=embed)
            
            await interaction.edit_original_response(
                content=f"✅ **Тикет успешно обработан как отклоненный!**\nОтчет отправлен в канал {channel.mention}.\n🔗 [Открыть отчет в логах]({log_msg.jump_url})\n\n🔒 *Пожалуйста, нажмите кнопку **Закрыть** (Close) ниже от бота Tickets.bot, чтобы закрыть тикет и сгенерировать веб-транскрипт (историю переписки)!*"
            )
            
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при отправке отчета:** `{str(e)}`"
            )

    @app_commands.command(name="left_guild", description="Помечает, что принятый игрок покинул гильдию.")
    @app_commands.describe(
        nickname="Игровой никнейм игрока (необязательно)",
        member_id="Discord ID или упоминание игрока (необязательно)",
        reason="Причина выхода (необязательно)"
    )
    @has_bot_permission()
    async def left_guild(self, interaction: discord.Interaction, nickname: str = None, member_id: str = None, reason: str = None):
        await interaction.response.send_message("⏳ *Регистрация выхода игрока из гильдии...*", ephemeral=True)
        
        try:
            # Загружаем настройки и получаем сохраненный канал логов
            # Используем канал для отклоненных тикетов как наиболее подходящий, или основной канал тикетов
            settings = load_settings()
            channel_id = settings.get("rejected_log_channel_id") or settings.get("ticket_log_channel_id")
            
            if not channel_id:
                await interaction.edit_original_response(
                    content="❌ **Канал логов отклоненных или принятых тикетов не настроен!** Пожалуйста, настройте его с помощью `/setting_rejected_channel`."
                )
                return
                
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                await interaction.edit_original_response(
                    content="❌ **Сохраненный лог-канал не найден на сервере!**"
                )
                return

            orig_msg = await interaction.original_response()
            command_url = orig_msg.jump_url
            
            # Разрешаем ID и упоминание
            cleaned_member_id = None
            member_mention = "Не указан"
            if member_id:
                cleaned_member_id = member_id.replace("<", "").replace(">", "").replace("@", "").replace("!", "").strip()
                try:
                    resolved_member = interaction.guild.get_member(int(cleaned_member_id))
                    if resolved_member:
                        member_mention = resolved_member.mention
                    else:
                        member_mention = f"<@{cleaned_member_id}>"
                except Exception:
                    member_mention = f"<@{cleaned_member_id}>"
                    
            nickname_val = f"`{nickname}`" if nickname else "`Не указан`"
            member_id_str = f"`{cleaned_member_id}`" if cleaned_member_id else "`Не указан`"
            reason_val = reason if reason else "Не указана"
            
            # Попробуем найти оригинальное сообщение о принятии и его рекрутера
            edited_orig_log = False
            log_entry = None
            original_recruiter_id = None
            
            if cleaned_member_id:
                log_entry = settings.get("acceptance_logs", {}).get(str(cleaned_member_id))
            if not log_entry and nickname:
                log_entry = settings.get("acceptance_logs", {}).get(nickname.lower())
                
            if log_entry:
                original_recruiter_id = log_entry.get("recruiter_id")
                try:
                    target_channel_id = int(log_entry["channel_id"])
                    target_message_id = int(log_entry["message_id"])
                    target_channel = interaction.guild.get_channel(target_channel_id)
                    if target_channel:
                        orig_acceptance_msg = await target_channel.fetch_message(target_message_id)
                        if orig_acceptance_msg and orig_acceptance_msg.embeds:
                            # Редактируем первый Embed
                            orig_embed = orig_acceptance_msg.embeds[0]
                            
                            # Меняем заголовок и цвет
                            orig_embed.title = "🎫 Отчет о закрытии тикета (Принят | 🚪 ПОКИНУЛ ГИЛЬДИЮ)"
                            orig_embed.color = discord.Color.orange()
                            
                            # Добавляем поле о выходе из гильдии
                            reason_text = reason if reason else "Не указана"
                            orig_embed.add_field(
                                name="🚪 Статус: Покинул гильдию",
                                value=(
                                    f"**Зарегистрировал уход:** {interaction.user.mention}\n"
                                    f"**Причина:** {reason_text}\n"
                                    f"**Дата ухода:** <t:{int(interaction.created_at.timestamp())}:f>"
                                ),
                                inline=False
                            )
                            
                            await orig_acceptance_msg.edit(embed=orig_embed)
                            edited_orig_log = True
                except Exception as e:
                    print(f"Ошибка редактирования оригинального сообщения о принятии: {e}")
            
            # Определяем рекрутера, на которого списываем покинувшего гильдию (оригинальный рекрутер или текущий как fallback)
            target_recruiter_id = original_recruiter_id if original_recruiter_id else str(interaction.user.id)
            
            # Инкрементируем статистику вышедших на целевого рекрутера
            increment_stat('left_players', target_recruiter_id)
                    
            embed = discord.Embed(
                title="🚪 Игрок покинул гильдию",
                color=discord.Color.orange(),
                timestamp=interaction.created_at
            )
            
            # Блок Участника
            embed.add_field(
                name="👤 Участник",
                value=(
                    f"**Ник в игре:** {nickname_val}\n"
                    f"**ID:** {member_id_str}\n"
                    f"**Ник в Discord:** {member_mention}"
                ),
                inline=False
            )
            
            # Блок Причины
            embed.add_field(
                name="📝 Детали выхода",
                value=f"**Причина:** {reason_val}",
                inline=False
            )
            
            # Блок Рекрутера
            embed.add_field(
                name="🔑 Зарегистрировал уход",
                value=f"{interaction.user.mention} (ID: `{interaction.user.id}`)",
                inline=False
            )
            
            # Ссылки на MurderLedger / AlbionDB
            if nickname:
                encoded_nick = quote(nickname)
                ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
                adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"
                embed.add_field(
                    name="🔗 Источники данных игрока",
                    value=(
                        f"🔗 [MurderLedger - {nickname}]({ml_link})\n"
                        f"🔗 [AlbionDB - {nickname}]({adb_link})"
                    ),
                    inline=False
                )
                
            embed.set_footer(text="United Force Recruitment")
            
            # Отправляем лог
            log_msg = await channel.send(embed=embed)
            
            notice_text = ""
            if edited_orig_log:
                notice_text = f"\n🔄 **Оригинальное лог-сообщение о принятии на сервере успешно обновлено! Действие привязано к принявшему рекрутеру (<@{target_recruiter_id}>).**"
            else:
                notice_text = "\n⚠️ *Оригинальный лог принятия не найден в базе данных бота. Действие записано на вас.*"
                
            await interaction.edit_original_response(
                content=f"✅ **Выход игрока успешно зарегистрирован!**\nОтчет отправлен в канал {channel.mention}.\n🔗 [Открыть отчет в логах]({log_msg.jump_url}){notice_text}"
            )
            
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при регистрации выхода:** `{str(e)}`"
            )

    @app_commands.command(name="ban", description="Логирует бан игрока в сохраненный бан-канал.")
    @app_commands.describe(
        nickname="Игровой ник (IGN) забаненного игрока (необязательно)",
        ds_name="Ник в Discord (DSN) забаненного игрока (необязательно)",
        ds_id="ID в Discord (DSI) забаненного игрока (необязательно)",
        reason="Причина занесения в бан-лист (REASON) (необязательно)"
    )
    @has_bot_permission()
    async def ban(self, interaction: discord.Interaction, nickname: str = None, ds_name: str = None, ds_id: str = None, reason: str = None):
        await interaction.response.send_message("⏳ *Внесение игрока в бан-лист и генерация отчета...*", ephemeral=True)
        
        try:
            # Инкрементируем статистику банов
            increment_stat('banned_players', interaction.user.id)
            
            # Загружаем настройки и получаем сохраненный канал логов банов
            settings = load_settings()
            channel_id = settings.get("ban_log_channel_id")
            
            if not channel_id:
                await interaction.edit_original_response(
                    content="❌ **Канал логов банов не настроен!** Администратор должен сначала задать его командой `/setting_ban_channel`."
                )
                return
                
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                await interaction.edit_original_response(
                    content="❌ **Сохраненный канал банов не найден на сервере!** Пожалуйста, перенастройте его с помощью `/setting_ban_channel`."
                )
                return
            
            # Определяем значения по умолчанию для пустых полей
            nickname_val = nickname if nickname else "Не указан"
            ds_name_val = ds_name if ds_name else "Не указан"
            ds_id_val = ds_id if ds_id else "Не указан"
            reason_val = reason if reason else "Не указан"
            
            # Формируем сообщение в точечном формате, как просил пользователь
            ban_log_text = (
                f"IGN    {nickname_val}\n"
                f"DSN    {ds_name_val}\n"
                f"DSI    {ds_id_val}\n"
                f"REASON {reason_val}"
            )
            
            # Добавим красивый Embed для наглядности (чтобы это выглядело премиально, но с сохранением оригинального текста)
            embed = discord.Embed(
                title="🔨 Внесение игрока в бан-лист гильдии",
                color=discord.Color.red(),
                timestamp=interaction.created_at
            )
            
            # Блок с точечным логом (удобным для копирования рекрутерами)
            embed.description = f"```text\n{ban_log_text}\n```"
            
            # Ссылка на источники данных как в /start
            if nickname:
                encoded_nick = quote(nickname)
                ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
                adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"
                embed.add_field(
                    name="🔗 Источники данных игрока",
                    value=(
                        f"🔗 [MurderLedger - {nickname}]({ml_link})\n"
                        f"🔗 [AlbionDB - {nickname}]({adb_link})"
                    ),
                    inline=False
                )
            
            # Блок Рекрутера, выдавшего бан
            embed.add_field(
                name="👤 Рекрутер",
                value=f"{interaction.user.mention} (ID: `{interaction.user.id}`)",
                inline=True
            )
            
            embed.set_footer(text="Забанен через бот United Force")
            
            # Отправляем текстовый точечный лог И Embed в заданный канал
            log_msg = await channel.send(content=f"🔨 **Новый бан в системе:**\n```text\n{ban_log_text}\n```", embed=embed)
            
            await interaction.edit_original_response(
                content=f"✅ **Игрок успешно внесен в бан-лист!**\nОтчет отправлен в канал {channel.mention}.\n🔗 [Открыть отчет в логах]({log_msg.jump_url})"
            )
            
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при отправке бана:** `{str(e)}`"
            )

    @app_commands.command(name="ticket_stats", description="Показывает общую накопленную статистику рекрутинга и банов за указанный период.")
    @app_commands.describe(days="Количество последних дней для фильтрации (например, 7 или 30) (необязательно)")
    @has_bot_permission()
    async def ticket_stats(self, interaction: discord.Interaction, days: int = None):
        await interaction.response.send_message("⏳ *Сбор статистических данных...*", ephemeral=True)
        
        try:
            # Загружаем настройки, где хранятся наши счетчики
            settings = load_settings()
            stats = settings.get("stats", {})
            
            yes_count = 0
            no_count = 0
            ban_count = 0
            left_count = 0
            recruiters_display_data = {}
            
            # Если задан период (days)
            if days is not None:
                if days <= 0:
                    await interaction.edit_original_response(content="❌ Количество дней должно быть больше 0.")
                    return
                    
                import datetime
                now = datetime.datetime.utcnow()
                days_limit = now - datetime.timedelta(days=days)
                
                filtered_entries = []
                for entry in stats.get("history", []):
                    try:
                        entry_time = datetime.datetime.fromisoformat(entry["timestamp"])
                        if entry_time >= days_limit:
                            filtered_entries.append(entry)
                    except Exception:
                        continue
                        
                yes_count = sum(1 for e in filtered_entries if e["action"] == "closed_tickets_yes")
                no_count = sum(1 for e in filtered_entries if e["action"] == "closed_tickets_no")
                ban_count = sum(1 for e in filtered_entries if e["action"] == "banned_players")
                left_count = sum(1 for e in filtered_entries if e["action"] == "left_players")
                
                # Собираем данные по рекрутерам за этот период
                for e in filtered_entries:
                    r_id = e.get("recruiter_id")
                    if r_id and r_id != "None":
                        if r_id not in recruiters_display_data:
                            recruiters_display_data[r_id] = {}
                        action = e["action"]
                        recruiters_display_data[r_id][action] = recruiters_display_data[r_id].get(action, 0) + 1
            else:
                # Все время (All Time)
                yes_count = stats.get("closed_tickets_yes", 0)
                no_count = stats.get("closed_tickets_no", 0)
                ban_count = stats.get("banned_players", 0)
                left_count = stats.get("left_players", 0)
                recruiters_display_data = stats.get("recruiters", {})
            
            total_closed = yes_count + no_count
            remained_in_guild = yes_count - left_count
            if remained_in_guild < 0:
                remained_in_guild = 0
                
            period_title = f"за последние {days} дн." if days is not None else "за все время"
            
            # Создаем красивый Embed для статистики
            embed = discord.Embed(
                title=f"📊 Статистика рекрутинга United Force ({period_title})",
                color=discord.Color.blue(),
                timestamp=interaction.created_at
            )
            
            embed.add_field(
                name="📈 Общая статистика гильдии",
                value=(
                    f"🎫 **Всего обработано тикетов:** `{total_closed}`\n"
                    f"🟢 **Приняты (Всего зашли):** `{yes_count}`\n"
                    f"🏠 **Остались в гильдии:** `{remained_in_guild}`\n"
                    f"🚪 **Покинули гильдию:** `{left_count}`\n"
                    f"🔴 **Отклонены:** `{no_count}`\n"
                    f"🔨 **Забанено игроков через бота:** `{ban_count}`"
                ),
                inline=False
            )
            
            # Получаем детальную статистику по каждому рекрутеру
            recruiters_text_list = []
            
            for r_id_str, r_stats in recruiters_display_data.items():
                r_yes = r_stats.get("closed_tickets_yes", 0)
                r_no = r_stats.get("closed_tickets_no", 0)
                r_ban = r_stats.get("banned_players", 0)
                r_left = r_stats.get("left_players", 0)
                r_total = r_yes + r_no
                
                recruiters_text_list.append(
                    f"👤 <@{r_id_str}>\n"
                    f"└─ тикетов: `{r_total}` (🟢 `{r_yes}` / 🔴 `{r_no}`) | 🚪 покинули: `{r_left}` | 🔨 забанено: `{r_ban}`"
                )
                
            recruiters_value = "\n\n".join(recruiters_text_list) if recruiters_text_list else "*Статистика по рекрутерам пока отсутствует.*"
            
            embed.add_field(
                name="👥 Статистика по рекрутерам",
                value=recruiters_value,
                inline=False
            )
            
            # Указываем источник данных
            embed.add_field(
                name="📂 Источник данных статистики",
                value="• Накопление данных производится в конфигурационном файле бота `settings.json`.",
                inline=False
            )
            
            embed.set_footer(text="Статистика United Force")
            
            await interaction.edit_original_response(content=None, embed=embed)
            
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при получении статистики:** `{str(e)}`"
            )

    @app_commands.command(name="search_id", description="Ищет упоминания пользователя по его Discord ID или по игровому нику.")
    @app_commands.describe(
        user_id="ID пользователя или его упоминание (необязательно)",
        nickname="Игровой никнейм для поиска в тексте сообщений (необязательно)"
    )
    @has_bot_permission()
    async def search_id(self, interaction: discord.Interaction, user_id: str = None, nickname: str = None):
        if not user_id and not nickname:
            await interaction.response.send_message("❌ **Пожалуйста, укажите хотя бы один параметр для поиска:** `user_id` или `nickname`.", ephemeral=True)
            return

        # Начинаем поиск
        search_terms = []
        if user_id:
            search_terms.append(f"Discord ID: `{user_id}`")
        if nickname:
            search_terms.append(f"Игровой ник: `{nickname}`")
            
        await interaction.response.send_message(f"🔎 Начинаю поиск упоминаний ({', '.join(search_terms)}) по текстовым каналам...", ephemeral=True)
        
        # Парсим ID
        target_id = None
        if user_id:
            try:
                cleaned_user_id = user_id.replace("<", "").replace(">", "").replace("@", "").replace("!", "").strip()
                target_id = int(cleaned_user_id)
            except ValueError:
                pass
                
        found_messages = []
        # Выбираем текстовые каналы, к которым у бота есть доступ на чтение истории
        channels = [
            c for c in interaction.guild.text_channels 
            if c.permissions_for(interaction.guild.me).read_message_history and c.permissions_for(interaction.guild.me).read_messages
        ]
        
        # Сканируем каналы. Чтобы бот не завис на огромном сервере, ограничим до 150 сообщений в канале и 15 совпадений
        for channel in channels:
            try:
                async for message in channel.history(limit=150):
                    match = False
                    
                    # 1. Поиск по ID в Discord (упоминания или вхождение строки в текст)
                    if user_id:
                        if target_id and target_id in message.raw_mentions:
                            match = True
                        elif str(user_id) in message.content:
                            match = True
                        elif target_id and str(target_id) in message.content:
                            match = True
                            
                    # 2. Поиск по игровому нику (регистронезависимый поиск в тексте сообщения)
                    if nickname and nickname.lower() in message.content.lower():
                        match = True
                        
                    if match:
                        found_messages.append(message)
                        if len(found_messages) >= 15:
                            break
            except Exception:
                continue
            if len(found_messages) >= 15:
                break
                
        if not found_messages:
            await interaction.edit_original_response(content=f"🤷 Совпадений по вашему запросу ({', '.join(search_terms)}) в последних сообщениях каналов не найдено.")
            return
            
        embed = discord.Embed(
            title="🔎 Результаты поиска упоминаний",
            color=discord.Color.blue(),
            description=f"Найденные совпадения ({', '.join(search_terms)}) в последних сообщениях каналов (лимит: 15):"
        )
        
        for idx, msg in enumerate(found_messages, 1):
            channel_link = f"https://discord.com/channels/{interaction.guild_id}/{msg.channel.id}"
            author_mention = msg.author.mention
            content_snippet = (msg.content[:150] + "...") if len(msg.content) > 150 else msg.content
            if not content_snippet:
                content_snippet = "*[Вложение или Embed]*"
                
            field_name = f"{idx}. #{msg.channel.name}"
            field_value = (
                f"**Отправитель:** {author_mention}\n"
                f"**Сообщение:** {content_snippet}\n"
                f"🔗 [Перейти к сообщению]({msg.jump_url}) | [Открыть канал]({channel_link})"
            )
            embed.add_field(name=field_name, value=field_value, inline=False)
            
        await interaction.edit_original_response(content="✅ Поиск успешно завершен!", embed=embed)

    @app_commands.command(name="start_murder", description="Fetches and displays high value kills with details for a given player.")
    @has_bot_permission()
    async def start_murder(self, interaction: discord.Interaction, nickname: str):
        loading_embed = discord.Embed(
            title=f"🔎 Поиск киллов: {nickname}",
            description="Пожалуйста, подождите. Обход защиты и загрузка данных с MurderLedger (около 20 секунд)...",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=loading_embed)

        try:
            events = await self._fetch_events(nickname)
            if events is None:
                error_embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"Не удалось получить киллы для игрока **{nickname}**. Возможно, профиль скрыт или сайт недоступен.",
                    color=discord.Color.red()
                )
                await interaction.edit_original_response(embed=error_embed)
                return

            from datetime import datetime, timedelta
            now = datetime.now()
            two_months_ago = now - timedelta(days=60)
            
            gucci_kills = []
            recent_kills = []

            for event in events:
                total_fame = event.get('total_kill_fame', 0)
                event_time_ts = event.get('time', 0)
                event_time = datetime.fromtimestamp(event_time_ts)
                
                killer = event.get('killer', {})
                victim = event.get('victim', {})
                
                if killer.get('name', '').lower() != nickname.lower():
                    continue
                
                k_name = killer.get('name', 'Unknown')
                k_ally = f"[{killer.get('alliance_name')}]" if killer.get('alliance_name') else ""
                k_guild = killer.get('guild_name', '')
                k_ip = killer.get('item_power', 0)
                
                v_name = victim.get('name', 'Unknown')
                v_ally = f"[{victim.get('alliance_name')}]" if victim.get('alliance_name') else ""
                v_guild = victim.get('guild_name', '')
                v_ip = victim.get('item_power', 0)
                
                k_str = f"{k_name} {k_ally} {k_guild}".strip()
                v_str = f"{v_name} {v_ally} {v_guild}".strip()
                
                days_ago = (now - event_time).days
                if days_ago == 0:
                    time_str = "Today"
                elif days_ago < 30:
                    time_str = f"{days_ago} days ago"
                else:
                    time_str = f"{days_ago // 30} months ago"

                event_id = event.get('id')
                link = f"https://murderledger-europe.albiononline2d.com/events/{event_id}"
                
                kill_entry = (
                    f"{k_str} ({k_ip} IP) | {v_str} ({v_ip} IP)\n"
                    f"{total_fame:,} Fame | {time_str}\n"
                    f"🔗 [Ссылка на килл]({link})"
                )

                if total_fame > 1_000_000:
                    gucci_kills.append(kill_entry)
                elif total_fame > 500_000 and event_time >= two_months_ago:
                    recent_kills.append(kill_entry)

            gucci_kills = gucci_kills[:5]
            recent_kills = recent_kills[:5]

            text = f"⚔️ **Киллы игрока: {nickname}**\n\n"
            separator = "\n\n"

            if gucci_kills:
                text += "💎 **Подпись Гучи килл (Fame > 1kk)**\n"
                text += separator.join(gucci_kills) + "\n\n"
            
            if recent_kills:
                text += "🔥 **Килы за последние 2 месяца (Fame > 500k)**\n"
                text += separator.join(recent_kills) + "\n\n"

            if not gucci_kills and not recent_kills:
                text += "Нет Гучи киллов (> 1kk) или недавних киллов (> 500k за 2 мес).\n"

            if len(text) > 2000:
                text = text[:1997] + "..."

            await interaction.edit_original_response(content=text, embed=None)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Произошла ошибка",
                description=f"При обработке данных возникла ошибка: `{str(e)}`",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=error_embed)

    @app_commands.command(name="guild_roster", description="Показывает текущий состав гильдии из файла или текста.")
    @app_commands.describe(
        file="Текстовый файл состава (например, guild.txt) (необязательно)",
        text="Текст состава гильдии (необязательно)"
    )
    @has_bot_permission()
    async def guild_roster(self, interaction: discord.Interaction, file: discord.Attachment = None, text: str = None):
        if not file and not text:
            await interaction.response.send_modal(RosterModal(self))
            return

        await interaction.response.send_message("⏳ *Обработка списка состава гильдии...*", ephemeral=True)
        
        try:
            if file:
                file_content = await file.read()
                # Пробуем декодировать
                try:
                    raw_text = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        raw_text = file_content.decode('cp1251')
                    except UnicodeDecodeError:
                        await interaction.edit_original_response(content="❌ **Ошибка кодировки.** Файл должен быть в формате UTF-8.")
                        return
            else:
                raw_text = text

            roster = parse_roster_text(raw_text)
            if not roster:
                await interaction.edit_original_response(content="⚠️ Не удалось найти корректные данные в переданном источнике.")
                return
                
            embed = discord.Embed(title="📜 Текущий состав гильдии", color=discord.Color.blue())
            
            # Разделяем на чанки, чтобы не превысить лимит (4096 символов для description)
            chunks = []
            current_chunk = ""
            for item in roster:
                if len(current_chunk) + len(item) + 2 > 4000:
                    chunks.append(current_chunk)
                    current_chunk = item + "\n"
                else:
                    current_chunk += item + "\n"
            if current_chunk:
                chunks.append(current_chunk)
                
            embed.description = chunks[0]
            embed.set_footer(text=f"Всего игроков: {len(roster)}")
                
            await interaction.edit_original_response(content="✅ Список состава гильдии сформирован:", embed=embed)
            
            # Отправляем остальные части, если они есть
            for chunk in chunks[1:]:
                chunk_embed = discord.Embed(description=chunk, color=discord.Color.blue())
                await interaction.followup.send(embed=chunk_embed, ephemeral=True)
                
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ **Ошибка при обработке состава гильдии:** `{str(e)}`")

    @app_commands.command(name="guild_exit", description="Регистрирует выход игрока и логирует его в бан-канал.")
    @app_commands.describe(
        nickname="Игровой никнейм игрока (IGN)",
        reason="Причина выхода (по умолчанию: Покинул без пояснений)",
        member_id="Discord ID или упоминание игрока (необязательно)"
    )
    @has_bot_permission()
    async def guild_exit(self, interaction: discord.Interaction, nickname: str, reason: str = "Покинул без пояснений", member_id: str = None):
        await interaction.response.send_message("⏳ *Обработка регистрации выхода игрока...*", ephemeral=True)
        
        try:
            settings = load_settings()
            ban_channel_id = settings.get("ban_log_channel_id")
            
            if not ban_channel_id:
                await interaction.edit_original_response(
                    content="❌ **Канал логов банов/выходов не настроен!** Администратор должен сначала задать его командой `/setting_ban_channel`."
                )
                return
                
            ban_channel = interaction.guild.get_channel(int(ban_channel_id))
            if not ban_channel:
                await interaction.edit_original_response(
                    content="❌ **Сохраненный канал банов/выходов не найден на сервере!** Пожалуйста, перенастройте его с помощью `/setting_ban_channel`."
                )
                return

            ign = nickname
            ign_lower = ign.lower()
            dsi = member_id if member_id else "Неизвестно"
            dsn = "Неизвестно"
            
            # Попробуем распарсить member_id, если он передан
            if member_id:
                dsi = member_id.replace("<", "").replace(">", "").replace("@", "").replace("!", "").strip()
            
            # Если Discord ID не передан, ищем его в логах принятия
            acceptance_logs = settings.get("acceptance_logs", {})
            log_entry = None
            if dsi == "Неизвестно":
                log_entry = acceptance_logs.get(ign_lower)
                if log_entry:
                    msg_id = log_entry.get("message_id")
                    for k, v in acceptance_logs.items():
                        if k != ign_lower and k.isdigit() and isinstance(v, dict) and v.get("message_id") == msg_id:
                            dsi = k
                            break
            else:
                log_entry = acceptance_logs.get(dsi) or acceptance_logs.get(ign_lower)

            # Определяем Discord Name (dsn) по ID
            if dsi != "Неизвестно":
                try:
                    member = interaction.guild.get_member(int(dsi))
                    if member:
                        dsn = member.name
                    else:
                        try:
                            user = await self.bot.fetch_user(int(dsi))
                            dsn = user.name
                        except Exception:
                            pass
                except Exception:
                    pass

            # Попробуем обновить оригинальный Embed принятия, если лог найден
            edited_orig_log = False
            original_recruiter_id = None
            if log_entry:
                original_recruiter_id = log_entry.get("recruiter_id")
                try:
                    target_channel_id = int(log_entry["channel_id"])
                    target_message_id = int(log_entry["message_id"])
                    target_channel = interaction.guild.get_channel(target_channel_id)
                    if target_channel:
                        orig_acceptance_msg = await target_channel.fetch_message(target_message_id)
                        if orig_acceptance_msg and orig_acceptance_msg.embeds:
                            orig_embed = orig_acceptance_msg.embeds[0]
                            orig_embed.title = "🎫 Отчет о закрытии тикета (Принят | 🚪 ПОКИНУЛ ГИЛЬДИЮ)"
                            orig_embed.color = discord.Color.orange()
                            orig_embed.add_field(
                                name="🚪 Статус: Покинул гильдию",
                                value=(
                                    f"**Зарегистрировал уход:** {interaction.user.mention}\n"
                                    f"**Причина:** {reason}\n"
                                    f"**Дата ухода:** <t:{int(interaction.created_at.timestamp())}:f>"
                                ),
                                inline=False
                            )
                            await orig_acceptance_msg.edit(embed=orig_embed)
                            edited_orig_log = True
                except Exception as e:
                    print(f"Ошибка редактирования оригинального сообщения о принятии: {e}")

            # Инкрементируем статистику вышедших на оригинального рекрутера (или текущего)
            target_recruiter_id = original_recruiter_id if original_recruiter_id else str(interaction.user.id)
            increment_stat('left_players', target_recruiter_id)

            # Формируем точечный текст сообщения для лог-канала банов
            ban_log_text = (
                f"IGN    {ign}\n"
                f"DSN    {dsn}\n"
                f"DSI    {dsi}\n"
                f"REASON {reason}"
            )
            
            # Красивый Embed с подробными ссылками на MurderLedger и AlbionDB
            encoded_nick = quote(ign)
            ml_link = f"https://murderledger-europe.albiononline2d.com/players/{encoded_nick}/ledger"
            adb_link = f"https://europe.albiondb.net/player/{encoded_nick}"
            
            embed = discord.Embed(
                title="🚪 Регистрация выхода из гильдии",
                color=discord.Color.orange(),
                timestamp=interaction.created_at
            )
            embed.description = f"```text\n{ban_log_text}\n```"
            embed.add_field(
                name="🔗 Источники данных игрока",
                value=(
                    f"🔗 [MurderLedger - {ign}]({ml_link})\n"
                    f"🔗 [AlbionDB - {ign}]({adb_link})"
                ),
                inline=False
            )
            embed.add_field(
                name="👤 Зарегистрировал уход",
                value=f"{interaction.user.mention} (ID: `{interaction.user.id}`)",
                inline=True
            )
            embed.set_footer(text="United Force Recruitment")

            # Отправляем сообщение в бан-канал
            # Сначала чисто текстовый лог, затем красивый Embed
            log_msg = await ban_channel.send(
                content=f"🚪 **Игрок покинул гильдию:**\n```text\n{ban_log_text}\n```",
                embed=embed
            )

            notice_text = ""
            if edited_orig_log:
                notice_text = f"\n🔄 **Оригинальное лог-сообщение о принятии на сервере успешно обновлено! Действие привязано к принявшему рекрутеру (<@{target_recruiter_id}>).**"
            else:
                notice_text = "\n⚠️ *Оригинальный лог принятия не найден в базе данных бота. Действие записано на рекрутера, вызвавшего команду.*"

            await interaction.edit_original_response(
                content=f"✅ **Выход игрока успешно зарегистрирован!**\nЛог отправлен в бан-канал {ban_channel.mention}.\n🔗 [Открыть лог]({log_msg.jump_url}){notice_text}"
            )

        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ **Произошла ошибка при регистрации выхода:** `{str(e)}`"
            )

    @app_commands.command(name="guild_exits", description="Обрабатывает список покинувших гильдию из файла или текста.")
    @app_commands.describe(
        file="Текстовый файл покинувших гильдию (например, exits.txt) (необязательно)",
        text="Текст покинувших гильдию (необязательно)"
    )
    @has_bot_permission()
    async def guild_exits(self, interaction: discord.Interaction, file: discord.Attachment = None, text: str = None):
        if not file and not text:
            await interaction.response.send_modal(ExitsModal(self))
            return

        await interaction.response.send_message("⏳ *Обработка списка покинувших гильдию...*", ephemeral=True)
        
        settings = load_settings()
        ban_channel_id = settings.get("ban_log_channel_id")
        
        if not ban_channel_id:
            await interaction.edit_original_response(content="❌ **Канал логов банов не настроен!** Администратор должен сначала задать его командой `/setting_ban_channel`.")
            return
            
        ban_channel = interaction.guild.get_channel(int(ban_channel_id))
        if not ban_channel:
            await interaction.edit_original_response(content="❌ **Сохраненный канал банов не найден на сервере!** Пожалуйста, перенастройте его с помощью `/setting_ban_channel`.")
            return
            
        try:
            if file:
                file_content = await file.read()
                # Пробуем декодировать
                try:
                    raw_text = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        raw_text = file_content.decode('cp1251')
                    except UnicodeDecodeError:
                        await interaction.edit_original_response(content="❌ **Ошибка кодировки.** Файл должен быть в формате UTF-8.")
                        return
            else:
                raw_text = text

            last_date = settings.get("last_processed_exit_date", "")
            acceptance_logs = settings.get("acceptance_logs", {})
            new_exits, new_last_date = parse_exits_text(raw_text, last_date)
            
            if not new_exits:
                await interaction.edit_original_response(content="⚠️ В переданном источнике нет новых записей о покинувших игроках.")
                return
                
            sent_count = 0
            
            # Отправляем новых игроков в бан-канал
            for date_str, ign in reversed(new_exits): # от старых к новым
                ign_lower = ign.lower()
                dsi = "Неизвестно"
                dsn = "Неизвестно"
                
                # Ищем DSI
                log_entry = acceptance_logs.get(ign_lower)
                if log_entry:
                    msg_id = log_entry.get("message_id")
                    for k, v in acceptance_logs.items():
                        if k != ign_lower and k.isdigit() and isinstance(v, dict) and v.get("message_id") == msg_id:
                            dsi = k
                            break
                            
                # Ищем DSN
                if dsi != "Неизвестно":
                    member = interaction.guild.get_member(int(dsi))
                    if member:
                        dsn = member.name
                    else:
                        try:
                            user = await self.bot.fetch_user(int(dsi))
                            dsn = user.name
                        except Exception:
                            pass
                            
                ban_log_text = (
                    f"IGN    {ign}\n"
                    f"DSN    {dsn}\n"
                    f"DSI    {dsi}\n"
                    f"REASON Покинул гильдию ({date_str})"
                )
                
                await ban_channel.send(f"🚪 **Игрок покинул гильдию:**\n```text\n{ban_log_text}\n```")
                sent_count += 1
                
            # Сохраняем новую дату, если мы обрабатывали файл с датами
            if new_last_date > last_date:
                settings["last_processed_exit_date"] = new_last_date
                save_settings(settings)
                
            await interaction.edit_original_response(content=f"✅ Обработано **{sent_count}** покинувших гильдию игроков. Логи отправлены в {ban_channel.mention}.")
            
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ **Ошибка при обработке списка выходов:** `{str(e)}`")

    @app_commands.command(name='ava_portal', description="Информация о локации Авалонского портала")
    @app_commands.describe(location="Название аволонской локации (например: Fynitos-Ezatam)")
    @has_bot_permission()
    async def ava_portal(self, interaction: discord.Interaction, location: str):
        loc_clean = location.strip().lower()
        found = None
        for p in self.portals:
            if p['location'].lower() == loc_clean:
                found = p
                break
                
        if not found:
            return await interaction.response.send_message(
                f"❌ Локация `{location}` не найдена! Убедитесь, что выбрали локацию из выпадающего списка.",
                ephemeral=True
            )
            
        raw_contents = found.get('contents', '')
        contents_list = [c.strip() for c in raw_contents.split(',') if c.strip()]
        formatted_contents = ""
        for i, c in enumerate(contents_list):
            if i < len(contents_list) - 1:
                formatted_contents += f"{c}, \n"
            else:
                formatted_contents += f"{c}"

        description_text = (
            f"📍 **Тир локации** {found.get('tier', 'Неизвестно')}\n"
            f"📦 **Размер сундуков**\n{found.get('size', 'Неизвестно')}\n"
            f"✨ **Содержимое**\n{formatted_contents if formatted_contents else 'Пусто'}"
        )

        embed = discord.Embed(
            title=f"🌀 Авалонский портал: {found['location']}",
            description=description_text,
            color=discord.Color.from_str("#00FFD8")
        )
        embed.set_footer(text="United Force • База данных Авалона")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)

    @ava_portal.autocomplete('location')
    async def ava_portal_location_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()
        
        choices = []
        for p in self.portals:
            loc_name = p['location']
            if not current_lower or current_lower in loc_name.lower():
                choices.append(app_commands.Choice(name=loc_name, value=loc_name))
                if len(choices) >= 25:
                    break
        return choices

async def setup(bot):
    await bot.add_cog(Recruiter(bot))
