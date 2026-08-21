import urllib
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
            import json
            import re
            import urllib
            import urllib.parse
            from datetime import datetime

            def get_options():
                opts = uc.ChromeOptions()
                opts.add_argument('--headless=new')
                opts.add_argument('--no-sandbox')
                opts.add_argument('--disable-dev-shm-usage')
                opts.add_argument('--window-size=1200,800')
                return opts

            def get_installed_chrome_version():
                import subprocess
                reg_keys = [
                    r'HKCU\Software\Google\Chrome\BLBeacon',
                    r'HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome',
                    r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome'
                ]
                for key in reg_keys:
                    try:
                        out = subprocess.check_output(f'reg query "{key}" /v version', shell=True, text=True, stderr=subprocess.DEVNULL)
                        m = re.search(r'(\d+)\.\d+\.\d+\.\d+', out)
                        if m:
                            return int(m.group(1))
                    except Exception:
                        pass
                    try:
                        out = subprocess.check_output(f'reg query "{key}" /v DisplayVersion', shell=True, text=True, stderr=subprocess.DEVNULL)
                        m = re.search(r'(\d+)\.\d+\.\d+\.\d+', out)
                        if m:
                            return int(m.group(1))
                    except Exception:
                        pass

                for cmd in ['google-chrome --version', 'chromium --version', 'chromium-browser --version']:
                    try:
                        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
                        m = re.search(r'(\d+)\.\d+\.\d+\.\d+', out)
                        if m:
                            return int(m.group(1))
                    except Exception:
                        pass
                return None

            detected_v = get_installed_chrome_version()
            version_candidates = []
            if detected_v:
                version_candidates.append(detected_v)
            for v_opt in [None, 151, 152, 153, 130]:
                if v_opt not in version_candidates:
                    version_candidates.append(v_opt)

            driver = None
            for v in version_candidates:
                try:
                    driver = uc.Chrome(options=get_options(), version_main=v) if v else uc.Chrome(options=get_options())
                    if driver:
                        break
                except Exception:
                    pass

            if not driver:
                print("Could not create undetected_chromedriver instance.")
                return []

            def fetch_single_url(target_nick):
                try:
                    driver.get(f"https://europe.albiondb.net/player/{urllib.parse.quote(target_nick)}")
                    time.sleep(3)
                    html = driver.page_source
                    soup = BeautifulSoup(html, 'html.parser')
                    next_script = soup.find('script', id='__NEXT_DATA__')
                    items = []
                    if next_script and next_script.string:
                        next_data = json.loads(next_script.string)
                        history_data = next_data.get('props', {}).get('pageProps', {}).get('history', [])
                        for h_item in history_data:
                            g_name = h_item.get('guild_name', '')
                            if g_name:
                                f_date = format_iso_date(h_item.get('first_seen'))
                                l_date = format_iso_date(h_item.get('last_seen'))
                                items.append({
                                    'guild': g_name,
                                    'first_seen': f_date,
                                    'last_seen': l_date
                                })
                    if not items:
                        table = soup.find('table', class_=re.compile(r'guild-history-table|ranking-table'))
                        if not table:
                            history_header = None
                            for h_tag in soup.find_all(['h1', 'h2', 'h3']):
                                if 'Guild History' in h_tag.get_text():
                                    history_header = h_tag
                                    break
                            if history_header:
                                table = history_header.find_next('table')

                        if table:
                            tbody = table.find('tbody')
                            rows = tbody.find_all('tr') if tbody else table.find_all('tr')
                            for row in rows:
                                cols = row.find_all('td')
                                if len(cols) >= 5:
                                    g_link = cols[0].find('a') or cols[0].find('strong')
                                    g_name = g_link.get_text(strip=True) if g_link else cols[0].get_text(strip=True)
                                    for badge in ['CURRENT', 'REJOINED', 'SPELL', 'Previous', 'Current']:
                                        g_name = re.sub(r'\b' + badge + r'\b', '', g_name, flags=re.IGNORECASE).strip()
                                    
                                    time_first = cols[3].find('time')
                                    first_seen = time_first.get_text(strip=True) if time_first else cols[3].get_text(strip=True)
                                    
                                    time_last = cols[4].find('time')
                                    last_seen = time_last.get_text(strip=True) if time_last else cols[4].get_text(strip=True)
                                    
                                    if g_name:
                                        items.append({
                                            'guild': g_name,
                                            'first_seen': first_seen,
                                            'last_seen': last_seen
                                        })
                    return items
                except Exception:
                    return []

            def format_iso_date(d_str):
                if not d_str:
                    return ""
                if any(w in str(d_str).lower() for w in ['current', 'present', 'настоящее', 'текущ']):
                    return "Present"
                months_ru = ['янв.', 'фев.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сен.', 'окт.', 'ноя.', 'дек.']
                try:
                    if 'T' in str(d_str):
                        dt = datetime.fromisoformat(str(d_str).replace('Z', '+00:00'))
                        return f"{dt.day} {months_ru[dt.month - 1]} {dt.year} г."
                except Exception:
                    pass
                return str(d_str)

            best_history = fetch_single_url(nickname)

            # If 1 or 0 items, check nickname variations (e.g. c <-> s ending) to find full profile
            if len(best_history) <= 1:
                variations = []
                if nickname.lower().endswith('c'):
                    variations.append(nickname[:-1] + 's')
                    variations.append(nickname[:-1] + 'S')
                elif nickname.lower().endswith('s'):
                    variations.append(nickname[:-1] + 'c')
                    variations.append(nickname[:-1] + 'C')
                
                for var_nick in variations:
                    var_history = fetch_single_url(var_nick)
                    if len(var_history) > len(best_history):
                        best_history = var_history

            try:
                driver.quit()
            except Exception:
                pass

            return best_history
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

