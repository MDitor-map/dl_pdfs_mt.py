#!/usr/bin/env python3
"""
Télécharge récursivement tous les fichiers PDF d'un site web.
Fonctionnalités : Multithreading, respect du robots.txt, détection de wrappers HTML.
"""

import os
import sys
import time
import argparse
import queue
import threading
import re
import warnings
import requests
from urllib.parse import urljoin, urlparse
from urllib import robotparser
from bs4 import BeautifulSoup
from tqdm import tqdm

warnings.filterwarnings('ignore', category=UserWarning, module='bs4')


class PDFCrawlerMT:
    def __init__(self, start_url, output_dir="./pdfs", max_depth=3, delay=0.5,
                 max_files=None, threads=5, check_robots=True, debug=False):
        self.start_url = start_url.rstrip("/")
        self.output_dir = output_dir
        self.max_depth = max_depth
        self.delay = delay
        self.max_files = max_files
        self.threads = threads
        self.check_robots = check_robots
        self.debug = debug

        self.url_queue = queue.Queue()
        self.visited = set()
        self.visited_lock = threading.Lock()
        self.downloaded_count = 0
        self.stats_lock = threading.Lock()
        self.stop_flag = False

        self.user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/115.0.0.0 Safari/537.36")
        self.robots_parser = robotparser.RobotFileParser()

        os.makedirs(self.output_dir, exist_ok=True)
        self._init_robots()

    def _init_robots(self):
        if not self.check_robots:
            return
        parsed = urlparse(self.start_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        self.robots_parser.set_url(robots_url)
        try:
            print(f"[*] Vérification de {robots_url}...")
            self.robots_parser.read()
            if not self.robots_parser.can_fetch(self.user_agent, self.start_url):
                print(f"[!] ATTENTION : robots.txt interdit l'accès à {self.start_url}")
        except Exception as e:
            print(f"[!] Impossible de lire robots.txt : {e}")

    def _get_session(self):
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        session.timeout = 10
        return session

    def is_valid_url(self, url):
        parsed = urlparse(url)
        return bool(parsed.netloc) and parsed.scheme in ("http", "https")

    def is_pdf(self, url):
        return urlparse(url).path.lower().endswith(".pdf")

    def extract_links(self, url, session):
        try:
            response = session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            links = set()
            for a_tag in soup.find_all("a", href=True):
                full_url = urljoin(url, a_tag["href"]).split("#")[0]
                if self.is_valid_url(full_url):
                    links.add(full_url)
            return links
        except Exception:
            return set()

    def _get_content_type(self, url, session):
        try:
            resp = session.head(url, timeout=8, allow_redirects=True)
            ct = resp.headers.get('Content-Type', '').lower()
            if ct:
                return ct
        except Exception:
            pass
        try:
            resp = session.get(url, stream=True, timeout=8)
            return resp.headers.get('Content-Type', '').lower()
        except Exception:
            return ''

    def download_pdf(self, url, session, html_redirect_depth=0):
        if html_redirect_depth > 3:
            print(f"\n[✗] Trop de redirections HTML pour {url}")
            return False

        try:
            response = session.get(url, stream=True, timeout=15)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()

            if 'text/html' in content_type:
                html_content = response.content.decode('utf-8', errors='ignore')

                if any(term in html_content.lower()
                       for term in ['téléchargement impossible', "n'existe pas",
                                    'file not found', '404 not found']):
                    print(f"\n[!] Le fichier {os.path.basename(url)} n'existe pas")
                    return False

                print(f"\n[!] Wrapper HTML détecté pour {os.path.basename(url)}")
                print("    -> Analyse de la page...")

                if self.debug:
                    print("\n    === HTML (lignes avec liens) ===")
                    for line in html_content.split('\n'):
                        if any(kw in line.lower() for kw in ['<a ', 'href', 'download', '.pdf']):
                            print(f"    {line.strip()[:120]}")
                    print("    === FIN ===\n")

                soup = BeautifulSoup(html_content, 'html.parser')
                candidate_links = []

                for a_tag in soup.find_all('a', href=True):
                    href = urljoin(url, a_tag['href']).split('#')[0]
                    text = a_tag.get_text(strip=True).lower()

                    # Exclure pages génériques
                    if any(bad in href.lower() for bad in ['index.php', 'index.html', 'home',
                            'accueil', 'contact', 'login', 'mentions', 'cookie', 'rss.php']):
                        continue

                    # === CALCUL DE PRIORITÉ RENFORCÉ ===
                    priority = 0
                    
                    # Priorité MAXIMALE pour download.php?filename= ou download_page.php?filename=
                    if ('download.php' in href.lower() or 'download_page.php' in href.lower()) and 'filename=' in href.lower():
                        priority += 100  # Priorité absolue
                    
                    if 'download' in href.lower():
                        priority += 10
                    if 'filename=' in href.lower():
                        priority += 10
                    if self.is_pdf(href):
                        priority += 5
                    if any(kw in text for kw in ['télécharger', 'download', 'cliquez', 'ici', 'obtenir']):
                        priority += 5
                    
                    # Bonus pour les liens avec paramètres (souvent des scripts de téléchargement)
                    if '?' in href and '.php' in href:
                        priority += 3

                    candidate_links.append((href, priority, text))

                # Trier par priorité décroissante
                candidate_links.sort(key=lambda x: x[1], reverse=True)

                if not candidate_links:
                    print("    -> [] Aucun lien candidat trouvé")
                    return False

                print(f"    -> {len(candidate_links)} lien(s) candidat(s)")
                
                # Afficher les top candidats
                for i, (cand_url, prio, txt) in enumerate(candidate_links[:3]):
                    print(f"       [{i+1}] {os.path.basename(cand_url)} (prio={prio})")

                # Tester TOUS les candidats (pas seulement 5)
                for candidate_url, priority, text in candidate_links:
                    if candidate_url == url:
                        continue

                    # Vérifier si déjà visité dans cette session
                    with self.visited_lock:
                        if candidate_url in self.visited and priority < 100:
                            continue

                    print(f"    -> Test: {os.path.basename(candidate_url)} (prio={priority})")

                    ct = self._get_content_type(candidate_url, session)

                    if 'application/pdf' in ct or 'application/octet-stream' in ct:
                        print(f"    -> ✓ Fichier binaire détecté ({ct})")
                        return self.download_pdf(candidate_url, session, html_redirect_depth + 1)
                    elif 'text/html' in ct and html_redirect_depth < 2:
                        print(f"    -> → Encore du HTML, poursuite...")
                        if self.download_pdf(candidate_url, session, html_redirect_depth + 1):
                            return True
                    else:
                        print(f"    -> → Type inattendu: {ct or 'inconnu'}")

                print("    -> [✗] Aucun lien valide trouvé")
                return False

            # === CAS 2 : Vrai fichier binaire ===
            path = urlparse(url).path
            filename = os.path.basename(path) or f"doc_{hash(url) & 0xFFFFFFFF}.pdf"

            if '?' in filename:
                filename = filename.split('?')[0]
            if not filename.endswith('.pdf'):
                filename += '.pdf'

            filepath = os.path.join(self.output_dir, filename)
            base, ext = os.path.splitext(filepath)
            counter = 1
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                counter += 1

            total_size = int(response.headers.get("content-length", 0))

            with open(filepath, "wb") as f, tqdm(
                total=total_size if total_size > 0 else None,
                unit="B", unit_scale=True, unit_divisor=1024,
                desc=filename[:40], leave=True
            ) as bar:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.stop_flag:
                        break
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))

            if not self.stop_flag:
                with self.stats_lock:
                    self.downloaded_count += 1
                    print(f"[✓] #{self.downloaded_count} : {filename}")
            return True

        except Exception as e:
            print(f"\n[✗] Échec: {os.path.basename(urlparse(url).path)} - {e}")
            return False

    def worker(self):
        session = self._get_session()
        while not self.stop_flag:
            try:
                url, depth = self.url_queue.get(timeout=2)
            except queue.Empty:
                continue

            try:
                if self.check_robots and not self.robots_parser.can_fetch(self.user_agent, url):
                    self.url_queue.task_done()
                    continue

                with self.visited_lock:
                    if url in self.visited:
                        self.url_queue.task_done()
                        continue
                    self.visited.add(url)

                with self.stats_lock:
                    if self.max_files and self.downloaded_count >= self.max_files:
                        self.stop_flag = True
                        self.url_queue.task_done()
                        continue

                if self.is_pdf(url):
                    self.download_pdf(url, session)
                elif depth < self.max_depth:
                    new_links = self.extract_links(url, session)
                    for link in new_links:
                        with self.visited_lock:
                            if link not in self.visited:
                                self.url_queue.put((link, depth + 1))

            finally:
                self.url_queue.task_done()
                if self.delay > 0:
                    time.sleep(self.delay)

    def run(self):
        print(f"[*] Démarrage : {self.start_url}")
        print(f"[*] Threads : {self.threads} | Profondeur : {self.max_depth} | Délai : {self.delay}s")
        self.url_queue.put((self.start_url, 0))

        threads_list = []
        for _ in range(self.threads):
            t = threading.Thread(target=self.worker, daemon=True)
            t.start()
            threads_list.append(t)

        try:
            self.url_queue.join()
        except KeyboardInterrupt:
            print("\n[⚠️] Interruption utilisateur...")
            self.stop_flag = True

        print(f"\n[✓] Terminé. {self.downloaded_count} PDF(s) sauvegardé(s) dans {self.output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Téléchargeur de PDF multithreadé")
    parser.add_argument("url", help="URL de départ")
    parser.add_argument("-o", "--output", default="./pdfs", help="Répertoire de sortie")
    parser.add_argument("-d", "--depth", type=int, default=3, help="Profondeur de récursion")
    parser.add_argument("-w", "--wait", type=float, default=0.5, help="Délai entre requêtes")
    parser.add_argument("-m", "--max", type=int, default=None, help="Nombre max de PDF")
    parser.add_argument("-t", "--threads", type=int, default=5, help="Nombre de threads")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignorer robots.txt")
    parser.add_argument("--debug", action="store_true", help="Mode debug HTML")

    args = parser.parse_args()

    crawler = PDFCrawlerMT(
        start_url=args.url,
        output_dir=args.output,
        max_depth=args.depth,
        delay=args.wait,
        max_files=args.max,
        threads=args.threads,
        check_robots=not args.ignore_robots,
        debug=args.debug,
    )
    crawler.run()


if __name__ == "__main__":
    main()
