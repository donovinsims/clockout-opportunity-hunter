"""Optional review-signals enrichment (file-based, from the separate gmr scraper).

Informational only: never changes score, qualification, findings or outreach angle.
A missing or malformed file produces a warning and the run continues.
Partial or failed scraper jobs are shown as incomplete, never as "no complaints".
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote

STRENGTHS = ('strong', 'weak', 'none-found', 'incomplete')
CSV_FIELDS = ['id', 'name', 'city', 'join', 'job_status', 'strength', 'reviews_scanned', 'explicit_matches', 'indirect_matches', 'signals', 'top_quote', 'top_quote_date', 'top_quote_review_id']


def _norm(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def _cid(url):
    m = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', unquote(url or ''), re.I)
    return m[1].lower() if m else ''


def load(path):
    """Return (businesses, warnings). Never raises for file or content problems."""
    if not path:
        return [], []
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        return [], [f'Review signals file not found: {p}; continuing without review signals']
    except (OSError, ValueError) as e:
        return [], [f'Review signals file unreadable ({type(e).__name__}); continuing without review signals']
    rows = data.get('businesses') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], ['Review signals file has no "businesses" list; continuing without review signals']
    good, skipped = [], 0
    for b in rows:
        if isinstance(b, dict) and (b.get('placeId') or b.get('inputUrl') or b.get('name')):
            b = dict(b)
            if b.get('jobStatus') != 'complete':
                b['strength'] = 'incomplete'
            elif b.get('strength') not in STRENGTHS:
                b['strength'] = 'strong' if any(m.get('kind', 'explicit') == 'explicit' for m in b.get('matches') or []) else ('weak' if b.get('matches') or b.get('businessSignals') else 'none-found')
            b.setdefault('matches', []); b.setdefault('businessSignals', [])
            good.append(b)
        else:
            skipped += 1
    warnings = [f'{skipped} malformed review-signal entries skipped'] if skipped else []
    return good, warnings


def match(p, businesses):
    """Join by place id / URL first (confirmed), then name + town (unconfirmed)."""
    pid = (p.get('maps_cid') or _cid(p.get('maps_url'))).lower()
    url = p.get('maps_url') or ''
    for b in businesses:
        bid = (b.get('placeId') or _cid(b.get('inputUrl'))).lower()
        if (pid and bid and pid == bid) or (url and b.get('inputUrl') and _cid(url) and _cid(url) == _cid(b['inputUrl'])):
            return b, 'confirmed (place id)'
    for b in businesses:
        town = b.get('town') or b.get('city')
        if _norm(b.get('name')) and _norm(b.get('name')) == _norm(p.get('name')) and (not town or _norm(town) == _norm(p.get('city'))):
            return b, 'unconfirmed (name' + (' + town' if town else ' only') + ')'
    return None, ''


def summarize(p, businesses):
    b, how = match(p, businesses)
    if not b:
        return None
    extra = []
    if p.get('maps_url') and p.get('maps_website_search_artifact'):
        extra.append({'topic': 'no_website_on_maps', 'kind': 'indirect', 'detail': 'Maps listing showed no website link when discovered'})
    explicit = [m for m in b['matches'] if m.get('kind', 'explicit') == 'explicit']
    indirect = [m for m in b['matches'] if m.get('kind') == 'indirect']
    strength = b['strength']
    if strength == 'none-found' and extra:
        strength = 'weak'
    return {'join': how, 'job_status': b.get('jobStatus', 'unknown'), 'strength': strength,
            'reviews_scanned': b.get('reviewsScanned', 0), 'explicit': explicit, 'indirect': indirect,
            'business_signals': list(b['businessSignals']) + extra,
            'note': 'incomplete: results do not establish absence of complaints' if strength == 'incomplete' else 'informational; not part of the verified score'}


def report_lines(leads, businesses):
    out = ['', '# Review signals (informational; not part of the verified score)', '',
           'Keyword matches from public Google reviews collected by the separate gmr tool. Every quote needs owner review before use.', '']
    seen = 0
    for p in leads:
        s = summarize(p, businesses)
        if not s:
            continue
        seen += 1
        out.append(f"## {p['name']} — {p['city']} — strength: {s['strength']}")
        out.append(f"Join: {s['join']}; scraper job: {s['job_status']}; reviews scanned: {s['reviews_scanned']}. {s['note']}")
        for m in s['explicit'] + s['indirect']:
            out.append(f"- [{m.get('kind', 'explicit')}: {m.get('topic')}] {m.get('rating', '?')} stars, {m.get('dateRaw') or m.get('date') or 'date unknown'} (review {m.get('reviewId')}): \"{m.get('quote', '')}\"")
        for x in s['business_signals']:
            out.append(f"- [indirect: {x['topic']}] {x.get('detail', '')}")
        out.append('')
    if not seen:
        out.append('No prospects matched the supplied review signals.')
    return out


def csv_rows(leads, businesses):
    rows = []
    for p in leads:
        s = summarize(p, businesses)
        if not s:
            continue
        top = (s['explicit'] or s['indirect'] or [{}])[0]
        rows.append({'id': p['id'], 'name': p['name'], 'city': p['city'], 'join': s['join'], 'job_status': s['job_status'],
                     'strength': s['strength'], 'reviews_scanned': s['reviews_scanned'], 'explicit_matches': len(s['explicit']),
                     'indirect_matches': len(s['indirect']),
                     'signals': '; '.join(dict.fromkeys([m.get('topic') for m in s['explicit'] + s['indirect']] + [x['topic'] for x in s['business_signals']])),
                     'top_quote': top.get('quote', ''), 'top_quote_date': top.get('dateRaw') or top.get('date') or '', 'top_quote_review_id': top.get('reviewId', '')})
    return rows
