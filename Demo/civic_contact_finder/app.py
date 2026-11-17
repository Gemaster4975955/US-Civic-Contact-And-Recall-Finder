from flask import Flask, jsonify, request, render_template
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from html.parser import HTMLParser
from collections import OrderedDict
from threading import Lock
import csv
import logging
import os
import time
import requests
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit

from waitress import serve

from geocode import (
    GeocodingError,
    geocode_location_details,
    haversine_km,
    looks_like_location,
    validate_coordinates,
)

# Simple Civic Contact Finder demo app
BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'data', 'agencies.csv')
STATE_SERVICES_FILE = os.path.join(BASE_DIR, 'data', 'state_services.csv')
FDA_RECALLS_URL = 'https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts'
USDA_RECALLS_URL = 'https://www.fsis.usda.gov/recalls-alerts'
CPSC_RECALLS_URL = 'https://www.cpsc.gov/Recalls'
RECALL_CACHE_TTL_SECONDS = 900
RECALL_STALE_TTL_SECONDS = 24 * 60 * 60
RECALL_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_recall_cache = None
_recall_cache_expiry = 0
_recall_cache_stale_expiry = 0
_recall_cache_lock = Lock()
_rate_limit_buckets = OrderedDict()
_rate_limit_lock = Lock()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024


def integer_setting(name, default):
    value = os.environ.get(name, str(default))
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f'{name} must be an integer.') from error


app.config['API_RATE_LIMIT_COUNT'] = integer_setting('API_RATE_LIMIT_COUNT', 120)
app.config['API_RATE_LIMIT_WINDOW_SECONDS'] = integer_setting(
    'API_RATE_LIMIT_WINDOW_SECONDS', 60
)
app.config['TRUSTED_PROXY_COUNT'] = integer_setting('TRUSTED_PROXY_COUNT', 0)
app.config['HSTS_MAX_AGE_SECONDS'] = integer_setting('HSTS_MAX_AGE_SECONDS', 31536000)
app.config['WAITRESS_THREADS'] = integer_setting('WAITRESS_THREADS', 4)
app.config['WAITRESS_CONNECTION_LIMIT'] = integer_setting(
    'WAITRESS_CONNECTION_LIMIT', 100
)
app.config['WAITRESS_CHANNEL_TIMEOUT'] = integer_setting(
    'WAITRESS_CHANNEL_TIMEOUT', 30
)

if app.config['TRUSTED_PROXY_COUNT'] > 0:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=app.config['TRUSTED_PROXY_COUNT'],
        x_proto=app.config['TRUSTED_PROXY_COUNT'],
    )

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
logger = logging.getLogger(__name__)
app.logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO').upper())


def configured_cors_origins():
    return {
        origin.strip().rstrip('/')
        for origin in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
        if origin.strip()
    }


def is_exact_https_origin(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return (
            parsed.scheme == 'https'
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and (port is None or 1 <= port <= 65535)
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and '*' not in value
        )
    except ValueError:
        return False


def production_configuration_errors():
    if os.environ.get('APP_ENV', '').strip().lower() != 'production':
        return []

    errors = []
    contact = os.environ.get('GEOCODER_CONTACT', '').strip()
    contact_domain = contact.rsplit('@', 1)[-1].lower()
    if (
        '@' not in contact
        or contact_domain.endswith(('.example', '.invalid', '.test', '.localhost'))
        or contact_domain in {'example.com', 'example.org'}
    ):
        errors.append('GEOCODER_CONTACT must be a real monitored email address.')
    if app.config['API_RATE_LIMIT_COUNT'] < 1:
        errors.append('API_RATE_LIMIT_COUNT must be greater than zero.')
    if app.config['API_RATE_LIMIT_WINDOW_SECONDS'] < 1:
        errors.append('API_RATE_LIMIT_WINDOW_SECONDS must be greater than zero.')
    if app.config['TRUSTED_PROXY_COUNT'] < 0:
        errors.append('TRUSTED_PROXY_COUNT must not be negative.')
    if app.config['TRUSTED_PROXY_COUNT'] == 0:
        errors.append('TRUSTED_PROXY_COUNT must match the trusted HTTPS reverse-proxy chain.')
    if app.config['HSTS_MAX_AGE_SECONDS'] < 0:
        errors.append('HSTS_MAX_AGE_SECONDS must not be negative.')
    if app.config['HSTS_MAX_AGE_SECONDS'] == 0:
        errors.append('HSTS_MAX_AGE_SECONDS must be greater than zero in production.')
    for setting in (
        'WAITRESS_THREADS',
        'WAITRESS_CONNECTION_LIMIT',
        'WAITRESS_CHANNEL_TIMEOUT',
    ):
        if app.config[setting] < 1:
            errors.append(f'{setting} must be greater than zero.')
    try:
        port = int(os.environ.get('PORT', '5001'))
        if not 1 <= port <= 65535:
            errors.append('PORT must be between 1 and 65535.')
    except ValueError:
        errors.append('PORT must be an integer between 1 and 65535.')
    if not os.environ.get('APP_HOST', '127.0.0.1').strip():
        errors.append('APP_HOST must not be empty.')
    if os.environ.get('LOG_LEVEL', 'INFO').upper() not in {
        'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL',
    }:
        errors.append('LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.')

    for origin in configured_cors_origins():
        if not is_exact_https_origin(origin):
            errors.append(
                'CORS_ALLOWED_ORIGINS must contain only exact HTTPS origins.'
            )
            break

    for setting in ('PRIVACY_POLICY_URL', 'SUPPORT_URL'):
        value = os.environ.get(setting, '').strip()
        safe_url = is_safe_official_url(value)
        hostname = (urlsplit(value).hostname or '') if safe_url else ''
        if (
            not safe_url
            or hostname.lower().endswith(('.example', '.invalid', '.test', '.localhost'))
            or hostname.lower() in {'example.com', 'example.org'}
        ):
            errors.append(f'{setting} must be a real HTTPS public URL.')
    return errors


def validate_directory_data():
    agencies = load_agencies()
    state_services = load_state_services()
    if not agencies:
        raise RuntimeError('The agency directory is empty.')
    if len(state_services) != 56:
        raise RuntimeError('The state-service directory must contain 56 jurisdictions.')

    jurisdictions = [service.get('jurisdiction', '').strip() for service in state_services]
    if any(not jurisdiction for jurisdiction in jurisdictions):
        raise RuntimeError('Every state-service row must have a jurisdiction.')
    if len(set(jurisdictions)) != len(jurisdictions):
        raise RuntimeError('The state-service directory contains duplicate jurisdictions.')
    for agency in agencies:
        if not agency.get('agency_name') or not is_safe_official_url(agency.get('contact_url')):
            raise RuntimeError('The agency directory contains an invalid contact route.')
        if not is_safe_official_url(agency.get('source_url')):
            raise RuntimeError('The agency directory contains an invalid source route.')
    for service in state_services:
        if not is_safe_official_url(service.get('dot_url')):
            raise RuntimeError('The state-service directory contains an invalid DOT URL.')
        if not is_safe_official_url(service.get('local_directory_url')):
            raise RuntimeError('The state-service directory contains an invalid local URL.')
        if not is_safe_official_url(service.get('source_url')):
            raise RuntimeError('The state-service directory contains an invalid source URL.')
    return agencies, state_services


def rate_limit_exceeded(client_key, now):
    limit = app.config['API_RATE_LIMIT_COUNT']
    window = app.config['API_RATE_LIMIT_WINDOW_SECONDS']
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.get(client_key)
        if bucket is None or now - bucket[0] >= window:
            if bucket is None and len(_rate_limit_buckets) >= 10000:
                for key, (start, _) in list(_rate_limit_buckets.items())[:1000]:
                    if now - start >= window:
                        del _rate_limit_buckets[key]
                if len(_rate_limit_buckets) >= 10000:
                    _rate_limit_buckets.popitem(last=False)
            _rate_limit_buckets[client_key] = (now, 1)
            return False, window
        start, count = bucket
        if count >= limit:
            return True, max(1, int(window - (now - start)))
        _rate_limit_buckets[client_key] = (start, count + 1)
        return False, window


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'no-referrer')
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(), microphone=(), geolocation=()',
    )
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self' mailto:",
    )
    if request.path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'no-store')
    if request.is_secure and app.config['HSTS_MAX_AGE_SECONDS'] > 0:
        response.headers.setdefault(
            'Strict-Transport-Security',
            f'max-age={app.config["HSTS_MAX_AGE_SECONDS"]}',
        )

    origin = request.headers.get('Origin', '').rstrip('/')
    allowed_origins = configured_cors_origins()
    if request.path.startswith('/api/') and origin and origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Max-Age'] = '600'
        response.headers.add('Vary', 'Origin')
    return response


@app.context_processor
def public_policy_links():
    return {
        'privacy_policy_url': (
            os.environ.get('PRIVACY_POLICY_URL', '').strip()
            if is_safe_official_url(os.environ.get('PRIVACY_POLICY_URL', '').strip())
            else ''
        ),
        'support_url': (
            os.environ.get('SUPPORT_URL', '').strip()
            if is_safe_official_url(os.environ.get('SUPPORT_URL', '').strip())
            else ''
        ),
    }


@app.before_request
def enforce_api_rate_limit():
    if not request.path.startswith('/api/') or request.method == 'OPTIONS':
        return None
    exceeded, retry_after = rate_limit_exceeded(
        request.remote_addr or 'unknown-client',
        time.monotonic(),
    )
    if exceeded:
        response = jsonify({'error': 'API request limit reached. Please retry later.'})
        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)
        return response
    return None


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        if request.path.startswith('/api/'):
            return jsonify({'error': error.description}), error.code
        return error
    logger.exception("Unhandled request error")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'An unexpected server error occurred.'}), 500
    return 'An unexpected server error occurred.', 500


def normalize_issue_types(raw_value):
    return [t.strip().lower() for t in (raw_value or '').split(';') if t.strip()]


def load_agencies():
    agencies = []
    if not os.path.exists(DATA_FILE):
        return agencies
    with open(DATA_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['issue_types'] = normalize_issue_types(row.get('issue_types', ''))
            agencies.append(row)
    return agencies


def load_state_services():
    with open(STATE_SERVICES_FILE, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def is_safe_official_url(value):
    if not value:
        return False
    try:
        if any(ord(character) < 32 for character in value):
            return False
        parsed = urlsplit(value.strip())
        return (
            parsed.scheme == 'https'
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        return False


if os.environ.get('APP_ENV', '').strip().lower() == 'production':
    configuration_errors = production_configuration_errors()
    if configuration_errors:
        raise RuntimeError(
            'Invalid production configuration: ' + ' '.join(configuration_errors)
        )
    validate_directory_data()


def serialize_agency(a, location_context=None, distance_km=None):
    a_copy = dict(a)
    a_copy['issue_types'] = '; '.join(a.get('issue_types', []))
    if not is_safe_official_url(a_copy.get('contact_url')):
        a_copy['contact_url'] = ''
    if not is_safe_official_url(a_copy.get('source_url')):
        a_copy['source_url'] = ''
    if location_context:
        a_copy['location_context'] = location_context
    if distance_km is not None:
        a_copy['distance_km'] = round(distance_km, 1)
    return a_copy


def resolve_location_context(raw_query, location_hint):
    if location_hint:
        candidate = location_hint.strip()
    elif raw_query and looks_like_location(raw_query):
        candidate = raw_query.strip()
    else:
        candidate = ''

    if not candidate:
        return None

    lat, lon, state = geocode_location_details(candidate)
    if lat is None or lon is None:
        return None

    return {
        'query': candidate,
        'lat': lat,
        'lon': lon,
        'state': state,
    }


def state_election_calendar_url(jurisdiction):
    if not jurisdiction or jurisdiction in {
        'American Samoa',
        'Guam',
        'Northern Mariana Islands',
        'Puerto Rico',
        'U.S. Virgin Islands',
    }:
        return 'https://www.usa.gov/when-to-vote'
    jurisdiction_slug = '-'.join(jurisdiction.lower().split())
    return (
        f'https://www.usvotefoundation.org/'
        f'{jurisdiction_slug}-election-dates-and-deadlines'
    )


def resolve_state_service(selected_state, location_context):
    state = selected_state.strip() if selected_state else ''
    if not state and location_context:
        state = location_context.get('state') or ''
    if not state:
        return None

    state_services = load_state_services()
    jurisdiction_aliases = {
        'virgin islands': 'u.s. virgin islands',
        'united states virgin islands': 'u.s. virgin islands',
        'commonwealth of the northern mariana islands': 'northern mariana islands',
        'cnmi': 'northern mariana islands',
    }
    state_key = jurisdiction_aliases.get(state.casefold(), state.casefold())
    match = next(
        (service for service in state_services
         if service['jurisdiction'].casefold() == state_key),
        None,
    )
    if not match:
        return None

    territory_portals = {
        'U.S. Virgin Islands': 'https://www.vi.gov/',
        'Puerto Rico': 'https://www.pr.gov/',
        'Guam': 'https://www.guam.gov/',
        'American Samoa': 'https://www.americansamoa.gov/',
        'Northern Mariana Islands': 'https://governor.cnmi.gov/cnmi-government-directory/',
    }
    government_portal = territory_portals.get(match['jurisdiction'])
    if not government_portal:
        portal_slug = match['jurisdiction'].lower().replace(' ', '-')
        government_portal = f'https://www.usa.gov/states/{portal_slug}'

    routes = [
        {
            'category': 'State government and services',
            'name': (
                f'{match["jurisdiction"]} government on USA.gov'
                if 'usa.gov' in government_portal
                else f'{match["jurisdiction"]} government portal'
            ),
            'url': government_portal,
            'description': 'Official directory for the selected state or territory, including major agencies and services.',
        },
        {
            'category': 'Consumer complaints and Attorney General',
            'name': 'Find your Attorney General',
            'url': 'https://www.naag.org/find-my-ag/',
            'description': 'Official national directory for the state or territorial Attorney General; choose the jurisdiction to reach its office and consumer-protection resources.',
        },
        {
            'category': 'Environmental agencies',
            'name': 'State and territorial environmental agencies',
            'url': 'https://www.epa.gov/aboutepa/health-and-environmental-agencies-us-states-and-territories',
            'description': 'EPA directory of state and territorial environment and public-health agencies. Many environmental complaints are handled by these agencies.',
        },
        {
            'category': 'Emergency management',
            'name': 'Find disaster and emergency resources',
            'url': 'https://www.fema.gov/locations',
            'description': 'FEMA location finder for state, territorial, and local emergency-management information. Call 911 for immediate danger.',
        },
        {
            'category': 'State elections and registration',
            'name': 'Find election dates, deadlines, and your election office',
            'url': state_election_calendar_url(match['jurisdiction']),
            'description': 'State election dates, registration deadlines, ballot rules, and early-voting options vary. Confirm details with your state or local election office.',
        },
        {
            'category': 'Food and drug recalls',
            'name': 'FDA recalls and safety alerts',
            'url': FDA_RECALLS_URL,
            'description': 'FDA recall notices for foods such as cheese, drugs, medical devices, cosmetics, and other FDA-regulated products. Check the notice for affected lots and distribution.',
        },
        {
            'category': 'Meat, poultry, and egg recalls',
            'name': 'USDA FSIS recalls and alerts',
            'url': USDA_RECALLS_URL,
            'description': 'USDA Food Safety and Inspection Service recall notices for meat, poultry, and processed egg products.',
        },
        {
            'category': 'Consumer product recalls',
            'name': 'Consumer Product Safety Commission recalls',
            'url': CPSC_RECALLS_URL,
            'description': 'Official recalls and safety notices for consumer products such as appliances, toys, batteries, and household goods.',
        },
        {
            'category': 'State roads and highways',
            'name': match.get('dot_name'),
            'url': match.get('dot_url'),
            'description': 'For roads and highways maintained by the state, not city or county streets.',
        },
        {
            'category': 'City and county services',
            'name': 'Local government directory',
            'url': match.get('local_directory_url'),
            'description': 'Find the relevant city or county for local roads, trash, parks, housing, and other municipal services.',
        },
    ]
    match['routes'] = [
        route for route in routes
        if is_safe_official_url(route['url'])
    ]
    return match


def federal_general_election_date(today=None):
    today = today or date.today()
    year = today.year if today.year % 2 == 0 else today.year + 1
    while True:
        november_first = date(year, 11, 1)
        first_monday = 1 + ((0 - november_first.weekday()) % 7)
        election_day = date(year, 11, first_monday + 1)
        if election_day >= today:
            return election_day
        year += 2


def build_election_info(state_service=None, today=None):
    today = today or datetime.now(timezone.utc).date()
    election_day = federal_general_election_date(today)
    days_until = (election_day - today).days
    in_election_season = 0 <= days_until <= 90
    jurisdiction = state_service['jurisdiction'] if state_service else None

    return {
        'federal_election_date': election_day.isoformat(),
        'days_until_federal_election': days_until,
        'is_federal_election_season': in_election_season,
        'jurisdiction': jurisdiction,
        'state_calendar_url': state_election_calendar_url(jurisdiction),
        'registration_url': 'https://www.usa.gov/register-to-vote',
    }


class FDARecallTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.current_row = None
        self.current_cell = None
        self.current_cell_tag = None
        self.current_link = None
        self.header_columns = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'table' and attributes.get('id') == 'datatable':
            self.in_table = True
        elif self.in_table and tag == 'tr':
            self.current_row = []
        elif self.in_table and tag in {'td', 'th'} and self.current_row is not None:
            self.current_cell_tag = tag
            self.current_cell = {'text': [], 'links': [], 'date': None}
        elif self.current_cell is not None and tag == 'time':
            self.current_cell['date'] = attributes.get('datetime')
        elif self.current_cell is not None and tag == 'a':
            href = attributes.get('href')
            if href:
                self.current_link = urljoin(FDA_RECALLS_URL, href)

    def handle_data(self, data):
        if self.current_cell is None:
            return
        self.current_cell['text'].append(data)
        if self.current_link:
            if self.current_cell['links']:
                self.current_cell['links'][-1]['text'].append(data)
            else:
                self.current_cell['links'].append({
                    'url': self.current_link,
                    'text': [data],
                })

    def handle_endtag(self, tag):
        if (
            self.in_table
            and tag in {'td', 'th'}
            and tag == self.current_cell_tag
            and self.current_cell is not None
        ):
            self.current_cell['text'] = ' '.join(
                ' '.join(self.current_cell['text']).split()
            )
            for link in self.current_cell['links']:
                link['text'] = ' '.join(' '.join(link['text']).split())
            self.current_row.append(self.current_cell)
            self.current_cell = None
            self.current_cell_tag = None
            self.current_link = None
        elif self.in_table and tag == 'tr' and self.current_row is not None:
            if self.current_row and self.current_cell_tag is None:
                if self.header_columns:
                    self.rows.append(self.current_row)
                else:
                    self.header_columns = [
                        self._column_key(cell['text'])
                        for cell in self.current_row
                    ]
            self.current_row = None
        elif tag == 'a':
            self.current_link = None
        elif tag == 'table' and self.in_table:
            self.in_table = False

    @staticmethod
    def _column_key(label):
        normalized = label.casefold()
        if 'date' in normalized:
            return 'date'
        if 'brand' in normalized:
            return 'brand'
        if 'product description' in normalized:
            return 'product'
        if 'recall reason' in normalized:
            return 'reason'
        if 'company name' in normalized:
            return 'company'
        if 'terminated recall' in normalized:
            return 'terminated'
        return ''


def parse_fda_recall_notices(page_html, limit=5):
    parser = FDARecallTableParser()
    parser.feed(page_html)
    notices = []
    if not {'date', 'brand', 'product', 'reason', 'company', 'terminated'}.issubset(
        parser.header_columns
    ):
        return notices
    for row in parser.rows:
        if len(row) != len(parser.header_columns):
            continue
        cells = {
            key: row[index]
            for index, key in enumerate(parser.header_columns)
            if key
        }
        # FDA's listing includes a "Terminated Recall" column; skip rows
        # explicitly marked terminated without claiming the others are active.
        if cells['terminated']['text']:
            continue
        title_links = cells['brand']['links']
        if not title_links:
            continue
        notice_url = title_links[0]['url']
        if not is_safe_official_url(notice_url) or urlsplit(notice_url).hostname not in {
            'fda.gov', 'www.fda.gov',
        }:
            continue
        notices.append({
            'date': cells['date']['date'] or cells['date']['text'],
            'title': title_links[0]['text'] or cells['brand']['text'],
            'url': notice_url,
            'product': cells['product']['text'],
            'reason': cells['reason']['text'],
            'company': cells['company']['text'],
            'status_note': 'Not marked terminated on the FDA listing; check the notice for current status and affected lots.',
        })
        if len(notices) >= limit:
            break
    return notices


class RecallFeedError(Exception):
    pass


def get_recent_fda_recalls():
    global _recall_cache, _recall_cache_expiry, _recall_cache_stale_expiry
    with _recall_cache_lock:
        now = time.monotonic()
        if _recall_cache is not None and now < _recall_cache_expiry:
            return _recall_cache
        try:
            response = requests.get(
                FDA_RECALLS_URL,
                headers={
                    'User-Agent': (
                        'CivicContactFinder/1.0 '
                        f'({os.environ.get("GEOCODER_CONTACT", "contact unavailable")})'
                    ),
                    'Accept': 'text/html',
                },
                timeout=(3.05, 10),
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    raise RecallFeedError(
                        f'FDA recall page returned HTTP {response.status_code}.'
                    )
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type.lower():
                    raise RecallFeedError('FDA recall page did not return HTML.')
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    content.extend(chunk)
                    if len(content) > RECALL_RESPONSE_MAX_BYTES:
                        raise RecallFeedError('FDA recall page exceeded the response-size limit.')
                page_html = bytes(content).decode('utf-8', errors='replace')
            finally:
                response.close()
            notices = parse_fda_recall_notices(page_html)
            if not notices:
                raise RecallFeedError('FDA recall page contained no parseable current notices.')
        except (requests.RequestException, RecallFeedError, AttributeError, TypeError) as error:
            logger.warning('Unable to retrieve FDA recall notices: %s', error)
            if _recall_cache is not None and now < _recall_cache_stale_expiry:
                stale_payload = dict(_recall_cache)
                stale_payload['is_stale'] = True
                stale_payload['warning'] = (
                    'FDA could not be refreshed. These cached notices may be outdated; '
                    'check the original source before acting.'
                )
                return stale_payload
            raise RecallFeedError('FDA recall notices are temporarily unavailable.') from error

        _recall_cache = {
            'source': 'U.S. Food and Drug Administration',
            'source_url': FDA_RECALLS_URL,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'is_stale': False,
            'notices': notices,
            'scope_note': (
                'These are recent notices listed by FDA, not a complete list of all recalls '
                'and not a guarantee that a recall is currently active. Check the linked '
                'official notice for affected products, lot numbers, distribution, and status.'
            ),
        }
        cache_updated_at = time.monotonic()
        _recall_cache_expiry = cache_updated_at + RECALL_CACHE_TTL_SECONDS
        _recall_cache_stale_expiry = cache_updated_at + RECALL_STALE_TTL_SECONDS
        return _recall_cache


def agency_distance(agency, location_context):
    if not location_context:
        return None

    lat, lon = validate_coordinates(agency.get('latitude'), agency.get('longitude'))
    if lat is None or lon is None:
        return None

    return haversine_km(
        location_context['lat'],
        location_context['lon'],
        lat,
        lon,
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/search', methods=['GET', 'POST'])
@app.route('/api/v1/search', methods=['GET', 'POST'])
def api_search():
    agencies = load_agencies()
    if request.method == 'POST':
        payload = request.get_json()
        if not isinstance(payload, dict):
            return jsonify({'error': 'Search body must be a JSON object.'}), 400
        raw_query = payload.get('q', '')
        location_hint = payload.get('location', '')
        selected_state = payload.get('state', '')
        if not all(isinstance(value, str) for value in (raw_query, location_hint, selected_state)):
            return jsonify({'error': 'Search, location, and jurisdiction values must be text.'}), 400
    else:
        raw_query = request.args.get('q', '') or ''
        location_hint = request.args.get('location', '') or ''
        selected_state = request.args.get('state', '') or ''
    raw_query = raw_query.strip()
    location_hint = location_hint.strip()
    selected_state = selected_state.strip()
    if len(raw_query) > 200 or len(location_hint) > 200 or len(selected_state) > 80:
        return jsonify({
            'error': 'Search, location, or jurisdiction input exceeds its maximum length.'
        }), 400

    q = raw_query.lower()
    location_error = None
    try:
        location_context = resolve_location_context(raw_query, location_hint)
    except GeocodingError:
        location_context = None
        location_error = 'The location service is temporarily unavailable. You can still select a state manually.'
    state_service = resolve_state_service(selected_state, location_context)
    election_info = build_election_info(state_service)

    if not q and not location_context:
        out = [serialize_agency(a) for a in agencies[:20]]
        return jsonify({
            'results': out,
            'location_context': None,
            'location_query': location_hint,
            'location_error': location_error,
            'state_service': state_service,
            'election_info': election_info,
        })

    results = []
    for a in agencies:
        searchable = ' '.join([
            a.get('agency_name', ''),
            a.get('jurisdiction', ''),
            a.get('keywords', ''),
        ]).lower()
        score = 0

        if q and any(q in t for t in a['issue_types']):
            score += 30
        if q and q in searchable:
            score += 15
        if q and q in (a.get('agency_name', '') or '').lower():
            score += 10
        if score > 0 or (not q and location_context):
            distance = agency_distance(a, location_context)
            results.append((
                score,
                distance,
                serialize_agency(a, location_context, distance),
            ))

    results.sort(key=lambda result: (
        -result[0],
        result[1] is None,
        result[1] if result[1] is not None else float('inf'),
    ))
    return jsonify({
        'results': [result[2] for result in results],
        'location_context': location_context,
        'location_query': location_hint,
        'location_error': location_error,
        'state_service': state_service,
        'election_info': election_info,
    })


@app.route('/api/state-services')
@app.route('/api/v1/state-services')
def api_state_services():
    return jsonify([
        service['jurisdiction']
        for service in load_state_services()
    ])


@app.route('/api/v1/recalls')
def api_recent_recalls():
    try:
        return jsonify(get_recent_fda_recalls())
    except RecallFeedError:
        return jsonify({
            'error': 'Recent FDA recall notices are temporarily unavailable.',
            'source_urls': {
                'fda': FDA_RECALLS_URL,
                'usda_fsis': USDA_RECALLS_URL,
                'cpsc': CPSC_RECALLS_URL,
            },
        }), 503


@app.route('/healthz')
def health_check():
    return jsonify({'status': 'ok'})


@app.route('/readyz')
def readiness_check():
    try:
        agencies, state_services = validate_directory_data()
        configuration_errors = production_configuration_errors()
        if configuration_errors:
            return jsonify({
                'status': 'unready',
                'configuration_errors': configuration_errors,
            }), 503
    except (OSError, csv.Error, RuntimeError, KeyError):
        logger.exception('Readiness check failed')
        return jsonify({'status': 'unready', 'error': 'Required directory data is invalid.'}), 503
    return jsonify({
        'status': 'ok',
        'agency_count': len(agencies),
        'jurisdiction_count': len(state_services),
    })


if __name__ == '__main__':
    host = os.environ.get('APP_HOST', '127.0.0.1')
    port = integer_setting('PORT', 5001)
    if not 1 <= port <= 65535:
        raise RuntimeError('PORT must be between 1 and 65535.')
    serve(
        app,
        host=host,
        port=port,
        threads=app.config['WAITRESS_THREADS'],
        connection_limit=app.config['WAITRESS_CONNECTION_LIMIT'],
        channel_timeout=app.config['WAITRESS_CHANNEL_TIMEOUT'],
        max_request_body_size=app.config['MAX_CONTENT_LENGTH'],
    )
