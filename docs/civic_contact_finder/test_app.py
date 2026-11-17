import unittest
from datetime import date
import time
from unittest.mock import Mock, patch

import app
from geocode import (
    GeocodingError,
    geocode_location,
    geocode_location_details,
    haversine_km,
    looks_like_location,
)


class LocationSearchTests(unittest.TestCase):
    def setUp(self):
        app._rate_limit_buckets.clear()
        app._recall_cache = None
        app._recall_cache_expiry = 0
        app._recall_cache_stale_expiry = 0
        self.agencies = [
            {
                'agency_name': 'Far Transit Agency',
                'issue_types': ['transit'],
                'jurisdiction': 'Region',
                'keywords': 'bus',
                'latitude': '40.1',
                'longitude': '-75.0',
            },
            {
                'agency_name': 'Nearby Public Works',
                'issue_types': ['potholes'],
                'jurisdiction': 'City',
                'keywords': 'roads',
                'latitude': '40.01',
                'longitude': '-75.0',
            },
            {
                'agency_name': 'Agency Without Coordinates',
                'issue_types': ['parks'],
                'jurisdiction': 'City',
                'keywords': 'parks',
                'latitude': '',
                'longitude': '',
            },
        ]
        self.client = app.app.test_client()

    def test_search_page_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Choose a state or territory', response.data)
        self.assertIn(b'/static/app.js', response.data)
        self.assertNotIn(b'<script>\n', response.data)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        self.assertIn(b'id="electionBanner"', response.data)
        self.assertIn(b'id="recallBanner"', response.data)

    def test_health_and_readiness_endpoints_report_status(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')
        ready = self.client.get('/readyz')
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.get_json()['jurisdiction_count'], 56)

    def test_readiness_fails_when_production_config_is_invalid(self):
        with patch.dict('os.environ', {'APP_ENV': 'production'}, clear=True):
            response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 503)
        self.assertIn('configuration_errors', response.get_json())

    def test_readiness_fails_when_curated_data_is_incomplete(self):
        with patch('app.load_state_services', return_value=[]):
            response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['status'], 'unready')

    def test_search_rejects_overlong_input(self):
        response = self.client.get('/api/search', query_string={'q': 'a' * 201})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.get_json())

    def test_json_search_endpoint_supports_mobile_and_desktop_clients(self):
        response = self.client.post(
            '/api/v1/search',
            json={'q': 'pothole', 'location': '', 'state': 'California'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['results'][0]['agency_name'], 'USA.gov - State and Local Governments')
        self.assertEqual(payload['state_service']['jurisdiction'], 'California')
        self.assertEqual(payload['election_info']['jurisdiction'], 'California')
        self.assertIn('Food and drug recalls', [
            route['category'] for route in payload['state_service']['routes']
        ])
        self.assertEqual(
            len(self.client.get('/api/v1/state-services').get_json()),
            56,
        )

    def test_json_search_rejects_non_text_fields(self):
        response = self.client.post(
            '/api/search',
            json={'q': ['pothole'], 'location': '', 'state': ''},
        )
        self.assertEqual(response.status_code, 400)

    def test_cors_is_not_open_by_default(self):
        with patch.dict('os.environ', {'CORS_ALLOWED_ORIGINS': ''}):
            response = self.client.get(
                '/api/state-services',
                headers={'Origin': 'https://untrusted.example'},
            )
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_cors_allowlist_allows_only_configured_origin(self):
        with patch.dict(
            'os.environ',
            {'CORS_ALLOWED_ORIGINS': 'https://android.example, https://desktop.example'},
        ):
            allowed = self.client.get(
                '/api/state-services',
                headers={'Origin': 'https://android.example'},
            )
            denied = self.client.get(
                '/api/state-services',
                headers={'Origin': 'https://attacker.example'},
            )
        self.assertEqual(
            allowed.headers['Access-Control-Allow-Origin'],
            'https://android.example',
        )
        self.assertNotIn('Access-Control-Allow-Origin', denied.headers)

    def test_api_rate_limit_returns_retry_after_without_trusting_forwarded_ip(self):
        original_limit = app.app.config['API_RATE_LIMIT_COUNT']
        original_window = app.app.config['API_RATE_LIMIT_WINDOW_SECONDS']
        app.app.config['API_RATE_LIMIT_COUNT'] = 1
        app.app.config['API_RATE_LIMIT_WINDOW_SECONDS'] = 60
        try:
            first = self.client.get(
                '/api/v1/state-services',
                environ_base={'REMOTE_ADDR': '198.51.100.15'},
                headers={'X-Forwarded-For': '203.0.113.44'},
            )
            second = self.client.get(
                '/api/v1/state-services',
                environ_base={'REMOTE_ADDR': '198.51.100.15'},
                headers={'X-Forwarded-For': '203.0.113.44'},
            )
        finally:
            app.app.config['API_RATE_LIMIT_COUNT'] = original_limit
            app.app.config['API_RATE_LIMIT_WINDOW_SECONDS'] = original_window
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn('Retry-After', second.headers)
        self.assertEqual(second.headers['Cache-Control'], 'no-store')

    def test_hsts_is_added_only_to_secure_requests(self):
        insecure = self.client.get('/healthz')
        secure = self.client.get('/healthz', base_url='https://localhost')
        self.assertNotIn('Strict-Transport-Security', insecure.headers)
        self.assertIn('Strict-Transport-Security', secure.headers)

    def test_production_configuration_requires_real_operational_values(self):
        env = {
            'APP_ENV': 'production',
            'GEOCODER_CONTACT': 'operator@civic.gov',
            'TRUSTED_PROXY_COUNT': '1',
            'PRIVACY_POLICY_URL': 'https://civic.gov/privacy',
            'SUPPORT_URL': 'https://civic.gov/support',
            'CORS_ALLOWED_ORIGINS': 'https://client.gov',
        }
        original_proxy_count = app.app.config['TRUSTED_PROXY_COUNT']
        try:
            app.app.config['TRUSTED_PROXY_COUNT'] = 1
            with patch.dict('os.environ', env, clear=True):
                self.assertEqual(app.production_configuration_errors(), [])
                os_env = patch.dict(
                    'os.environ',
                    {'CORS_ALLOWED_ORIGINS': 'https://client.gov/path'},
                    clear=False,
                )
                with os_env:
                    self.assertTrue(app.production_configuration_errors())
                invalid_contact = patch.dict(
                    'os.environ',
                    {'GEOCODER_CONTACT': 'operator@your-domain.invalid'},
                    clear=False,
                )
                with invalid_contact:
                    self.assertTrue(app.production_configuration_errors())
        finally:
            app.app.config['TRUSTED_PROXY_COUNT'] = original_proxy_count

    def test_unknown_state_does_not_return_arbitrary_routes(self):
        response = self.client.get('/api/search?state=Not+A+State')
        self.assertIsNone(response.get_json()['state_service'])

    def test_geocoding_outage_is_explicit_and_search_still_works(self):
        with patch('app.geocode_location_details', side_effect=GeocodingError):
            response = self.client.get('/api/search?location=Boston')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNotNone(payload['location_error'])
        self.assertEqual(len(payload['results']), 16)

    def test_directory_contains_real_official_contacts_and_local_locator(self):
        agencies = app.load_agencies()
        self.assertGreaterEqual(len(agencies), 6)
        self.assertIn('USA.gov - State and Local Governments', [
            agency['agency_name'] for agency in agencies
        ])
        for agency in agencies:
            self.assertNotIn(None, agency)
            self.assertTrue(agency['contact_url'].startswith('https://'))
            self.assertTrue(agency['source_url'].startswith('https://'))
            self.assertNotIn('example.gov', agency['contact_url'])
            self.assertNotIn('example.org', agency['contact_url'])
            self.assertTrue(agency['jurisdiction_scope'])

    def test_state_service_directory_covers_50_states_dc_and_territories(self):
        services = app.load_state_services()
        jurisdictions = {service['jurisdiction'] for service in services}
        self.assertEqual(len(services), 56)
        for jurisdiction in (
            'Alabama', 'California', 'New York', 'Wyoming', 'District of Columbia',
            'Puerto Rico', 'Guam', 'U.S. Virgin Islands', 'American Samoa',
            'Northern Mariana Islands',
        ):
            self.assertIn(jurisdiction, jurisdictions)
        self.assertTrue(all(
            service['dot_url'].startswith('https://')
            and service['local_directory_url'].startswith('https://')
            and service['source_url'].startswith('https://')
            for service in services
        ))

    def test_selected_state_returns_its_dot_and_local_directory(self):
        response = self.client.get('/api/search?state=California')
        service = response.get_json()['state_service']
        self.assertEqual(service['jurisdiction'], 'California')
        self.assertEqual(service['dot_name'], 'California Department of Transportation (Caltrans)')
        self.assertEqual(service['dot_url'], 'https://dot.ca.gov/')
        self.assertTrue(service['local_directory_url'].startswith('https://'))
        self.assertEqual(
            {route['category'] for route in service['routes']},
            {
                'State government and services',
                'Consumer complaints and Attorney General',
                'Environmental agencies',
                'Emergency management',
                'State elections and registration',
                'Food and drug recalls',
                'Meat, poultry, and egg recalls',
                'Consumer product recalls',
                'State roads and highways',
                'City and county services',
            },
        )
        routes = {route['category']: route for route in service['routes']}
        self.assertEqual(
            routes['State elections and registration']['url'],
            'https://www.usvotefoundation.org/california-election-dates-and-deadlines',
        )
        self.assertEqual(
            routes['State government and services']['url'],
            'https://www.usa.gov/states/california',
        )
        self.assertEqual(
            routes['Consumer complaints and Attorney General']['url'],
            'https://www.naag.org/find-my-ag/',
        )
        self.assertEqual(
            routes['Environmental agencies']['url'],
            'https://www.epa.gov/aboutepa/health-and-environmental-agencies-us-states-and-territories',
        )
        self.assertEqual(
            routes['Emergency management']['url'],
            'https://www.fema.gov/locations',
        )

    def test_territory_selection_uses_territorial_government_portal(self):
        response = self.client.get('/api/search?state=U.S.+Virgin+Islands')
        service = response.get_json()['state_service']
        government_route = next(
            route for route in service['routes']
            if route['category'] == 'State government and services'
        )
        self.assertEqual(government_route['url'], 'https://www.vi.gov/')

    def test_territory_alias_maps_to_supported_jurisdiction(self):
        response = self.client.post('/api/v1/search', json={
            'q': '',
            'location': '',
            'state': 'Virgin Islands',
        })
        self.assertEqual(
            response.get_json()['state_service']['jurisdiction'],
            'U.S. Virgin Islands',
        )

    def test_homelessness_search_routes_to_local_locator_not_hud(self):
        response = self.client.get('/api/search?q=homelessness')
        names = [agency['agency_name'] for agency in response.get_json()['results']]
        self.assertEqual(names, ['HUD Find Shelter'])
        self.assertIn('not a national shelter-placement', response.get_json()['results'][0]['notes'])

    def test_local_road_maintenance_routes_to_local_government(self):
        response = self.client.get('/api/search?q=pothole')
        results = response.get_json()['results']
        self.assertEqual(
            [agency['agency_name'] for agency in results],
            ['USA.gov - State and Local Governments'],
        )
        self.assertIn('not a complaint form', results[0]['notes'])

    def test_congressperson_search_finds_house_finder(self):
        response = self.client.get('/api/v1/search?q=congressperson')
        results = response.get_json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]['agency_name'],
            'U.S. House of Representatives - Find Your Representative',
        )
        self.assertEqual(
            results[0]['contact_url'],
            'https://www.house.gov/representatives/find-your-representative',
        )

    def test_senator_search_finds_senate_directory(self):
        response = self.client.get('/api/v1/search?q=senator')
        results = response.get_json()['results']
        self.assertEqual(results[0]['agency_name'], 'U.S. Senate - Find Your Senators')
        self.assertEqual(results[0]['phone'], '202-224-3121')

    def test_voter_registration_search_is_nonpartisan_and_warns_deadlines_vary(self):
        response = self.client.get('/api/v1/search?q=register+to+vote')
        results = response.get_json()['results']
        self.assertEqual(results[0]['agency_name'], 'USA.gov - Register to Vote')
        self.assertEqual(results[0]['contact_url'], 'https://www.usa.gov/register-to-vote')
        self.assertIn('deadlines vary', results[0]['notes'])

    def test_federal_election_banner_is_active_within_90_days(self):
        info = app.build_election_info(today=date(2026, 9, 29))
        self.assertEqual(info['federal_election_date'], '2026-11-03')
        self.assertEqual(info['days_until_federal_election'], 35)
        self.assertTrue(info['is_federal_election_season'])

    def test_election_calendar_link_uses_selected_jurisdiction_slug(self):
        for jurisdiction, expected_slug in (
            ('Georgia', 'georgia'),
            ('New York', 'new-york'),
            ('New Jersey', 'new-jersey'),
            ('District of Columbia', 'district-of-columbia'),
        ):
            with self.subTest(jurisdiction=jurisdiction):
                info = app.build_election_info(
                    {'jurisdiction': jurisdiction},
                    today=date(2026, 9, 29),
                )
                self.assertEqual(
                    info['state_calendar_url'],
                    f'https://www.usvotefoundation.org/{expected_slug}-election-dates-and-deadlines',
                )

    def test_new_jersey_selection_uses_us_vote_foundation_in_banner_and_state_route(self):
        response = self.client.post('/api/v1/search', json={
            'q': '',
            'location': '',
            'state': 'New Jersey',
        })
        payload = response.get_json()
        expected_url = (
            'https://www.usvotefoundation.org/'
            'new-jersey-election-dates-and-deadlines'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['election_info']['state_calendar_url'], expected_url)
        election_route = next(
            route for route in payload['state_service']['routes']
            if route['category'] == 'State elections and registration'
        )
        self.assertEqual(election_route['url'], expected_url)

    def test_geocoded_state_selects_state_election_calendar_link(self):
        with patch(
            'app.geocode_location_details',
            return_value=(33.749, -84.388, 'Georgia'),
        ):
            response = self.client.post('/api/v1/search', json={
                'q': '',
                'location': 'Atlanta',
                'state': '',
            })
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['state_service']['jurisdiction'], 'Georgia')
        self.assertEqual(
            payload['election_info']['state_calendar_url'],
            'https://www.usvotefoundation.org/georgia-election-dates-and-deadlines',
        )

    def test_territory_uses_general_election_calendar_link(self):
        info = app.build_election_info(
            {'jurisdiction': 'Puerto Rico'},
            today=date(2026, 9, 29),
        )
        self.assertEqual(info['state_calendar_url'], 'https://www.usa.gov/when-to-vote')

    def test_federal_election_reminder_window_starts_exactly_90_days_before(self):
        self.assertTrue(
            app.build_election_info(today=date(2026, 8, 5))['is_federal_election_season']
        )
        self.assertFalse(
            app.build_election_info(today=date(2026, 8, 4))['is_federal_election_season']
        )

    def test_federal_election_banner_moves_to_next_cycle_after_election_day(self):
        info = app.build_election_info(today=date(2026, 11, 4))
        self.assertEqual(info['federal_election_date'], '2028-11-07')
        self.assertFalse(info['is_federal_election_season'])

    def test_fda_recall_parser_returns_product_notice_and_ignores_terminated_rows(self):
        html = '''
        <table id="datatable"><thead><tr>
          <th>Date</th><th>Brand Name(s)</th><th>Product Description</th>
          <th>Product Type</th><th>Recall Reason Description</th>
          <th>Company Name</th><th>Terminated Recall</th><th>Excerpt</th>
        </tr></thead><tbody>
          <tr>
            <td><time datetime="2026-09-29T04:00:00Z">09/29/2026</time></td>
            <td><a href="/safety/recalls-market-withdrawals-safety-alerts/cheese-recall">Sierra Nevada Graziers</a></td>
            <td>Raw milk cheeses</td>
            <td>Food &amp; Beverages</td>
            <td>Potential contamination with E. coli</td>
            <td>Sierra Nevada Cheese Company</td>
            <td></td><td></td>
          </tr>
          <tr>
            <td><time datetime="2026-09-28T04:00:00Z">09/28/2026</time></td>
            <td><a href="/safety/recalls-market-withdrawals-safety-alerts/old-recall">Old Brand</a></td>
            <td>Product</td><td>Food</td><td>Issue</td><td>Company</td>
            <td>Terminated</td><td></td>
          </tr>
        </tbody></table>
        '''

        notices = app.parse_fda_recall_notices(html)

        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['title'], 'Sierra Nevada Graziers')
        self.assertEqual(notices[0]['date'], '2026-09-29T04:00:00Z')
        self.assertEqual(notices[0]['product'], 'Raw milk cheeses')
        self.assertIn('E. coli', notices[0]['reason'])
        self.assertEqual(
            notices[0]['url'],
            'https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts/cheese-recall',
        )

    def test_fda_recall_parser_rejects_non_fda_links(self):
        html = '''
        <table id="datatable"><thead><tr>
          <th>Date</th><th>Brand Name(s)</th><th>Product Description</th>
          <th>Product Type</th><th>Recall Reason Description</th>
          <th>Company Name</th><th>Terminated Recall</th><th>Excerpt</th>
        </tr></thead><tbody><tr>
          <td>09/29/2026</td>
          <td><a href="https://attacker.example/recall">Unsafe link</a></td>
          <td>Product</td><td>Food</td><td>Reason</td><td>Company</td><td></td><td></td>
        </tr></tbody></table>
        '''
        self.assertEqual(app.parse_fda_recall_notices(html), [])

    def test_fda_recall_parser_uses_column_names_not_fixed_positions(self):
        html = '''
        <table id="datatable"><thead><tr>
          <th>Company Name</th><th>Recall Reason Description</th>
          <th>Terminated Recall</th><th>Product Description</th>
          <th>Brand Name(s)</th><th>Date</th>
        </tr></thead><tbody><tr>
          <td>Cheese Company</td><td>Possible contamination</td><td></td>
          <td>Raw milk cheese</td>
          <td><a href="/safety/recalls-market-withdrawals-safety-alerts/cheese">Brand</a></td>
          <td><time datetime="2026-09-29">09/29/2026</time></td>
        </tr></tbody></table>
        '''
        notices = app.parse_fda_recall_notices(html)
        self.assertEqual(notices[0]['title'], 'Brand')
        self.assertEqual(notices[0]['company'], 'Cheese Company')

    def test_recall_endpoint_serves_cached_official_notices(self):
        app._recall_cache = None
        app._recall_cache_expiry = 0
        html = '''
        <table id="datatable"><thead><tr>
          <th>Date</th><th>Brand Name(s)</th><th>Product Description</th>
          <th>Product Type</th><th>Recall Reason Description</th>
          <th>Company Name</th><th>Terminated Recall</th><th>Excerpt</th>
        </tr></thead><tbody><tr>
          <td><time datetime="2026-09-29T04:00:00Z">09/29/2026</time></td>
          <td><a href="/safety/recalls-market-withdrawals-safety-alerts/cheese-recall">Cheese recall</a></td>
          <td>Raw milk cheese</td><td>Food</td><td>Potential contamination</td>
          <td>Cheese Company</td><td></td><td></td>
        </tr></tbody></table>
        '''
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.headers = {'Content-Type': 'text/html; charset=UTF-8'}
        response_mock.iter_content.return_value = [html.encode('utf-8')]
        with patch('app.requests.get', return_value=response_mock) as get:
            response = self.client.get('/api/v1/recalls')
            cached_response = self.client.get('/api/v1/recalls')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['notices'][0]['title'], 'Cheese recall')
        self.assertFalse(payload['is_stale'])
        self.assertIn('not a complete list', payload['scope_note'])
        self.assertEqual(cached_response.get_json(), payload)
        get.assert_called_once()

    def test_recall_endpoint_reports_source_outage_and_source_links(self):
        app._recall_cache = None
        app._recall_cache_expiry = 0
        with patch('app.requests.get', side_effect=app.requests.RequestException('offline')):
            response = self.client.get('/api/v1/recalls')
        self.assertEqual(response.status_code, 503)
        self.assertIn('fda', response.get_json()['source_urls'])

    def test_recall_endpoint_rejects_unexpected_upstream_content_type(self):
        app._recall_cache = None
        app._recall_cache_expiry = 0
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.headers = {'Content-Type': 'application/octet-stream'}
        with patch('app.requests.get', return_value=response_mock):
            response = self.client.get('/api/v1/recalls')
        self.assertEqual(response.status_code, 503)

    def test_recall_endpoint_marks_cached_data_stale_when_refresh_fails(self):
        app._recall_cache = {
            'notices': [{'title': 'Cached notice'}],
            'source': 'FDA',
            'source_url': app.FDA_RECALLS_URL,
            'retrieved_at': '2026-09-29T00:00:00+00:00',
            'is_stale': False,
            'scope_note': 'Not complete.',
        }
        app._recall_cache_expiry = 0
        app._recall_cache_stale_expiry = time.monotonic() + 60
        with patch('app.requests.get', side_effect=app.requests.RequestException('offline')):
            response = self.client.get('/api/v1/recalls')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['is_stale'])
        self.assertIn('may be outdated', response.get_json()['warning'])

    def test_fair_housing_search_returns_hud_with_scope(self):
        response = self.client.get('/api/search?q=fair+housing')
        result = response.get_json()['results'][0]
        self.assertIn('Housing and Urban Development', result['agency_name'])
        self.assertIn('not general landlord-tenant', result['notes'])

    def test_geocoder_is_restricted_to_us_locations(self):
        response = Mock()
        response.json.return_value = [{
            'lat': '40.0',
            'lon': '-75.0',
            'address': {'state': 'Pennsylvania'},
        }]
        with patch('geocode.requests.get', return_value=response) as get:
            self.assertEqual(geocode_location('Example City'), (40.0, -75.0))
            self.assertEqual(
                geocode_location_details('Example City'),
                (40.0, -75.0, 'Pennsylvania'),
            )
        self.assertEqual(
            get.call_args.kwargs['params']['countrycodes'],
            'us,pr,gu,vi,as,mp',
        )
        self.assertIn('CivicContactFinder/1.0', get.call_args.kwargs['headers']['User-Agent'])

    def test_geocoder_rejects_invalid_coordinates(self):
        response = Mock()
        response.json.return_value = [{'lat': '999', 'lon': '-75', 'address': {}}]
        with patch('geocode.requests.get', return_value=response):
            with self.assertRaises(GeocodingError):
                geocode_location_details('Invalid Coordinates')

    def test_location_search_ranks_nearest_first_and_reports_distances(self):
        with (
            patch('app.load_agencies', return_value=self.agencies),
            patch('app.geocode_location_details', return_value=(40.0, -75.0, 'Example State')),
        ):
            response = self.client.get('/api/search?location=Example+City')

        self.assertEqual(response.status_code, 200)
        results = response.get_json()['results']
        self.assertEqual(
            [agency['agency_name'] for agency in results],
            ['Nearby Public Works', 'Far Transit Agency', 'Agency Without Coordinates'],
        )
        self.assertAlmostEqual(results[0]['distance_km'], 1.1, places=1)
        self.assertAlmostEqual(results[1]['distance_km'], 11.1, places=1)
        self.assertNotIn('distance_km', results[2])

    def test_issue_relevance_remains_ahead_of_distance(self):
        with (
            patch('app.load_agencies', return_value=self.agencies),
            patch('app.geocode_location_details', return_value=(40.0, -75.0, 'Example State')),
        ):
            response = self.client.get('/api/search?q=transit&location=Example+City')

        results = response.get_json()['results']
        self.assertEqual(results[0]['agency_name'], 'Far Transit Agency')

    def test_distance_calculation_and_location_detection(self):
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.2, places=1)
        self.assertTrue(looks_like_location('12 Main St'))
        self.assertFalse(looks_like_location('streetlights'))


if __name__ == '__main__':
    unittest.main()
