const state = {
  metadata: null,
  mode: "single",
  matchupResult: null,
  gameDayResult: null,
  leagueResult: null,
  leagueGame: null,
  leagueVisibleGames: 60,
  leagueJobId: null,
  leaguePollTimer: null,
  franchise: null,
  franchiseSaves: [],
  lifecyclePlayerId: null,
  lifecycleProjection: null,
  healthPlayerId: null,
  scoutingBoard: [],
  scoutingPlayerId: null,
  scoutingBoardSaveId: null,
  draftProspectId: null,
  tradeBoard: null,
  tradeBoardSaveId: null,
  tradeEvaluation: null,
  tradeSelections: {},
  competitionResult: null,
  healthResult: null,
};

const LEAGUE_JOB_STORAGE_KEY = "nba-sim-active-league-job";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pct(value, digits = 1) {
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function number(value, digits = 1) {
  return Number(value).toFixed(digits);
}

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const whole = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remaining = whole % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remaining}s`;
  return `${remaining}s`;
}

function money(value, digits = 3) {
  if (value === null || value === undefined) return "Unknown";
  return `$${(Number(value) / 1_000_000).toFixed(digits)}M`;
}

const GUIDE_TOPICS = {
  start: {
    title: "Start here",
    body: `
      <p class="guide-lead">Choose the workspace that matches the question you want to answer. Every simulation is local, and every completed run keeps its seed so an unusual result can be reproduced.</p>
      <ol class="guide-steps">
        <li><strong>One matchup?</strong><span>Use Matchup Lab for a playable game, a raw distribution, or a calibrated hybrid forecast.</span></li>
        <li><strong>Today’s published slate?</strong><span>Use Game Day for point-in-time schedule, injury, rest, and travel context.</span></li>
        <li><strong>A whole NBA season?</strong><span>Use League Sim. It plays all 1,230 games once and saves every box score for this session.</span></li>
        <li><strong>Run a front office?</strong><span>Create a Franchise save, branch decisions, test transaction legality, and explore player development.</span></li>
        <li><strong>Check the model?</strong><span>Model Health audits league statistics and tests predictions on unseen historical games.</span></li>
      </ol>`,
  },
  matchup: {
    title: "Matchup Lab",
    body: `
      <p class="guide-lead">This is the most direct way to ask “what might happen if these two teams played?”</p>
      <div class="guide-section"><h3>Choose a mode</h3><p><strong>Single game</strong> plays one possession-by-possession result with a full event log. <strong>Monte Carlo</strong> repeats the game to show raw uncertainty. <strong>Hybrid</strong> reconciles those coherent games to the stronger macro margin and total forecast.</p></div>
      <div class="guide-section"><h3>Adjust availability</h3><p>Mark a player Out or add a minute cap. The rotation redistributes minutes before the game; it does not merely subtract a fixed point estimate.</p></div>
      <div class="guide-note"><strong>Best practice</strong><span>Use Single Game for storytelling and box scores. Use Hybrid when you care about win probability or ranges.</span></div>`,
  },
  gameday: {
    title: "Game Day",
    body: `
      <p class="guide-lead">Game Day forecasts only games present in the stored official NBA schedule snapshot.</p>
      <div class="guide-section"><h3>What enters the forecast</h3><p>The chronological team-strength distribution is the base. Current roster availability changes that base. Rest and travel are displayed, but they affect the forecast only when their held-out validation gate passes.</p></div>
      <div class="guide-section"><h3>Why “Report pending” appears</h3><p>The NBA injury report may not be published yet. In that case the tool says so and treats the current roster as active instead of inventing injuries.</p></div>
      <div class="guide-note"><strong>Schedule delta of +0.0</strong><span>This can be intentional: context is visible even when its learned effect is withheld for failing the promotion gate.</span></div>`,
  },
  league: {
    title: "League Sim",
    body: `
      <p class="guide-lead">League Sim builds the NBA’s 82-game opponent structure and plays one complete possession-level game for every matchup.</p>
      <ol class="guide-steps">
        <li><strong>Start the season</strong><span>A fresh seed defines this entire alternate season.</span></li>
        <li><strong>Watch progress</strong><span>The bar advances after each completed game and estimates remaining time once enough games have finished.</span></li>
        <li><strong>Browse the result</strong><span>Filter all 1,230 games by team or month and open any native player box score.</span></li>
      </ol>
      <div class="guide-note"><strong>Why one game, not 100?</strong><span>The objective here is a realized season, not an average season. Favorites can lose, outliers survive, and replaying with a new seed creates a genuinely different history.</span></div>`,
  },
  franchise: {
    title: "Franchise",
    body: `
      <p class="guide-lead">A Franchise is a durable, branching league timeline. It is the foundation for the rebuilding game.</p>
      <div class="guide-section"><h3>Save and branch</h3><p>Advancing the calendar autosaves a hash-chained event. Branching copies the exact loaded moment into an independent timeline, so you can compare choices without overwriting the original.</p></div>
      <div class="guide-section"><h3>League office</h3><p>Shows the canonical roster universe, date, phase, data coverage, integrity proof, and recent ledger events.</p></div>
      <div class="guide-section"><h3>Cap & CBA</h3><p>Shows official 2026–27 system levels and checks a transaction scenario. Real salaries remain Unknown until an authoritative contract source is imported.</p></div>
      <div class="guide-section"><h3>Player development</h3><p>Uses saved lifecycle baselines to project growth, prime, decline, workload effects, and retirement uncertainty without committing the scenario to your league.</p></div>`,
  },
  cba: {
    title: "Cap & CBA",
    body: `
      <p class="guide-lead">The salary cap, tax, and aprons are different lines. The cap controls ordinary signing room; the tax adds cost; the aprons remove transaction tools and can hard-cap a team.</p>
      <div class="guide-section"><h3>How to use the checker</h3><p>Enter full apron team salary before the move, salary leaving, salary arriving, and the transaction mechanism. A green result means the encoded gate clears under the listed assumptions—not that the other team accepts.</p></div>
      <div class="guide-section"><h3>First-apron triggers</h3><p>Examples encoded here include the non-taxpayer MLE, receiving a sign-and-traded player, and the expanded traded-player exception.</p></div>
      <div class="guide-section"><h3>Second-apron triggers</h3><p>Examples encoded here include aggregating outgoing salaries, sending cash in a trade, and using the taxpayer MLE.</p></div>
      <div class="guide-note"><strong>Important</strong><span>Trade kickers, prior exception use, cap holds, bonuses, multi-team routing, and pre-existing hard caps require more inputs. Every scenario lists these assumptions.</span></div>`,
  },
  development: {
    title: "Player development",
    body: `
      <p class="guide-lead">Development is a distribution, not a predetermined potential number. The tool simulates 400 plausible career paths and reports the middle 80% of outcomes.</p>
      <ol class="guide-steps">
        <li><strong>Choose opportunity</strong><span>Planned minutes represent both repetitions and physical workload. Young players can be held back by very low opportunity; very heavy veteran workloads can accelerate decline.</span></li>
        <li><strong>Choose a focus</strong><span>A specialized focus nudges one attribute more strongly while reducing broad-based development. Balanced training adds a smaller benefit everywhere.</span></li>
        <li><strong>Set injury burden</strong><span>This is a scenario input, not a medical diagnosis. Athleticism and defense are more sensitive to recurring physical limitations.</span></li>
        <li><strong>Read the band</strong><span>P10 is a difficult path, P50 the median, and P90 an optimistic path. Wider bands mean the system knows less.</span></li>
      </ol>
      <div class="guide-section"><h3>Age provenance</h3><p>Known ages come from the stored official 2025–26 NBA season-age snapshot and are advanced one season. The simulator never invents an exact birthday. If age is unavailable, age-specific growth, decline, and retirement effects are withheld.</p></div>
      <div class="guide-note"><strong>Current boundary</strong><span>The curve is research-informed but not yet trained on the app’s own longitudinal player history. Training, validation by player archetype, and committed offseason progression come in later lifecycle phases.</span></div>`,
  },
  workload: {
    title: "Health & workload",
    body: `
      <p class="guide-lead">Health state is persistent and scenario-based. It connects roster availability to accumulated external load while keeping medical uncertainty visible.</p>
      <ol class="guide-steps">
        <li><strong>Set availability</strong><span>Available, managed, questionable, doubtful, and out are distinct states. Doubtful and out remove the player from simulations; managed restrictions cap minutes.</span></li>
        <li><strong>Record sessions</strong><span>Minutes multiplied by intensity create a transparent external-load unit. Games, practices, conditioning, and rehabilitation use the same auditable scale.</span></li>
        <li><strong>Advance time</strong><span>Acute load, chronic load, and fatigue recover at different rates whenever the league date moves. Medical status never clears automatically.</span></li>
        <li><strong>Use it in games</strong><span>Keep “Use Franchise health” selected in Matchup Lab to apply saved absences and minute caps.</span></li>
      </ol>
      <div class="guide-section"><h3>Load concern is not injury probability</h3><p>The index flags rapid workload changes, detraining, fatigue, and existing restrictions. It cannot diagnose an injury or promise that rest prevents one.</p></div>
      <div class="guide-note"><strong>Data boundary</strong><span>Only game minutes are currently observed. Training intensity, sleep, internal load, biomechanics, and medical findings require licensed or user-supplied data, so the model labels its confidence.</span></div>`,
  },
  chemistry: {
    title: "Chemistry & coaching",
    body: `
      <p class="guide-lead">This workspace represents shared execution and tactical fit—not a mystical hidden rating. New saves start at a neutral, low-confidence prior.</p>
      <div class="guide-section"><h3>Team chemistry</h3><p>Cohesion, role clarity, trust, system familiarity, and morale are separate because they change for different reasons. Team sessions create gradual, diminishing improvements.</p></div>
      <div class="guide-section"><h3>Coaching plan</h3><p>Offensive and defensive systems, pace, rotation depth, development priority, and adaptability define strategy. The current game effects are intentionally small and bounded.</p></div>
      <div class="guide-note"><strong>Accuracy boundary</strong><span>These are user scenario inputs until lineup continuity, play-type execution, coaching identities, and possession-level tactical outcomes are trained chronologically.</span></div>`,
  },
  scouting: {
    title: "Players & scouting",
    body: `
      <p class="guide-lead">Current NBA players have exact, normalized 25–99 ratings. Scouting fog of war applies only to draft prospects whose professional ability is not yet known.</p>
      <ol class="guide-steps">
        <li><strong>Read established players directly</strong><span>OVR is normalized across the active league. The best possible rating is 99, while rotation and fringe players occupy progressively lower bands.</span></li>
        <li><strong>Open the detailed view</strong><span>Inspect finishing, shooting, playmaking, defense, rebounding, physical, mental, role, and potential ratings.</span></li>
        <li><strong>Use spatial evidence</strong><span>Restricted area, paint, mid-range, both corners, and above-the-break threes each retain attempt share, efficiency, a 25–99 zone rating, and hot/cold status.</span></li>
        <li><strong>Scout future draft classes</strong><span>When prospects are generated, the automatic department assigns its hours to useful unresolved evaluations. Manual reports remain available for advanced users.</span></li>
      </ol>
      <div class="guide-section"><h3>Ratings are model outputs</h3><p>“Exact” means the game exposes one current rating rather than forcing scouting. It does not mean real basketball ability is measurable without error. Progression and regression still change that current rating over time.</p></div>
      <div class="guide-note"><strong>Data boundary</strong><span>Current ratings use official season performance plus the stored spatial profile. Traits such as strength, vertical, hands, and post skill are model-derived where licensed measurements are unavailable.</span></div>`,
  },
  draft: {
    title: "Draft ecosystem",
    body: `
      <p class="guide-lead">The class is persistent: prospects, reports, your board, the lottery, and every selection live in the franchise event ledger and replay identically from the save.</p>
      <ol class="guide-steps">
        <li><strong>Generate the class</strong><span>Creates 75 fictional prospects from a reproducible class seed. Public consensus is noisy; each player also has a hidden professional outcome the UI never reveals.</span></li>
        <li><strong>Build information</strong><span>Manual scouting narrows Bayesian skill and potential bands. The combine verifies physical measurements and adds the same standardized observation to every prospect.</span></li>
        <li><strong>Set your board</strong><span>Public rank and your private rank are separate. Move a prospect to the top whenever your evaluation differs from consensus.</span></li>
        <li><strong>Run the lottery</strong><span>The 2027 3-2-1 format draws all 16 lottery positions. Until season standings are committed, the preliminary order uses current roster strength as a transparent projection.</span></li>
        <li><strong>Draft</strong><span>Simulate CPU selections to your next owned pick, then choose any undrafted prospect. All 60 picks and original/current ownership remain visible.</span></li>
      </ol>
      <div class="guide-note"><strong>Read a range correctly</strong><span>The center is your department’s present estimate—not hidden truth. An 80% band means outcomes outside it remain possible.</span></div>`,
  },
  trades: {
    title: "Trading & asset market",
    body: `
      <p class="guide-lead">Trade Center evaluates the deal as a transaction, a cap event, and a basketball decision. Legal does not mean accepted; accepted does not mean equally valuable.</p>
      <ol class="guide-steps">
        <li><strong>Choose a partner</strong><span>Select players and owned picks from both asset columns. Modeled cap charges are visibly labeled wherever authoritative contract data is missing.</span></li>
        <li><strong>Evaluate before executing</strong><span>The league office lists every active blocker by rule, both teams’ salary positions, and the CPU partner’s timeline-aware valuation response.</span></li>
        <li><strong>Customize the universe</strong><span>Every encoded rule has its own saved switch. Disabled rules create an explicit house-rule warning instead of silently changing legality.</span></li>
        <li><strong>Run the wider market</strong><span>The league cycle lets non-user teams trade with one another. Candidate deals are seeded, CBA-checked, and accepted only when both CPU timelines value the return.</span></li>
      </ol>
      <div class="guide-section"><h3>Injured players</h3><p>NBA rules do not impose a general ban on trading an injured player. The injured-player switch is therefore an optional house rule and starts off.</p></div>
      <div class="guide-note"><strong>Stepien Rule</strong><span>A team cannot leave itself without a first-round selection in consecutive future drafts. The evaluator checks the post-trade ownership ledger, not merely the picks visible in one offer.</span></div>`,
  },
  competition: {
    title: "Competition modes",
    body: `
      <p class="guide-lead">These lighter tools answer tournament questions without committing to a full NBA calendar.</p>
      <div class="guide-section"><h3>Round robin</h3><p>Choose 2–30 teams. Repeats control how often each pairing plays; two repeats gives one game at each home court.</p></div>
      <div class="guide-section"><h3>Playoff series</h3><p>Choose the higher and lower seed plus the series length. Best-of-seven uses the familiar 2–2–1–1–1 home pattern.</p></div>`,
  },
  health: {
    title: "Model Health",
    body: `
      <p class="guide-lead">This workspace asks whether the simulator is statistically believable and whether a forecast model earns promotion.</p>
      <div class="guide-section"><h3>League-stat audit</h3><p>Compares simulated scoring, shooting, assists, turnovers, defense, and fouls with source-season league ecology.</p></div>
      <div class="guide-section"><h3>Historical backtest</h3><p>Predicts each game before learning its result, then compares log loss, Brier score, margin error, and total error against strong baselines.</p></div>
      <div class="guide-note"><strong>Promotion withheld</strong><span>This is healthy behavior. A point estimate is not enough; the candidate must clear uncertainty bounds against every required baseline.</span></div>`,
  },
  glossary: {
    title: "Plain-language glossary",
    body: `
      <dl class="guide-glossary">
        <div><dt>Seed</dt><dd>The number that makes a random simulation exactly replayable.</dd></div>
        <div><dt>Monte Carlo</dt><dd>Many independent simulated games used to estimate a distribution.</dd></div>
        <div><dt>Hybrid</dt><dd>Complete simulated games reweighted toward a calibrated macro forecast.</dd></div>
        <div><dt>Calibration</dt><dd>Whether stated probabilities happen at the frequencies they promise.</dd></div>
        <div><dt>Schedule delta</dt><dd>The forecast change attributed to validated rest and travel context.</dd></div>
        <div><dt>Apron salary</dt><dd>The CBA-specific payroll calculation used for transaction restrictions.</dd></div>
        <div><dt>Hard cap</dt><dd>A line the team may not exceed for the rest of that cap year after a triggering action.</dd></div>
        <div><dt>Branch</dt><dd>An independent copy of a Franchise timeline at an exact revision.</dd></div>
        <div><dt>Lifecycle band</dt><dd>The middle range of simulated career outcomes, preserving uncertainty instead of showing one false-precision rating.</dd></div>
      </dl>`,
  },
};

function renderGuideTopic(topic) {
  const selected = GUIDE_TOPICS[topic] ? topic : "start";
  const content = GUIDE_TOPICS[selected];
  $("#guide-title").textContent = content.title;
  $("#guide-content").innerHTML = content.body;
  $$("[data-guide-nav]").forEach((button) =>
    button.classList.toggle("active", button.dataset.guideNav === selected),
  );
}

function openGuide(topic = "start") {
  const overlay = $("#guide-overlay");
  renderGuideTopic(topic);
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("guide-open");
  $("#guide-close").focus();
}

function closeGuide() {
  const overlay = $("#guide-overlay");
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("guide-open");
}

function initializeGuide() {
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-guide-topic]");
    if (trigger) openGuide(trigger.dataset.guideTopic);
  });
  $$("[data-guide-nav]").forEach((button) =>
    button.addEventListener("click", () => renderGuideTopic(button.dataset.guideNav)),
  );
  $("#guide-close").addEventListener("click", closeGuide);
  $(".guide-scrim").addEventListener("click", closeGuide);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#guide-overlay").classList.contains("hidden")) {
      closeGuide();
    }
  });
}

function team(abbreviation) {
  return state.metadata.teams.find((item) => item.abbreviation === abbreviation);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3400);
}

function setBusy(form, busy, label = "Running simulation…") {
  const button = $('button[type="submit"]', form);
  if (!button) return;
  button.disabled = busy;
  if (busy) {
    button.dataset.label = $("span", button).textContent;
    $("span", button).textContent = label;
  } else if (button.dataset.label) {
    $("span", button).textContent = button.dataset.label;
  }
}

function loading(target, copy) {
  target.innerHTML = `<div class="loading-block">${escapeHtml(copy)}</div>`;
}

function initializeNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
      $$(".view").forEach((view) => {
        view.classList.toggle("active", view.id === `view-${button.dataset.view}`);
      });
    });
  });
}

function optionList(selected) {
  return state.metadata.teams
    .map(
      (item) =>
        `<option value="${item.abbreviation}" ${item.abbreviation === selected ? "selected" : ""}>${item.abbreviation}</option>`,
    )
    .join("");
}

function initializeMetadata() {
  const defaults = state.metadata.defaults;
  $("#data-season").textContent = `${state.metadata.data_season} snapshot · local`;
  $("#home-team").innerHTML = optionList(defaults.home);
  $("#away-team").innerHTML = optionList(defaults.away);
  $("#higher-seed").innerHTML = optionList("DEN");
  $("#lower-seed").innerHTML = optionList("MIN");
  $("#franchise-team").innerHTML = optionList("UTA");
  $("#matchup-trials").value = defaults.trials;
  const inventory = state.metadata.snapshot_inventory || [];
  const gameSeasons = inventory.filter((item) => item.dataset === "game-logs");
  const rosterSnapshots = inventory
    .filter((item) => item.dataset === "rosters")
    .sort((a, b) => a.season.localeCompare(b.season));
  const currentRoster = rosterSnapshots.at(-1);
  const coverage = state.metadata.profile_coverage;
  const gameRows = gameSeasons.reduce((sum, item) => sum + Number(item.recorded_rows || 0), 0);
  $("#data-inventory").textContent =
    gameSeasons.length > 0
      ? `${gameSeasons.length} official seasons · ${gameRows.toLocaleString()} team-game source rows${currentRoster ? ` · ${currentRoster.season} roster` : ""}${coverage ? ` · ${coverage.official}/${coverage.total} official player profiles` : ""}`
      : "No historical warehouse snapshots yet.";

  const initialSeasonTeams = new Set(["UTA", "MEM", "DEN", "MIN"]);
  $("#season-team-grid").innerHTML = state.metadata.teams
    .map(
      (item) => `
        <label class="team-chip" title="${escapeHtml(item.name)}">
          <input type="checkbox" value="${item.abbreviation}" ${initialSeasonTeams.has(item.abbreviation) ? "checked" : ""} />
          <span>${item.abbreviation}</span>
        </label>`,
    )
    .join("");
  renderRosters();
  renderGameDay(state.metadata.game_day);
  loadFranchiseIndex();
}

function formatGameDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short",
  }).format(new Date(`${value}T12:00:00`));
}

function formatTip(game) {
  if (!game.scheduled_at) return game.status_text || "TBD";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(game.scheduled_at));
}

function renderGameDay(data) {
  if (!data) return;
  const counts = data.counts;
  const releaseCopy = {
    complete: "The official regular-season slate is fully populated.",
    partial: "The official regular-season slate is only partially populated.",
    preseason_only: "Preseason is published. The full regular-season slate is not in the official feed yet.",
    announced_events_only: "Only announced event placeholders are in the official feed.",
    not_available: "No 2026–27 schedule snapshot is stored yet. Refresh the official feed to check.",
  };
  const snapshot = data.latest_snapshot;
  const contextGate = data.context_validation;
  $("#slate-summary").innerHTML = `
    <div class="slate-state ${data.full_regular_season_available ? "complete" : "partial"}">
      <div>
        <p class="eyebrow">Feed state · ${escapeHtml(data.release_state.replaceAll("_", " "))}</p>
        <strong>${escapeHtml(releaseCopy[data.release_state] || "Official feed status unavailable.")}</strong>
        <span>${snapshot ? `Snapshot ${new Date(snapshot.available_at).toLocaleString()}` : "No local snapshot"}</span>
        ${contextGate ? `<span class="context-gate-copy ${contextGate.promoted ? "passed" : "withheld"}">${contextGate.promoted ? "Context gate passed" : "Context effects withheld"} · 2025–26 holdout ${number(contextGate.context_margin_mae, 3)} MAE vs ${number(contextGate.baseline_margin_mae, 3)} venue baseline</span>` : ""}
      </div>
      <div class="slate-counts">
        <div><strong>${counts.published}</strong><span>Published</span></div>
        <div><strong>${counts.identified}</strong><span>Matchups</span></div>
        <div><strong>${counts.regular_season}</strong><span>Regular</span></div>
        <div><strong>${counts.injury_rows}</strong><span>Injury rows</span></div>
      </div>
    </div>`;

  if (!data.games.length) {
    $("#schedule-feed").innerHTML = `
      <div class="schedule-empty">
        <strong>No published games in the local snapshot.</strong>
        <span>Use “Refresh official feed” to check the NBA source.</span>
      </div>`;
    return;
  }

  $("#schedule-feed").innerHTML = data.games
    .map((game) => {
      const availability = game.availability || [];
      const reportCopy = availability.length
        ? `${availability.length} official availability ${availability.length === 1 ? "row" : "rows"} matched`
        : "Official injury report not published yet";
      const matchup = game.teams_identified
        ? `<div class="schedule-matchup">
            <span>${escapeHtml(game.away_team)}</span><em>@</em><span>${escapeHtml(game.home_team)}</span>
          </div>`
        : `<div class="schedule-matchup placeholder"><span>Teams</span><em>—</em><span>TBD</span></div>`;
      const statusChips = availability
        .slice(0, 3)
        .map(
          (row) =>
            `<span class="availability-chip status-${row.status.toLowerCase()}">${escapeHtml(row.player_name)} · ${escapeHtml(row.status)}</span>`,
        )
        .join("");
      const context = game.schedule_context;
      const contextCopy = context
        ? `${game.away_team} ${context.away.rest_days}d rest · ${Math.round(context.away.travel_miles).toLocaleString()} mi · ${game.home_team} ${context.home.rest_days}d rest`
        : "Schedule load unavailable";
      return `
        <article class="schedule-card" data-game-id="${escapeHtml(game.game_id)}">
          <div class="schedule-date">
            <strong>${escapeHtml(formatGameDate(game.game_date))}</strong>
            <span>${escapeHtml(game.game_label || "NBA")} ${game.game_sub_label ? `· ${escapeHtml(game.game_sub_label)}` : ""}</span>
          </div>
          <div class="schedule-main">
            ${matchup}
            <strong class="schedule-tip">${escapeHtml(formatTip(game))}</strong>
            <span class="schedule-venue">${escapeHtml(game.arena_name || "Venue TBD")}${game.neutral_site ? " · neutral site" : ""}</span>
          </div>
          <div class="schedule-availability">
            <span>${escapeHtml(reportCopy)}</span>
            <div class="availability-chips">${statusChips}</div>
            <span class="schedule-context-copy">${escapeHtml(contextCopy)}</span>
          </div>
          <div class="schedule-actions">
            <button class="forecast-game" type="button" ${game.teams_identified ? "" : "disabled"}>Forecast 1,000×</button>
            <button class="load-game" type="button" ${game.teams_identified ? "" : "disabled"}>Adjust rotation</button>
          </div>
        </article>`;
    })
    .join("");

  $$(".forecast-game", $("#schedule-feed")).forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".schedule-card");
      const gameId = card.dataset.gameId;
      button.disabled = true;
      const original = button.textContent;
      button.textContent = "Forecasting…";
      loading($("#game-day-result"), "Sampling availability and game outcomes…");
      try {
        state.gameDayResult = await api("/api/game-day", {
          game_id: gameId,
          trials: 1000,
        });
        renderGameDayForecast(state.gameDayResult);
      } catch (error) {
        renderError($("#game-day-result"), error.message);
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
  });

  $$(".load-game", $("#schedule-feed")).forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".schedule-card");
      const game = data.games.find((item) => item.game_id === card.dataset.gameId);
      loadScheduledMatchup(game);
    });
  });
}

function loadScheduledMatchup(game) {
  if (!game?.teams_identified) return;
  $("#away-team").value = game.away_team;
  $("#home-team").value = game.home_team;
  renderRosters();
  (game.availability || [])
    .filter((row) => row.automatically_inactive && row.player_id)
    .forEach((row) => {
      const side = row.team === game.home_team ? "home" : "away";
      const playerRow = $(`.player-row[data-player-id="${row.player_id}"]`, $(`#${side}-roster`));
      if (!playerRow) return;
      const toggle = $(".out-toggle", playerRow);
      toggle.checked = true;
      toggle.dispatchEvent(new Event("change"));
    });
  $('.nav-item[data-view="matchup"]').click();
  showToast(`Loaded ${game.away_team} at ${game.home_team}. Official Out statuses applied.`);
}

function renderGameDayForecast(result) {
  const target = $("#game-day-result");
  const game = result.scheduled_game;
  const homeWin = result.home_win_probability;
  const assumptions = result.availability.length
    ? result.availability
        .map(
          (row) => `
            <div class="availability-row">
              <div>
                <strong>${escapeHtml(row.player_name)}</strong>
                <span>${escapeHtml(row.team)} · ${escapeHtml(row.reason || "No reason listed")}</span>
              </div>
              <span class="availability-status status-${row.status.toLowerCase()}">${escapeHtml(row.status)}</span>
              <strong>${pct(row.availability_probability, 0)} active</strong>
            </div>`,
        )
        .join("")
    : `<div class="availability-none">No official injury report was available at forecast time, so the current roster was treated as active.</div>`;
  const context = result.schedule_context;
  const adjustment = result.context_adjustment;
  const base = result.base_distribution;
  target.innerHTML = `
    <div class="result-header">
      <div class="result-mode">
        <span>${escapeHtml(game.game_label || "NBA")} · ${escapeHtml(formatGameDate(game.game_date))}</span>
        <span>Seed ${result.seed}</span>
      </div>
      <div class="probability-wrap">
        <div class="probability-row">
          <span>${result.away_team} ${pct(1 - homeWin)}</span>
          <strong>${pct(homeWin)}</strong>
          <span>${result.home_team} win</span>
        </div>
        <div class="probability-track"><div class="probability-fill" style="width:${homeWin * 100}%"></div></div>
      </div>
    </div>
    <div class="result-stat-grid">
      <div class="result-stat"><span>Mean margin</span><strong>${Number(result.mean_margin) >= 0 ? "+" : ""}${number(result.mean_margin, 1)}</strong></div>
      <div class="result-stat"><span>Mean total</span><strong>${number(result.mean_total, 1)}</strong></div>
      <div class="result-stat"><span>Availability scenarios</span><strong>${result.distinct_availability_scenarios}</strong></div>
    </div>
    <div class="game-day-result-body">
      <div class="model-provenance">
        <div><span>Dynamic base</span><strong>${base.mean_margin >= 0 ? "+" : ""}${number(base.mean_margin, 1)} margin</strong></div>
        <div><span>Roster delta</span><strong>${result.mean_roster_margin_delta >= 0 ? "+" : ""}${number(result.mean_roster_margin_delta, 1)}</strong></div>
        <div>
          <span>Schedule delta · applied</span>
          <strong>${adjustment.margin_points >= 0 ? "+" : ""}${number(adjustment.margin_points, 1)}</strong>
          <small>${adjustment.learned_increment_applied ? "Holdout gate passed" : `${adjustment.learned_increment >= 0 ? "+" : ""}${number(adjustment.learned_increment, 1)} estimated · withheld`}</small>
        </div>
      </div>
      <div class="schedule-context-detail">
        <div>
          <span>${result.away_team} load</span>
          <strong>${context.away.rest_days}d rest · ${Math.round(context.away.travel_miles).toLocaleString()} mi travel${context.away.back_to_back ? " · B2B" : ""}</strong>
        </div>
        <div>
          <span>${result.home_team} load</span>
          <strong>${context.home.rest_days}d rest · ${Math.round(context.home.travel_miles).toLocaleString()} mi travel${context.home.back_to_back ? " · B2B" : ""}</strong>
        </div>
        <p>${adjustment.learned_increment_applied ? "The chronological schedule-context gate passed and its learned increment is active." : "The learned rest/travel increment did not clear the holdout gate, so it is shown but cannot move this forecast."}</p>
      </div>
      <div class="availability-heading">
        <div><p class="eyebrow">Point-in-time availability</p><h2>${result.availability.length ? "Official report matched" : "Report pending"}</h2></div>
        <span>${result.trials} trials</span>
      </div>
      <div class="availability-list">${assumptions}</div>
      <p class="fine-print">${escapeHtml(result.forecast_method)} ${escapeHtml(result.availability_method)}</p>
      ${distributionBody(result)}
    </div>`;
}

function initializeGameDay() {
  $("#refresh-schedule").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Refreshing…";
    try {
      const result = await api("/api/sync-schedule", { season: "2026-27" });
      state.metadata.game_day = result.game_day;
      renderGameDay(result.game_day);
      showToast(`Official feed refreshed · ${result.sync.records} entries stored.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });
}

function initializeLeague() {
  $("#run-league").addEventListener("click", async () => {
    setLeagueRunning(true);
    $("#league-progress").classList.remove("hidden");
    try {
      const job = await api("/api/league-season/start", {
        start_date: "2026-10-20",
        end_date: "2027-04-12",
      });
      state.leagueJobId = job.job_id;
      localStorage.setItem(LEAGUE_JOB_STORAGE_KEY, job.job_id);
      renderLeagueProgress(job);
      scheduleLeaguePoll(250);
    } catch (error) {
      showToast(error.message);
      setLeagueRunning(false);
    }
  });

  $("#cancel-league").addEventListener("click", async (event) => {
    if (!state.leagueJobId) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Stopping after this game…";
    try {
      const job = await api("/api/league-season/cancel", {
        job_id: state.leagueJobId,
      });
      renderLeagueProgress(job);
      scheduleLeaguePoll(250);
    } catch (error) {
      showToast(error.message);
      button.disabled = false;
      button.textContent = "Stop simulation";
    }
  });

  $$(".league-section-tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".league-section-tab").forEach((item) =>
        item.classList.toggle("active", item === button),
      );
      $$(".league-panel").forEach((panel) =>
        panel.classList.toggle(
          "active",
          panel.id === `league-panel-${button.dataset.leagueTab}`,
        ),
      );
    });
  });

  $("#league-team-filter").addEventListener("change", () => {
    state.leagueVisibleGames = 60;
    renderLeagueGames();
  });
  $("#league-month-filter").addEventListener("change", () => {
    state.leagueVisibleGames = 60;
    renderLeagueGames();
  });
  $("#league-more").addEventListener("click", () => {
    state.leagueVisibleGames += 60;
    renderLeagueGames();
  });
}

function setLeagueRunning(running) {
  const button = $("#run-league");
  button.disabled = running;
  $("#league-launch-title").textContent = running
    ? "Season in motion"
    : state.leagueResult
      ? "Ready for another season"
      : "Ready to tip off";
  $("span", button).textContent = running
    ? "Detailed season in progress"
    : state.leagueResult
      ? "Simulate another season"
      : "Simulate full season";
}

function renderLeagueProgress(job) {
  const panel = $("#league-progress");
  const terminal = ["completed", "cancelled", "failed"].includes(job.status);
  panel.classList.remove("hidden", "complete", "stopped", "failed");
  if (job.status === "completed") panel.classList.add("complete");
  if (job.status === "cancelled") panel.classList.add("stopped");
  if (job.status === "failed") panel.classList.add("failed");

  const percent = Number(job.percent || 0);
  $("#league-progress-fill").style.width = `${Math.min(100, percent)}%`;
  $("#league-progress-fill").style.minWidth = percent > 0 ? "3px" : "0";
  $("#league-progress-percent").textContent = `${percent.toFixed(2)}%`;
  $("#league-progress-track").setAttribute("aria-valuenow", percent.toFixed(2));
  $("#league-progress-count").textContent =
    `${Number(job.completed_games).toLocaleString()} / ${Number(job.total_games).toLocaleString()} games`;
  $("#league-progress-trial").textContent =
    job.status === "running" && job.current_game
      ? "Playing one complete possession-level game"
      : "One detailed game per matchup";
  $("#league-progress-elapsed").textContent =
    `Elapsed ${duration(job.elapsed_seconds)}`;
  $("#league-progress-eta").textContent =
    job.eta_seconds === null || job.eta_seconds === undefined
      ? terminal
        ? "Finished"
        : "Calibrating ETA…"
      : `About ${duration(job.eta_seconds)} remaining`;
  $("#league-progress-seed").textContent = `Seed ${job.seed}`;

  const statusCopy = {
    preparing: "Preparing detailed season",
    running: "Possession engine running",
    cancelling: "Finishing the current game",
    completed: "Detailed regular season complete",
    cancelled: "Simulation stopped",
    failed: "Simulation interrupted",
  };
  $("#league-progress-kicker").textContent =
    statusCopy[job.status] || "League simulation";
  if (job.current_game) {
    const gameDate = new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(`${job.current_game.date}T12:00:00`));
    $("#league-progress-matchup").textContent =
      `${job.current_game.away_team} at ${job.current_game.home_team} · ${gameDate}`;
  } else {
    $("#league-progress-matchup").textContent =
      job.status === "preparing"
        ? "Loading rosters and calibrated ratings…"
        : "No matchup in progress";
  }

  const cancel = $("#cancel-league");
  cancel.classList.toggle("hidden", terminal);
  cancel.disabled = job.status === "cancelling";
  cancel.textContent =
    job.status === "cancelling" ? "Stopping after this game…" : "Stop simulation";
}

function scheduleLeaguePoll(delay = 900) {
  window.clearTimeout(state.leaguePollTimer);
  state.leaguePollTimer = window.setTimeout(pollLeagueSimulation, delay);
}

async function pollLeagueSimulation() {
  if (!state.leagueJobId) return;
  try {
    const job = await api("/api/league-season/progress", {
      job_id: state.leagueJobId,
    });
    renderLeagueProgress(job);
    if (job.status === "completed" && job.result) {
      state.leagueResult = job.result;
      state.leagueVisibleGames = 60;
      state.leagueJobId = null;
      localStorage.removeItem(LEAGUE_JOB_STORAGE_KEY);
      renderLeagueSeason(state.leagueResult);
      $("#league-results").classList.remove("hidden");
      setLeagueRunning(false);
      showToast(`Detailed season complete · seed ${state.leagueResult.seed}`);
      return;
    }
    if (job.status === "cancelled" || job.status === "failed") {
      state.leagueJobId = null;
      localStorage.removeItem(LEAGUE_JOB_STORAGE_KEY);
      setLeagueRunning(false);
      showToast(
        job.status === "failed"
          ? job.error || "League simulation failed."
          : "League simulation stopped.",
      );
      return;
    }
    scheduleLeaguePoll();
  } catch (error) {
    state.leagueJobId = null;
    localStorage.removeItem(LEAGUE_JOB_STORAGE_KEY);
    setLeagueRunning(false);
    $("#league-progress").classList.add("hidden");
    showToast(error.message);
  }
}

function resumeLeagueSimulation() {
  const jobId = localStorage.getItem(LEAGUE_JOB_STORAGE_KEY);
  if (!jobId) return;
  state.leagueJobId = jobId;
  setLeagueRunning(true);
  $("#league-progress").classList.remove("hidden");
  scheduleLeaguePoll(0);
}

function initializeFranchise() {
  $$(".franchise-workspace-tab").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.franchiseTab;
      $$(".franchise-workspace-tab").forEach((item) =>
        item.classList.toggle("active", item === button),
      );
      $$(".franchise-overview-section").forEach((section) =>
        section.classList.toggle("hidden", target !== "overview"),
      );
      $("#franchise-cap-workspace").classList.toggle("hidden", target !== "cap");
      $("#franchise-trade-workspace").classList.toggle(
        "hidden",
        target !== "trades",
      );
      $("#franchise-development-workspace").classList.toggle(
        "hidden",
        target !== "development",
      );
      $("#franchise-health-workspace").classList.toggle(
        "hidden",
        target !== "health",
      );
      $("#franchise-chemistry-workspace").classList.toggle(
        "hidden",
        target !== "chemistry",
      );
      $("#franchise-scouting-workspace").classList.toggle(
        "hidden",
        target !== "scouting",
      );
      $("#franchise-draft-workspace").classList.toggle(
        "hidden",
        target !== "draft",
      );
      if (target === "scouting" && state.franchise?.scouting?.ready) {
        loadScoutingBoard();
      }
      if (target === "trades" && state.franchise?.trade_center?.ready) {
        loadTradeBoard();
      }
    });
  });

  $("#scouting-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.firstElementChild.textContent = "Initializing…";
    try {
      state.franchise = await api("/api/franchise/initialize-scouting", {
        save_id: state.franchise.save.save_id,
      });
      state.scoutingBoardSaveId = null;
      renderFranchise(state.franchise);
      await loadScoutingBoard();
      showToast("Scouting beliefs added to this timeline.");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.firstElementChild.textContent = "Prepare draft scouting";
    }
  });

  $("#scouting-run-cycle").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.firstElementChild.textContent = "Scouting league…";
    try {
      state.franchise = await api("/api/franchise/run-scouting-cycle", {
        save_id: state.franchise.save.save_id,
      });
      state.scoutingBoardSaveId = null;
      renderFranchise(state.franchise);
      await loadScoutingBoard();
      showToast(`${state.franchise.scouting_cycle_targets || 0} reports updated.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.firstElementChild.textContent = "Run weekly cycle";
    }
  });

  $("#scouting-department-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const form = event.currentTarget;
    setBusy(form, true, "Saving department…");
    try {
      state.franchise = await api(
        "/api/franchise/update-scouting-department",
        {
          save_id: state.franchise.save.save_id,
          automation_enabled: $("#scouting-automation").checked,
          weekly_hours: Number($("#scouting-hours").value),
          priority: $("#scouting-priority").value,
          risk_tolerance: $("#scouting-risk").value,
        },
      );
      renderFranchise(state.franchise);
      showToast("Scouting department settings saved.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  ["#scouting-search", "#scouting-team-filter", "#scouting-confidence-filter"]
    .forEach((selector) => {
      $(selector).addEventListener(
        selector === "#scouting-search" ? "input" : "change",
        renderScoutingBoard,
      );
    });

  $("#draft-initialize").addEventListener("click", async (event) => {
    await runDraftAction(
      "/api/franchise/initialize-draft",
      {},
      event.currentTarget,
      "Generating class…",
      "The 2027 draft class is now part of this timeline.",
    );
  });

  $("#draft-combine").addEventListener("click", async (event) => {
    await runDraftAction(
      "/api/franchise/run-draft-combine",
      {},
      event.currentTarget,
      "Running combine…",
      "Combine measurements verified and reports updated.",
    );
  });

  $("#draft-lottery").addEventListener("click", async (event) => {
    await runDraftAction(
      "/api/franchise/run-draft-lottery",
      {},
      event.currentTarget,
      "Drawing 16 teams…",
      "The complete 2027 lottery order is locked.",
    );
  });

  $("#draft-sim-to-pick").addEventListener("click", async (event) => {
    await runDraftAction(
      "/api/franchise/simulate-to-draft-pick",
      {},
      event.currentTarget,
      "Simulating picks…",
      "CPU selections complete. Your draft room is updated.",
    );
  });

  $("#draft-make-pick").addEventListener("click", async (event) => {
    if (!state.draftProspectId) {
      showToast("Choose an available prospect first.");
      return;
    }
    await runDraftAction(
      "/api/franchise/make-draft-pick",
      { player_id: state.draftProspectId },
      event.currentTarget,
      "Submitting pick…",
      "The selection is official and saved to the ledger.",
    );
  });

  $("#draft-search").addEventListener("input", () =>
    renderFranchiseDraft(state.franchise),
  );

  $("#trade-initialize").addEventListener("click", async (event) => {
    await runTradeAction(
      "/api/franchise/initialize-trades",
      {},
      event.currentTarget,
      "Initializing market…",
      "Trade rules and future pick ownership added to this branch.",
    );
    await loadTradeBoard(true);
  });

  $("#trade-partner").addEventListener("change", () => {
    clearTradeProposal();
    renderTradeBuilder();
  });

  $("#trade-clear").addEventListener("click", () => {
    clearTradeProposal();
    renderTradeBuilder();
  });

  $("#trade-evaluate").addEventListener("click", async (event) => {
    if (!state.franchise || !tradeProposalHasAssets()) {
      showToast("Select at least one player or pick.");
      return;
    }
    const button = event.currentTarget;
    const label = button.querySelector("span") || button;
    const original = label.textContent;
    button.disabled = true;
    label.textContent = "Evaluating…";
    try {
      const result = await api("/api/franchise/evaluate-trade", {
        save_id: state.franchise.save.save_id,
        packages: selectedTradePackages(),
      });
      state.tradeEvaluation = result.evaluation;
      renderTradeEvaluation();
    } catch (error) {
      showToast(error.message);
    } finally {
      label.textContent = original;
      button.disabled = false;
    }
  });

  $("#trade-rules-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const payload = {};
    $$("[data-trade-rule]").forEach((input) => {
      payload[input.dataset.tradeRule] = input.checked;
    });
    payload.ai_aggressiveness = Number($("#trade-ai-aggression").value);
    const form = event.currentTarget;
    setBusy(form, true, "Saving rules…");
    try {
      state.franchise = await api("/api/franchise/update-trade-rules", {
        save_id: state.franchise.save.save_id,
        ...payload,
      });
      state.tradeEvaluation = null;
      renderFranchise(state.franchise);
      showToast("Trade rule policy saved to this branch.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#trade-ai-aggression").addEventListener("input", (event) => {
    $("output", event.currentTarget.parentElement).textContent =
      pct(Number(event.currentTarget.value), 0);
  });

  $("#trade-run-market").addEventListener("click", async (event) => {
    const result = await runTradeAction(
      "/api/franchise/run-ai-trade-market",
      { max_deals: Number($("#trade-ai-max").value) },
      event.currentTarget,
      "Running league calls…",
      null,
    );
    if (!result) return;
    state.tradeBoard = null;
    state.tradeBoardSaveId = null;
    clearTradeProposal();
    await loadTradeBoard(true);
    showToast(
      result.ai_trades_made
        ? `${result.ai_trades_made} CPU-to-CPU trade${result.ai_trades_made === 1 ? "" : "s"} completed.`
        : "No mutually acceptable CPU trades emerged in this cycle.",
    );
  });

  $("#health-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.firstElementChild.textContent = "Initializing…";
    try {
      state.franchise = await api("/api/franchise/initialize-health", {
        save_id: state.franchise.save.save_id,
      });
      renderFranchise(state.franchise);
      showToast("Player health state added to this timeline.");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.firstElementChild.textContent = "Initialize health";
    }
  });

  $("#environment-initialize").addEventListener("click", async () => {
    if (!state.franchise) return;
    state.franchise = await api("/api/franchise/initialize-environment", {
      save_id: state.franchise.save.save_id,
    });
    renderFranchise(state.franchise);
    showToast("Team environment initialized.");
  });

  $("#chemistry-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Saving chemistry…");
    try {
      state.franchise = await api("/api/franchise/update-chemistry", {
        save_id: state.franchise.save.save_id,
        cohesion: Number($("#chemistry-cohesion").value),
        role_clarity: Number($("#chemistry-roles").value),
        trust: Number($("#chemistry-trust").value),
        system_familiarity: Number($("#chemistry-system").value),
        morale: Number($("#chemistry-morale").value),
      });
      renderFranchise(state.franchise);
      showToast("Team assessment saved.");
    } finally {
      setBusy(form, false);
    }
  });

  $("#coaching-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Saving plan…");
    try {
      state.franchise = await api("/api/franchise/update-coaching", {
        save_id: state.franchise.save.save_id,
        coach_name: $("#coach-name").value,
        offensive_system: $("#coach-offense").value,
        defensive_system: $("#coach-defense").value,
        pace_emphasis: Number($("#coach-pace").value),
        rotation_depth: Number($("#coach-depth").value),
        development_priority: $("#coach-development").value,
        adaptability: Number($("#coach-adaptability").value),
      });
      renderFranchise(state.franchise);
      showToast("Coaching plan saved.");
    } finally {
      setBusy(form, false);
    }
  });

  $("#chemistry-session-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Running session…");
    try {
      state.franchise = await api("/api/franchise/record-chemistry-session", {
        save_id: state.franchise.save.save_id,
        emphasis: $("#chemistry-session-emphasis").value,
        intensity: Number($("#chemistry-session-intensity").value),
      });
      renderFranchise(state.franchise);
      showToast("Shared team session recorded.");
    } finally {
      setBusy(form, false);
    }
  });

  $$(".chemistry-slider-grid input").forEach((input) => {
    input.addEventListener("input", () => {
      $("output", input.parentElement).textContent = input.value;
    });
  });

  $("#health-status-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise || !state.healthPlayerId) return;
    const form = event.currentTarget;
    setBusy(form, true, "Saving status…");
    try {
      state.franchise = await api("/api/franchise/update-health", {
        save_id: state.franchise.save.save_id,
        player_id: state.healthPlayerId,
        availability: $("#health-status").value,
        body_area: $("#health-body-area").value,
        minute_limit: $("#health-minute-limit").value,
        expected_return: $("#health-return-date").value,
        detail: $("#health-detail").value,
      });
      renderFranchise(state.franchise);
      showToast("Availability saved and linked to Matchup Lab.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#health-workload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise || !state.healthPlayerId) return;
    const form = event.currentTarget;
    setBusy(form, true, "Recording load…");
    try {
      state.franchise = await api("/api/franchise/record-workload", {
        save_id: state.franchise.save.save_id,
        player_id: state.healthPlayerId,
        kind: $("#health-session-kind").value,
        minutes: Number($("#health-session-minutes").value),
        intensity: Number($("#health-session-intensity").value),
      });
      renderFranchise(state.franchise);
      showToast("Workload recorded. Recovery will follow league time.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#lifecycle-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.firstElementChild.textContent = "Initializing…";
    try {
      state.franchise = await api("/api/franchise/initialize-lifecycle", {
        save_id: state.franchise.save.save_id,
      });
      renderFranchise(state.franchise);
      await refreshFranchiseSaveList(state.franchise.save.save_id);
      showToast("Player lifecycle state added to this timeline.");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.firstElementChild.textContent = "Initialize players";
    }
  });

  $("#lifecycle-player").addEventListener("change", (event) => {
    state.lifecyclePlayerId = Number(event.currentTarget.value);
    state.lifecycleProjection = null;
    renderFranchiseLifecycle(state.franchise);
  });

  $("#lifecycle-projection-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const form = event.currentTarget;
    setBusy(form, true, "Projecting 400 paths…");
    loading($("#lifecycle-result"), "Simulating uncertain career paths…");
    try {
      state.lifecyclePlayerId = Number($("#lifecycle-player").value);
      state.lifecycleProjection = await api(
        "/api/franchise/project-lifecycle",
        {
          save_id: state.franchise.save.save_id,
          player_id: state.lifecyclePlayerId,
          focus: $("#lifecycle-focus").value,
          planned_minutes: Number($("#lifecycle-minutes").value),
          injury_burden: Number($("#lifecycle-injury").value),
          seasons: Number($("#lifecycle-seasons").value),
          paths: 400,
        },
      );
      renderLifecycleProjection(state.lifecycleProjection);
    } catch (error) {
      renderError($("#lifecycle-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#cap-scenario-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Checking rules…");
    try {
      const toDollars = (selector) =>
        Math.round(Number($(selector).value) * 1_000_000);
      const result = await api("/api/franchise/cap-scenario", {
        team_salary: toDollars("#cap-team-salary"),
        outgoing_salary: toDollars("#cap-outgoing-salary"),
        incoming_salary: toDollars("#cap-incoming-salary"),
        action: $("#cap-action").value,
      });
      renderCapScenario(result.evaluation);
    } catch (error) {
      renderError($("#cap-scenario-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#franchise-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Creating league…");
    try {
      const result = await api("/api/franchise/create", {
        name: $("#franchise-name").value,
        user_team: $("#franchise-team").value,
      });
      state.franchise = result;
      await loadFranchiseIndex(result.save.save_id);
      showToast(`${result.summary.league_name} created and saved.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#franchise-save-select").addEventListener("change", async (event) => {
    await loadFranchise(event.currentTarget.value);
  });

  $("#new-franchise").addEventListener("click", () => {
    $("#franchise-workspace").classList.add("hidden");
    $("#franchise-onboarding").classList.remove("hidden");
    $("#franchise-name").focus();
  });

  $("#franchise-branch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const button = $('button[type="submit"]', event.currentTarget);
    const branchName = $("#franchise-branch-name").value.trim();
    if (!branchName) {
      showToast("Name the branch first.");
      return;
    }
    button.disabled = true;
    button.textContent = "Creating…";
    try {
      const result = await api("/api/franchise/branch", {
        save_id: state.franchise.save.save_id,
        branch_name: branchName,
      });
      $("#franchise-branch-name").value = "";
      await loadFranchiseIndex(result.save.save_id);
      showToast(`Branch “${result.save.branch_name}” created.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Create branch";
    }
  });

  $$("[data-franchise-days]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.franchise) return;
      const controls = $$("[data-franchise-days]");
      controls.forEach((control) => {
        control.disabled = true;
      });
      $("#franchise-autosave-state").textContent = "Saving…";
      try {
        state.franchise = await api("/api/franchise/advance-date", {
          save_id: state.franchise.save.save_id,
          days: Number(button.dataset.franchiseDays),
        });
        renderFranchise(state.franchise);
        await refreshFranchiseSaveList(state.franchise.save.save_id);
        showToast(`Advanced to ${formatFranchiseDate(state.franchise.summary.current_date)}.`);
      } catch (error) {
        showToast(error.message);
      } finally {
        controls.forEach((control) => {
          control.disabled = false;
        });
        $("#franchise-autosave-state").textContent = "Autosaved";
      }
    });
  });
}

async function loadFranchiseIndex(preferredSaveId = null) {
  try {
    const result = await api("/api/franchise/saves", {});
    state.franchiseSaves = result.saves;
    if (!result.saves.length) {
      state.franchise = null;
      $("#franchise-workspace").classList.add("hidden");
      $("#franchise-onboarding").classList.remove("hidden");
      return;
    }
    const saveId =
      preferredSaveId && result.saves.some((save) => save.save_id === preferredSaveId)
        ? preferredSaveId
        : result.saves[0].save_id;
    renderFranchiseSaveOptions(saveId);
    await loadFranchise(saveId);
  } catch (error) {
    showToast(error.message);
  }
}

async function refreshFranchiseSaveList(activeSaveId) {
  const result = await api("/api/franchise/saves", {});
  state.franchiseSaves = result.saves;
  renderFranchiseSaveOptions(activeSaveId);
}

function renderFranchiseSaveOptions(activeSaveId) {
  $("#franchise-save-select").innerHTML = state.franchiseSaves
    .map(
      (save) =>
        `<option value="${save.save_id}" ${save.save_id === activeSaveId ? "selected" : ""}>${escapeHtml(save.name)} · ${escapeHtml(save.branch_name)} · ${save.user_team}</option>`,
    )
    .join("");
}

async function loadFranchise(saveId) {
  try {
    state.franchise = await api("/api/franchise/load", { save_id: saveId });
    renderFranchise(state.franchise);
    renderFranchiseSaveOptions(saveId);
  } catch (error) {
    showToast(error.message);
  }
}

function formatFranchiseDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

async function runDraftAction(path, payload, button, loadingLabel, successLabel) {
  if (!state.franchise) return;
  const label = button.querySelector("span") || button;
  const originalLabel = label.textContent;
  button.disabled = true;
  label.textContent = loadingLabel;
  try {
    state.franchise = await api(path, {
      save_id: state.franchise.save.save_id,
      ...payload,
    });
    renderFranchise(state.franchise);
    await refreshFranchiseSaveList(state.franchise.save.save_id);
    showToast(successLabel);
  } catch (error) {
    showToast(error.message);
  } finally {
    label.textContent = originalLabel;
    if (state.franchise) renderFranchise(state.franchise);
  }
}

async function runTradeAction(path, payload, button, loadingLabel, successLabel) {
  if (!state.franchise) return null;
  const label = button.querySelector("span") || button;
  const originalLabel = label.textContent;
  button.disabled = true;
  label.textContent = loadingLabel;
  try {
    const result = await api(path, {
      save_id: state.franchise.save.save_id,
      ...payload,
    });
    state.franchise = result;
    renderFranchise(state.franchise);
    await refreshFranchiseSaveList(state.franchise.save.save_id);
    if (successLabel) showToast(successLabel);
    return result;
  } catch (error) {
    showToast(error.message);
    return null;
  } finally {
    label.textContent = originalLabel;
    if (state.franchise) renderFranchise(state.franchise);
  }
}

function renderFranchise(result) {
  $("#franchise-onboarding").classList.add("hidden");
  $("#franchise-workspace").classList.remove("hidden");
  const summary = result.summary;
  const save = result.save;
  const counts = summary.counts;
  $("#franchise-hero-kicker").textContent =
    `${summary.season} · ${save.branch_name} · revision ${summary.revision}`;
  $("#franchise-hero-title").textContent =
    `${summary.user_team} front office`;
  $("#franchise-hero-copy").textContent =
    `${summary.league_name} · ${counts.players.toLocaleString()} current players across ${counts.franchises} franchises. Every change is autosaved to this branch.`;
  $("#franchise-current-date").textContent =
    formatFranchiseDate(summary.current_date);
  $("#franchise-phase").textContent =
    summary.phase.replaceAll("_", " ");

  $("#franchise-metrics").innerHTML = `
    <div><span>Franchises</span><strong>${counts.franchises}</strong><small>canonical teams</small></div>
    <div><span>Players</span><strong>${counts.players.toLocaleString()}</strong><small>current roster identities</small></div>
    <div><span>Ledger</span><strong>${result.integrity.replayed_events}</strong><small>verified events</small></div>
    <div><span>Branch</span><strong>${escapeHtml(save.branch_name)}</strong><small>${save.parent_save_id ? `from revision ${save.parent_revision}` : "original timeline"}</small></div>`;

  $("#franchise-integrity").innerHTML = `
    <div><span>Replay</span><strong>${result.integrity.verified ? "Verified" : "Failed"}</strong></div>
    <div><span>Revision</span><strong>${result.integrity.revision}</strong></div>
    <div><span>Ledger head</span><strong title="${result.integrity.head_hash}">${result.integrity.head_hash.slice(0, 12)}…</strong></div>
    <div><span>Seed</span><strong>${summary.seed}</strong></div>`;

  const coverageNames = {
    franchises: "Franchises",
    players: "Players",
    player_lifecycle: "Player lifecycle",
    player_health: "Health & workload",
    team_chemistry: "Team chemistry",
    coaching_profiles: "Coaching profiles",
    scouting_reports: "Scouting beliefs",
    scouting_departments: "Scouting departments",
    staff: "Staff",
    contracts: "Contracts",
    draft_assets: "Draft assets",
    draft_ecosystem: "Draft class",
    trade_center: "Trade market",
    cap_exceptions: "Cap exceptions",
    injuries: "Injuries",
    transactions: "Transactions",
  };
  $("#franchise-coverage").innerHTML = Object.entries(result.coverage)
    .map(
      ([key, coverage]) => `
        <div class="${coverage.status === "loaded" ? "loaded" : ""}">
          <span>${coverageNames[key]}</span>
          <strong>${coverage.status === "loaded" ? `${coverage.records.toLocaleString()} loaded` : "Schema ready"}</strong>
        </div>`,
    )
    .join("");

  $("#franchise-roster-title").textContent =
    `${summary.user_team} · ${summary.season}`;
  $("#franchise-roster-count").textContent =
    `${result.roster.length} active`;
  $("#franchise-roster").innerHTML = result.roster
    .map(
      (player) => `
        <div class="franchise-roster-row">
          <div><strong>${escapeHtml(player.name)}</strong><span>${escapeHtml(player.position || "Unknown")} · ${escapeHtml(player.profile_source)}</span></div>
          <span>${number(player.expected_minutes, 1)} min</span>
        </div>`,
    )
    .join("");

  const eventNames = {
    league_created: "League created",
    branch_created: "Timeline branched",
    date_advanced: "Calendar advanced",
    staff_registered: "Staff registered",
    contract_registered: "Contract registered",
    draft_asset_registered: "Draft asset registered",
    cap_exception_registered: "Cap exception registered",
    injury_recorded: "Injury recorded",
    transaction_recorded: "Transaction recorded",
    player_lifecycles_initialized: "Player lifecycles initialized",
    player_health_initialized: "Player health initialized",
    player_health_updated: "Availability updated",
    player_workload_recorded: "Workload recorded",
    team_environment_initialized: "Team environment initialized",
    team_chemistry_updated: "Team chemistry updated",
    coaching_profile_updated: "Coaching plan updated",
    chemistry_session_recorded: "Team session recorded",
    scouting_initialized: "Scouting initialized",
    scouting_report_updated: "Scouting report updated",
    scouting_department_updated: "Scouting department updated",
    scouting_cycle_completed: "Scouting cycle completed",
    draft_ecosystem_initialized: "Draft class generated",
    draft_lottery_completed: "Draft lottery completed",
    draft_combine_completed: "Draft combine completed",
    draft_prospect_scouted: "Draft prospect scouted",
    draft_board_updated: "Draft board updated",
    draft_pick_made: "Draft selection recorded",
    trade_center_initialized: "Trade market initialized",
    trade_rule_policy_updated: "Trade rules updated",
    trade_completed: "Trade completed",
  };
  $("#franchise-event-count").textContent =
    `${save.event_count} events`;
  $("#franchise-events").innerHTML = result.events
    .map(
      (event) => `
        <div class="franchise-event-row">
          <span class="franchise-event-sequence">${String(event.sequence).padStart(3, "0")}</span>
          <div><strong>${eventNames[event.event_type] || escapeHtml(event.event_type)}</strong><span>${formatFranchiseDate(event.occurred_on)} · ${escapeHtml(event.actor)}</span></div>
          <code title="${event.event_hash}">${event.event_hash.slice(0, 8)}</code>
        </div>`,
    )
    .join("");
  renderFranchiseCap(result);
  renderFranchiseLifecycle(result);
  renderFranchiseHealth(result);
  renderTeamEnvironment(result);
  renderFranchiseScouting(result);
  renderFranchiseDraft(result);
  renderFranchiseTradeCenter(result);
}

function renderFranchiseCap(result) {
  const rules = result.cba;
  const thresholds = [
    ["Minimum payroll", rules.minimum_team_salary, "Teams must reach this payroll floor."],
    ["Salary cap", rules.salary_cap, "Ordinary signing room ends here."],
    ["Luxury tax", rules.tax_level, "Tax payments begin above this line."],
    ["First apron", rules.first_apron, "Several roster-building tools hard-cap here."],
    ["Second apron", rules.second_apron, "Aggregation, cash, and other tools disappear."],
  ];
  $("#cap-thresholds").innerHTML = thresholds
    .map(
      ([label, amount, description], index) => `
        <div class="cap-threshold ${index > 2 ? "apron" : ""}">
          <span>${escapeHtml(label)}</span>
          <strong>${money(amount)}</strong>
          <small>${escapeHtml(description)}</small>
        </div>`,
    )
    .join("");

  const sheet = result.cap_sheet;
  $("#cap-sheet-title").textContent = `${sheet.team} · ${sheet.season}`;
  $("#cap-sheet-coverage").textContent =
    `${sheet.players_with_salary} / ${sheet.roster_players} salaries`;
  $("#cap-data-warning").innerHTML = sheet.complete
    ? `<strong>Cap sheet complete</strong><span>Verified payroll: ${money(sheet.known_salary)}</span>`
    : `<strong>Contract import pending</strong><span>${escapeHtml(sheet.warning)} The checker remains usable with a full payroll amount you enter.</span>`;
  $("#cap-roster-table").innerHTML = sheet.players
    .map(
      (player) => `
        <div class="cap-roster-row">
          <span>${escapeHtml(player.name)}</span>
          <strong class="${player.salary === null ? "unknown" : ""}">${player.salary === null ? "Unknown" : money(player.salary)}</strong>
        </div>`,
    )
    .join("");
}

function renderFranchiseLifecycle(result) {
  if (!result || !result.player_lifecycle) return;
  const lifecycle = result.player_lifecycle;
  $("#lifecycle-initialize-card").classList.toggle("hidden", lifecycle.ready);
  $("#development-ready").classList.toggle("hidden", !lifecycle.ready);
  if (!lifecycle.ready) return;

  const records = lifecycle.records;
  if (!records.length) {
    $("#development-ready").classList.add("hidden");
    return;
  }
  if (!records.some((record) => record.player_id === state.lifecyclePlayerId)) {
    state.lifecyclePlayerId = records[0].player_id;
    state.lifecycleProjection = null;
  }
  $("#lifecycle-player").innerHTML = records
    .map(
      (record) =>
        `<option value="${record.player_id}" ${record.player_id === state.lifecyclePlayerId ? "selected" : ""}>${escapeHtml(record.name)} · ${number(record.overall, 1)} OVR</option>`,
    )
    .join("");

  const selected = records.find(
    (record) => record.player_id === state.lifecyclePlayerId,
  );
  if (!selected) return;
  const age = selected.age === null ? "Age unknown" : `Age ${number(selected.age, 0)}`;
  const potentialLow = Math.max(20, selected.potential_mean - selected.potential_sd);
  const potentialHigh = Math.min(99, selected.potential_mean + selected.potential_sd);
  $("#lifecycle-player-card").innerHTML = `
    <div class="lifecycle-player-heading">
      <div>
        <p class="eyebrow">${escapeHtml(selected.team)} · ${escapeHtml(selected.position || "Position unknown")}</p>
        <h2>${escapeHtml(selected.name)}</h2>
        <span>${age} · ${escapeHtml(selected.stage.replaceAll("_", " "))} · ${escapeHtml(selected.confidence)} confidence</span>
      </div>
      <strong>${number(selected.overall, 1)}<small>OVR</small></strong>
    </div>
    <div class="lifecycle-attribute-grid">
      ${[
        ["Offense", selected.offense],
        ["Playmaking", selected.playmaking],
        ["Defense", selected.defense],
        ["Athleticism", selected.athleticism],
      ]
        .map(
          ([label, value]) =>
            `<div><span>${label}</span><strong>${number(value, 1)}</strong></div>`,
        )
        .join("")}
    </div>
    <div class="lifecycle-confidence">
      <span>Current potential belief</span>
      <strong>${number(potentialLow, 1)}–${number(potentialHigh, 1)}</strong>
      <small>${selected.age === null ? "Age curve withheld · wider uncertainty" : escapeHtml(selected.age_source.replaceAll("_", " "))}</small>
    </div>`;

  $("#lifecycle-minutes").value = String(
    Math.min(3500, Math.max(0, Math.round(selected.workload_minutes / 50) * 50)),
  );
  if (
    state.lifecycleProjection &&
    state.lifecycleProjection.player_id === selected.player_id
  ) {
    renderLifecycleProjection(state.lifecycleProjection);
  } else {
    $("#lifecycle-result").innerHTML = `
      <div class="empty-state inline">
        <p class="eyebrow">Ready to project</p>
        <p>Adjust the scenario and run 400 independent paths for ${escapeHtml(selected.name)}.</p>
      </div>`;
  }
}

function renderLifecycleProjection(result) {
  const baseline = Number(result.baseline.overall);
  const career = result.career_high_overall;
  const trajectory = result.trajectory
    .map((row) => {
      if (!row.overall) {
        return `
          <div class="lifecycle-year-row retired">
            <span>${escapeHtml(row.season)}</span>
            <div><em>Retired in all paths</em></div>
            <strong>—</strong>
          </div>`;
      }
      const low = Number(row.overall.p10);
      const median = Number(row.overall.p50);
      const high = Number(row.overall.p90);
      const left = Math.max(0, Math.min(100, ((low - 20) / 79) * 100));
      const width = Math.max(1, Math.min(100 - left, ((high - low) / 79) * 100));
      const marker = Math.max(0, Math.min(100, ((median - low) / Math.max(high - low, 0.01)) * 100));
      return `
        <div class="lifecycle-year-row">
          <span>${escapeHtml(row.season)}<small>${row.age === null ? "age unknown" : `age ${number(row.age, 0)}`}</small></span>
          <div class="lifecycle-band" title="P10 ${number(low, 1)} · median ${number(median, 1)} · P90 ${number(high, 1)}">
            <i style="left:${left}%;width:${width}%"><b style="left:${marker}%"></b></i>
          </div>
          <strong>${number(median, 1)}<small>${number(low, 1)}–${number(high, 1)}</small></strong>
        </div>`;
    })
    .join("");
  $("#lifecycle-result").innerHTML = `
    <div class="lifecycle-result-heading">
      <div>
        <p class="eyebrow">${escapeHtml(result.config.focus)} focus · seed ${result.seed}</p>
        <h2>${escapeHtml(result.player_name)} career outlook</h2>
      </div>
      <span>${result.config.paths} paths</span>
    </div>
    <div class="lifecycle-result-metrics">
      <div><span>Baseline</span><strong>${number(baseline, 1)}</strong></div>
      <div><span>Median career high</span><strong>${number(career.p50, 1)}</strong></div>
      <div><span>Breakout chance</span><strong>${pct(result.breakout_probability)}</strong></div>
      <div><span>Retired by horizon</span><strong>${result.age_known ? pct(result.retirement_probability_by_horizon) : "Withheld"}</strong></div>
    </div>
    <div class="lifecycle-chart-key">
      <span><i></i> P10–P90 range</span><span><b></b> Median</span>
    </div>
    <div class="lifecycle-trajectory">${trajectory}</div>
    <div class="lifecycle-interpretation">
      <strong>How to read this</strong>
      <p>${escapeHtml(result.interpretation)} The band is uncertainty, not a guaranteed rating path.</p>
    </div>`;
}

function renderFranchiseHealth(result) {
  if (!result || !result.player_health) return;
  const health = result.player_health;
  $("#health-initialize-card").classList.toggle("hidden", health.ready);
  $("#health-ready").classList.toggle("hidden", !health.ready);
  if (!health.ready || !health.records.length) return;
  if (!health.records.some((record) => record.player_id === state.healthPlayerId)) {
    state.healthPlayerId = health.records[0].player_id;
  }
  const selected = health.records.find(
    (record) => record.player_id === state.healthPlayerId,
  );
  $("#health-team-title").textContent = `${result.summary.user_team} health`;
  $("#health-restricted-count").textContent =
    `${health.coverage.restricted} restricted`;
  $("#health-roster-list").innerHTML = health.records
    .map(
      (record) => `
        <button class="health-roster-row ${record.player_id === state.healthPlayerId ? "active" : ""}" data-health-player="${record.player_id}" type="button">
          <span class="health-status-dot status-${record.availability}"></span>
          <div><strong>${escapeHtml(record.name)}</strong><small>${escapeHtml(record.availability.replaceAll("_", " "))}${record.minute_limit === null ? "" : ` · ${number(record.minute_limit, 0)} min cap`}</small></div>
          <em>${number(record.readiness, 0)}</em>
        </button>`,
    )
    .join("");
  $$("[data-health-player]", $("#health-roster-list")).forEach((button) => {
    button.addEventListener("click", () => {
      state.healthPlayerId = Number(button.dataset.healthPlayer);
      renderFranchiseHealth(state.franchise);
    });
  });
  if (!selected) return;
  const preparedWeek = Math.max(Number(selected.chronic_load) / 4, 1);
  const ratio = Number(selected.acute_load) / preparedWeek;
  const concernLabel =
    selected.load_concern < 0.24
      ? "Low"
      : selected.load_concern < 0.48
        ? "Watch"
        : selected.load_concern < 0.7
          ? "Elevated"
          : "High";
  $("#health-player-summary").innerHTML = `
    <div class="health-summary-heading">
      <div><p class="eyebrow">${escapeHtml(selected.team)} · ${escapeHtml(selected.position || "Position unknown")}</p><h2>${escapeHtml(selected.name)}</h2><span>${escapeHtml(selected.availability.replaceAll("_", " "))} · ${escapeHtml(selected.confidence)} confidence</span></div>
      <strong>${number(selected.readiness, 0)}<small>readiness</small></strong>
    </div>
    <div class="health-metric-strip">
      <div><span>Acute load</span><strong>${number(selected.acute_load, 1)}</strong><small>7-day weighted</small></div>
      <div><span>Chronic load</span><strong>${number(selected.chronic_load, 1)}</strong><small>28-day weighted</small></div>
      <div><span>Load ratio</span><strong>${number(ratio, 2)}×</strong><small>acute / prepared week</small></div>
      <div><span>Fatigue</span><strong>${number(selected.fatigue, 0)}</strong><small>0–100 index</small></div>
      <div class="concern-${concernLabel.toLowerCase()}"><span>Load concern</span><strong>${concernLabel}</strong><small>${pct(selected.load_concern)}</small></div>
    </div>
    <p class="health-boundary">${escapeHtml(health.interpretation)} Last load: ${selected.last_load_date ? formatFranchiseDate(selected.last_load_date) : "no session recorded in this save"}.</p>`;

  $("#health-status").value = selected.availability;
  $("#health-body-area").value = selected.body_area || "";
  $("#health-minute-limit").value =
    selected.minute_limit === null ? "" : String(selected.minute_limit);
  $("#health-return-date").value = selected.expected_return || "";
  $("#health-detail").value = selected.detail || "";
}

function renderTeamEnvironment(result) {
  if (!result || !result.team_environment) return;
  const environment = result.team_environment;
  $("#environment-initialize-card").classList.toggle("hidden", environment.ready);
  $("#environment-ready").classList.toggle("hidden", !environment.ready);
  if (!environment.ready) return;
  const chemistry = environment.chemistry;
  const coaching = environment.coaching;
  const score = (
    chemistry.cohesion +
    chemistry.role_clarity +
    chemistry.trust +
    chemistry.system_familiarity +
    chemistry.morale
  ) / 5;
  $("#chemistry-score-card").innerHTML = `
    <div><p class="eyebrow">${escapeHtml(chemistry.team)} environment · ${escapeHtml(chemistry.confidence)} confidence</p><h2>${number(score, 0)}<small>team environment</small></h2></div>
    <div class="chemistry-score-facts"><span>${escapeHtml(coaching.offensive_system.replaceAll("_", " "))} offense</span><span>${escapeHtml(coaching.defensive_system.replaceAll("_", " "))} defense</span><span>${chemistry.shared_sessions} shared sessions</span></div>
    <p>${escapeHtml(environment.interpretation)}</p>`;
  const chemistryFields = [
    ["#chemistry-cohesion", chemistry.cohesion],
    ["#chemistry-roles", chemistry.role_clarity],
    ["#chemistry-trust", chemistry.trust],
    ["#chemistry-system", chemistry.system_familiarity],
    ["#chemistry-morale", chemistry.morale],
  ];
  chemistryFields.forEach(([selector, value]) => {
    const input = $(selector);
    input.value = String(Math.round(value));
    $("output", input.parentElement).textContent = input.value;
  });
  $("#coach-name").value = coaching.coach_name;
  $("#coach-offense").value = coaching.offensive_system;
  $("#coach-defense").value = coaching.defensive_system;
  $("#coach-pace").value = String(coaching.pace_emphasis);
  $("#coach-depth").value = String(coaching.rotation_depth);
  $("#coach-development").value = coaching.development_priority;
  $("#coach-adaptability").value = String(coaching.adaptability);
}

function renderFranchiseTradeCenter(result) {
  if (!result?.trade_center) return;
  const center = result.trade_center;
  $("#trade-initialize-card").classList.toggle("hidden", center.ready);
  $("#trade-ready").classList.toggle("hidden", !center.ready);
  if (!center.ready) return;
  $("#trade-user-team").textContent = result.summary.user_team;
  renderTradeRules(center);
  renderTradeHistory(center.recent_trades || []);
  if (
    state.tradeBoardSaveId &&
    state.tradeBoardSaveId !== result.save.save_id
  ) {
    state.tradeBoard = null;
    state.tradeBoardSaveId = null;
    clearTradeProposal();
  }
  $("#trade-run-market").disabled = !center.policy.ai_to_ai_trades;
}

async function loadTradeBoard(force = false) {
  if (!state.franchise?.trade_center?.ready) return;
  const saveId = state.franchise.save.save_id;
  if (!force && state.tradeBoardSaveId === saveId && state.tradeBoard) {
    renderTradeBuilder();
    return;
  }
  loading($("#trade-user-assets"), "Loading league assets…");
  loading($("#trade-partner-assets"), "Loading league assets…");
  try {
    state.tradeBoard = await api("/api/franchise/trade-board", {
      save_id: saveId,
    });
    state.tradeBoardSaveId = saveId;
    const userTeam = state.franchise.summary.user_team;
    const partner = $("#trade-partner");
    const current = partner.value;
    partner.innerHTML = Object.keys(state.tradeBoard.strategies)
      .filter((team) => team !== userTeam)
      .sort()
      .map((team) => `<option value="${team}">${team} · ${escapeHtml(state.tradeBoard.strategies[team])}</option>`)
      .join("");
    if ([...partner.options].some((option) => option.value === current)) {
      partner.value = current;
    }
    $("#trade-salary-note").textContent = state.tradeBoard.salary_note;
    if (!Object.keys(state.tradeSelections).length) clearTradeProposal();
    renderTradeBuilder();
  } catch (error) {
    renderError($("#trade-user-assets"), error.message);
    renderError($("#trade-partner-assets"), error.message);
  }
}

function clearTradeProposal() {
  state.tradeSelections = {};
  state.tradeEvaluation = null;
  if ($("#trade-evaluation")) {
    $("#trade-evaluation").innerHTML =
      `<div class="empty-state inline"><p class="eyebrow">League office review</p><p>Select players or picks from both sides, then evaluate the proposal.</p></div>`;
  }
}

function tradeSelection(team) {
  if (!state.tradeSelections[team]) {
    state.tradeSelections[team] = { player_ids: [], asset_ids: [] };
  }
  return state.tradeSelections[team];
}

function selectedTradePackages() {
  const userTeam = state.franchise.summary.user_team;
  const partner = $("#trade-partner").value;
  const user = tradeSelection(userTeam);
  const other = tradeSelection(partner);
  return [
    {
      team: userTeam,
      player_ids: [...user.player_ids],
      asset_ids: [...user.asset_ids],
    },
    {
      team: partner,
      player_ids: [...other.player_ids],
      asset_ids: [...other.asset_ids],
    },
  ];
}

function tradeProposalHasAssets() {
  return selectedTradePackages().some(
    (item) => item.player_ids.length || item.asset_ids.length,
  );
}

function renderTradeBuilder() {
  if (!state.tradeBoard || !state.franchise) return;
  const userTeam = state.franchise.summary.user_team;
  const partner = $("#trade-partner").value;
  if (!partner) return;
  $("#trade-user-package-title").textContent =
    `${userTeam} · ${escapeHtml(state.tradeBoard.strategies[userTeam])}`;
  $("#trade-partner-package-title").textContent =
    `${partner} · ${escapeHtml(state.tradeBoard.strategies[partner])}`;
  renderTradeAssets(userTeam, $("#trade-user-assets"));
  renderTradeAssets(partner, $("#trade-partner-assets"));
  updateTradePackageCounts();
}

function renderTradeAssets(team, root) {
  const selection = tradeSelection(team);
  const players = state.tradeBoard.players
    .filter((player) => player.team === team)
    .sort((a, b) => b.trade_value - a.trade_value);
  const picks = state.tradeBoard.assets
    .filter((asset) => asset.current_team === team)
    .sort((a, b) =>
      a.draft_year - b.draft_year ||
      a.round - b.round ||
      a.original_team.localeCompare(b.original_team),
    );
  root.innerHTML = `
    <div class="trade-asset-section">
      <p class="eyebrow">Players · ${players.length}</p>
      ${players.map((player) => `
        <label class="trade-asset-row">
          <input type="checkbox" data-trade-asset="player" data-trade-team="${team}" value="${player.player_id}" ${selection.player_ids.includes(player.player_id) ? "checked" : ""} />
          <div><strong>${escapeHtml(player.name)}</strong><span>${escapeHtml(player.position || "—")} · OVR ${number(player.overall, 0)} · ${escapeHtml(player.health)}</span></div>
          <span><strong>${money(player.salary, 1)}</strong><small>${player.salary_source === "authoritative-contract" ? "contract" : "modeled"} · value ${number(player.trade_value, 0)}</small></span>
        </label>`).join("")}
    </div>
    <div class="trade-asset-section">
      <p class="eyebrow">Draft assets · ${picks.length}</p>
      ${picks.map((asset) => `
        <label class="trade-asset-row pick">
          <input type="checkbox" data-trade-asset="pick" data-trade-team="${team}" value="${escapeHtml(asset.asset_id)}" ${selection.asset_ids.includes(asset.asset_id) ? "checked" : ""} />
          <div><strong>${asset.draft_year} round ${asset.round}</strong><span>${asset.original_team === team ? "Own selection" : `Via ${escapeHtml(asset.original_team)}`} · ${asset.protection ? escapeHtml(asset.protection) : "unprotected"}</span></div>
          <span><strong>${number(asset.trade_value, 0)}</strong><small>asset value</small></span>
        </label>`).join("")}
    </div>`;
  $$("[data-trade-asset]", root).forEach((input) => {
    input.addEventListener("change", () => {
      const selected = tradeSelection(input.dataset.tradeTeam);
      const key = input.dataset.tradeAsset === "player"
        ? "player_ids"
        : "asset_ids";
      const value = key === "player_ids" ? Number(input.value) : input.value;
      selected[key] = input.checked
        ? [...new Set([...selected[key], value])]
        : selected[key].filter((item) => item !== value);
      state.tradeEvaluation = null;
      $("#trade-evaluation").innerHTML =
        `<div class="empty-state inline"><p class="eyebrow">Proposal changed</p><p>Evaluate again to refresh legality and team acceptance.</p></div>`;
      updateTradePackageCounts();
    });
  });
}

function updateTradePackageCounts() {
  const userTeam = state.franchise.summary.user_team;
  const partner = $("#trade-partner").value;
  const count = (team) => {
    const selection = tradeSelection(team);
    return selection.player_ids.length + selection.asset_ids.length;
  };
  const userCount = count(userTeam);
  const partnerCount = count(partner);
  $("#trade-user-package-count").textContent =
    `${userCount} asset${userCount === 1 ? "" : "s"}`;
  $("#trade-partner-package-count").textContent =
    `${partnerCount} asset${partnerCount === 1 ? "" : "s"}`;
}

function renderTradeRules(center) {
  const policy = center.policy;
  $("#trade-rule-list").innerHTML = center.rule_coverage
    .map((rule) => `
      <label class="trade-rule-row ${rule.key === "injury_house_rule" ? "house" : ""}">
        <input type="checkbox" data-trade-rule="${escapeHtml(rule.key)}" ${policy[rule.key] ? "checked" : ""} />
        <span><strong>${escapeHtml(rule.label)}</strong><small>${escapeHtml(rule.authority)}</small></span>
      </label>`)
    .join("");
  $("#trade-ai-aggression").value = String(policy.ai_aggressiveness);
  $("output", $("#trade-ai-aggression").parentElement).textContent =
    pct(policy.ai_aggressiveness, 0);
}

function renderTradeEvaluation() {
  const evaluation = state.tradeEvaluation;
  if (!evaluation) return;
  const title = !evaluation.legal
    ? "League office blocked the trade"
    : evaluation.accepted
      ? "The trade can be completed"
      : "The partner wants more value";
  const status = !evaluation.legal ? "blocked" : evaluation.accepted ? "accepted" : "counter";
  $("#trade-evaluation").innerHTML = `
    <div class="trade-evaluation-heading ${status}">
      <div><p class="eyebrow">${evaluation.legal ? "Legal construction" : "Illegal construction"}</p><h2>${title}</h2></div>
      <span>${evaluation.blockers.length} blocker${evaluation.blockers.length === 1 ? "" : "s"}</span>
    </div>
    <div class="trade-team-evaluations">
      ${evaluation.teams.map((team) => `
        <div>
          <p class="eyebrow">${escapeHtml(team.team)} · ${escapeHtml(team.strategy)}</p>
          <h3>${team.accepts ? "Accepts" : "Declines"} <small>${team.value_delta >= 0 ? "+" : ""}${number(team.value_delta, 1)} value</small></h3>
          <p>${escapeHtml(team.acceptance_copy)}</p>
          <dl>
            <div><dt>Outgoing salary</dt><dd>${money(team.outgoing_salary, 1)}</dd></div>
            <div><dt>Incoming salary</dt><dd>${money(team.incoming_salary, 1)}</dd></div>
            <div><dt>After trade</dt><dd>${money(team.after_salary, 1)}</dd></div>
            <div><dt>Cap band</dt><dd>${escapeHtml(team.salary_band_after.replaceAll("_", " "))}</dd></div>
          </dl>
        </div>`).join("")}
    </div>
    ${evaluation.blockers.length ? `<div class="trade-blockers"><p class="eyebrow">Active blockers</p>${evaluation.blockers.map((item) => `<div><strong>${escapeHtml(item.rule.replaceAll("_", " "))}</strong><span>${escapeHtml(item.message)}</span></div>`).join("")}</div>` : ""}
    ${evaluation.warnings.length ? `<div class="trade-warnings">${evaluation.warnings.map((warning) => `<span>${escapeHtml(warning)}</span>`).join("")}</div>` : ""}
    <button class="run-button full" id="trade-execute" type="button" ${evaluation.can_execute ? "" : "disabled"}><span>Accept and complete trade</span><span>→</span></button>`;
  $("#trade-execute").addEventListener("click", async (event) => {
    const result = await runTradeAction(
      "/api/franchise/execute-trade",
      { packages: selectedTradePackages() },
      event.currentTarget,
      "Completing trade…",
      "Trade completed and every asset ledger updated.",
    );
    if (!result) return;
    state.tradeBoard = null;
    state.tradeBoardSaveId = null;
    clearTradeProposal();
    await loadTradeBoard(true);
  });
}

function renderTradeHistory(records) {
  $("#trade-history").innerHTML = records.length
    ? `<p class="eyebrow">Recent league trades</p>${records.map((record) => `
        <div><strong>${escapeHtml(record.teams.join(" ↔ "))}</strong><span>${escapeHtml(record.summary)}</span><small>${formatFranchiseDate(record.occurred_on)} · ${escapeHtml(record.source)}</small></div>`).join("")}`
    : `<div class="empty-state inline"><p>No trades have been completed on this branch.</p></div>`;
}

function renderFranchiseDraft(result) {
  if (!result?.draft) return;
  const draft = result.draft;
  $("#draft-initialize-card").classList.toggle("hidden", draft.ready);
  $("#draft-ready").classList.toggle("hidden", !draft.ready);
  if (!draft.ready) {
    state.draftProspectId = null;
    return;
  }

  const available = draft.prospects.filter((prospect) => !prospect.drafted);
  if (!available.some((prospect) => prospect.player_id === state.draftProspectId)) {
    state.draftProspectId = available[0]?.player_id || draft.prospects[0]?.player_id || null;
  }
  const statusCopy = {
    class_ready: [
      "Class ready",
      "Scout the class, verify measurements at the combine, then draw the complete lottery order.",
    ],
    lottery_complete: [
      "Lottery complete",
      "The 60-pick order is locked. Simulate to your first owned selection when you are ready.",
    ],
    in_progress: [
      "Draft in progress",
      "CPU front offices use imperfect public information, team context, and reproducible decision noise.",
    ],
    complete: [
      "Draft complete",
      "All 60 draft rights are permanent entries in this franchise timeline.",
    ],
  }[draft.status] || ["Draft class", "Your saved draft universe is ready."];
  $("#draft-status-kicker").textContent =
    `${draft.draft_year} draft · ${draft.model_version}`;
  $("#draft-status-title").textContent = statusCopy[0];
  $("#draft-status-copy").textContent = statusCopy[1];
  $("#draft-combine").disabled = draft.combine_complete || draft.status === "complete";
  $("#draft-combine").textContent =
    draft.combine_complete ? "Combine verified" : "Run combine";
  const lotteryButton = $("#draft-lottery");
  lotteryButton.disabled = draft.order.length > 0;
  const lotteryLabel = lotteryButton.querySelector("span") || lotteryButton;
  lotteryLabel.textContent =
    draft.order.length ? "Lottery order locked" : "Run 3-2-1 lottery";

  renderDraftBoard(draft);
  renderDraftDossier(draft);
  renderDraftRoom(draft, result.summary.user_team);
}

function renderDraftBoard(draft) {
  const query = $("#draft-search").value.trim().toLowerCase();
  const rows = draft.prospects.filter((prospect) =>
    !query ||
    prospect.name.toLowerCase().includes(query) ||
    prospect.position.toLowerCase().includes(query) ||
    prospect.origin.toLowerCase().includes(query),
  );
  const availableCount = draft.prospects.filter((prospect) => !prospect.drafted).length;
  $("#draft-board-count").textContent =
    `${availableCount} available · ${draft.prospects.length} ranked`;
  $("#draft-board").innerHTML = rows.length
    ? rows.map((prospect) => `
        <button class="draft-board-row ${prospect.player_id === state.draftProspectId ? "active" : ""} ${prospect.drafted ? "drafted" : ""}" data-draft-prospect="${prospect.player_id}" type="button">
          <span class="draft-board-rank">${String(prospect.board_rank).padStart(2, "0")}</span>
          <div>
            <strong>${escapeHtml(prospect.name)}</strong>
            <span>${escapeHtml(prospect.position)} · ${escapeHtml(prospect.origin)} · consensus #${prospect.consensus_rank}</span>
          </div>
          <span class="scouting-range">${number(prospect.overall_mean, 1)}<small>${number(prospect.overall_low, 0)}–${number(prospect.overall_high, 0)}</small></span>
          <em class="confidence-${prospect.confidence}">${prospect.drafted ? `#${prospect.selection.overall_pick} ${prospect.selection.team}` : escapeHtml(prospect.confidence)}</em>
        </button>`).join("")
    : `<div class="empty-state inline"><p>No prospects match that search.</p></div>`;
  $$("[data-draft-prospect]", $("#draft-board")).forEach((button) => {
    button.addEventListener("click", () => {
      state.draftProspectId = Number(button.dataset.draftProspect);
      renderFranchiseDraft(state.franchise);
    });
  });
}

function renderDraftDossier(draft) {
  const prospect = draft.prospects.find(
    (item) => item.player_id === state.draftProspectId,
  );
  if (!prospect) {
    $("#draft-dossier").innerHTML =
      `<div class="empty-state inline"><p class="eyebrow">Class exhausted</p><p>Every prospect has been selected.</p></div>`;
    return;
  }
  const attributes = [
    ["Offense", prospect.offense_mean, prospect.offense_sd],
    ["Playmaking", prospect.playmaking_mean, prospect.playmaking_sd],
    ["Defense", prospect.defense_mean, prospect.defense_sd],
    ["Athleticism", prospect.athleticism_mean, prospect.athleticism_sd],
    ["Potential", prospect.potential_mean, prospect.potential_sd],
  ];
  const archetypes = [
    ["Creator", prospect.creator_probability],
    ["Shooter", prospect.shooter_probability],
    ["Two-way", prospect.two_way_probability],
    ["Rim anchor", prospect.rim_probability],
    ["Connector", prospect.connector_probability],
  ].sort((a, b) => b[1] - a[1]);
  const measurements = draft.combine_complete
    ? `<div class="draft-measurements">
        <div><span>Height</span><strong>${formatHeight(prospect.height_inches)}</strong></div>
        <div><span>Wingspan</span><strong>${formatHeight(prospect.wingspan_inches)}</strong></div>
        <div><span>Weight</span><strong>${prospect.weight_pounds} lb</strong></div>
      </div>`
    : `<div class="draft-measurements pending"><span>Physical measurements are unverified until the combine.</span></div>`;
  $("#draft-dossier").innerHTML = `
    <div class="scouting-dossier-heading">
      <div>
        <p class="eyebrow">${escapeHtml(prospect.position)} · ${escapeHtml(prospect.origin)} · age ${number(prospect.age, 1)}</p>
        <h2>${escapeHtml(prospect.name)}</h2>
        <span>Your board #${prospect.board_rank} · public consensus #${prospect.consensus_rank} · ${escapeHtml(prospect.confidence)} confidence</span>
      </div>
      <strong>${number(prospect.overall_mean, 1)}<small>estimated OVR</small></strong>
    </div>
    <p class="scouting-boundary">This is your department’s present belief, not hidden true talent. CPU teams do not read your private report.</p>
    ${measurements}
    <div class="scouting-attributes">
      ${attributes.map(([label, mean, sd]) => {
        const low = Math.max(25, mean - 1.28 * sd);
        const high = Math.min(99, mean + 1.28 * sd);
        return `<div><span>${label}<small>${number(low, 0)}–${number(high, 0)}</small></span><i><b style="left:${low}%;width:${Math.max(2, high - low)}%"></b><em style="left:${mean}%"></em></i><strong>${number(mean, 1)}</strong></div>`;
      }).join("")}
    </div>
    <div class="scouting-evidence">
      <div><span>Observation</span><strong>${number(prospect.observation_hours, 0)}h</strong></div>
      <div><span>Reports</span><strong>${prospect.evaluations}</strong></div>
      <div><span>Potential band</span><strong>${number(prospect.potential_low, 0)}–${number(prospect.potential_high, 0)}</strong></div>
    </div>
    <div class="scouting-archetypes">
      <p class="eyebrow">Archetype probabilities</p>
      ${archetypes.map(([label, probability]) => `<div><span>${label}</span><i><b style="width:${probability * 100}%"></b></i><strong>${pct(probability, 0)}</strong></div>`).join("")}
    </div>
    <div class="draft-dossier-actions">
      <button class="quiet-button" id="draft-move-top" type="button" ${prospect.board_rank === 1 ? "disabled" : ""}>Move to top of board</button>
      <form id="draft-scout-form">
        <label><span>Scout hours</span><input id="draft-scout-hours" type="number" min="1" max="120" value="16" /></label>
        <button class="run-button" type="submit"><span>Scout prospect</span><span>→</span></button>
      </form>
    </div>`;
  $("#draft-move-top").addEventListener("click", async (event) => {
    const ordered = [
      prospect.player_id,
      ...draft.prospects
        .filter((item) => item.player_id !== prospect.player_id)
        .map((item) => item.player_id),
    ];
    await runDraftAction(
      "/api/franchise/update-draft-board",
      { player_ids: ordered },
      event.currentTarget,
      "Moving…",
      `${prospect.name} moved to the top of your board.`,
    );
  });
  $("#draft-scout-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Scouting prospect…");
    try {
      state.franchise = await api("/api/franchise/scout-draft-prospect", {
        save_id: state.franchise.save.save_id,
        player_id: prospect.player_id,
        hours: Number($("#draft-scout-hours").value),
      });
      renderFranchise(state.franchise);
      showToast(`${prospect.name} report updated.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function renderDraftRoom(draft, userTeam) {
  const next = draft.next_slot;
  const complete = draft.status === "complete";
  $("#draft-room-progress").textContent =
    `${draft.selections.length} / ${draft.order.length || 60} picks`;
  $("#draft-room-title").textContent = complete
    ? "Two rounds complete"
    : next
      ? `${next.current_team} is on the clock`
      : "Lottery pending";
  $("#draft-on-clock").innerHTML = next
    ? `<div class="${draft.user_on_clock ? "user-pick" : ""}">
        <span>Pick ${next.overall_pick} · round ${next.round}, pick ${next.pick_in_round}</span>
        <strong>${escapeHtml(next.current_team)}</strong>
        <small>${next.current_team !== next.original_team ? `via ${escapeHtml(next.original_team)}` : draft.user_on_clock ? "Your selection" : "CPU front office"}</small>
      </div>`
    : draft.order.length
      ? `<div><strong>Draft complete</strong><small>All rights are recorded below.</small></div>`
      : `<div><strong>Run the lottery first</strong><small>The projected preliminary order uses current roster strength.</small></div>`;
  $("#draft-sim-to-pick").disabled =
    !next || draft.user_on_clock || complete;
  $("#draft-make-pick").disabled =
    !next || !draft.user_on_clock || !state.draftProspectId || complete;

  const lottery = draft.lottery || [];
  const lotteryMarkup = !draft.selections.length && lottery.length
    ? `<div class="draft-lottery-order">
        <p class="eyebrow">2027 lottery result</p>
        ${lottery.map((slot) => `<div><span>${slot.overall_pick}</span><strong>${escapeHtml(slot.current_team)}</strong><small>${slot.original_team !== slot.current_team ? `via ${escapeHtml(slot.original_team)}` : `${slot.lottery_balls} ball${slot.lottery_balls === 1 ? "" : "s"}`}</small></div>`).join("")}
      </div>`
    : "";
  const selections = [...draft.selections].reverse();
  $("#draft-ledger").innerHTML = lotteryMarkup || (selections.length
    ? `<div class="draft-selection-ledger">
        <p class="eyebrow">Selection ledger · newest first</p>
        ${selections.map((selection) => `
          <div>
            <span>${selection.overall_pick}</span>
            <div><strong>${escapeHtml(selection.player_name)}</strong><small>${escapeHtml(selection.position)} · ${escapeHtml(selection.team)}${selection.team !== selection.original_team ? ` via ${escapeHtml(selection.original_team)}` : ""}</small></div>
          </div>`).join("")}
      </div>`
    : `<div class="empty-state inline"><p>The lottery and all 60 selections will appear here.</p></div>`);
}

function formatHeight(value) {
  const inches = Math.round(Number(value));
  return `${Math.floor(inches / 12)}′${inches % 12}″`;
}

function renderFranchiseScouting(result) {
  if (!result?.scouting) return;
  const scouting = result.scouting;
  const prospectReady = scouting.prospect_scouting_ready;
  $("#scouting-initialize-card").classList.toggle("hidden", prospectReady);
  $("#scouting-ready").classList.remove("hidden");
  if (!scouting.department) return;
  const department = scouting.department;
  const prospects = scouting.coverage.draft_prospects || 0;
  $("#scouting-department-title").textContent =
    prospects
      ? `${department.team} · ${department.weekly_hours} prospect hours per week`
      : "Draft scouting ready";
  $("#scouting-department-copy").textContent =
    prospects
      ? `${department.automation_enabled ? "Automatic scouting is on" : "Automatic scouting is paused"} · ${department.priority.replaceAll("_", " ")} priority · ${department.cycles_completed} completed cycles · ${prospects} draft prospects.`
      : "There are no undrafted prospects in this league yet. Established NBA players are fully known; the department will activate automatically when a draft class is created.";
  $("#scouting-automation").checked = department.automation_enabled;
  $("#scouting-hours").value = String(department.weekly_hours);
  $("#scouting-priority").value = department.priority;
  $("#scouting-risk").value = department.risk_tolerance;
  $("#scouting-run-cycle").disabled =
    !prospectReady || !department.automation_enabled || prospects === 0;
  $("#scouting-department-form")
    .closest("details")
    .classList.toggle("hidden", !prospectReady);
  if (
    state.scoutingBoardSaveId &&
    state.scoutingBoardSaveId !== result.save.save_id
  ) {
    state.scoutingBoard = [];
    state.scoutingPlayerId = null;
    state.scoutingBoardSaveId = null;
  }
}

async function loadScoutingBoard() {
  if (!state.franchise?.scouting?.ready) return;
  const saveId = state.franchise.save.save_id;
  if (state.scoutingBoardSaveId === saveId && state.scoutingBoard.length) {
    renderScoutingBoard();
    return;
  }
  loading($("#scouting-board"), "Loading uncertain league beliefs…");
  try {
    const result = await api("/api/franchise/scouting-board", {
      save_id: saveId,
    });
    state.scoutingBoard = result.records;
    state.scoutingBoardSaveId = saveId;
    const teams = [...new Set(result.records.map((row) => row.team))].sort();
    $("#scouting-team-filter").innerHTML =
      `<option value="">All teams</option>` +
      teams.map((team) => `<option value="${team}">${team}</option>`).join("");
    if (
      !state.scoutingBoard.some(
        (record) => record.player_id === state.scoutingPlayerId,
      )
    ) {
      state.scoutingPlayerId = result.records[0]?.player_id || null;
    }
    renderScoutingBoard();
  } catch (error) {
    renderError($("#scouting-board"), error.message);
  }
}

function renderScoutingBoard() {
  const query = $("#scouting-search").value.trim().toLowerCase();
  const team = $("#scouting-team-filter").value;
  const confidence = $("#scouting-confidence-filter").value;
  const rows = state.scoutingBoard.filter(
    (record) =>
      (!query || record.name.toLowerCase().includes(query)) &&
      (!team || record.team === team) &&
      (!confidence || record.confidence === confidence),
  );
  $("#scouting-board-count").textContent =
    `${rows.length.toLocaleString()} players`;
  $("#scouting-board").innerHTML = rows.length
    ? rows.slice(0, 180).map(
      (record) => `
        <button class="scouting-row ${record.player_id === state.scoutingPlayerId ? "active" : ""}" data-scouting-player="${record.player_id}" type="button">
          <div><strong>${escapeHtml(record.name)}</strong><span>${escapeHtml(record.team)} · ${escapeHtml(record.position || "—")} · ${escapeHtml(record.primary_archetype)}</span></div>
          <span class="scouting-range">${record.exact ? Number(record.overall).toFixed(0) : number(record.overall_mean, 1)}<small>${record.exact ? `#${record.league_rank} league` : `${number(record.overall_low, 0)}–${number(record.overall_high, 0)}`}</small></span>
          <em class="confidence-${record.confidence}">${record.exact ? "exact" : escapeHtml(record.confidence)}</em>
        </button>`,
    ).join("")
    : `<div class="empty-state inline"><p>No players match these filters.</p></div>`;
  $$("[data-scouting-player]", $("#scouting-board")).forEach((button) => {
    button.addEventListener("click", () => {
      state.scoutingPlayerId = Number(button.dataset.scoutingPlayer);
      renderScoutingBoard();
    });
  });
  renderScoutingDossier(
    state.scoutingBoard.find(
      (record) => record.player_id === state.scoutingPlayerId,
    ),
  );
}

function renderScoutingDossier(record) {
  if (!record) {
    $("#scouting-dossier").innerHTML =
      `<div class="empty-state inline"><p class="eyebrow">Select a player</p><p>Open a dossier to inspect uncertainty.</p></div>`;
    return;
  }
  if (record.exact && record.established_player) {
    renderEstablishedPlayerDossier(record);
    return;
  }
  const attributes = [
    ["Offense", record.offense_mean, record.offense_sd],
    ["Playmaking", record.playmaking_mean, record.playmaking_sd],
    ["Defense", record.defense_mean, record.defense_sd],
    ["Athleticism", record.athleticism_mean, record.athleticism_sd],
    ["Potential", record.potential_mean, record.potential_sd],
  ];
  const archetypes = [
    ["Creator", record.creator_probability],
    ["Shooter", record.shooter_probability],
    ["Two-way", record.two_way_probability],
    ["Rim anchor", record.rim_probability],
    ["Connector", record.connector_probability],
  ].sort((a, b) => b[1] - a[1]);
  $("#scouting-dossier").innerHTML = `
    <div class="scouting-dossier-heading">
      <div><p class="eyebrow">${escapeHtml(record.team)} · ${escapeHtml(record.position || "Position unknown")}</p><h2>${escapeHtml(record.name)}</h2><span>${escapeHtml(record.confidence)} confidence · updated ${formatFranchiseDate(record.as_of_date)}</span></div>
      <strong>${number(record.overall_mean, 1)}<small>estimated OVR</small></strong>
    </div>
    <p class="scouting-boundary">${escapeHtml(state.franchise.scouting.interpretation)}</p>
    <div class="scouting-attributes">
      ${attributes.map(([label, mean, sd]) => {
        const low = Math.max(0, mean - 1.28 * sd);
        const high = Math.min(100, mean + 1.28 * sd);
        return `<div><span>${label}<small>${number(low, 0)}–${number(high, 0)}</small></span><i><b style="left:${low}%;width:${Math.max(2, high - low)}%"></b><em style="left:${mean}%"></em></i><strong>${number(mean, 1)}</strong></div>`;
      }).join("")}
    </div>
    <div class="scouting-evidence">
      <div><span>Observation</span><strong>${number(record.observation_hours, 0)}h</strong></div>
      <div><span>Reports</span><strong>${record.evaluations}</strong></div>
      <div><span>Potential band</span><strong>${number(record.potential_low, 0)}–${number(record.potential_high, 0)}</strong></div>
    </div>
    <div class="scouting-archetypes">
      <p class="eyebrow">Archetype probabilities</p>
      ${archetypes.map(([label, probability]) => `<div><span>${label}</span><i><b style="width:${probability * 100}%"></b></i><strong>${pct(probability, 0)}</strong></div>`).join("")}
    </div>
    <details class="scouting-manual">
      <summary>Commission manual observation</summary>
      <form id="scout-player-form">
        <label><span>Scout hours</span><input id="scout-player-hours" type="number" min="1" max="120" value="16" /></label>
        <button class="run-button" type="submit"><span>Scout player</span><span>→</span></button>
      </form>
      <p>More hours usually narrow the band. A new observation may also move the estimate.</p>
    </details>`;
  $("#scout-player-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Evaluating player…");
    try {
      state.franchise = await api("/api/franchise/scout-player", {
        save_id: state.franchise.save.save_id,
        player_id: record.player_id,
        hours: Number($("#scout-player-hours").value),
      });
      state.scoutingBoardSaveId = null;
      renderFranchise(state.franchise);
      await loadScoutingBoard();
      showToast(`${record.name} scouting report updated.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function renderEstablishedPlayerDossier(record) {
  const groups = record.attribute_groups || {};
  const labels = record.attribute_labels || {};
  const basis = record.overall_components || {};
  const roles = Object.entries(record.role_probabilities || {})
    .sort((a, b) => b[1] - a[1]);
  $("#scouting-dossier").innerHTML = `
    <div class="scouting-dossier-heading">
      <div>
        <p class="eyebrow">${escapeHtml(record.team)} · ${escapeHtml(record.position || "Position unknown")} · #${record.league_rank} league</p>
        <h2>${escapeHtml(record.name)}</h2>
        <span>${escapeHtml(record.primary_role)} · exact current rating · ${escapeHtml(record.source)}</span>
      </div>
      <strong>${record.overall}<small>OVR</small></strong>
    </div>
    <p class="scouting-boundary">Established NBA players do not require scouting. Current OVR blends an established 2K-scale prior with role-balanced ${escapeHtml(state.metadata?.attribute_season || "current-season")} performance, then advances the player through the age curve into the franchise season.</p>
    <div class="scouting-section-heading rating-basis-heading"><h3>Why this OVR</h3><span>${escapeHtml(basis.prior_source || "established prior")} · ${pct(basis.current_evidence_weight || 0)} current evidence</span></div>
    <div class="established-role-strip rating-basis-strip">
      <div><span>Established prior</span><strong>${number(basis.established_prior, 0)}</strong></div>
      <div><span>Current performance</span><strong>${number(basis.current_performance, 0)} <small>#${basis.current_performance_rank || "—"}</small></strong></div>
      <div><span>Age transition</span><strong>${Number(basis.age_adjustment || 0) >= 0 ? "+" : ""}${number(basis.age_adjustment, 1)}</strong></div>
      <div><span>2026–27 OVR</span><strong>${record.overall}</strong></div>
    </div>
    <div class="scouting-section-heading"><h3>Role profile</h3><span>probabilities are descriptive, not OVR weights</span></div>
    <div class="established-role-strip">
      ${roles.slice(0, 4).map(([label, probability]) => `<div><span>${escapeHtml(label)}</span><strong>${pct(probability, 0)}</strong></div>`).join("")}
    </div>
    <div class="hot-zone-section">
      <div class="scouting-section-heading"><p class="eyebrow">Spatial shooting</p><span>Hot zones compare efficiency with the league prior</span></div>
      <div class="hot-zone-grid">
        ${(record.zones || []).map((zone) => `
          <div class="hot-zone zone-${zone.status}">
            <span>${escapeHtml(zone.label)}</span>
            <strong>${zone.rating}</strong>
            <small>${pct(zone.make_probability)} · ${pct(zone.frequency)} of shots</small>
            <em>${escapeHtml(zone.status)}</em>
          </div>`).join("")}
      </div>
    </div>
    <div class="detailed-attributes">
      ${Object.entries(groups).map(([group, names]) => `
        <section>
          <div class="scouting-section-heading"><h3>${escapeHtml(group)}</h3><span>${names.length} attributes</span></div>
          <div>
            ${names.map((name) => `
              <div class="detailed-attribute-row">
                <span>${escapeHtml(labels[name] || name.replaceAll("_", " "))}</span>
                <i><b style="width:${record.attributes[name]}%"></b></i>
                <strong class="rating-${ratingTier(record.attributes[name])}">${record.attributes[name]}</strong>
              </div>`).join("")}
          </div>
        </section>`).join("")}
    </div>`;
}

function ratingTier(value) {
  if (value >= 90) return "elite";
  if (value >= 80) return "great";
  if (value >= 70) return "solid";
  if (value >= 60) return "limited";
  return "poor";
}

function capBandLabel(value) {
  const labels = {
    below_cap: "Below cap",
    over_cap: "Over cap",
    tax: "Tax team",
    first_apron: "Above first apron",
    second_apron: "Above second apron",
  };
  return labels[value] || String(value).replaceAll("_", " ");
}

function renderCapScenario(evaluation) {
  const result = $("#cap-scenario-result");
  const messages = [...evaluation.blockers, ...evaluation.explanations];
  result.className = `cap-scenario-result ${evaluation.legal ? "legal" : "blocked"}`;
  result.innerHTML = `
    <div class="cap-result-heading">
      <div>
        <span>${evaluation.legal ? "Rule check passed" : "Move blocked"}</span>
        <strong>${escapeHtml(evaluation.action_label)}</strong>
      </div>
      <em>${money(evaluation.after.team_salary)} · ${escapeHtml(capBandLabel(evaluation.after.band))}</em>
    </div>
    <div class="cap-result-metrics">
      <div><span>Before</span><strong>${money(evaluation.before.team_salary)}</strong></div>
      <div><span>After</span><strong>${money(evaluation.after.team_salary)}</strong></div>
      <div><span>Max incoming</span><strong>${evaluation.maximum_incoming_salary === null ? "Not applicable" : money(evaluation.maximum_incoming_salary)}</strong></div>
      <div><span>Hard cap</span><strong>${evaluation.hard_cap_triggered ? evaluation.hard_cap_triggered.replaceAll("_", " ") : "None triggered"}</strong></div>
    </div>
    <ul class="cap-result-messages">
      ${messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}
    </ul>
    <details class="cap-assumptions">
      <summary>Assumptions used</summary>
      <ul>${evaluation.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </details>`;
}

function renderLeagueSeason(result) {
  $("#league-season-bar").innerHTML = `
    <div>
      <p class="eyebrow">2026–27 complete · seed ${result.seed}</p>
      <h2>${result.regular_season_leader} finishes with the NBA’s best record</h2>
    </div>
    <div class="league-season-facts">
      <span>${result.games_played.toLocaleString()} games</span>
      <span>${result.box_scores_available.toLocaleString()} native box scores</span>
      <span>one detailed game / matchup</span>
      <span>${escapeHtml(result.model_name)}</span>
    </div>`;

  $("#league-standings").innerHTML = ["East", "West"]
    .map((conference) => {
      const rows = result.conference_standings[conference]
        .map(
          (row, index) => `<tr class="${index < 6 ? "playoff-lock" : index < 10 ? "play-in" : ""}">
            <td><span class="standing-rank">${index + 1}</span>${row.team}</td>
            <td>${row.wins}</td>
            <td>${row.losses}</td>
            <td>${pct(row.win_percentage, 1)}</td>
            <td>${row.point_differential > 0 ? "+" : ""}${row.point_differential}</td>
            <td>${row.home_record}</td>
            <td>${row.away_record}</td>
          </tr>`,
        )
        .join("");
      return `
        <section class="conference-card">
          <div class="conference-heading"><p class="eyebrow">${conference}ern conference</p><h2>${result.conference_standings[conference][0].team} · No. 1</h2></div>
          <div class="conference-table-wrap">
            <table class="data-table league-standing-table">
              <thead><tr><th>Team</th><th>W</th><th>L</th><th>PCT</th><th>DIFF</th><th>HOME</th><th>AWAY</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </section>`;
    })
    .join("");

  $("#league-team-filter").innerHTML = `
    <option value="">All teams</option>
    ${state.metadata.teams.map((item) => `<option value="${item.abbreviation}">${item.abbreviation}</option>`).join("")}`;
  const months = [...new Set(result.games.map((game) => game.date.slice(0, 7)))];
  $("#league-month-filter").innerHTML = `
    <option value="">All months</option>
    ${months
      .map(
        (month) =>
          `<option value="${month}">${new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(new Date(`${month}-02T12:00:00`))}</option>`,
      )
      .join("")}`;
  renderLeagueGames();
}

function filteredLeagueGames() {
  if (!state.leagueResult) return [];
  const selectedTeam = $("#league-team-filter").value;
  const selectedMonth = $("#league-month-filter").value;
  return state.leagueResult.games.filter(
    (game) =>
      (!selectedTeam ||
        game.home_team === selectedTeam ||
        game.away_team === selectedTeam) &&
      (!selectedMonth || game.date.startsWith(selectedMonth)),
  );
}

function renderLeagueGames() {
  const games = filteredLeagueGames();
  const visible = games.slice(0, state.leagueVisibleGames);
  $("#league-game-count").innerHTML = `<strong>${games.length.toLocaleString()}</strong><span>${games.length === 1 ? "game" : "games"}</span>`;
  $("#league-game-list").innerHTML = visible
    .map(
      (game) => `
        <button class="league-game-row" type="button" data-game-id="${game.game_id}">
          <span class="league-game-date">${escapeHtml(formatGameDate(game.date))}</span>
          <span class="league-game-team ${game.winner === game.away_team ? "winner" : ""}">${game.away_team}<strong>${game.away_score}</strong></span>
          <span class="league-game-team ${game.winner === game.home_team ? "winner" : ""}">${game.home_team}<strong>${game.home_score}</strong></span>
          <span class="league-game-open">Box score →</span>
        </button>`,
    )
    .join("");
  $("#league-more").classList.toggle("hidden", visible.length >= games.length);
  $$(".league-game-row", $("#league-game-list")).forEach((button) => {
    button.addEventListener("click", () => loadLeagueGame(button.dataset.gameId, button));
  });
}

async function loadLeagueGame(gameId, button) {
  $$(".league-game-row").forEach((row) => row.classList.toggle("active", row === button));
  loading($("#league-boxscore"), "Opening the box score…");
  try {
    state.leagueGame = await api("/api/league-game", {
      season_id: state.leagueResult.season_id,
      game_id: gameId,
    });
    renderLeagueBoxScore(state.leagueGame);
  } catch (error) {
    renderError($("#league-boxscore"), error.message);
  }
}

function renderLeagueBoxScore(game) {
  const rows = [game.away_team, game.home_team]
    .map((abbreviation) => {
      const players = game.box_scores
        .filter((player) => player.team === abbreviation)
        .map(
          (player) => `<tr>
            <td>${escapeHtml(player.name)}</td>
            <td>${number(player.minutes, 1)}</td>
            <td>${player.points}</td>
            <td>${player.field_goals_made}-${player.field_goals_attempted}</td>
            <td>${player.threes_made}-${player.threes_attempted}</td>
            <td>${player.free_throws_made}-${player.free_throws_attempted}</td>
            <td>${player.offensive_rebounds + player.defensive_rebounds}</td>
            <td>${player.assists}</td>
            <td>${player.steals}</td>
            <td>${player.blocks}</td>
            <td>${player.turnovers}</td>
          </tr>`,
        )
        .join("");
      return `<tr class="table-team-row"><td colspan="11">${abbreviation}</td></tr>${players}`;
    })
    .join("");
  $("#league-boxscore").innerHTML = `
    <div class="league-boxscore-header">
      <div>
        <p class="eyebrow">${escapeHtml(formatGameDate(game.date))} · final</p>
        <h2>${game.away_team} ${game.away_score} — ${game.home_team} ${game.home_score}</h2>
      </div>
      <span>${number(game.possessions, 1)} possessions</span>
    </div>
    <div class="league-boxscore-table">
      <table class="data-table">
        <thead><tr><th>Player</th><th>MIN</th><th>PTS</th><th>FG</th><th>3P</th><th>FT</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="fine-print">Native single-game possession simulation · pregame calibrated forecast ${number(game.forecast.mean_margin, 1)} expected margin retained as context.</p>`;
}

function renderRosters() {
  renderRoster("away", $("#away-team").value);
  renderRoster("home", $("#home-team").value);
}

function renderRoster(side, abbreviation) {
  const selectedTeam = team(abbreviation);
  $(`#${side}-roster-title`).textContent =
    `${abbreviation}${state.metadata.roster_season ? ` · ${state.metadata.roster_season}` : ""}`;
  $(`#${side}-roster`).innerHTML = selectedTeam.roster
    .map(
      (player) => `
        <div class="player-row" data-player-id="${player.player_id}">
          <div class="player-meta">
            <span class="player-name">${escapeHtml(player.name)}${player.profile_source === "replacement-prior" ? '<em class="prior-flag" title="No official prior-season observation; replacement-level prior is used">PRIOR</em>' : ""}${player.profile_source.startsWith("official-") ? '<em class="stat-flag" title="Profile calibrated from official prior-season statistics">STAT</em>' : ""}</span>
            <span class="player-detail">${escapeHtml(player.position)} · ${number(player.expected_minutes, 1)} MIN${player.modeled_rotation ? " · rotation" : ""}</span>
          </div>
          <label class="out-control" title="Mark ${escapeHtml(player.name)} inactive">
            <input class="out-toggle" type="checkbox" aria-label="${escapeHtml(player.name)} is out" />
          </label>
          <input class="minute-cap" type="number" min="0" max="48" step="1" placeholder="—" aria-label="${escapeHtml(player.name)} minute cap" />
        </div>`,
    )
    .join("");

  $$(".out-toggle", $(`#${side}-roster`)).forEach((input) => {
    input.addEventListener("change", () => {
      const row = input.closest(".player-row");
      row.classList.toggle("is-out", input.checked);
      $(".minute-cap", row).disabled = input.checked;
      if (input.checked) $(".minute-cap", row).value = "";
    });
  });
}

function rosterPayload(side) {
  const out = [];
  const minuteLimits = {};
  $$(".player-row", $(`#${side}-roster`)).forEach((row) => {
    const playerId = Number(row.dataset.playerId);
    if ($(".out-toggle", row).checked) out.push(playerId);
    const cap = $(".minute-cap", row).value;
    if (cap !== "") minuteLimits[playerId] = Number(cap);
  });
  return { out, minuteLimits };
}

function initializeMatchup() {
  $$(".mode-option").forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      $$(".mode-option").forEach((item) => item.classList.toggle("active", item === button));
      $("#trials-field").classList.toggle("hidden", state.mode === "single");
      $("#matchup-trials").min = state.mode === "hybrid" ? "25" : "1";
      $("#run-label").textContent =
        state.mode === "single"
          ? "Simulate game"
          : state.mode === "hybrid"
            ? "Run hybrid model"
            : "Run Monte Carlo";
    });
  });

  $("#home-team").addEventListener("change", renderRosters);
  $("#away-team").addEventListener("change", renderRosters);
  $("#swap-teams").addEventListener("click", () => {
    const home = $("#home-team").value;
    $("#home-team").value = $("#away-team").value;
    $("#away-team").value = home;
    renderRosters();
  });
  $("#reset-availability").addEventListener("click", () => {
    $$(".player-row").forEach((row) => {
      const out = $(".out-toggle", row);
      const cap = $(".minute-cap", row);
      out.checked = false;
      cap.disabled = false;
      cap.value = "";
      row.classList.remove("is-out");
    });
    showToast("Availability reset.");
  });

  $("#matchup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const home = rosterPayload("home");
    const away = rosterPayload("away");
    const payload = {
      mode: state.mode,
      home: $("#home-team").value,
      away: $("#away-team").value,
      trials: Number($("#matchup-trials").value),
      workers: 1,
      include_events: true,
      home_out: home.out,
      away_out: away.out,
      home_minute_limits: home.minuteLimits,
      away_minute_limits: away.minuteLimits,
      franchise_save_id:
        $("#matchup-use-health").checked && state.franchise
          ? state.franchise.save.save_id
          : null,
      franchise_environment_save_id:
        $("#matchup-use-environment").checked && state.franchise
          ? state.franchise.save.save_id
          : null,
    };
    if (payload.home === payload.away) {
      showToast("Choose two different teams.");
      return;
    }
    setBusy(form, true);
    loading($("#matchup-result"), state.mode === "single" ? "Playing the game…" : "Building the distribution…");
    try {
      state.matchupResult = await api("/api/matchup", payload);
      renderMatchupResult(state.matchupResult);
    } catch (error) {
      renderError($("#matchup-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function renderError(target, message) {
  target.innerHTML = `
    <div class="empty-state">
      <p class="eyebrow">Could not run</p>
      <h2>Check the setup</h2>
      <p>${escapeHtml(message)}</p>
    </div>`;
  showToast(message);
}

function renderMatchupResult(result) {
  if (result.kind === "single") {
    renderSingleGame(result);
  } else {
    renderDistribution(result);
  }
}

function renderSingleGame(result) {
  const target = $("#matchup-result");
  target.innerHTML = `
    <div class="result-header">
      <div class="result-mode"><span>Single game · seed ${result.seed}</span><span>${result.periods > 4 ? `${result.periods - 4} OT` : "Final"}</span></div>
      <div class="scoreline">
        <div class="score-team"><strong>${result.away_score}</strong><span>${result.away_team}</span></div>
        <span class="score-separator">—</span>
        <div class="score-team"><strong>${result.home_score}</strong><span>${result.home_team}</span></div>
      </div>
      <div class="winner-tag">${result.winner} wins · ${result.total} total points · ${Math.abs(result.margin)}-point margin</div>
    </div>
    <div class="result-stat-grid">
      <div class="result-stat"><span>Winner</span><strong>${result.winner}</strong></div>
      <div class="result-stat"><span>Total</span><strong>${result.total}</strong></div>
      <div class="result-stat"><span>Possession events</span><strong>${result.events.length}</strong></div>
    </div>
    <div class="result-tabs">
      <button class="result-tab active" data-tab="box">Box score</button>
      <button class="result-tab" data-tab="events">Events</button>
      <button class="result-tab" data-tab="raw">Raw JSON</button>
    </div>
    <div class="result-body"></div>`;
  bindResultTabs(target, result, "box");
}

function bindResultTabs(target, result, initial) {
  const render = (tab) => {
    $$(".result-tab", target).forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
    const body = $(".result-body", target);
    if (tab === "box") body.innerHTML = boxScoreTable(result);
    if (tab === "events") body.innerHTML = eventTable(result);
    if (tab === "distribution") body.innerHTML = distributionBody(result);
    if (tab === "raw") body.innerHTML = `<pre class="raw-output">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  };
  $$(".result-tab", target).forEach((button) => button.addEventListener("click", () => render(button.dataset.tab)));
  render(initial);
}

function boxScoreTable(result) {
  const columns = ["MIN", "PTS", "FG", "3P", "FT", "REB", "AST", "STL", "BLK", "TO", "PF"];
  const sides = [result.away_team, result.home_team];
  let rows = "";
  sides.forEach((abbreviation) => {
    rows += `<tr class="table-team-row"><td colspan="12">${abbreviation}</td></tr>`;
    result.box_scores
      .filter((player) => player.team === abbreviation)
      .sort((a, b) => b.minutes - a.minutes)
      .forEach((player) => {
        rows += `<tr>
          <td title="${escapeHtml(player.name)}">${escapeHtml(player.name)}</td>
          <td>${number(player.minutes, 1)}</td>
          <td>${player.points}</td>
          <td>${player.field_goals_made}-${player.field_goals_attempted}</td>
          <td>${player.threes_made}-${player.threes_attempted}</td>
          <td>${player.free_throws_made}-${player.free_throws_attempted}</td>
          <td>${player.offensive_rebounds + player.defensive_rebounds}</td>
          <td>${player.assists}</td>
          <td>${player.steals}</td>
          <td>${player.blocks}</td>
          <td>${player.turnovers}</td>
          <td>${player.personal_fouls}</td>
        </tr>`;
      });
  });
  return `<table class="data-table"><thead><tr><th>Player</th>${columns.map((item) => `<th>${item}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
}

function clock(milliseconds) {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function playerName(id) {
  if (!id) return "—";
  for (const item of state.metadata.teams) {
    const player = item.roster.find((candidate) => candidate.player_id === id);
    if (player) return player.name;
  }
  return `#${id}`;
}

function eventTable(result) {
  const rows = result.events
    .filter((event) => !["clock_advanced", "possession_started"].includes(event.event_type))
    .map(
      (event) => `<tr>
        <td>${event.sequence}</td>
        <td>Q${event.period} · ${clock(event.period_clock_ms)}</td>
        <td>${escapeHtml(event.event_type.replaceAll("_", " "))}</td>
        <td>${event.team || "—"}</td>
        <td>${escapeHtml(playerName(event.player_id))}</td>
      </tr>`,
    )
    .join("");
  return `<table class="data-table"><thead><tr><th>#</th><th>Clock</th><th>Event</th><th>Team</th><th>Player</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderDistribution(result) {
  const home = result.home_team;
  const away = result.away_team;
  const homeWin = result.home_win_probability;
  const raw = result.kind === "monte_carlo";
  const target = $("#matchup-result");
  target.innerHTML = `
    <div class="result-header">
      <div class="result-mode"><span>${raw ? "Monte Carlo" : "Hybrid reconciliation"} · ${result.trials} trials</span><span>Seed ${result.seed}</span></div>
      <div class="probability-wrap">
        <div class="probability-row"><span>${away} ${pct(1 - homeWin)}</span><strong>${pct(homeWin)}</strong><span>${home} win</span></div>
        <div class="probability-track"><div class="probability-fill" style="width:${homeWin * 100}%"></div></div>
      </div>
    </div>
    <div class="result-stat-grid">
      <div class="result-stat"><span>Mean margin</span><strong>${Number(result.mean_margin) >= 0 ? "+" : ""}${number(result.mean_margin, 1)}</strong></div>
      <div class="result-stat"><span>Mean total</span><strong>${number(result.mean_total, 1)}</strong></div>
      <div class="result-stat"><span>${raw ? "Overtime" : "Effective sample"}</span><strong>${raw ? pct(result.overtime_probability) : number(result.effective_sample_size, 1)}</strong></div>
    </div>
    <div class="result-tabs">
      <button class="result-tab active" data-tab="distribution">Distribution</button>
      <button class="result-tab" data-tab="raw">Raw JSON</button>
    </div>
    <div class="result-body"></div>`;
  bindResultTabs(target, result, "distribution");
}

function distributionBody(result) {
  const margin = result.margin_quantiles;
  const total = result.total_quantiles;
  const labels = { "0.05": "5th pct", "0.25": "25th pct", "0.50": "Median", "0.75": "75th pct", "0.95": "95th pct" };
  const values = Object.values(total).map(Number);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const rows = Object.keys(labels)
    .map((key) => {
      const width = 12 + ((Number(total[key]) - min) / Math.max(max - min, 1)) * 88;
      return `<div class="quantile-item"><span>${labels[key]}</span><div class="quantile-bar"><span style="width:${width}%"></span></div><strong>${total[key]}</strong></div>`;
    })
    .join("");
  return `
    <p class="eyebrow">Total-points interval</p>
    <div class="quantile-list">${rows}</div>
    <div class="result-stat-grid" style="margin:24px -20px -22px">
      <div class="result-stat"><span>5% margin</span><strong>${margin["0.05"]}</strong></div>
      <div class="result-stat"><span>Median margin</span><strong>${margin["0.50"]}</strong></div>
      <div class="result-stat"><span>95% margin</span><strong>${margin["0.95"]}</strong></div>
    </div>`;
}

function initializeCompetitions() {
  $("#season-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const teams = $$("#season-team-grid input:checked").map((input) => input.value);
    setBusy(form, true, "Simulating season…");
    loading($("#competition-result"), "Playing the schedule…");
    try {
      state.competitionResult = await api("/api/season", {
        teams,
        repeats: Number($("#season-repeats").value),
        start_date: $("#season-date").value,
        include_games: true,
      });
      renderSeason(state.competitionResult);
    } catch (error) {
      renderError($("#competition-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#series-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if ($("#higher-seed").value === $("#lower-seed").value) {
      showToast("Choose two different teams.");
      return;
    }
    setBusy(form, true, "Playing series…");
    loading($("#competition-result"), "Playing the series…");
    try {
      state.competitionResult = await api("/api/series", {
        higher_seed: $("#higher-seed").value,
        lower_seed: $("#lower-seed").value,
        best_of: Number($("#best-of").value),
      });
      renderSeries(state.competitionResult);
    } catch (error) {
      renderError($("#competition-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function renderSeason(result) {
  const rows = result.standings
    .map(
      (row, index) => `<tr>
        <td>${index + 1}. ${row.team}</td>
        <td>${row.wins}</td><td>${row.losses}</td>
        <td>${pct(row.win_percentage, 1)}</td>
        <td>${row.point_differential > 0 ? "+" : ""}${row.point_differential}</td>
        <td>${row.points_for}</td><td>${row.points_against}</td>
      </tr>`,
    )
    .join("");
  $("#competition-result").innerHTML = `
    <div class="competition-header">
      <p class="eyebrow">Season complete · seed ${result.seed}</p>
      <h2>${result.games_played} games played</h2>
    </div>
    <div class="standings-wrap">
      <table class="data-table standings-table">
        <thead><tr><th>Team</th><th>W</th><th>L</th><th>Win %</th><th>Diff</th><th>PF</th><th>PA</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderSeries(result) {
  const games = result.games
    .map(
      (game, index) => `<div class="series-game">
        <span>GAME ${index + 1} · ${game.periods > 4 ? "OT" : "FINAL"}</span>
        <strong>${game.away_team} ${game.away_score} · ${game.home_team} ${game.home_score}</strong>
      </div>`,
    )
    .join("");
  $("#competition-result").innerHTML = `
    <div class="competition-header">
      <p class="eyebrow">${result.games.length}-game series · seed ${result.seed}</p>
      <h2>${result.winner} advances, ${result.higher_seed_wins}–${result.lower_seed_wins}</h2>
    </div>
    <div class="series-wrap"><div class="series-ledger">${games}</div></div>`;
}

function initializeHealth() {
  $("#validation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Running audit…");
    loading($("#health-result"), "Simulating league matchups…");
    try {
      state.healthResult = await api("/api/validate", {
        games_per_matchup: Number($("#validation-games").value),
        seed: Number($("#validation-seed").value),
      });
      renderHealth(state.healthResult);
    } catch (error) {
      renderError($("#health-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#backtest-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Running backtest…");
    loading($("#health-result"), "Walking through historical games…");
    try {
      state.healthResult = await api("/api/backtest", {
        evaluation_start: $("#backtest-start").value,
        evaluation_end: $("#backtest-end").value,
        bootstrap_samples: 2000,
        seed: 2026,
      });
      renderBacktest(state.healthResult);
    } catch (error) {
      renderError($("#health-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function renderHealth(result) {
  const rows = result.metrics
    .map(
      (metric) => `<tr>
        <td>${escapeHtml(metric.name.replaceAll("_", " "))}</td>
        <td>${number(metric.target, 2)}</td>
        <td>${number(metric.simulated, 2)}</td>
        <td><span class="metric-error">${pct(metric.absolute_percentage_error, 2)}</span></td>
      </tr>`,
    )
    .join("");
  const profileLabel = result.profile_roster_season
    ? `${result.profile_roster_season} roster · ${result.profile_stat_season || "prior"} stats`
    : `${result.season} profiles`;
  $("#health-result").innerHTML = `
    <div class="health-header">
      <p class="eyebrow">${escapeHtml(profileLabel)} · ${result.simulated_games} games · ${result.simulated_team_games} team-games</p>
      <h2>${pct(result.mean_absolute_percentage_error, 2)} mean error</h2>
      <span class="gate-pill ${result.gate.passed ? "" : "fail"}">${result.gate.passed ? "● Gate passed" : "● Gate failed"}</span>
    </div>
    <div class="health-metrics">
      <table class="data-table">
        <thead><tr><th>Statistic</th><th>Target</th><th>Simulated</th><th>Error</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderBacktest(result) {
  const rows = Object.entries(result.metrics)
    .map(
      ([name, metric]) => `<tr>
        <td>${escapeHtml(name)}</td>
        <td>${number(metric.log_loss, 4)}</td>
        <td>${number(metric.brier_score, 4)}</td>
        <td>${number(metric.margin_mae, 2)}</td>
        <td>${number(metric.total_mae, 2)}</td>
      </tr>`,
    )
    .join("");
  const comparisonCopy = result.comparisons
    .map((comparison) => {
      const delta = comparison.candidate_minus_baseline_log_loss;
      return `${comparison.baseline}: ${delta.observed_difference > 0 ? "+" : ""}${number(delta.observed_difference, 4)} log loss`;
    })
    .join(" · ");
  const failedComparisons = result.comparisons.filter(
    (comparison) =>
      comparison.candidate_minus_baseline_log_loss.upper_95 >= 0 ||
      comparison.candidate_minus_baseline_margin_absolute_error.upper_95 >= 0,
  );
  const gateExplanation = result.promotion_passed
    ? "The candidate beat every baseline on both required metrics with 95% paired-bootstrap confidence."
    : `The point estimate is competitive, but ${failedComparisons.length} baseline comparison${failedComparisons.length === 1 ? "" : "s"} did not clear both uncertainty bounds. The production gate therefore stays closed.`;
  $("#health-result").innerHTML = `
    <div class="health-header">
      <p class="eyebrow">${result.games.toLocaleString()} unseen games · ${result.evaluation_start} to ${result.evaluation_end}</p>
      <h2>${result.promotion_passed ? "Candidate promoted" : "Promotion withheld"}</h2>
      <span class="gate-pill ${result.promotion_passed ? "" : "fail"}">${result.promotion_passed ? "● All baselines beaten" : "● Baseline gate not cleared"}</span>
    </div>
    <div class="health-metrics">
      <table class="data-table">
        <thead><tr><th>Model</th><th>Log loss</th><th>Brier</th><th>Margin MAE</th><th>Total MAE</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="backtest-explainer"><strong>Why ${result.promotion_passed ? "promoted" : "withheld"}?</strong><span>${escapeHtml(gateExplanation)}</span></div>
      <p class="fine-print" style="margin-top:18px">${escapeHtml(comparisonCopy)}</p>
    </div>`;
}

async function initialize() {
  initializeGuide();
  initializeNavigation();
  initializeMatchup();
  initializeGameDay();
  initializeLeague();
  initializeFranchise();
  initializeCompetitions();
  initializeHealth();
  try {
    const response = await fetch("/api/metadata");
    if (!response.ok) throw new Error("Could not load simulator data");
    state.metadata = await response.json();
    initializeMetadata();
    resumeLeagueSimulation();
  } catch (error) {
    showToast(error.message);
    $("#data-season").textContent = "Data unavailable";
  }
}

document.addEventListener("DOMContentLoaded", initialize);
