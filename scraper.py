import urllib.request
import urllib.parse
import json
import datetime
import gc

class AlbionScraper:
    def __init__(self):
        pass

    def get_guild_history_albiondb(self, nickname):
        """Fetches full guild history table from europe.albiondb.net using undetected_chromedriver."""
        try:
            import undetected_chromedriver as uc
            from bs4 import BeautifulSoup
            import time

            options = uc.ChromeOptions()
            options.add_argument('--window-size=1200,800')

            driver = None
            try:
                driver = uc.Chrome(options=options, version_main=151)
            except Exception:
                try:
                    driver = uc.Chrome(options=options)
                except Exception:
                    pass

            if not driver:
                return []

            driver.get(f"https://europe.albiondb.net/player/{nickname}")
            time.sleep(7)
            html = driver.page_source

            try:
                driver.quit()
            except Exception:
                pass

            soup = BeautifulSoup(html, 'html.parser')
            guild_history = []
            history_header = None
            for h2 in soup.find_all('h2'):
                if 'Guild History' in h2.get_text():
                    history_header = h2
                    break

            if history_header:
                table = history_header.find_next('table')
                if table:
                    tbody = table.find('tbody')
                    rows = tbody.find_all('tr') if tbody else table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 5:
                            g_name = cols[0].get_text(strip=True)
                            first_seen = cols[3].get_text(strip=True)
                            last_seen = cols[4].get_text(strip=True)
                            if g_name:
                                guild_history.append({
                                    'guild': g_name,
                                    'first_seen': first_seen,
                                    'last_seen': last_seen
                                })
            return guild_history
        except Exception as e:
            print(f"AlbionDB history fetch error: {e}")
            return []

    def get_player_stats(self, nickname):
        """Fetches detailed player statistics using official Albion Online Europe API + AlbionDB history."""
        try:
            encoded_nick = urllib.parse.quote(nickname)
            # 1. Search player ID
            search_url = f"https://gameinfo-ams.albiononline.com/api/gameinfo/search?q={encoded_nick}"
            req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                search_data = json.loads(resp.read().decode('utf-8'))
                players = search_data.get('players', [])
                exact = [p for p in players if p.get('Name', '').lower() == nickname.lower()]
                if not exact and players:
                    exact = [players[0]]
                if not exact:
                    return None
                player_info = exact[0]
                player_id = player_info['Id']

            # 2. Get player details
            details_url = f"https://gameinfo-ams.albiononline.com/api/gameinfo/players/{player_id}"
            req_d = urllib.request.Request(details_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req_d, timeout=10) as resp_d:
                p_data = json.loads(resp_d.read().decode('utf-8'))

            lifetime = p_data.get('LifetimeStatistics', {})
            pve = lifetime.get('PvE', {})
            gath = lifetime.get('Gathering', {}).get('All', {})
            craft = lifetime.get('Crafting', {})

            current_guild = p_data.get('GuildName', '')

            # 3. Get Guild History from AlbionDB
            history = self.get_guild_history_albiondb(nickname)
            if not history and current_guild:
                history = [
                    {
                        'guild': current_guild,
                        'first_seen': 'Current',
                        'last_seen': 'Present'
                    }
                ]

            data = {
                'kill_fame': str(p_data.get('KillFame', 0)),
                'death_fame': str(p_data.get('DeathFame', 0)),
                'pve_fame': {
                    'total': str(pve.get('Total', 0)),
                    'royal': str(pve.get('Royal', 0)),
                    'outlands': str(pve.get('Outlands', 0)),
                    'avalon': str(pve.get('Avalon', 0))
                },
                'gathering': {
                    'all': str(gath.get('Total', 0))
                },
                'crafting': {
                    'total': str(craft.get('Total', 0))
                },
                'guild_history': history
            }
            return data
        except Exception as e:
            print(f"Error fetching official player stats for {nickname}: {e}")
            return None
        finally:
            gc.collect()


    def get_murderledger_events(self, nickname):
        """Fetches top kill events from official Albion Online Europe API."""
        try:
            encoded_nick = urllib.parse.quote(nickname)
            search_url = f"https://gameinfo-ams.albiononline.com/api/gameinfo/search?q={encoded_nick}"
            req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                search_data = json.loads(resp.read().decode('utf-8'))
                players = search_data.get('players', [])
                exact = [p for p in players if p.get('Name', '').lower() == nickname.lower()]
                if not exact:
                    return []
                player_id = exact[0]['Id']

            kills_url = f"https://gameinfo-ams.albiononline.com/api/gameinfo/players/{player_id}/topkills"
            req_k = urllib.request.Request(kills_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req_k, timeout=10) as resp_k:
                kills_data = json.loads(resp_k.read().decode('utf-8'))

            events = []
            for k in kills_data:
                killer = k.get('Killer', {})
                victim = k.get('Victim', {})
                time_str = k.get('TimeStamp', '')
                time_ts = int(datetime.datetime.now().timestamp())
                try:
                    dt = datetime.datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    time_ts = int(dt.timestamp())
                except Exception:
                    pass

                victim_fame = k.get('TotalVictimKillFame') or victim.get('KillFame') or 500000

                events.append({
                    'id': k.get('EventId'),
                    'total_kill_fame': victim_fame,
                    'time': time_ts,
                    'killer': {
                        'name': killer.get('Name', ''),
                        'alliance_name': killer.get('AllianceName', ''),
                        'guild_name': killer.get('GuildName', ''),
                        'item_power': int(killer.get('AverageItemPower', 0))
                    },
                    'victim': {
                        'name': victim.get('Name', ''),
                        'alliance_name': victim.get('AllianceName', ''),
                        'guild_name': victim.get('GuildName', ''),
                        'item_power': int(victim.get('AverageItemPower', 0))
                    }
                })
            return events
        except Exception as e:
            print(f"Error fetching top kills for {nickname}: {e}")
            return []
        finally:
            gc.collect()

    def close(self):
        gc.collect()

if __name__ == "__main__":
    scraper = AlbionScraper()
    print("Testing official scraper:")
    stats = scraper.get_player_stats("SERQxQ")
    print(json.dumps(stats, indent=4, ensure_ascii=False))

