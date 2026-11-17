(() => {
  const qInput = document.getElementById('q');
  const stateInput = document.getElementById('state');
  const btn = document.getElementById('searchBtn');
  const results = document.getElementById('results');
  const locationStatus = document.getElementById('locationStatus');
  const stateRouting = document.getElementById('stateRouting');
  const electionBanner = document.getElementById('electionBanner');
  const dataBase = './civic_contact_finder/data/';

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let field = '';
    let quoted = false;

    for (let index = 0; index < text.length; index += 1) {
      const character = text[index];
      if (quoted) {
        if (character === '"') {
          if (text[index + 1] === '"') {
            field += '"';
            index += 1;
          } else {
            quoted = false;
          }
        } else {
          field += character;
        }
      } else if (character === '"' && field.length === 0) {
        quoted = true;
      } else if (character === ',') {
        row.push(field);
        field = '';
      } else if (character === '\n' || character === '\r') {
        row.push(field);
        if (row.some(value => value !== '')) rows.push(row);
        row = [];
        field = '';
        if (character === '\r' && text[index + 1] === '\n') index += 1;
      } else {
        field += character;
      }
    }

    if (quoted) throw new Error('The directory CSV contains an unfinished quoted field.');
    row.push(field);
    if (row.some(value => value !== '')) rows.push(row);
    if (rows.length < 2) throw new Error('The directory CSV has no data rows.');

    const headers = rows[0].map((header, index) =>
      index === 0 ? header.replace(/^\uFEFF/, '') : header,
    );
    return rows.slice(1).map((values, rowIndex) => {
      if (values.length !== headers.length) {
        throw new Error(`Directory CSV row ${rowIndex + 2} has an unexpected number of columns.`);
      }
      return Object.fromEntries(headers.map((header, index) => [header, values[index]]));
    });
  }

  async function loadCsv(filename) {
    const response = await fetch(`${dataBase}${filename}`);
    if (!response.ok) throw new Error(`Could not load ${filename} (HTTP ${response.status}).`);
    return parseCsv(await response.text());
  }

  function safeHttpsUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' ? url.href : '';
    } catch {
      return '';
    }
  }

  function createLink(url, label) {
    const safeUrl = safeHttpsUrl(url);
    if (!safeUrl) return document.createTextNode(label);
    const link = document.createElement('a');
    link.href = safeUrl;
    link.textContent = label;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }

  function addParagraph(parent, text, className) {
    const paragraph = document.createElement('p');
    if (className) paragraph.className = className;
    paragraph.textContent = text;
    parent.appendChild(paragraph);
    return paragraph;
  }

  function stateElectionCalendarUrl(jurisdiction) {
    const territories = new Set([
      'American Samoa',
      'Guam',
      'Northern Mariana Islands',
      'Puerto Rico',
      'U.S. Virgin Islands',
    ]);
    if (!jurisdiction || territories.has(jurisdiction)) {
      return 'https://www.usa.gov/when-to-vote';
    }
    const slug = jurisdiction.toLowerCase().split(/\s+/).join('-');
    return `https://www.usvotefoundation.org/${slug}-election-dates-and-deadlines`;
  }

  function nextFederalElectionDate(today) {
    let year = today.getUTCFullYear();
    if (year % 2 !== 0) year += 1;

    for (;;) {
      const novemberFirst = new Date(Date.UTC(year, 10, 1));
      const firstMonday = 1 + ((1 - novemberFirst.getUTCDay() + 7) % 7);
      const electionDate = new Date(Date.UTC(year, 10, firstMonday + 1));
      if (electionDate >= today) return electionDate;
      year += 2;
    }
  }

  function renderElectionBanner(jurisdiction) {
    electionBanner.replaceChildren();
    const today = new Date();
    const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
    const electionDate = nextFederalElectionDate(new Date(todayUtc));
    const daysUntil = Math.round((electionDate.getTime() - todayUtc) / 86400000);
    const formattedDate = new Intl.DateTimeFormat(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(electionDate);

    addParagraph(
      electionBanner,
      daysUntil <= 90
        ? `Federal election season: Election Day is ${formattedDate} (${daysUntil} days away). If eligible, register or check/update your registration now; deadlines vary by state.`
        : `The federal election reminder window is not active. The next federal Election Day is ${formattedDate}. You can register or check your status anytime; state election dates and deadlines vary.`,
      'election-message',
    );
    const links = document.createElement('p');
    links.className = 'election-links';
    links.append(
      createLink('https://www.usa.gov/register-to-vote', 'Register or check your voter registration'),
      document.createTextNode(' · '),
      createLink(stateElectionCalendarUrl(jurisdiction), 'State and local election dates and deadlines'),
    );
    electionBanner.appendChild(links);
  }

  function renderStateRoutes(service) {
    stateRouting.replaceChildren();
    if (!service) return;

    const jurisdiction = service.jurisdiction;
    const territoryPortals = {
      'U.S. Virgin Islands': 'https://www.vi.gov/',
      'Puerto Rico': 'https://www.pr.gov/',
      Guam: 'https://www.guam.gov/',
      'American Samoa': 'https://www.americansamoa.gov/',
      'Northern Mariana Islands': 'https://governor.cnmi.gov/cnmi-government-directory/',
    };
    const governmentPortal = territoryPortals[jurisdiction]
      || `https://www.usa.gov/states/${jurisdiction.toLowerCase().replace(/\s+/g, '-')}`;
    const routes = [
      {
        category: 'State government and services',
        name: territoryPortals[jurisdiction]
          ? `${jurisdiction} government portal`
          : `${jurisdiction} government on USA.gov`,
        url: governmentPortal,
        description: 'Official directory for the selected state or territory, including major agencies and services.',
      },
      {
        category: 'Consumer complaints and Attorney General',
        name: 'Find your Attorney General',
        url: 'https://www.naag.org/find-my-ag/',
        description: 'Official national directory for the state or territorial Attorney General; choose the jurisdiction to reach its office and consumer-protection resources.',
      },
      {
        category: 'Environmental agencies',
        name: 'State and territorial environmental agencies',
        url: 'https://www.epa.gov/aboutepa/health-and-environmental-agencies-us-states-and-territories',
        description: 'EPA directory of state and territorial environment and public-health agencies.',
      },
      {
        category: 'Emergency management',
        name: 'Find disaster and emergency resources',
        url: 'https://www.fema.gov/locations',
        description: 'FEMA location finder for state, territorial, and local emergency-management information. Call 911 for immediate danger.',
      },
      {
        category: 'State elections and registration',
        name: 'Find election dates, deadlines, and your election office',
        url: stateElectionCalendarUrl(jurisdiction),
        description: 'State election dates, registration deadlines, ballot rules, and early-voting options vary. Confirm details with your state or local election office.',
      },
      {
        category: 'Food and drug recalls',
        name: 'FDA recalls and safety alerts',
        url: 'https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts',
        description: 'FDA recall notices for food, drugs, medical devices, cosmetics, and other FDA-regulated products.',
      },
      {
        category: 'Meat, poultry, and egg recalls',
        name: 'USDA FSIS recalls and alerts',
        url: 'https://www.fsis.usda.gov/recalls-alerts',
        description: 'USDA Food Safety and Inspection Service recall notices for meat, poultry, and processed egg products.',
      },
      {
        category: 'Consumer product recalls',
        name: 'Consumer Product Safety Commission recalls',
        url: 'https://www.cpsc.gov/Recalls',
        description: 'Official recalls and safety notices for consumer products such as appliances, toys, batteries, and household goods.',
      },
      {
        category: 'State roads and highways',
        name: service.dot_name,
        url: service.dot_url,
        description: 'For roads and highways maintained by the state, not city or county streets.',
      },
      {
        category: 'City and county services',
        name: 'Local government directory',
        url: service.local_directory_url,
        description: 'Find the relevant city or county for local roads, trash, parks, housing, and other municipal services.',
      },
    ];

    const section = document.createElement('section');
    section.className = 'state-routing';
    const heading = document.createElement('h2');
    heading.textContent = `${jurisdiction} service routes`;
    section.appendChild(heading);
    addParagraph(section, 'Choose the route that matches your issue. Local services are handled by the city or county; statewide links do not replace local service desks.');

    const grid = document.createElement('div');
    grid.className = 'route-grid';
    for (const route of routes) {
      if (!safeHttpsUrl(route.url)) continue;
      const card = document.createElement('article');
      card.className = 'route';
      const routeHeading = document.createElement('h3');
      routeHeading.textContent = route.category;
      card.appendChild(routeHeading);
      addParagraph(card, route.description);
      const link = createLink(route.url, route.name || route.category);
      card.appendChild(link);
      grid.appendChild(card);
    }
    section.appendChild(grid);
    stateRouting.appendChild(section);
  }

  function addAction(parent, url, label, className) {
    let safeUrl = safeHttpsUrl(url);
    if (!safeUrl && /^(mailto|tel):/i.test(url)) {
      try {
        const parsed = new URL(url);
        if (parsed.protocol === 'mailto:' || parsed.protocol === 'tel:') {
          safeUrl = parsed.href;
        }
      } catch {
        safeUrl = '';
      }
    }
    if (!safeUrl) return;
    const link = document.createElement('a');
    link.className = className;
    link.href = safeUrl;
    link.textContent = label;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    parent.appendChild(link);
  }

  function renderAgency(agency) {
    const card = document.createElement('article');
    card.className = 'card';
    const heading = document.createElement('h2');
    heading.textContent = agency.agency_name || '';
    card.appendChild(heading);
    addParagraph(card, agency.jurisdiction || '', 'meta');
    if (agency.jurisdiction_scope) {
      const scope = document.createElement('p');
      scope.className = 'scope';
      const label = document.createElement('strong');
      label.textContent = 'Scope: ';
      scope.append(label, document.createTextNode(agency.jurisdiction_scope));
      card.appendChild(scope);
    }
    addParagraph(card, `Issues: ${agency.issue_types || ''}`);
    if (agency.keywords) addParagraph(card, agency.keywords);

    const actions = document.createElement('div');
    actions.className = 'actions';
    addAction(actions, agency.contact_url, 'Open official contact', 'btn');
    addAction(actions, agency.source_url, 'Source / scope', 'source-link');
    const email = String(agency.email || '').replace(/[\r\n]/g, '');
    if (email) {
      const subject = encodeURIComponent('Service request');
      const body = encodeURIComponent(
        `Hello\n\nI would like to report: ${agency.issue_types || ''}\n\nLocation: [paste address or intersection here]\n\nThanks`,
      );
      addAction(actions, `mailto:${email}?subject=${subject}&body=${body}`, 'Email', 'btn');
    }
    const phone = String(agency.phone || '').replace(/[^\d+(). -]/g, '');
    if (phone) addAction(actions, `tel:${phone}`, 'Call', 'btn');
    card.appendChild(actions);
    if (agency.notes) addParagraph(card, agency.notes, 'notes');
    return card;
  }

  function searchAgencies(agencies) {
    const query = qInput.value.trim().slice(0, 200).toLowerCase();
    const matches = [];

    for (const agency of agencies) {
      const issueTypes = (agency.issue_types || '')
        .split(';')
        .map(value => value.trim().toLowerCase())
        .filter(Boolean);
      const searchable = [
        agency.agency_name || '',
        agency.jurisdiction || '',
        agency.keywords || '',
      ].join(' ').toLowerCase();
      let score = 0;
      if (query && issueTypes.some(issue => issue.includes(query))) score += 30;
      if (query && searchable.includes(query)) score += 15;
      if (query && (agency.agency_name || '').toLowerCase().includes(query)) score += 10;
      if (score > 0) matches.push({ agency, score });
    }

    matches.sort((left, right) => right.score - left.score);
    return query ? matches.map(match => match.agency) : agencies.slice(0, 20);
  }

  function renderResults(agencies) {
    const matches = searchAgencies(agencies);
    results.replaceChildren();
    if (!matches.length) {
      results.textContent = 'No matches found. Try a different phrase.';
      return;
    }
    for (const agency of matches) results.appendChild(renderAgency(agency));
  }

  async function initialize() {
    try {
      const [agencies, services] = await Promise.all([
        loadCsv('agencies.csv'),
        loadCsv('state_services.csv'),
      ]);
      if (services.length !== 56 || services.some(service => !service.jurisdiction)) {
        throw new Error('The state and territory directory is incomplete or invalid.');
      }
      if (!agencies.length || agencies.some(agency => !agency.agency_name)) {
        throw new Error('The agency directory is empty or invalid.');
      }

      stateInput.replaceChildren();
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Choose state/territory';
      stateInput.appendChild(placeholder);
      for (const service of services) {
        const option = document.createElement('option');
        option.value = service.jurisdiction;
        option.textContent = service.jurisdiction;
        stateInput.appendChild(option);
      }

      stateInput.value = 'District of Columbia';
      stateInput.disabled = false;
      btn.disabled = false;
      renderStateRoutes(services.find(service => service.jurisdiction === stateInput.value));
      renderElectionBanner(stateInput.value);
      renderResults(agencies);
      locationStatus.textContent = `Showing the demo for Washington, D.C. (${services.length} jurisdictions available).`;

      function updatePage() {
        const service = services.find(item => item.jurisdiction === stateInput.value);
        renderStateRoutes(service);
        renderElectionBanner(stateInput.value);
        renderResults(agencies);
        locationStatus.textContent = service
          ? `Showing ${service.jurisdiction} service routes.`
          : 'Choose a state or territory to see its service routes.';
      }

      btn.addEventListener('click', () => updatePage());
      qInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') updatePage();
      });
      stateInput.addEventListener('change', updatePage);
    } catch (error) {
      locationStatus.textContent = `The static directory could not be loaded: ${error.message}`;
      results.replaceChildren();
      stateRouting.replaceChildren();
      btn.disabled = true;
      stateInput.disabled = true;
    }
  }

  initialize();
})();
