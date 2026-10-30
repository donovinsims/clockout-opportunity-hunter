"""Bounded public HTTP research with saved source bytes; never execute page instructions."""
import hashlib
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

AGENT = 'OpportunityHunter/0.1 (manual public business research; no form submission)'
MAX_BYTES = 3_000_000
DIRECTORY_DOMAINS={'instagram.com','youtube.com','tiktok.com','twitter.com','x.com','facebook.com','yelp.com','angi.com','bbb.org','yellowpages.com','houzz.com','mapquest.com','linkedin.com','google.com','dexknows.com','permitdeck.com','downtobid.com','expertise.com','trustanalytica.org','threebestrated.com','manta.com','chamberofcommerce.com','homeadvisor.com'}


def directory_url(url):
    host=domain(url)
    return any(host==d or host.endswith('.'+d) for d in DIRECTORY_DOMAINS)


def is_challenge(html):
    # Normal business forms load reCAPTCHA scripts. The script name is not an access challenge.
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(['script', 'style', 'noscript']):
        el.decompose()
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    visible = soup.get_text(' ', strip=True)[:1500]
    return bool(re.search(r'verify (?:that )?you are human|unusual traffic|checking your browser|access denied', title+' '+visible, re.I)
                or re.fullmatch(r'\s*(?:just a moment\.*|captcha)\s*', title, re.I))


def now():
    return datetime.now(timezone.utc).isoformat()


def public_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('Only public HTTP(S) URLs on standard ports are allowed')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private/local network destination refused')
    return url


def domain(url):
    return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, root, settings):
        self.root = Path(root)
        self.settings = settings
        self.last = {}
        self.robots = {}
        self.cache = {}
        self.opener = urllib.request.build_opener(Redirect())

    def _request(self, url):
        public_url(url)
        host = domain(url)
        time.sleep(max(0, self.settings['request_interval_seconds'] - (time.monotonic() - self.last.get(host, 0))))
        self.last[host] = time.monotonic()
        req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,application/json,text/plain,*/*;q=0.1'})
        with self.opener.open(req, timeout=self.settings['timeout_seconds']) as r:
            body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('Response exceeds research size limit')
            return r.status, r.geturl(), body, r.headers.get_content_charset() or 'utf-8', r.headers.get('Content-Type', '')

    def allowed(self, url):
        p = urllib.parse.urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:
                status, _, body, _, _ = self._request(origin + '/robots.txt')
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(body.decode('utf-8', errors='replace').splitlines())
                self.robots[origin] = rp
            except urllib.error.HTTPError as e:
                self.robots[origin] = False if e.code in (401, 403, 429) else (None if e.code in (404, 410) else False)
            except Exception:
                self.robots[origin] = False
        rp = self.robots[origin]
        return rp is None or (rp is not False and rp.can_fetch('OpportunityHunter', url))

    def fetch(self, url):
        if url in self.cache:
            return self.cache[url]
        result = {'requested_url': url, 'url': url, 'checked_at': now(), 'status': None, 'error': None}
        try:
            public_url(url)
            if not self.allowed(url):
                raise ValueError('robots unavailable or disallow research; stopped without bypass')
            for attempt in range(2):
                try:
                    status, final, body, charset, content_type = self._request(url)
                    break
                except urllib.error.HTTPError as e:
                    if e.code not in (502, 503, 504) or attempt:
                        raise
                    time.sleep(1)
            digest = hashlib.sha256(body).hexdigest()
            dest = self.root / 'data/evidence' / (digest + '.html')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            result.update(status=status, url=final, sha256=digest, artifact=str(dest.relative_to(self.root)), content_type=content_type)
            text = body.decode(charset, errors='replace')
            if is_challenge(text):
                raise ValueError('Possible access challenge; manual review required, no bypass attempted')
            result['html'] = text
        except urllib.error.HTTPError as e:
            result.update(status=e.code, error=f'HTTP {e.code}; not proof the site is broken for customers')
        except Exception as e:
            result['error'] = str(e)[:240]
        self.cache[url] = result
        return result


def parse_page(page):
    soup = BeautifulSoup(page.get('html', ''), 'html.parser')
    for el in soup(['script', 'style', 'noscript']):
        el.decompose()
    text = soup.get_text(' ', strip=True)
    links = [{'label': a.get_text(' ', strip=True), 'url': urllib.parse.urljoin(page['url'], a.get('href', ''))} for a in soup.select('a[href]')
             if not re.search(r'[\\"<>\s]',a.get('href',''))]
    phones = list(dict.fromkeys(re.findall(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)', text)))
    emails = [e for e in dict.fromkeys(re.findall(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text))
              if e.rsplit('.',1)[-1].lower() not in ('png','jpg','jpeg','gif','webp','svg','woff','css','js')]
    for link in links:
        if link['url'].startswith('mailto:'):
            emails.append(link['url'][7:].split('?')[0])
        if link['url'].startswith('tel:'):
            phones.append(link['url'][4:])
    from .enrichment import valid_email
    emails=[urllib.parse.unquote(e).lower() for e in emails if valid_email(e)]
    return {'title': soup.title.get_text(strip=True) if soup.title else '', 'text': text,
            'phones': list(dict.fromkeys(phones)), 'emails': list(dict.fromkeys(emails)), 'links': links,
            'has_viewport': bool(soup.select_one('meta[name="viewport"]')), 'forms': len(soup.select('form'))}


def excerpt(text, pattern, radius=130):
    m = re.search(pattern, text, re.I)
    return text[max(0, m.start()-radius):m.end()+radius] if m else ''
