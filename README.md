# 📊 United Force • Recruiter & Stats Bot

Профессиональный Discord-бот, разработанный специально для рекрутеров и офицеров гильдии **United Force** в Albion Online. Преддназначен для быстрого получения игровой статистики кандидатов напрямую с платформ **AlbionDB** и **MurderLedger** в реальном времени через слэш-команды Discord.

---

## 🚀 Основные возможности

*   **⚡ Быстрые ссылки (`/start`)**: Мгновенное создание кликабельных переходов на профили игрока на MurderLedger и AlbionDB.
*   **⚔️ Анализ PvP-киллов (`/start_murder`)**: Автоматический парсинг и отображение выдающихся убийств игрока с MurderLedger:
    *   **💎 Gucci Kills** — убийства игроков с ценностью (Fame) более 1 000 000.
    *   **🔥 Недавние крупные киллы** — убийства с Fame > 500k за последние 2 месяца.
*   **📊 Игровая статистика (`/start_db`)**: Глубокий разбор игровой активности персонажа на сервере Europe:
    *   ⚔️ **PvP Статистика**: общее количество Fame за убийства и смерти.
    *   🛡️ **PvE Fame**: детальное разделение опыта (Total, Outlands, Royal, Avalon).
    *   🎒 **Сбор и Крафт**: общие показатели очков активности сбора и крафта.
    *   📜 **История гильдий**: полный список прошлых гильдий кандидата с подсчетом дней, проведенных в каждой из них (🔴 помечает гильдии, где игрок пробыл менее 7 дней).
*   **🛡️ Безопасность и права**: Система контроля доступа к командам бота на основе ролей Discord.

---

## 📂 Структура файлов проекта

*   📄 **[main.py](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/main.py)** — Главная точка входа. Создает экземпляр бота, загружает расширения (cogs) и отвечает за синхронизацию командного дерева (`app_commands.tree`).
*   📄 **[scraper.py](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/scraper.py)** — Ядро парсинга. Реализует обход защиты (Cloudflare/User-Agents) и парсит JSON/HTML структуры сайтов AlbionDB и MurderLedger.
*   📄 **[settings_manager.py](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/settings_manager.py)** — Управляет доступами к командам бота, сохраняя ID авторизованной роли в `settings.json`.
*   📁 **[cogs/](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/cogs)** — Папка модулей команд бота:
    *   [recruiter.py](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/cogs/recruiter.py) — Основные команды сбора статистики (`/start`, `/start_db`, `/start_murder`, `/info`, тикеты, статистика).
    *   [admin.py](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/cogs/admin.py) — Управление настройками роли доступа и лог-каналов (`/setting_role`, `/setting_channel` и др.).
*   📄 **[requirements.txt](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/requirements.txt)** — Необходимые для работы библиотеки.
*   📄 **[discloud.config](file:///c:/Users/Ivan/Desktop/Discord%20Bot/Recruiter/discloud.config)** — Файл конфигурации хостинга Discloud.

---

## 🛠️ Слэш-команды бота (Slash Commands)

> [!NOTE]
> Все команды бота переведены на современный формат слэш-команд Discord (`/`).

### 👥 Для рекрутеров и участников
*   `/start_db [nickname]` — Детальный парсинг игровой статистики (PvP, PvE, крафт, сбор и полная история гильдий).
*   `/start_murder [nickname]` — Вывод подробного лога Gucci-киллов игрока (свыше 1kk ценности) и крупных убийств за последние 2 месяца.
*   `/start [nickname]` — Быстрый вывод ссылок на профили игрока на MurderLedger и AlbionDB.
*   `/info` — Красивое интерактивное Embed-меню с описанием команд.
*   `/stats` — Мониторинг использования ОЗУ (памяти в MB / % от лимита 100MB Discloud), CPU, Uptime и принудительный запуск сборщика мусора (GC).


### 🔑 Для администраторов сервера
*   `/setting_role [role]` — Привязывает минимальную роль в Discord, обладатели которой могут использовать команды бота. (Требуются права Администратора).

---

## ⚙️ Установка и запуск

### 1. Требования
*   Python 3.10+
*   Токен Discord-бота (полученный в [Discord Developer Portal](https://discord.com/developers/applications))

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 3. Настройка окружения
Создайте файл `.env` в корневой директории бота:
```env
DISCORD_TOKEN=ваш_токен_бота_здесь
```

### 4. Запуск бота
```bash
python main.py
```

---

## ☁️ Деплой на Discloud

Бот полностью подготовлен для деплоя на хостинг **Discloud**:
1. Настроена конфигурация в `discloud.config` (RAM 100MB, Python 3.11).
2. Для деплоя упакуйте файлы проекта в ZIP-архив и загрузите в панель Discloud.

