(() => {
  const qInput = document.getElementById('q');
  const locationInput = document.getElementById('location');
  const stateInput = document.getElementById('state');
  const btn = document.getElementById('searchBtn');
  const results = document.getElementById('results');
  const locationStatus = document.getElementById('locationStatus');
  const stateRouting = document.getElementById('stateRouting');
  const electionBanner = document.getElementById('electionBanner');
  const recallBanner = document.getElementById('recallBanner');
  let requestSequence = 0;

  async function search(q, location, state) {
    const sequence = ++requestSequence;
    btn.disabled = true;
    locationStatus.textContent = 'Searching…';

    try {
      const response = await fetch('/api/v1/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q, location, state }),
      });
      const data = await response.json();
      if (sequence !== requestSequence) return;
      if (!response.ok) {
        throw new Error(data.error || 'Search failed. Please try again.');
      }
      renderResults(data);
    } catch (error) {
      if (sequence !== requestSequence) return;
      locationStatus.textContent = error.message || 'Could not reach the search service.';
      results.replaceChildren();
    } finally {
      if (sequence === requestSequence) btn.disabled = false;
    }
  }

  async function loadStates() {
    const response = await fetch('/api/v1/state-services');
    if (!response.ok) throw new Error('Could not load state and territory routes.');
    const states = await response.json();
    for (const name of states) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      stateInput.appendChild(option);
    }
  }

  async function loadRecalls() {
    try {
      const response = await fetch('/api/v1/recalls');
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Recall notices are temporarily unavailable.');
      }
      renderRecallNotices(data);
    } catch (error) {
      renderRecallUnavailable(error.message || 'Recall notices are temporarily unavailable.');
    }
  }

  function renderResults(data) {
    const items = Array.isArray(data.results) ? data.results : [];
    const locationContext = data.location_context;

    if (data.location_error) {
      locationStatus.textContent = data.location_error;
    } else if (locationContext) {
      locationStatus.textContent = locationContext.state
        ? `Location found: ${locationContext.query}, ${locationContext.state}.`
        : `Location found: ${locationContext.query}. Choose your state or territory if it was not identified automatically.`;
    } else if (data.location_query) {
      locationStatus.textContent = 'Could not resolve that U.S. location. Check the address or try again later.';
    } else {
      locationStatus.textContent = '';
    }

    renderStateRoutes(data.state_service);
    renderElectionBanner(data.election_info);
    results.replaceChildren();
    if (items.length === 0) {
      results.textContent = 'No matches found. Try a different phrase.';
      return;
    }

    for (const agency of items) {
      const card = document.createElement('article');
      card.className = 'card';
      const contactUrl = safeHttpsUrl(agency.contact_url);
      const sourceUrl = safeHttpsUrl(agency.source_url);
      const email = String(agency.email || '').replace(/[\r\n]/g, '');
      const phone = String(agency.phone || '').replace(/[^\d+(). -]/g, '');

      card.innerHTML = `
        <h2>${escapeHtml(agency.agency_name || '')}</h2>
        <p class="meta">${escapeHtml(agency.jurisdiction || '')}</p>
        ${agency.jurisdiction_scope ? `<p class="scope"><strong>Scope:</strong> ${escapeHtml(agency.jurisdiction_scope)}</p>` : ''}
        ${Number.isFinite(agency.distance_km) ? `<p class="distance">${agency.distance_km} km away</p>` : ''}
        <p><strong>Issues:</strong> ${escapeHtml(agency.issue_types || '')}</p>
        <p>${escapeHtml(agency.keywords || '')}</p>
        <div class="actions">
          ${contactUrl ? `<a class="btn" href="${escapeAttr(contactUrl)}" target="_blank" rel="noopener noreferrer">Open official contact</a>` : ''}
          ${sourceUrl ? `<a class="source-link" href="${escapeAttr(sourceUrl)}" target="_blank" rel="noopener noreferrer">Source / scope</a>` : ''}
          ${email ? `<a class="btn" href="mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent('Service request')}&body=${encodeURIComponent(prefillBody(agency))}">Email</a>` : ''}
          ${phone ? `<a class="btn" href="tel:${encodeURIComponent(phone)}">Call</a>` : ''}
        </div>
        ${agency.notes ? `<p class="notes">${escapeHtml(agency.notes)}</p>` : ''}
      `;
      results.appendChild(card);
    }
  }

  function renderStateRoutes(service) {
    stateRouting.replaceChildren();
    if (!service) return;
    stateInput.value = service.jurisdiction;

    const section = document.createElement('section');
    section.className = 'state-routing';
    section.innerHTML = `
      <h2>${escapeHtml(service.jurisdiction)} service routes</h2>
      <p>Choose the route that matches your issue. Local services are handled by the city or county; statewide links do not replace local service desks.</p>
      <div class="route-grid">
        ${service.routes.map(route => {
          const url = safeHttpsUrl(route.url);
          if (!url) return '';
          return `
            <article class="route">
              <h3>${escapeHtml(route.category)}</h3>
              <p>${escapeHtml(route.description)}</p>
              <a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(route.name || route.category)}</a>
            </article>`;
        }).join('')}
      </div>
      ${service.verification_notes ? `<p class="notes">${escapeHtml(service.verification_notes)}</p>` : ''}
    `;
    stateRouting.appendChild(section);
  }

  function renderElectionBanner(info) {
    electionBanner.replaceChildren();
    if (!info || !info.federal_election_date) {
      electionBanner.textContent = 'Election information is temporarily unavailable.';
      return;
    }

    const electionDate = new Date(`${info.federal_election_date}T00:00:00`);
    const formattedDate = new Intl.DateTimeFormat(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }).format(electionDate);
    const federalMessage = document.createElement('p');
    federalMessage.className = 'election-message';
    if (info.is_federal_election_season) {
      federalMessage.textContent = `Federal election season: Election Day is ${formattedDate} (${info.days_until_federal_election} days away). If eligible, register or check/update your registration now; deadlines vary by state.`;
    } else {
      federalMessage.textContent = `The federal election reminder window is not active. The next federal Election Day is ${formattedDate}. You can register or check your status anytime; state election dates and deadlines vary.`;
    }
    electionBanner.appendChild(federalMessage);

    const links = document.createElement('p');
    links.className = 'election-links';
    links.append(
      createLink(info.registration_url, 'Register or check your voter registration'),
      document.createTextNode(' · '),
      createLink(info.state_calendar_url, 'State and local election dates and deadlines'),
    );
    electionBanner.appendChild(links);
  }

  function renderRecallNotices(data) {
    recallBanner.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = 'Recent product recalls';
    recallBanner.appendChild(heading);
    if (data.is_stale && data.warning) {
      const warning = document.createElement('p');
      warning.className = 'stale-warning';
      warning.setAttribute('role', 'status');
      warning.textContent = data.warning;
      recallBanner.appendChild(warning);
    }
    if (data.retrieved_at) {
      const sourceDate = document.createElement('p');
      sourceDate.className = 'recall-note';
      sourceDate.textContent = `${data.is_stale ? 'Last successful source check' : 'Source checked'}: ${formatRecallDate(data.retrieved_at)}`;
      recallBanner.appendChild(sourceDate);
    }

    if (!Array.isArray(data.notices) || data.notices.length === 0) {
      const empty = document.createElement('p');
      empty.textContent = 'No recent notices were returned by the FDA listing. Check the official recall pages below; this is not a guarantee that no recalls exist.';
      recallBanner.appendChild(empty);
    } else {
      const list = document.createElement('ul');
      list.className = 'recall-list';
      for (const notice of data.notices) {
        const item = document.createElement('li');
        const title = document.createElement('a');
        title.href = safeHttpsUrl(notice.url) || '#';
        title.textContent = notice.title || 'FDA recall notice';
        title.target = '_blank';
        title.rel = 'noopener noreferrer';
        item.appendChild(title);
        if (notice.date) {
          const date = document.createElement('span');
          date.className = 'recall-date';
          date.textContent = ` — ${formatRecallDate(notice.date)}`;
          item.appendChild(date);
        }
        if (notice.company) {
          const company = document.createElement('p');
          company.textContent = `Company: ${notice.company}`;
          item.appendChild(company);
        }
        if (notice.product) {
          const product = document.createElement('p');
          product.textContent = notice.product;
          item.appendChild(product);
        }
        if (notice.reason) {
          const reason = document.createElement('p');
          reason.textContent = `Reason: ${notice.reason}`;
          item.appendChild(reason);
        }
        if (notice.status_note) {
          const status = document.createElement('p');
          status.className = 'recall-note';
          status.textContent = notice.status_note;
          item.appendChild(status);
        }
        list.appendChild(item);
      }
      recallBanner.appendChild(list);
    }

    const scope = document.createElement('p');
    scope.className = 'recall-note';
    scope.textContent = data.scope_note || 'Check the original notice for affected products, lot numbers, distribution, and current status.';
    recallBanner.appendChild(scope);

    const sources = document.createElement('p');
    sources.className = 'recall-sources';
    sources.append(
      createLink(data.source_url, 'FDA food, drug, and device notices'),
      document.createTextNode(' · '),
      createLink('https://www.fsis.usda.gov/recalls-alerts', 'USDA meat, poultry, and egg recalls'),
      document.createTextNode(' · '),
      createLink('https://www.cpsc.gov/Recalls', 'CPSC consumer product recalls'),
    );
    recallBanner.appendChild(sources);
  }

  function formatRecallDate(value) {
    const datePart = /^\d{4}-\d{2}-\d{2}/.exec(value);
    if (!datePart) return value;
    const parsedDate = new Date(`${datePart[0]}T00:00:00`);
    if (Number.isNaN(parsedDate.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }).format(parsedDate);
  }

  function renderRecallUnavailable(message) {
    recallBanner.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = 'Recent product recalls';
    const error = document.createElement('p');
    error.textContent = `${message} Check official recall sources directly:`;
    const sources = document.createElement('p');
    sources.append(
      createLink('https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts', 'FDA food, drug, and device notices'),
      document.createTextNode(' · '),
      createLink('https://www.fsis.usda.gov/recalls-alerts', 'USDA meat, poultry, and egg recalls'),
      document.createTextNode(' · '),
      createLink('https://www.cpsc.gov/Recalls', 'CPSC consumer product recalls'),
    );
    recallBanner.append(heading, error, sources);
  }

  function createLink(url, label) {
    const link = document.createElement('a');
    link.href = safeHttpsUrl(url) || '#';
    link.textContent = label;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }

  function prefillBody(agency) {
    return `Hello\n\nI would like to report: ${agency.issue_types || ''}\n\nLocation: [paste address or intersection here]\n\nThanks`;
  }

  function safeHttpsUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' ? url.href : '';
    } catch {
      return '';
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[character]);
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  btn.addEventListener('click', () => search(qInput.value, locationInput.value, stateInput.value));
  qInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') search(qInput.value, locationInput.value, stateInput.value);
  });
  locationInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') search(qInput.value, locationInput.value, stateInput.value);
  });
  stateInput.addEventListener('change', () => search(qInput.value, locationInput.value, stateInput.value));

  loadStates()
    .then(() => search('', '', ''))
    .catch(error => {
      locationStatus.textContent = error.message || 'Could not load the civic directory.';
      btn.disabled = true;
    });
  loadRecalls();
})();
