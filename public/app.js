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
  franchiseSeasonJobId: null,
  franchiseSeasonPollTimer: null,
  franchiseSeasonBaseGames: 0,
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
  tradeFinder: null,
  contractEvaluation: null,
  freeAgentEvaluation: null,
  competitionResult: null,
  healthResult: null,
  playtestAudit: null,
};

const LEAGUE_JOB_STORAGE_KEY = "nba-sim-active-league-job";
const FRANCHISE_SEASON_JOB_STORAGE_KEY = "nba-sim-active-franchise-season-job";
const TUTORIAL_STORAGE_KEY = "nba-sim-guided-tutorial-v1-seen";
const TUTORIAL_COOKIE_KEY = "nba_sim_guided_tutorial_v1";
let tutorialStep = 0;
let tutorialPreviousFocus = null;
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
  gm: {
    title: "Front Office AI",
    body: `
      <p class="guide-lead">Every team has a persistent organizational plan. It is not a hidden difficulty modifier: the same saved priorities and constraints are visible here and consumed by trade valuation and CPU negotiation.</p>
      <ol class="guide-steps">
        <li><strong>Direction</strong><span>Contend, compete, retool, and rebuild describe the club's current competitive window. The automatic review uses roster strength, actual record, recent form, age, payroll, health, depth, and picks.</span></li>
        <li><strong>Ownership pressure</strong><span>Market size, spending willingness, patience, and job security determine how long a plan can survive and how aggressively a front office acts.</span></li>
        <li><strong>Asset posture</strong><span>Protected core, trade block, and positional needs flow directly into trade premiums, offer ranking, and counteroffers.</span></li>
        <li><strong>Automatic reviews</strong><span>Plans are reassessed at season checkpoints, weekly market advances, completed trades, and after the postseason. A patient organization will not reverse course on a tiny sample.</span></li>
      </ol>
      <div class="guide-note"><strong>Advanced controls</strong><span>Automatic is the recommended experience. Switching your team to a manual mandate freezes its direction and priority weights while the other 29 offices continue to adapt.</span></div>`,
  },
  playtest: {
    title: "Playtest & settings",
    body: `
      <p class="guide-lead">This is the front door for a new league and the final check before you share one. Settings change how much is explained and delegated—not the basketball engine.</p>
      <ol class="guide-steps">
        <li><strong>Pick a control preset</strong><span>Guided delegates specialist work, Balanced asks you to approve important choices, and Full control exposes manual staff settings.</span></li>
        <li><strong>Pick negotiation difficulty</strong><span>Difficulty changes information and how tolerant CPU negotiators are. It never boosts or lowers ratings, injuries, game probabilities, or seeds.</span></li>
        <li><strong>Create a safety branch</strong><span>Copy the exact revision before a consequential experiment. The original timeline remains untouched.</span></li>
        <li><strong>Run the readiness audit</strong><span>The audit verifies the save ledger, league structure, schedule, rotations, ratings, health, contracts, CBA fixtures, and completed box scores.</span></li>
        <li><strong>Copy the tester report</strong><span>Include it with feedback so the exact branch, revision, and seed can be reproduced.</span></li>
      </ol>
      <div class="guide-note"><strong>Recommended first test</strong><span>Choose Guided + Pro, simulate one week, inspect one box score, try Trade Finder on a safety branch, then run the audit again.</span></div>`,
  },
  season_hub: {
    title: "Season Hub",
    body: `
      <p class="guide-lead">Season Hub turns the simulator into one persistent basketball history. It uses an NBA-balanced 1,230-game calendar: 82 games per team, 41 home and 41 away.</p>
      <ol class="guide-steps">
        <li><strong>Choose how far to continue</strong><span>Advance to your next game for a hands-on franchise, one league day for maximum control, or seven/thirty days when you want the front office to move faster.</span></li>
        <li><strong>Let the league play</strong><span>Every matchup is one untouched possession-level result. The saved rotation, health plan and coaching environment are applied before tipoff.</span></li>
        <li><strong>Review the history</strong><span>Open any completed team game for its native box score. Standings, point differential and player per-game leaders are recalculated from saved results.</span></li>
        <li><strong>Reach the postseason</strong><span>After all 1,230 games, the top ten in each conference enter the 7–10 play-in and seeded best-of-seven bracket. The champion and awards persist into the offseason.</span></li>
      </ol>
      <div class="guide-note"><strong>Why results can look surprising</strong><span>A franchise season preserves night-to-night randomness. It does not replace each game with the average of hundreds of trials, so upsets and extreme performances become part of the saved league history.</span></div>`,
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
      <p class="guide-lead">Health state is persistent and game-aware. The league automatically generates and manages injuries while advanced users can still override any medical scenario.</p>
      <ol class="guide-steps">
        <li><strong>Set availability</strong><span>Available, managed, questionable, doubtful, and out are distinct states. Doubtful and out remove the player from simulations; managed restrictions cap minutes.</span></li>
        <li><strong>Record sessions</strong><span>Minutes multiplied by intensity create a transparent external-load unit. Games, practices, conditioning, and rehabilitation use the same auditable scale.</span></li>
        <li><strong>Advance time</strong><span>Acute load, chronic load, and fatigue recover at different rates. Simulated injuries move through out, return-to-play, and available automatically; your manual scenarios remain manual.</span></li>
        <li><strong>Injuries from games</strong><span>Every appearance has a seeded risk derived from minutes, age, load spikes, fatigue, managed returns, and prior injury history. The result is recorded after the final and changes future availability without altering the possession RNG of the game that produced it.</span></li>
        <li><strong>Use it in games</strong><span>Keep “Use Franchise health” selected in Matchup Lab to apply saved absences and minute caps.</span></li>
      </ol>
      <div class="guide-section"><h3>Load concern is not a displayed injury probability</h3><p>The index is one input to the occurrence model alongside exposure, age and history. It cannot diagnose a real injury or promise that rest prevents one.</p></div>
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
        <li><strong>Generate the class</strong><span>Creates 75 fictional prospects from a reproducible class seed. Public consensus is noisy; latent skill, durability, development variance, and ceiling remain hidden.</span></li>
        <li><strong>Build information</strong><span>Manual scouting narrows Bayesian skill and potential bands. The combine verifies physical measurements and adds the same standardized observation to every prospect.</span></li>
        <li><strong>Set your board</strong><span>Public rank and your private rank are separate. Move a prospect to the top whenever your evaluation differs from consensus.</span></li>
        <li><strong>Run the lottery</strong><span>The 3-2-1 format draws all 16 lottery positions. Until season standings are committed, the preliminary order uses current roster strength as a transparent projection.</span></li>
        <li><strong>Draft</strong><span>CPU teams combine their own scouting quality, positional need, risk tolerance, and noisy information. When the draft ends, 60 rookie contracts and 15 undrafted free agents become permanent league records.</span></li>
      </ol>
      <div class="guide-note"><strong>Read a range correctly</strong><span>The center is your department’s present estimate—not hidden truth. An 80% band means outcomes outside it remain possible.</span></div>`,
  },
  trades: {
    title: "Trade Finder & negotiation",
    body: `
      <p class="guide-lead">Start with Trade Finder. It calls the league, removes illegal and rejected constructions, and ranks only offers the other front office is actually prepared to complete.</p>
      <ol class="guide-steps">
        <li><strong>Shop or acquire</strong><span>Shop one asset or select a package of up to six players and picks across all 29 teams. Target packages must belong to one current owner.</span></li>
        <li><strong>Choose the goal</strong><span>Best deal balances value. Win now favors present OVR, youth favors age and upside, cap relief lowers incoming salary, and draft capital prioritizes picks.</span></li>
        <li><strong>Read why it works</strong><span>Every offer shows the partner's competitive window, needs, core-player premium, salary structure and the concrete factors behind acceptance.</span></li>
        <li><strong>Negotiate</strong><span>Open an offer in the advanced machine, edit it, or request the other team’s minimum legal two-team counteroffer. Add a third team when salary, roster, or asset routing needs another participant.</span></li>
        <li><strong>Customize the universe</strong><span>Every encoded rule has its own saved switch. Disabled rules create an explicit house-rule warning instead of silently changing legality.</span></li>
      </ol>
      <div class="guide-section"><h3>The same AI runs the league</h3><p>CPU-to-CPU deals and user negotiations share the same front-office profiles, bilateral acceptance, asset ownership and CBA evaluator. Your team is excluded from autonomous league trades.</p></div>
      <div class="guide-section"><h3>Why three role players do not automatically buy a superstar</h3><p>The engine values packages together. Elite scarcity is nonlinear, while second, third, and fourth incoming players receive diminishing consolidation weight. Contract control, projected pick slot, protection, age curve, injury status, roster need, and front-office timeline all change the answer.</p></div>
      <div class="guide-section"><h3>Injured players</h3><p>NBA rules do not impose a general ban on trading an injured player. The injured-player switch is therefore an optional house rule and starts off.</p></div>
      <div class="guide-note"><strong>Stepien Rule</strong><span>A team cannot leave itself without a first-round selection in consecutive future drafts. The evaluator checks the post-trade ownership ledger, not merely the picks visible in one offer.</span></div>`,
  },
  roster: {
    title: "Roster & Rotation",
    body: `
      <p class="guide-lead">One persistent depth chart connects front-office decisions to the court. Staff automation handles the complexity by default; advanced controls remain available player by player.</p>
      <ol class="guide-steps">
        <li><strong>Choose delegation</strong><span>Staff handles it updates automatically after health, workload, coaching and calendar changes. Staff recommends shows issues without taking control. Manual preserves your choices.</span></li>
        <li><strong>Choose direction</strong><span>Balanced blends present ability and upside. Win now favors current impact. Develop youth creates more opportunity for younger high-upside players.</span></li>
        <li><strong>Build and review</strong><span>The optimizer selects five starters and allocates exactly 240 minutes subject to availability, limits, workload and rotation depth.</span></li>
        <li><strong>Override if needed</strong><span>Edit minutes, role, designation, starter status and role promises, then save. Matchup Lab uses the saved plan whenever Franchise rotation & health is enabled.</span></li>
      </ol>
      <div class="guide-section"><h3>Assignments</h3><p>Standard and two-way players can enter the game plan. G League and inactive players receive zero minutes. Two-way rosters are capped at three and their NBA active-game limit is shown in the interface.</p></div>
      <div class="guide-note"><strong>Medical boundary</strong><span>Readiness and load concern guide playing-time decisions; they are planning signals, not diagnoses or promises that an injury will or will not occur.</span></div>`,
  },
  contracts: {
    title: "Contracts & Free Agency",
    body: `
      <p class="guide-lead">The default view answers three questions: what are you committed to, what needs a decision, and whom can you afford? Every negotiation is saved only when you execute it.</p>
      <ol class="guide-steps">
        <li><strong>Read the five-year horizon</strong><span>Payroll is compared with projected cap and apron lines so one signing cannot hide a future squeeze.</span></li>
        <li><strong>Follow the recommendations</strong><span>Options, expiring contracts and roster limits surface first. You can ignore the rest until it matters.</span></li>
        <li><strong>Negotiate</strong><span>Players weigh salary, years, promised role, team quality, age and upside. A legal offer can still be rejected.</span></li>
        <li><strong>Run the CPU market</strong><span>Other teams perform a seeded roster review and can place marginal players into the available pool without touching your roster.</span></li>
      </ol>
      <div class="guide-section"><h3>Bird rights and exceptions</h3><p>Cap room is checked first. Over-cap teams then need a valid exception path. Bird, Early Bird, Non-Bird, mid-level and minimum mechanisms remain distinct.</p></div>
      <div class="guide-note"><strong>Data honesty</strong><span>The 2026–27 cap, tax and apron lines are official. Existing salaries and contract lengths are clearly labeled modeled until a licensed contract feed replaces them.</span></div>`,
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

const TUTORIAL_STEPS = [
  {
    label: "Welcome",
    kicker: "You are the general manager now",
    title: "Running the Suns is easier than it looks.",
    copy: "You make the fun choices. Your staff can handle rotations, scouting, health, and front-office busywork until you decide you want more control.",
    body: `
      <div class="tutorial-hero-visual">
        <span class="tutorial-sun" aria-hidden="true">☀</span>
        <div><strong>PHOENIX SUNS</strong><small>Your example team for this tour</small></div>
      </div>
      <div class="tutorial-rule"><strong>The only rule you need right now</strong><span>If you are unsure, leave staff automation on and press the gold button.</span></div>`,
  },
  {
    label: "The map",
    kicker: "Six doors, six simple questions",
    title: "Go to the screen that matches your question.",
    copy: "You never need to understand every workspace at once.",
    body: `
      <div class="tutorial-map-grid">
        <div><b>1</b><strong>Matchup Lab</strong><small>What happens in one game?</small></div>
        <div><b>2</b><strong>Game Day</strong><small>Who plays today, and who is out?</small></div>
        <div><b>3</b><strong>League Sim</strong><small>What does one entire alternate season look like?</small></div>
        <div class="featured"><b>4</b><strong>Franchise</strong><small>How do I run and rebuild the Suns?</small></div>
        <div><b>5</b><strong>Competitions</strong><small>Who wins a series or mini-league?</small></div>
        <div><b>6</b><strong>Model Health</strong><small>Why should I trust the model?</small></div>
      </div>
      <div class="tutorial-rule"><strong>Your home base</strong><span>For team management, live in Franchise. The other screens are specialist tools.</span></div>`,
  },
  {
    label: "Create a league",
    kicker: "Your first three clicks",
    title: "Choose Phoenix. Name the world. Start.",
    copy: "A Franchise is a saved basketball universe. It remembers every game, trade, injury, contract, pick, and decision.",
    body: `
      <ol class="tutorial-big-steps">
        <li><span>1</span><div><strong>Open Franchise</strong><small>Use the top navigation.</small></div></li>
        <li><span>2</span><div><strong>Choose PHX</strong><small>This makes you the Suns' decision-maker. The other 29 teams run themselves.</small></div></li>
        <li><span>3</span><div><strong>Create league</strong><small>The game builds the complete NBA and autosaves it locally.</small></div></li>
      </ol>
      <div class="tutorial-rule safe"><strong>You cannot lose your work</strong><span>Every real decision is autosaved. Branches let you try a different future without deleting the original.</span></div>`,
  },
  {
    label: "Your daily loop",
    kicker: "The normal way to play",
    title: "Read. Decide. Simulate. Repeat.",
    copy: "Most days you only need Season Hub and the staff recommendations.",
    body: `
      <div class="tutorial-loop">
        <div><span>1</span><strong>READ</strong><small>Check your record, next opponent, schedule, and alerts.</small></div><i>→</i>
        <div><span>2</span><strong>DECIDE</strong><small>Accept a recommendation or change something you care about.</small></div><i>→</i>
        <div><span>3</span><strong>SIM</strong><small>Play to your next game, one day, one week, or thirty days.</small></div>
      </div>
      <div class="tutorial-rule"><strong>Best beginner pace</strong><span>Use “Next team game.” You see every Suns result while the rest of the league keeps moving.</span></div>`,
  },
  {
    label: "Players & staff",
    kicker: "Let the experts handle the knobs",
    title: "The staff builds a legal rotation for you.",
    copy: "Guided mode automatically responds to ability, role, fatigue, injury status, coaching preferences, and player development.",
    body: `
      <div class="tutorial-staff-grid">
        <div><span>✓</span><strong>Roster & Rotation</strong><small>Five starters and exactly 240 minutes. Out players sit automatically.</small></div>
        <div><span>✓</span><strong>Health & Workload</strong><small>Availability and minute limits feed directly into games.</small></div>
        <div><span>✓</span><strong>Chemistry & Coaching</strong><small>Small, visible tactical effects—never a magical hidden boost.</small></div>
        <div><span>✓</span><strong>Player Development</strong><small>Age, workload, potential, prime, decline, and uncertainty shape careers.</small></div>
      </div>
      <div class="tutorial-rule"><strong>When should you intervene?</strong><span>Only when you disagree. Switch one area to Recommend or Manual; everything else can stay automatic.</span></div>`,
  },
  {
    label: "Build the team",
    kicker: "Trades and contracts without the headache",
    title: "Ask the league before building a trade by hand.",
    copy: "Trade Finder searches all 29 teams, removes illegal offers, and shows deals the other front office would actually accept.",
    body: `
      <div class="tutorial-decision-path">
        <div><b>A</b><strong>Want to move a Sun?</strong><small>Choose “Shop my package,” select one or several assets, and run Trade Finder.</small></div>
        <div><b>B</b><strong>Want someone else?</strong><small>Choose “Acquire an asset.” The AI finds the minimum acceptable construction.</small></div>
        <div><b>C</b><strong>Worried about money?</strong><small>Contracts shows five years. Cap & CBA explains the exact rule blocking a move.</small></div>
      </div>
      <div class="tutorial-rule"><strong>Three-team trades</strong><span>Open the advanced trade machine, add a third team, select assets, and choose the destination shown under every selected player or pick.</span></div>
      <div class="tutorial-rule warning"><strong>Never judge only by OVR</strong><span>Age, role, fit, salary, picks, team direction, protections, aprons, and future flexibility all matter to trade AI.</span></div>`,
  },
  {
    label: "Find the future",
    kicker: "Scouting and the draft",
    title: "NBA players are known. Prospects are guesses.",
    copy: "Current professionals show exact game ratings because the league has evidence. Draft prospects keep uncertainty because nobody truly knows their NBA future.",
    body: `
      <div class="tutorial-compare">
        <div><p class="eyebrow">Established player</p><strong>84 OVR</strong><small>Detailed attributes, shot zones, hot zones, age curve, and role are visible.</small></div>
        <div><p class="eyebrow">Draft prospect</p><strong>72–86</strong><small>Scouting narrows the belief. It never reveals hidden truth before the career happens.</small></div>
      </div>
      <ol class="tutorial-mini-list"><li>Let automatic scouting spend weekly hours.</li><li>Use your private board when you disagree with public rank.</li><li>Run the lottery, simulate to your pick, then choose.</li></ol>
      <div class="tutorial-rule"><strong>Simple beginner strategy</strong><span>Keep automatic scouting on and draft from the top of your private board unless team fit clearly matters more.</span></div>`,
  },
  {
    label: "Understand results",
    kicker: "Random does not mean inaccurate",
    title: "One simulated game is one possible night.",
    copy: "A great team can lose. A role player can get hot. That is the point of a realized season—not a bug.",
    body: `
      <div class="tutorial-results-grid">
        <div><strong>Single game</strong><small>One story with a play-by-play and real box score.</small></div>
        <div><strong>Hybrid forecast</strong><small>Use this for the best win probability and result range.</small></div>
        <div><strong>Franchise season</strong><small>Every matchup happens once, so surprises become permanent history.</small></div>
      </div>
      <div class="tutorial-seed"><span aria-hidden="true">✦</span><div><strong>The seed is the receipt</strong><small>Every run gets a fresh seed. Keep it to reproduce the exact same random outcome.</small></div></div>`,
  },
  {
    label: "Play safely",
    kicker: "Experiment without fear",
    title: "Branch first. Then do something wild.",
    copy: "A branch is an independent copy of this exact moment. Trade the core on one branch, keep it on another, and compare both futures.",
    body: `
      <div class="tutorial-branch-visual"><div><strong>MAIN</strong><small>Suns core stays together</small></div><i>→</i><div><strong>BRANCH A</strong><small>Deadline blockbuster</small></div><i>↘</i><div><strong>BRANCH B</strong><small>Build through the draft</small></div></div>
      <div class="tutorial-difficulty">
        <div><strong>Rookie</strong><small>More explanation, friendlier negotiation.</small></div>
        <div class="active"><strong>Pro</strong><small>Complete information, normal negotiation.</small></div>
        <div><strong>Expert</strong><small>Information fog, tougher negotiation.</small></div>
      </div>
      <div class="tutorial-rule safe"><strong>Difficulty never cheats</strong><span>It cannot change player ratings, possession probabilities, injuries, schedules, or seeds.</span></div>`,
  },
  {
    label: "Ready",
    kicker: "Your Phoenix day-one checklist",
    title: "You are ready to run the Suns.",
    copy: "Start simple. The deep controls will still be there when you want them.",
    body: `
      <div class="tutorial-final-checklist">
        <div><span>1</span><strong>Create PHX with Guided + Pro.</strong></div>
        <div><span>2</span><strong>Open Season Hub and play to the next Suns game.</strong></div>
        <div><span>3</span><strong>Read the box score and staff recommendations.</strong></div>
        <div><span>4</span><strong>Create a safety branch before your first trade.</strong></div>
        <div><span>5</span><strong>Use Trade Finder, not guesswork.</strong></div>
      </div>
      <div class="tutorial-rule"><strong>If you ever get lost</strong><span>Open Handbook for the current feature, or replay Tutorial from the top-right corner. Playtest & Settings also checks whether the whole league is healthy.</span></div>`,
    final: true,
  },
];

function tutorialHasBeenSeen() {
  try {
    if (localStorage.getItem(TUTORIAL_STORAGE_KEY) === "seen") return true;
  } catch (_error) {
    // Cookie fallback below covers browsers that disable local storage.
  }
  return document.cookie
    .split("; ")
    .some((item) => item === `${TUTORIAL_COOKIE_KEY}=seen`);
}

function rememberTutorial() {
  try {
    localStorage.setItem(TUTORIAL_STORAGE_KEY, "seen");
  } catch (_error) {
    // A same-site cookie provides a second, deliberately non-account-based memory.
  }
  document.cookie = `${TUTORIAL_COOKIE_KEY}=seen; Max-Age=31536000; Path=/; SameSite=Lax`;
}

function renderTutorialStep() {
  const steps = interfaceMode === 'normal' ? NORMAL_TUTORIAL_STEPS : TUTORIAL_STEPS;
  const step = steps[tutorialStep];
  const count = steps.length;
  const progress = ((tutorialStep + 1) / count) * 100;
  $("#tutorial-step-label").textContent = `Step ${tutorialStep + 1} of ${count}`;
  $("#tutorial-progress-label").textContent = step.label;
  $("#tutorial-progress-bar").style.width = `${progress}%`;
  const progressbar = $(".tutorial-progress");
  progressbar.setAttribute("aria-valuemax", String(count));
  progressbar.setAttribute("aria-valuenow", String(tutorialStep + 1));
  $("#tutorial-content").innerHTML = `
    <div class="tutorial-copy">
      <p class="eyebrow">${step.kicker}</p>
      <h2 id="tutorial-title">${step.title}</h2>
      <p id="tutorial-description">${step.copy}</p>
    </div>
    <div class="tutorial-lesson">${step.body}</div>`;
  $("#tutorial-back").disabled = tutorialStep === 0;
  $("#tutorial-skip").textContent = tutorialStep === count - 1
    ? "Close and explore myself"
    : "Skip — I can replay this later";
  const nextLabel = $("span", $("#tutorial-next"));
  nextLabel.textContent = step.final ? "Set up the Phoenix Suns" : "Next";
  $("#tutorial-content").scrollTop = 0;
}

function openTutorial({ force = false } = {}) {
  if (!force && tutorialHasBeenSeen()) return;
  rememberTutorial();
  tutorialPreviousFocus = document.activeElement;
  tutorialStep = 0;
  renderTutorialStep();
  const overlay = $("#tutorial-overlay");
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("tutorial-open");
  window.setTimeout(() => $("#tutorial-close").focus(), 0);
}

function closeTutorial() {
  const overlay = $("#tutorial-overlay");
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("tutorial-open");
  if (tutorialPreviousFocus && tutorialPreviousFocus.isConnected) {
    tutorialPreviousFocus.focus();
  }
}

function preparePhoenixFranchise() {
  closeTutorial();
  const franchiseTab = $('.nav-item[data-view="franchise"]');
  if (franchiseTab) franchiseTab.click();
  if (state.franchise && $("#new-franchise")) $("#new-franchise").click();
  $("#franchise-team").value = "PHX";
  $("#franchise-name").value = "Phoenix Suns Dynasty";
  window.setTimeout(() => $("#franchise-name").focus(), 0);
  showToast("Phoenix is selected. Name the league however you like, then create it.");
}

function initializeTutorial() {
  $("#tutorial-replay").addEventListener("click", () => openTutorial({ force: true }));
  $("#tutorial-close").addEventListener("click", closeTutorial);
  $("#tutorial-skip").addEventListener("click", closeTutorial);
  $("#tutorial-back").addEventListener("click", () => {
    if (tutorialStep === 0) return;
    tutorialStep -= 1;
    renderTutorialStep();
  });
  $("#tutorial-next").addEventListener("click", () => {
    if (tutorialStep === (interfaceMode === 'normal' ? NORMAL_TUTORIAL_STEPS : TUTORIAL_STEPS).length - 1) {
      preparePhoenixFranchise();
      return;
    }
    tutorialStep += 1;
    renderTutorialStep();
  });
  document.addEventListener("keydown", (event) => {
    const overlay = $("#tutorial-overlay");
    if (overlay.classList.contains("hidden")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeTutorial();
      return;
    }
    if (event.key === "ArrowRight" && event.target.tagName !== "INPUT") {
      event.preventDefault();
      $("#tutorial-next").click();
      return;
    }
    if (event.key === "ArrowLeft" && event.target.tagName !== "INPUT") {
      event.preventDefault();
      $("#tutorial-back").click();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = $$('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])', overlay);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

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
    const message = data.error || "Request failed";
    throw new Error(data.guidance ? `${message} ${data.guidance}` : message);
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
  const labelNode = $("span", button) || button;
  button.disabled = busy;
  if (busy) {
    button.dataset.label = labelNode.textContent;
    labelNode.textContent = label;
  } else if (button.dataset.label) {
    labelNode.textContent = button.dataset.label;
  }
}

function loading(target, copy) {
  target.innerHTML = `<div class="loading-block">${escapeHtml(copy)}</div>`;
}

function initializeNavigation() {
  const buttons = $$(".nav-item");
  const activate = (button) => {
    buttons.forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
      item.tabIndex = active ? 0 : -1;
    });
    $$(".view").forEach((view) => {
      view.classList.toggle("active", view.id === `view-${button.dataset.view}`);
    });
  };
  buttons.forEach((button, index) => {
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(button.classList.contains("active")));
    button.tabIndex = button.classList.contains("active") ? 0 : -1;
    button.addEventListener("click", () => {
      activate(button);
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === "Home" ? 0
        : event.key === "End" ? buttons.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[nextIndex].focus();
      activate(buttons[nextIndex]);
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
  const deployment = state.metadata.deployment || { mode: "local" };
  const hosted = deployment.mode === "vercel-demo";
  $("#data-season").textContent = hosted
    ? `${state.metadata.data_season} · hosted demo`
    : `${state.metadata.data_season} snapshot · local`;
  $("#home-team").innerHTML = optionList(defaults.home);
  $("#away-team").innerHTML = optionList(defaults.away);
  $("#higher-seed").innerHTML = optionList("DEN");
  $("#lower-seed").innerHTML = optionList("MIN");
  $("#franchise-team").innerHTML = optionList("UTA");
  const trialInput = $("#matchup-trials");
  trialInput.max = deployment.matchup_trial_limit || 10000;
  trialInput.value = hosted ? Math.min(25, defaults.trials) : defaults.trials;
  const inventory = state.metadata.snapshot_inventory || [];
  const gameSeasons = inventory.filter((item) => item.dataset === "game-logs");
  const rosterSnapshots = inventory
    .filter((item) => item.dataset === "rosters")
    .sort((a, b) => a.season.localeCompare(b.season));
  const currentRoster = rosterSnapshots.at(-1);
  const coverage = state.metadata.profile_coverage;
  const gameRows = gameSeasons.reduce((sum, item) => sum + Number(item.recorded_rows || 0), 0);
  $("#data-inventory").textContent = hosted
    ? "Fictional demonstration profiles · no downloaded NBA dataset or model weights"
    : gameSeasons.length > 0
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
  if (hosted) {
    document.body.classList.add("hosted-demo");
    $("#deployment-banner").classList.remove("hidden");
    ["#matchup-use-health", "#matchup-use-environment"].forEach((selector) => {
      const input = $(selector);
      if (!input) return;
      input.checked = false;
      input.disabled = true;
      input.closest("label")?.classList.add("hidden");
    });
    $('.mode-option[data-mode="hybrid"]').click();
  } else {
    renderGameDay(state.metadata.game_day);
    loadFranchiseIndex();
  }
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
  $("#season-simulate-all").disabled = running;
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

function setFranchiseSeasonRunning(running) {
  const button = $("#season-simulate");
  const scope = $("#season-scope");
  const shell = $(".season-progress-shell");
  button.disabled = running;
  scope.disabled = running;
  $("#season-playoff-next").disabled = running;
  $("#season-postseason").disabled = running;
  shell.classList.toggle("running", running);
  $("#season-job-detail").classList.toggle("hidden", !running);
  $("span", button).textContent = running
    ? "Season in motion"
    : "Continue season";
}

function renderFranchiseSeasonProgress(job) {
  const completed = Number(job.completed_games || 0);
  const total = Number(job.total_games || 0);
  const percent = Math.max(0, Math.min(100, Number(job.progress || 0) * 100));
  const terminal = ["completed", "cancelled", "failed"].includes(job.status);
  const postseason = String(job.scope || "").startsWith("postseason:");
  if (postseason) {
    $("#season-playoff-progress-copy").textContent =
      `${completed.toLocaleString()} exact playoff games complete${total ? ` · ${Math.round(percent)}% of the maximum path` : ""}`;
    $("#season-playoff-progress-fill").style.width = `${percent}%`;
  } else {
    $("#season-progress-copy").textContent =
      `${completed.toLocaleString()} of ${total.toLocaleString()} games in this run`;
    $("#season-progress-percent").textContent =
      `${percent < 10 && percent > 0 ? percent.toFixed(1) : Math.round(percent)}%`;
    $("#season-progress-fill").style.width = `${percent}%`;
    $("#season-progress-track").setAttribute("aria-valuenow", percent.toFixed(2));
  }
  $("#season-job-count").textContent =
    `${completed.toLocaleString()} / ${total.toLocaleString()} exact games complete`;
  const rate = Number(job.games_per_second || 0);
  const rateCopy = rate > 0
    ? `${(rate * 60).toFixed(rate * 60 >= 10 ? 0 : 1)} games/min`
    : "Measuring speed";
  const etaCopy = job.eta_seconds === null || job.eta_seconds === undefined
    ? terminal ? "Finished" : "Calculating ETA"
    : `${duration(job.eta_seconds)} left`;
  $("#season-job-timing").textContent =
    `Elapsed ${duration(job.elapsed_seconds)} · ${etaCopy} · ${rateCopy}`;
  if (job.current_game) {
    $("#season-job-matchup").textContent =
      `Latest final · ${job.current_game.away_team} at ${job.current_game.home_team} · ${formatGameDate(job.current_game.date)}`;
  } else {
    $("#season-job-matchup").textContent =
      job.status === "preparing"
        ? "Preparing exact game simulations…"
        : "Playing the first possession-level game…";
  }
  const cancel = $("#season-job-cancel");
  const stoppable = ["preparing", "running"].includes(job.status);
  cancel.disabled = Boolean(job.cancel_requested) || !stoppable;
  cancel.textContent = job.cancel_requested ? "Stopping safely…" : "Stop safely";
  cancel.classList.toggle("hidden", !stoppable);
}

function scheduleFranchiseSeasonPoll(delay = 220) {
  window.clearTimeout(state.franchiseSeasonPollTimer);
  state.franchiseSeasonPollTimer = window.setTimeout(
    pollFranchiseSeasonSimulation,
    delay,
  );
}

async function pollFranchiseSeasonSimulation() {
  if (!state.franchiseSeasonJobId) return;
  try {
    const job = await api("/api/franchise/simulate-games/progress", {
      job_id: state.franchiseSeasonJobId,
    });
    renderFranchiseSeasonProgress(job);
    if (job.status === "completed" && job.result) {
      const completed = Number(job.completed_games || 0);
      const postseason = String(job.scope || "").startsWith("postseason:");
      state.franchise = job.result;
      state.franchiseSeasonJobId = null;
      localStorage.removeItem(FRANCHISE_SEASON_JOB_STORAGE_KEY);
      setFranchiseSeasonRunning(false);
      renderFranchise(state.franchise);
      const champion = state.franchise.postseason_simulation?.champion;
      const newInjuries = state.franchise.season_simulation?.new_injuries || [];
      const injuryCopy = newInjuries.length
        ? ` · ${newInjuries.length} new injur${newInjuries.length === 1 ? "y" : "ies"}`
        : "";
      showToast(champion
        ? `${champion} won the NBA championship · ${completed} playoff games completed.`
        : `${completed} exact ${postseason ? "playoff " : ""}game${completed === 1 ? "" : "s"} completed in ${duration(job.elapsed_seconds)}${injuryCopy}.`);
      return;
    }
    if (job.status === "cancelled" || job.status === "failed") {
      const postseason = String(job.scope || "").startsWith("postseason:");
      state.franchiseSeasonJobId = null;
      localStorage.removeItem(FRANCHISE_SEASON_JOB_STORAGE_KEY);
      setFranchiseSeasonRunning(false);
      if (postseason && job.status === "cancelled" && state.franchise) {
        try {
          state.franchise = await api("/api/franchise/load", {
            save_id: state.franchise.save.save_id,
          });
        } catch (_error) { /* Keep the last rendered snapshot if reload fails. */ }
      }
      if (state.franchise) renderFranchiseSeason(state.franchise);
      showToast(
        job.status === "failed"
          ? job.error || "Season simulation failed."
          : postseason
            ? "Postseason stopped safely. Completed rounds remain saved; the in-progress round was discarded."
            : "Season simulation stopped; no partial results were saved.",
      );
      return;
    }
    scheduleFranchiseSeasonPoll();
  } catch (error) {
    state.franchiseSeasonJobId = null;
    localStorage.removeItem(FRANCHISE_SEASON_JOB_STORAGE_KEY);
    setFranchiseSeasonRunning(false);
    if (state.franchise) renderFranchiseSeason(state.franchise);
    showToast(error.message);
  }
}

function resumeFranchiseSeasonSimulation() {
  if (state.franchiseSeasonJobId) return;
  const jobId = localStorage.getItem(FRANCHISE_SEASON_JOB_STORAGE_KEY);
  if (!jobId) return;
  state.franchiseSeasonJobId = jobId;
  state.franchiseSeasonBaseGames = Number(
    state.franchise?.season_hub?.games_played || 0,
  );
  setFranchiseSeasonRunning(true);
  scheduleFranchiseSeasonPoll(0);
}

function initializeFranchise() {
  const workspaceTabs = $$(".franchise-workspace-tab");
  const activateWorkspace = (button) => {
      const target = button.dataset.franchiseTab;
      workspaceTabs.forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", String(active));
        item.tabIndex = active ? 0 : -1;
      });
      $$(".franchise-overview-section").forEach((section) =>
        section.classList.toggle("hidden", target !== "overview"),
      );
      $("#franchise-cap-workspace").classList.toggle("hidden", target !== "cap");
      $('#franchise-stats-workspace').classList.toggle('hidden', target !== 'stats');
      if (target === 'stats') loadFranchiseStats();
      $("#franchise-season-workspace").classList.toggle(
        "hidden",
        target !== "season",
      );
      $("#franchise-gm-workspace").classList.toggle(
        "hidden",
        target !== "gm",
      );
      $("#franchise-playtest-workspace").classList.toggle(
        "hidden",
        target !== "playtest",
      );
      $("#franchise-contract-workspace").classList.toggle(
        "hidden",
        target !== "contracts",
      );
      $("#franchise-trade-workspace").classList.toggle(
        "hidden",
        target !== "trades",
      );
      $("#franchise-roster-workspace").classList.toggle(
        "hidden",
        target !== "roster",
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
  };
  workspaceTabs.forEach((button, index) => {
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(button.classList.contains("active")));
    button.tabIndex = button.classList.contains("active") ? 0 : -1;
    button.addEventListener("click", () => activateWorkspace(button));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === "Home" ? 0
        : event.key === "End" ? workspaceTabs.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + workspaceTabs.length) % workspaceTabs.length;
      workspaceTabs[nextIndex].focus();
      activateWorkspace(workspaceTabs[nextIndex]);
    });
  });

  $("#experience-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const form = event.currentTarget;
    const preset = $('input[name="experience-preset"]:checked', form)?.value || "guided";
    const difficulty = $('input[name="experience-difficulty"]:checked', form)?.value || "pro";
    setBusy(form, true, "Applying settings…");
    try {
      state.franchise = await api("/api/franchise/configure-experience", {
        save_id: state.franchise.save.save_id,
        preset,
        difficulty,
        contextual_help: $("#experience-help").checked,
        confirm_consequential_moves: $("#experience-confirm").checked,
        show_advanced_by_default: $("#experience-advanced").checked,
      });
      state.playtestAudit = null;
      renderFranchise(state.franchise);
      await refreshFranchiseSaveList(state.franchise.save.save_id);
      showToast("Experience settings saved. Basketball accuracy is unchanged.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#playtest-branch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const form = event.currentTarget;
    const name = $("#playtest-branch-name").value.trim();
    if (!name) {
      showToast("Name the safety branch first.");
      return;
    }
    setBusy(form, true, "Creating branch…");
    try {
      const result = await api("/api/franchise/branch", {
        save_id: state.franchise.save.save_id,
        branch_name: name,
      });
      $("#playtest-branch-name").value = "";
      state.playtestAudit = null;
      await loadFranchiseIndex(result.save.save_id);
      showToast(`Safety branch “${result.save.branch_name}” is active.`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#playtest-audit-run").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    const label = $("span", button);
    const original = label.textContent;
    button.disabled = true;
    label.textContent = "Auditing league…";
    loading($("#playtest-audit-result"), "Replaying the save and checking league invariants…");
    try {
      state.playtestAudit = await api("/api/franchise/playtest-audit", {
        save_id: state.franchise.save.save_id,
      });
      renderPublicExperience(state.franchise);
      showToast(state.playtestAudit.ready_for_playtest
        ? "This branch cleared every required playtest check."
        : "The audit found a required check that needs attention.");
    } catch (error) {
      showToast(error.message);
      renderPublicExperience(state.franchise);
    } finally {
      button.disabled = false;
      label.textContent = original;
    }
  });

  $("#season-hub-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/initialize-season", {
        save_id: state.franchise.save.save_id,
      });
      renderFranchise(state.franchise);
      showToast("Season calendar added to this branch.");
    } catch (error) { showToast(error.message); }
    finally { setBusy(button, false); }
  });

  $("#gm-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/initialize-gm", {
        save_id: state.franchise.save.save_id,
      });
      renderFranchise(state.franchise);
      showToast("All 30 front offices now have persistent plans.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  $("#gm-review").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/review-gm", {
        save_id: state.franchise.save.save_id,
        reason: "user-requested league audit",
      });
      renderFranchise(state.franchise);
      showToast("Every automatic front office reviewed its direction.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  $("#gm-plan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise) return;
    const form = event.currentTarget;
    setBusy(form, true, "Saving mandate…");
    try {
      state.franchise = await api("/api/franchise/update-gm-plan", {
        save_id: state.franchise.save.save_id,
        automation_enabled: $("#gm-automation").value === "true",
        direction: $("#gm-direction").value,
        evaluation_horizon: Number($("#gm-evaluation-horizon").value),
        priorities: {
          win_now: Number($("#gm-weight-win").value),
          development: Number($("#gm-weight-development").value),
          flexibility: Number($("#gm-weight-flexibility").value),
          draft_capital: Number($("#gm-weight-draft").value),
        },
      });
      renderFranchise(state.franchise);
      state.tradeBoard = null;
      state.tradeBoardSaveId = null;
      showToast("Your organizational mandate is saved and active in trade AI.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  const startRegularSeason = async (scope, button) => {
    if (!state.franchise || state.franchiseSeasonJobId) return;
    button.disabled = true;
    state.franchiseSeasonBaseGames = Number(
      state.franchise.season_hub?.games_played || 0,
    );
    try {
      const job = await api("/api/franchise/simulate-games/start", {
        save_id: state.franchise.save.save_id,
        scope,
      });
      state.franchiseSeasonJobId = job.job_id;
      localStorage.setItem(FRANCHISE_SEASON_JOB_STORAGE_KEY, job.job_id);
      setFranchiseSeasonRunning(true);
      renderFranchiseSeasonProgress(job);
      scheduleFranchiseSeasonPoll(150);
    } catch (error) {
      button.disabled = false;
      showToast(error.message);
      renderFranchiseSeason(state.franchise);
    }
  };

  $("#season-simulate").addEventListener("click", (event) => {
    startRegularSeason($("#season-scope").value, event.currentTarget);
  });
  $("#season-simulate-all").addEventListener("click", (event) => {
    startRegularSeason("full_season", event.currentTarget);
  });

  $("#season-job-cancel").addEventListener("click", async (event) => {
    if (!state.franchiseSeasonJobId) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Stopping safely…";
    try {
      const job = await api("/api/franchise/simulate-games/cancel", {
        job_id: state.franchiseSeasonJobId,
      });
      renderFranchiseSeasonProgress(job);
      scheduleFranchiseSeasonPoll(150);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Stop safely";
      showToast(error.message);
    }
  });

  const runPostseason = async (scope, button) => {
    if (!state.franchise) return;
    let started = false;
    setBusy(button, true);
    const nextRound = state.franchise.season_hub?.postseason?.next_round?.replaceAll("_", " ") || "postseason";
    $("#season-playoff-copy").textContent = scope === "all"
      ? "Simulating every remaining series with the full game engine…"
      : `Simulating the ${nextRound} game by game…`;
    try {
      const job = await api("/api/franchise/simulate-postseason/start", {
        save_id: state.franchise.save.save_id,
        scope,
      });
      state.franchiseSeasonJobId = job.job_id;
      started = true;
      localStorage.setItem(FRANCHISE_SEASON_JOB_STORAGE_KEY, job.job_id);
      setFranchiseSeasonRunning(true);
      renderFranchiseSeasonProgress(job);
      scheduleFranchiseSeasonPoll(150);
    } catch (error) { showToast(error.message); renderFranchiseSeason(state.franchise); }
    finally { if (!started) setBusy(button, false); }
  };

  $("#season-postseason").addEventListener("click", (event) => runPostseason("all", event.currentTarget));
  $("#season-playoff-next").addEventListener("click", (event) => runPostseason("next_round", event.currentTarget));

  $("#offseason-continue").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    const expectedStage = button.dataset.expectedStage;
    setBusy(button, true, "Saving stage…");
    try {
      state.franchise = await api("/api/franchise/advance-offseason", {
        save_id: state.franchise.save.save_id,
        expected_stage: expectedStage,
      });
      renderFranchise(state.franchise);
      const transition = state.franchise.offseason_transition || {};
      showToast(transition.opened_season
        ? `${transition.opened_season} is open with a new 1,230-game schedule.`
        : `${String(transition.completed_stage || expectedStage).replaceAll("_", " ")} saved.`);
    } catch (error) {
      showToast(error.message);
      renderFranchiseSeason(state.franchise);
    } finally {
      setBusy(button, false);
    }
  });

  $("#offseason-open-room").addEventListener("click", (event) => {
    const destination = event.currentTarget.dataset.destination;
    const tab = $(`.franchise-workspace-tab[data-franchise-tab="${destination}"]`);
    if (tab) tab.click();
  });

  $("#season-user-games").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-season-game]");
    if (!button || !state.franchise) return;
    try {
      const game = await api("/api/franchise/season-game", {
        save_id: state.franchise.save.save_id,
        game_id: button.dataset.seasonGame,
      });
      renderFranchiseSeasonGame(game);
    } catch (error) { showToast(error.message); }
  });

  $("#season-playoff-bracket").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-season-game]");
    if (!button || !state.franchise) return;
    try {
      const game = await api("/api/franchise/season-game", {
        save_id: state.franchise.save.save_id,
        game_id: button.dataset.seasonGame,
      });
      renderFranchiseSeasonGame(game);
    } catch (error) { showToast(error.message); }
  });

  $("#roster-operations-initialize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/initialize-roster-operations", {
        save_id: state.franchise.save.save_id,
      });
      renderFranchise(state.franchise);
      showToast("League rotations initialized.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  $("#roster-optimize").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/optimize-roster-plan", {
        save_id: state.franchise.save.save_id,
        delegation: $("#roster-delegation").value,
        objective: $("#roster-objective").value,
      });
      renderFranchise(state.franchise);
      showToast("Staff plan saved.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  $("#roster-save").addEventListener("click", async (event) => {
    if (!state.franchise) return;
    const button = event.currentTarget;
    const assignments = $$(".roster-plan-row").map((row) => ({
      player_id: Number(row.dataset.playerId),
      depth_slot: Number(row.dataset.depthSlot),
      target_minutes: Number($("[data-roster-minutes]", row).value || 0),
      starter: $("[data-roster-starter]", row).checked,
      role: $("[data-roster-role]", row).value,
      designation: $("[data-roster-designation]", row).value,
      role_promise: $("[data-roster-promise]", row).value || null,
    }));
    setBusy(button, true);
    try {
      state.franchise = await api("/api/franchise/save-roster-plan", {
        save_id: state.franchise.save.save_id,
        delegation: $("#roster-delegation").value,
        objective: $("#roster-objective").value,
        assignments,
      });
      renderFranchise(state.franchise);
      showToast("Rotation saved to this branch.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
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
      "The next calibrated draft class is now part of this timeline.",
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
      "The complete lottery order is locked.",
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

  $("#contract-initialize").addEventListener("click", async (event) => {
    await runContractAction(
      "/api/franchise/initialize-contracts",
      {},
      event.currentTarget,
      "Building ledger…",
      "The multi-year contract ledger is ready.",
    );
  });

  $("#contract-extension-player").addEventListener("change", () => {
    state.contractEvaluation = null;
    syncExtensionAsk();
    $("#contract-extension-result").innerHTML = "<p>Adjust the offer, then discuss it with the player.</p>";
  });

  $("#contract-extension-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Discussing offer…");
    try {
      const result = await api("/api/franchise/evaluate-extension", extensionPayload());
      state.contractEvaluation = result.evaluation;
      renderContractOfferResult($("#contract-extension-result"), result.evaluation);
    } catch (error) {
      renderError($("#contract-extension-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#contract-sign-extension").addEventListener("click", async (event) => {
    await runContractAction(
      "/api/franchise/sign-extension",
      extensionPayload(),
      event.currentTarget,
      "Signing…",
      "Extension signed and saved to the league ledger.",
    );
    state.contractEvaluation = null;
  });

  $("#contract-run-market").addEventListener("click", async (event) => {
    const result = await runContractAction(
      "/api/franchise/run-contract-market",
      { max_moves: 3 },
      event.currentTarget,
      "Reviewing rosters…",
      "CPU roster review completed.",
    );
    if (result && !result.cpu_contract_moves.length) showToast("No CPU roster needed a move today.");
  });

  $("#free-agent-player").addEventListener("change", () => {
    state.freeAgentEvaluation = null;
    syncFreeAgentAsk();
  });

  $("#free-agent-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Testing offer…");
    try {
      const result = await api("/api/franchise/evaluate-free-agent", freeAgentPayload());
      state.freeAgentEvaluation = result.evaluation;
      renderContractOfferResult($("#free-agent-result"), result.evaluation);
    } catch (error) {
      renderError($("#free-agent-result"), error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#free-agent-sign").addEventListener("click", async (event) => {
    await runContractAction(
      "/api/franchise/sign-free-agent",
      freeAgentPayload(),
      event.currentTarget,
      "Signing…",
      "Free-agent signing completed.",
    );
    state.freeAgentEvaluation = null;
  });

  $("#trade-finder-mode").addEventListener("change", () => {
    state.tradeFinder = null;
    renderTradeFinderAssetOptions();
    renderTradeFinderResults();
  });

  $("#trade-finder-asset").addEventListener("change", () => {
    state.tradeFinder = null;
    renderTradeFinderContext();
    renderTradeFinderResults();
  });

  $("#trade-finder-objective").addEventListener("change", () => {
    state.tradeFinder = null;
    renderTradeFinderResults();
  });

  $("#trade-finder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.franchise || !state.tradeBoard) return;
    const selected = [...$("#trade-finder-asset").selectedOptions].map((option) => option.value);
    if (!selected.length) {
      showToast("Choose at least one player or pick first.");
      return;
    }
    if (selected.length > 6) {
      showToast("Trade Finder can shop up to six assets at once.");
      return;
    }
    const playerIds = selected
      .filter((value) => value.startsWith("player:"))
      .map((value) => Number(value.slice(7)));
    const assetIds = selected
      .filter((value) => value.startsWith("pick:"))
      .map((value) => value.slice(5));
    const form = event.currentTarget;
    setBusy(form, true, "Calling the league…");
    try {
      state.tradeFinder = await api("/api/franchise/find-trades", {
        save_id: state.franchise.save.save_id,
        mode: $("#trade-finder-mode").value,
        objective: $("#trade-finder-objective").value,
        max_offers: Number($("#trade-finder-max").value),
        player_ids: playerIds,
        asset_ids: assetIds,
      });
      renderTradeFinderResults();
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#trade-partner").addEventListener("change", () => {
    clearTradeProposal();
    populateThirdTradeTeams();
    renderTradeBuilder();
  });

  $("#trade-third-enabled").addEventListener("change", () => {
    if (!$("#trade-third-enabled").checked) $("#trade-fourth-enabled").checked = false;
    clearTradeProposal();
    populateThirdTradeTeams();
    renderTradeBuilder();
  });

  $("#trade-third-team").addEventListener("change", () => {
    clearTradeProposal();
    populateThirdTradeTeams();
    renderTradeBuilder();
  });

  $("#trade-fourth-enabled").addEventListener("change", () => {
    clearTradeProposal();
    populateThirdTradeTeams();
    renderTradeBuilder();
  });

  $("#trade-fourth-team").addEventListener("change", () => {
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
    state.tradeFinder = null;
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
        season: state.franchise?.summary?.season || "2026-27",
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
    if (state.franchise?.save?.save_id !== saveId) state.playtestAudit = null;
    state.franchise = await api("/api/franchise/load", { save_id: saveId });
    renderFranchise(state.franchise);
    renderFranchiseSaveOptions(saveId);
    resumeFranchiseSeasonSimulation();
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

async function runContractAction(path, payload, button, loadingLabel, successLabel) {
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
    renderFranchise(result);
    await refreshFranchiseSaveList(result.save.save_id);
    if (successLabel) showToast(successLabel);
    return result;
  } catch (error) {
    showToast(error.message);
    return null;
  } finally {
    label.textContent = originalLabel;
    button.disabled = false;
  }
}

function extensionPayload() {
  return {
    save_id: state.franchise.save.save_id,
    player_id: Number($("#contract-extension-player").value),
    years: Number($("#contract-extension-years").value),
    annual_salary: Math.round(Number($("#contract-extension-salary").value) * 1_000_000),
    role: $("#contract-extension-role").value,
  };
}

function freeAgentPayload() {
  return {
    save_id: state.franchise.save.save_id,
    player_id: Number($("#free-agent-player").value),
    years: Number($("#free-agent-years").value),
    annual_salary: Math.round(Number($("#free-agent-salary").value) * 1_000_000),
    role: $("#free-agent-role").value,
  };
}

function renderFranchise(result) {
  renderNormalHome(result);
  if ($('[data-franchise-tab="stats"]')?.classList.contains('active')) loadFranchiseStats();
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
    roster_plans: "Roster plans",
    season_cycle: "Season calendar",
    gm_plans: "Front-office intelligence",
    experience: "Playtest settings",
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
    contract_market_initialized: "Contract market initialized",
    contract_updated: "Extension signed",
    contract_option_decided: "Contract option decided",
    player_waived: "Player waived",
    free_agent_signed: "Free agent signed",
    roster_operations_initialized: "League rotations initialized",
    roster_plan_updated: "Rotation plan updated",
    season_cycle_initialized: "Season calendar initialized",
    season_games_simulated: "League games simulated",
    season_stage_advanced: "Season stage advanced",
    gm_intelligence_initialized: "Front-office plans initialized",
    gm_plans_reviewed: "League plans reviewed",
    gm_plan_updated: "Organizational mandate updated",
    experience_configured: "Experience settings updated",
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
  renderGeneralManager(result);
  renderPublicExperience(result);
  renderFranchiseTradeCenter(result);
  renderRosterOperations(result);
  renderFranchiseSeason(result);
  renderContractMarket(result);
}

function renderPublicExperience(result) {
  const experience = result.experience;
  if (!experience) return;
  const preset = $(`input[name="experience-preset"][value="${experience.preset}"]`);
  const difficulty = $(`input[name="experience-difficulty"][value="${experience.difficulty}"]`);
  if (preset) preset.checked = true;
  if (difficulty) difficulty.checked = true;
  $("#experience-help").checked = Boolean(experience.contextual_help);
  $("#experience-confirm").checked = Boolean(experience.confirm_consequential_moves);
  $("#experience-advanced").checked = Boolean(experience.show_advanced_by_default);
  $("#experience-status").textContent = experience.onboarding_complete
    ? `${experience.preset.replaceAll("_", " ")} · ${experience.difficulty}`
    : "Recommended defaults";
  $("#experience-accuracy-contract").innerHTML = `
    <strong>Accuracy contract</strong>
    <span>${escapeHtml(experience.accuracy_contract)}</span>
    <small>${escapeHtml(experience.difficulty_copy)}</small>`;
  document.body.classList.toggle("contextual-help-off", !experience.contextual_help);
  $$(".gm-advanced-card").forEach((details) => {
    details.open = Boolean(experience.show_advanced_by_default);
  });

  const journey = [
    [true, "League created", "Your durable local timeline exists."],
    [Boolean(result.general_manager?.ready), "Front offices ready", "All 30 organizations can act from persistent plans."],
    [Boolean(result.roster_operations?.ready), "Rotations ready", "Every team has a valid playable game plan."],
    [Boolean(result.trade_center?.ready), "Trade market explored", "Initialize Trade Center and open one finder result."],
    [Number(result.season_hub?.games_played || 0) > 0, "A game is history", "Simulate through at least one completed league game."],
    [Boolean(result.save?.parent_save_id), "Safety branch active", "Branch once before an experimental decision."],
    [Boolean(state.playtestAudit?.ready_for_playtest), "Readiness verified", "Run the audit and copy its tester report."],
  ];
  const complete = journey.filter(([done]) => done).length;
  $("#playtest-journey-progress").textContent = `${complete} of ${journey.length}`;
  $("#playtest-journey").innerHTML = `
    <div class="playtest-progress-track"><i style="width:${(complete / journey.length) * 100}%"></i></div>
    ${journey.map(([done, title, copy], index) => `
      <div class="playtest-step ${done ? "complete" : ""}">
        <span>${done ? "✓" : index + 1}</span><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(copy)}</small></div>
      </div>`).join("")}`;

  const audit = state.playtestAudit;
  if (!audit) {
    $("#playtest-audit-result").innerHTML = `<div class="empty-state inline"><p class="eyebrow">Not run this session</p><p>The audit is read-only and does not advance or modify the league.</p></div>`;
    return;
  }
  $("#playtest-audit-result").innerHTML = `
    <div class="audit-verdict ${audit.ready_for_playtest ? "ready" : "attention"}">
      <div><p class="eyebrow">${audit.ready_for_playtest ? "Required gate cleared" : "Needs attention"}</p><h3>${audit.passed} of ${audit.required} required checks passed</h3><p>${audit.warnings} optional check${audit.warnings === 1 ? " is" : "s are"} waiting for more league activity.</p></div>
      <strong>${Math.round(audit.score * 100)}%</strong>
    </div>
    <div class="audit-check-grid">
      ${audit.checks.map((check) => `
        <div class="audit-check ${escapeHtml(check.status)}">
          <span>${check.status === "pass" ? "✓" : check.status === "waiting" ? "○" : "!"}</span>
          <div><strong>${escapeHtml(check.label)}</strong><small>${escapeHtml(check.detail)}</small></div>
          <em>${check.required ? "required" : "optional"}</em>
        </div>`).join("")}
    </div>
    <div class="audit-report-actions"><p>Copy this report when sharing feedback so the exact revision and seed can be reproduced.</p><button class="quiet-button" id="copy-tester-report" type="button">Copy tester report</button></div>`;
  $("#copy-tester-report").addEventListener("click", async (event) => {
    try {
      await navigator.clipboard.writeText(audit.tester_report);
      event.currentTarget.textContent = "Copied";
      showToast("Tester report copied to your clipboard.");
    } catch (_error) {
      showToast("Clipboard access was blocked. Select and copy the report from the browser console.");
    }
  });
}

function renderFranchiseSeason(result) {
  const hub = result.season_hub;
  const ready = Boolean(hub?.ready);
  $("#season-hub-initialize-card").classList.toggle("hidden", ready);
  $("#season-hub-ready").classList.toggle("hidden", !ready);
  if (!ready) return;
  const user = result.summary.user_team;
  const row = hub.standings.find((item) => item.team === user);
  const conference = hub.conference_standings[row?.conference || "West"] || [];
  const seed = conference.findIndex((item) => item.team === user) + 1;
  $("#season-hub-kicker").textContent = `${hub.season} · ${hub.status.replaceAll("_", " ")}`;
  $("#season-hub-record").textContent = row ? `${row.wins}–${row.losses}` : "0–0";
  $("#season-hub-position").textContent = row && row.games
    ? `${ordinal(seed)} in the ${row.conference} · ${row.point_differential >= 0 ? "+" : ""}${row.point_differential} point differential`
    : "Your season begins on opening night.";
  if (!state.franchiseSeasonJobId) {
    $("#season-progress-copy").textContent = `${hub.games_played.toLocaleString()} of ${hub.total_games.toLocaleString()} regular-season games`;
    $("#season-progress-percent").textContent = `${Math.round(hub.progress * 100)}%`;
    $("#season-progress-fill").style.width = `${Math.max(0, Math.min(100, hub.progress * 100))}%`;
    $("#season-progress-track").setAttribute(
      "aria-valuenow",
      String(Math.max(0, Math.min(100, hub.progress * 100))),
    );
    $("#season-job-detail").classList.add("hidden");
  }
  $("#season-simulate").classList.toggle("hidden", hub.status !== "preseason" && hub.status !== "regular_season");
  $("#season-simulate-all").classList.toggle("hidden", hub.status !== "preseason" && hub.status !== "regular_season");
  $("#season-scope").closest("label").classList.toggle("hidden", hub.status !== "preseason" && hub.status !== "regular_season");
  $("#season-postseason").classList.toggle("hidden", hub.status !== "postseason");
  $("#season-offseason-card").classList.toggle("hidden", !result.offseason_hub?.ready);
  renderFranchisePostseason(hub);
  renderFranchiseOffseason(result.offseason_hub);
  if (hub.champion) {
    $("#season-champion").textContent = `${hub.champion} are NBA champions`;
    $("#season-awards").innerHTML = Object.entries(hub.awards || {}).filter(([key]) => key !== "champion").map(([key, value]) => `<div><span>${key.replaceAll("_", " ")}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  }

  const gameRow = (game, completed) => {
    const home = game.home_team === user;
    const opponent = home ? game.away_team : game.home_team;
    const userScore = home ? game.home_score : game.away_score;
    const opponentScore = home ? game.away_score : game.home_score;
    return `<button class="season-game-row ${completed ? "final" : "upcoming"}" type="button" ${completed ? `data-season-game="${game.game_id}"` : "disabled"}>
      <span>${formatFranchiseDate(game.date)}</span><strong>${home ? "vs" : "at"} ${opponent}</strong>${completed ? `<em class="${userScore > opponentScore ? "win" : "loss"}">${userScore > opponentScore ? "W" : "L"} ${userScore}–${opponentScore}</em>` : `<em>${game.stage.replaceAll("_", " ")}</em>`}</button>`;
  };
  $("#season-user-games").innerHTML = `
    <div class="season-game-group"><span>Recent finals</span>${hub.recent_user_games.length ? hub.recent_user_games.map((game) => gameRow(game, true)).join("") : "<p>No games played yet.</p>"}</div>
    <div class="season-game-group"><span>Coming up</span>${hub.upcoming_user_games.length ? hub.upcoming_user_games.map((game) => gameRow(game, false)).join("") : "<p>Regular-season schedule complete.</p>"}</div>`;

  $("#season-conferences").innerHTML = ["East", "West"].map((name) => `
    <div><h3>${name}</h3>${hub.conference_standings[name].map((team, index) => `<div class="season-standing-row ${team.team === user ? "user" : ""}"><span>${index + 1}</span><strong>${team.team}</strong><em>${team.wins}–${team.losses}</em><small>${team.point_differential >= 0 ? "+" : ""}${team.point_differential}</small></div>`).join("")}</div>`).join("");
  $("#season-leaders").innerHTML = hub.league_leaders.length
    ? hub.league_leaders.map((player, index) => `<div class="season-leader-row"><span>${index + 1}</span><div><strong>${escapeHtml(player.name)}</strong><small>${player.team} · ${player.games} GP</small></div><em>${number(player.ppg, 1)} PPG</em><small>${number(player.rpg, 1)} RPG · ${number(player.apg, 1)} APG</small></div>`).join("")
    : `<div class="empty-state inline"><p>League leaders appear after opening night.</p></div>`;
  const injuries = result.player_health?.injuries || [];
  const activeInjuries = injuries.filter((item) => ["active", "recovering", "out", "questionable"].includes(item.status));
  $("#season-injury-report").classList.toggle("hidden", !injuries.length);
  if (injuries.length) {
    $("#season-injury-count").textContent = `${activeInjuries.length} active · ${injuries.length} total`;
    $("#season-injury-feed").innerHTML = injuries.slice(0, 12).map((injury) => `<article class="${escapeHtml(injury.status)}"><span>${escapeHtml(injury.status.replaceAll("_", " "))}</span><div><strong>${escapeHtml(injury.name)}</strong><small>${escapeHtml(injury.description)} · ${escapeHtml(injury.severity.replaceAll("_", " "))}</small></div><em>${injury.status === "cleared" ? `${injury.games_missed} missed` : injury.expected_return ? `Est. ${formatFranchiseDate(injury.expected_return)}` : "Under evaluation"}</em></article>`).join("");
  }
}

function renderFranchiseOffseason(offseason) {
  if (!offseason?.ready) return;
  const current = offseason.stages.find((item) => item.status === "current");
  const percent = Math.round(Number(offseason.progress || 0) * 100);
  $("#offseason-progress-label").textContent =
    `${offseason.completed_stages} of ${offseason.total_stages} stages complete`;
  $("#offseason-progress-percent").textContent = `${percent}%`;
  $("#offseason-progress-fill").style.width = `${percent}%`;
  $("#offseason-progress-track").setAttribute("aria-valuenow", String(percent));
  $("#offseason-current-copy").textContent = current
    ? `${current.label}: ${current.description}`
    : `The ${offseason.next_season} season is ready.`;
  $("#offseason-integrity-copy").textContent = offseason.integrity_rule;
  $("#season-offseason-steps").innerHTML = offseason.stages.map((stage, index) => `
    <article class="${escapeHtml(stage.status)}">
      <span>${index + 1}</span>
      <div><strong>${escapeHtml(stage.label)}</strong><small>${escapeHtml(stage.description)}</small></div>
      <em>${stage.status === "complete" ? "Saved" : stage.status === "current" ? "Now" : "Later"}</em>
    </article>`).join("");
  const checks = offseason.checks || [];
  $("#offseason-readiness").innerHTML = checks.map((check) => `
    <div class="${check.passed ? "pass" : "blocked"}"><span>${check.passed ? "✓" : "!"}</span><div><strong>${escapeHtml(check.label)}</strong><small>${escapeHtml(check.detail)}</small></div></div>`).join("");
  const continueButton = $("#offseason-continue");
  const automaticCanPrepare = Boolean(current?.automatic);
  continueButton.disabled = !offseason.can_advance && !automaticCanPrepare;
  continueButton.dataset.expectedStage = offseason.current_stage;
  $("span", continueButton).textContent = offseason.current_stage === "ready_for_next_season"
    ? `Open ${offseason.next_season}`
    : automaticCanPrepare && !offseason.can_advance
      ? `Complete ${current.label}`
      : "Save stage & continue";
  const room = $("#offseason-open-room");
  const destination = current?.destination;
  room.classList.toggle("hidden", !destination || destination === "season");
  room.dataset.destination = destination || "";
  const roomLabels = {
    draft: "Open Draft Room",
    contracts: "Open Contracts & Free Agency",
    development: "Open Player Development",
    roster: "Open Roster & Rotation",
  };
  room.textContent = roomLabels[destination] || "Open control room";
}

function renderFranchisePostseason(hub) {
  const postseason = hub.postseason || { series: [], games_completed: 0 };
  const visible = hub.status === "postseason" || postseason.started || (hub.honors || []).length;
  $("#season-playoff-hub").classList.toggle("hidden", !visible);
  if (!visible) return;
  const roundLabels = {
    play_in: "Play-In Tournament",
    first_round: "First Round",
    conference_semifinals: "Conference Semifinals",
    conference_finals: "Conference Finals",
    nba_finals: "NBA Finals",
  };
  const roundOrder = Object.keys(roundLabels);
  const completed = postseason.completed_round ? roundOrder.indexOf(postseason.completed_round) + 1 : 0;
  const nextLabel = roundLabels[postseason.next_round] || "Postseason complete";
  $("#season-playoff-title").textContent = postseason.champion
    ? `${postseason.champion} are NBA champions`
    : nextLabel;
  $("#season-playoff-copy").textContent = postseason.next_round
    ? `${postseason.games_completed} playoff games are saved. Next: ${nextLabel}. Every matchup uses the same possession-level engine as Matchup Lab.`
    : `${postseason.games_completed} playoff games and every box score are preserved on this branch.`;
  $("#season-playoff-next").classList.toggle("hidden", !postseason.next_round);
  $("#season-playoff-next").querySelector("span").textContent = postseason.next_round
    ? `Sim ${nextLabel}`
    : "Postseason complete";
  $("#season-playoff-progress-copy").textContent = completed
    ? `${completed} of ${roundOrder.length} rounds complete`
    : "Bracket set · Play-In is next";
  $("#season-playoff-progress-fill").style.width = `${(completed / roundOrder.length) * 100}%`;

  const seriesByRound = Object.fromEntries(roundOrder.map((round) => [round, []]));
  (postseason.series || []).forEach((series) => {
    if (seriesByRound[series.round]) seriesByRound[series.round].push(series);
  });
  const liveRounds = roundOrder.filter((round) => seriesByRound[round].length || round === postseason.next_round);
  $("#season-playoff-bracket").innerHTML = liveRounds.length
    ? liveRounds.map((round) => `<section class="season-bracket-round">
        <div><span>${roundLabels[round]}</span><small>${seriesByRound[round].length} series</small></div>
        ${seriesByRound[round].length ? seriesByRound[round].map((series) => {
          const teamRows = series.teams.map((team) => `<div class="${series.winner === team.team ? "winner" : ""}"><span>${team.seed || "—"}</span><strong>${team.team}</strong><em>${team.wins}</em></div>`).join("");
          const games = series.games.map((game) => `<button type="button" data-season-game="${escapeHtml(game.game_id)}" title="Open Game ${game.series_game_number || 1} box score">G${game.series_game_number || 1} · ${game.away_team} ${game.away_score}–${game.home_score} ${game.home_team}</button>`).join("");
          return `<article class="season-series-card ${series.status}"><header><span>${escapeHtml(series.series_id)}</span><em>${series.status.replaceAll("_", " ")}</em></header>${teamRows}<details><summary>${series.games.length} game${series.games.length === 1 ? "" : "s"} · box scores</summary>${games}</details></article>`;
        }).join("") : `<div class="season-bracket-placeholder"><span>Up next</span><p>Matchups lock when the previous round is complete.</p></div>`}
      </section>`).join("")
    : `<div class="season-bracket-placeholder"><span>Postseason ready</span><p>The complete bracket will appear here round by round.</p></div>`;

  const honors = hub.honors || [];
  $("#season-honors").innerHTML = honors.length
    ? honors.map((honor) => `<article class="season-honor ${honor.kind}"><div><span>${escapeHtml(honor.label)}</span><small>${honor.kind.replaceAll("_", " ")}</small></div><strong>${honor.recipients.map((item) => `${item.rank > 1 ? `${item.rank}. ` : ""}${escapeHtml(item.name)} · ${item.team}`).join(" · ")}</strong><p>${escapeHtml(honor.rationale)}</p></article>`).join("")
    : `<div class="empty-state inline"><p>Regular-season honors are calculated when the Play-In begins.</p></div>`;

  const performance = hub.playoff_performance || { risers: [], fallers: [] };
  const performers = (label, rows, direction) => `<div><h3>${label}</h3>${rows.length
    ? rows.slice(0, 6).map((player, index) => `<article><span>${index + 1}</span><div><strong>${escapeHtml(player.name)}</strong><small>${player.team} · ${player.playoff_games} playoff games</small></div><em class="${direction}">${player.adjusted_delta > 0 ? "+" : ""}${number(player.adjusted_delta, 2)}</em></article>`).join("")
    : `<p>Available once playoff games are complete.</p>`}</div>`;
  $("#season-playoff-performers").innerHTML = `${performers("Playoff risers", performance.risers || [], "up")}${performers("Playoff fallers", performance.fallers || [], "down")}<small>${escapeHtml(performance.method || "Sample-adjusted playoff impact")}</small>`;
}

function renderFranchiseSeasonGame(game) {
  const target = $("#season-game-detail");
  target.classList.remove("hidden");
  const teamBoxes = (team) => game.box_scores.filter((item) => item.team === team).sort((a, b) => b.minutes - a.minutes);
  const table = (team) => `<div class="season-box-team"><h3>${team}</h3><div class="season-box-header"><span>Player</span><span>MIN</span><span>PTS</span><span>REB</span><span>AST</span><span>STL</span><span>BLK</span><span>FG</span><span>3PT</span></div>${teamBoxes(team).map((player) => `<div class="season-box-row"><strong>${escapeHtml(player.name)}</strong><span>${number(player.minutes, 1)}</span><span>${player.points}</span><span>${player.rebounds}</span><span>${player.assists}</span><span>${player.steals}</span><span>${player.blocks}</span><span>${player.field_goals_made}-${player.field_goals_attempted}</span><span>${player.threes_made}-${player.threes_attempted}</span></div>`).join("")}</div>`;
  const stage = game.round_name ? game.round_name.replaceAll("_", " ") : game.stage.replaceAll("_", " ");
  target.innerHTML = `<div class="season-box-score-heading"><div><p class="eyebrow">${formatFranchiseDate(game.date)} · ${stage}${game.series_game_number ? ` · game ${game.series_game_number}` : ""}</p><h2>${game.away_team} ${game.away_score} <span>at</span> ${game.home_team} ${game.home_score}</h2></div><span>Seed ${game.seed}</span></div><div class="season-box-grid">${table(game.away_team)}${table(game.home_team)}</div>`;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

function ordinal(value) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`;
  return `${value}${({ 1: "st", 2: "nd", 3: "rd" })[value % 10] || "th"}`;
}

function renderRosterOperations(result) {
  const operations = result.roster_operations;
  const ready = Boolean(operations?.ready);
  $("#roster-operations-initialize-card").classList.toggle("hidden", ready);
  $("#roster-operations-ready").classList.toggle("hidden", !ready);
  if (!ready) return;

  $("#roster-operations-title").textContent = `${operations.team} rotation plan`;
  $("#roster-delegation").value = operations.delegation;
  $("#roster-objective").value = operations.objective;
  const delegationCopy = {
    automatic: "Staff will re-optimize after health, workload, coaching and calendar changes.",
    recommend: "Staff flags conflicts; your saved rotation stays in place until you act.",
    manual: "Every rotation choice stays yours until you change it.",
  };
  $("#roster-operations-status").textContent = delegationCopy[operations.delegation];
  const metrics = operations.metrics;
  $("#roster-operations-metrics").innerHTML = [
    ["Starters", `${metrics.starters} / 5`, "opening group"],
    ["Rotation", metrics.rotation_players, "players with minutes"],
    ["Minutes", number(metrics.target_minutes, 1), "must equal 240"],
    ["Assignments", metrics.g_league_assignments + metrics.inactive, "G League or inactive"],
    ["Two-way", `${metrics.two_way_players} / ${operations.limits.two_way_contracts}`, `${operations.limits.two_way_active_games}-game NBA limit`],
  ].map(([label, value, note]) => `<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("");

  const roleOptions = ["franchise", "star", "starter", "sixth", "rotation", "bench", "development"];
  const designationOptions = [
    ["standard", "NBA roster"], ["two_way", "Two-way"],
    ["g_league", "G League"], ["inactive", "Inactive"],
  ];
  $("#roster-plan-table").innerHTML = `
    <div class="roster-plan-header"><span>Start</span><span>Player</span><span>Role</span><span>Minutes</span><span>Assignment</span><span>Promise</span></div>
    ${operations.assignments.map((player) => `
      <div class="roster-plan-row ${player.target_minutes <= 0 ? "outside-rotation" : ""}" data-player-id="${player.player_id}" data-depth-slot="${player.depth_slot}">
        <label class="starter-check" title="Starter"><input data-roster-starter type="checkbox" ${player.starter ? "checked" : ""} /><span>${player.depth_slot}</span></label>
        <div class="roster-player-cell"><strong>${escapeHtml(player.name)}</strong><span>${escapeHtml(player.position || "—")} · ${player.overall == null ? "—" : Math.round(player.overall)} OVR · ${escapeHtml(player.availability)}</span></div>
        <select data-roster-role aria-label="Role for ${escapeHtml(player.name)}">${roleOptions.map((role) => `<option value="${role}" ${player.role === role ? "selected" : ""}>${role.replaceAll("_", " ")}</option>`).join("")}</select>
        <input data-roster-minutes aria-label="Minutes for ${escapeHtml(player.name)}" type="number" min="0" max="48" step="0.5" value="${number(player.target_minutes, 1)}" />
        <select data-roster-designation aria-label="Assignment for ${escapeHtml(player.name)}">${designationOptions.map(([value, label]) => `<option value="${value}" ${player.designation === value ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select data-roster-promise aria-label="Role promise for ${escapeHtml(player.name)}"><option value="">None</option>${roleOptions.map((role) => `<option value="${role}" ${player.role_promise === role ? "selected" : ""}>${role.replaceAll("_", " ")}</option>`).join("")}</select>
      </div>`).join("")}`;

  $("#roster-recommendations").innerHTML = operations.recommendations.map((item) => `
    <article class="roster-recommendation ${escapeHtml(item.severity)}"><span>${escapeHtml(item.severity)}</span><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></article>`).join("");
}

function renderFranchiseCap(result) {
  const rules = result.cba;
  $("#cap-rules-label").textContent = `${rules.season} system levels · ${rules.rules_version.includes("projected") ? "projected" : "official"}`;
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
  $("#cap-data-warning").innerHTML = sheet.complete && sheet.official_salary_data
    ? `<strong>Cap sheet complete</strong><span>Verified payroll: ${money(sheet.known_salary)}</span>`
    : sheet.complete
      ? `<strong>Modeled cap sheet</strong><span>${escapeHtml(sheet.warning)} Planning payroll: ${money(sheet.known_salary)}${sheet.dead_money ? ` · ${money(sheet.dead_money)} dead money` : ""}</span>`
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

function renderContractMarket(result) {
  if (!result?.contract_market) return;
  const market = result.contract_market;
  $("#contract-initialize-card").classList.toggle("hidden", market.ready);
  $("#contract-ready").classList.toggle("hidden", !market.ready);
  if (!market.ready) return;
  $("#contract-cap-label").textContent = `${market.season} · ${market.cap_position.band.replaceAll("_", " ")}`;
  $("#contract-payroll").textContent = `${money(market.payroll, 1)} payroll`;
  $("#contract-data-label").textContent = market.data_label;
  $("#contract-cap-horizon").innerHTML = market.projections.map((row) => {
    const width = Math.min(100, (row.payroll / row.second_apron) * 100);
    const overCap = row.payroll > row.salary_cap;
    return `<article class="contract-cap-year ${overCap ? "over" : ""}">
      <header><span>${escapeHtml(row.season)}</span><strong>${money(row.payroll, 1)}</strong></header>
      <div class="contract-cap-track"><i style="width:${width}%"></i><b style="left:${(row.salary_cap / row.second_apron) * 100}%"></b></div>
      <footer><span>${row.committed_players} committed</span><span>${row.cap_room >= 0 ? `${money(row.cap_room, 1)} room` : `${money(Math.abs(row.cap_room), 1)} over`}</span></footer>
    </article>`;
  }).join("");

  $("#contract-recommendations").innerHTML = market.recommendations
    .map((item, index) => `<div><strong>${String(index + 1).padStart(2, "0")}</strong><span>${escapeHtml(item)}</span></div>`)
    .join("");
  $("#contract-ledger-count").textContent = `${market.contracts.length} contracts`;
  $("#contract-ledger").innerHTML = market.contracts.map((contract) => `
    <article class="contract-player-row">
      <div class="contract-player-identity"><strong>${escapeHtml(contract.name)}</strong><span>${number(contract.overall, 0)} OVR · ${contract.age === null ? "age unknown" : `age ${number(contract.age, 0)}`} · ${escapeHtml((contract.rights || "no rights").replaceAll("_", " "))}</span></div>
      <div class="contract-year-cells">${contract.years.slice(0, 5).map((year) => `<span><small>${escapeHtml(year.season)}</small><strong>${money(year.salary, 1)}</strong>${year.option ? `<em>${escapeHtml(year.option.replaceAll("_", " "))}</em>` : ""}</span>`).join("")}</div>
      <div class="contract-row-actions">
        ${contract.option ? `<button class="quiet-button compact" data-contract-option="${contract.player_id}" type="button">${contract.option.option === "player" ? "Resolve player option" : "Exercise team option"}</button>` : ""}
        <button class="text-button danger" data-contract-waive="${contract.player_id}" type="button">Waive</button>
      </div>
    </article>`).join("");

  const extensionSelect = $("#contract-extension-player");
  const previousExtension = Number(extensionSelect.value);
  const eligibleExtensions = market.contracts.filter((item) => item.extension_eligible);
  extensionSelect.innerHTML = eligibleExtensions.map((contract) => `<option value="${contract.player_id}">${escapeHtml(contract.name)} · ${number(contract.overall, 0)} OVR · asks ${money(contract.asking_salary, 1)}</option>`).join("");
  if (eligibleExtensions.some((item) => item.player_id === previousExtension)) extensionSelect.value = String(previousExtension);
  $("#contract-extension-form").classList.toggle("hidden", !eligibleExtensions.length);
  if (eligibleExtensions.length) syncExtensionAsk();

  const hasFreeAgents = market.free_agents.length > 0;
  $("#free-agent-count").textContent = `${market.free_agents.length} available`;
  $("#free-agency-empty").classList.toggle("hidden", hasFreeAgents);
  $("#free-agent-form").classList.toggle("hidden", !hasFreeAgents);
  const freeAgentSelect = $("#free-agent-player");
  const previousFreeAgent = Number(freeAgentSelect.value);
  freeAgentSelect.innerHTML = market.free_agents.map((player) => `<option value="${player.player_id}">${escapeHtml(player.name)} · ${number(player.overall, 0)} OVR · asks ${money(player.asking_salary, 1)} · interest: ${player.interested_teams.join(", ")}</option>`).join("");
  if (market.free_agents.some((item) => item.player_id === previousFreeAgent)) freeAgentSelect.value = String(previousFreeAgent);
  if (hasFreeAgents) syncFreeAgentAsk();
  else $("#free-agent-result").innerHTML = "";
  $("#contract-assumptions").innerHTML = `<ul>${market.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul><p>Base rules source: official NBA 2026–27 salary-cap release. Later cap years are visibly projected; existing salary estimates are never labeled official.</p>`;

  $$('[data-contract-option]', $("#contract-ledger")).forEach((button) => {
    button.addEventListener("click", async () => {
      await runContractAction(
        "/api/franchise/decide-option",
        { player_id: Number(button.dataset.contractOption), exercise: true },
        button,
        "Resolving…",
        "Contract option resolved and saved.",
      );
    });
  });
  $$('[data-contract-waive]', $("#contract-ledger")).forEach((button) => {
    button.addEventListener("click", async () => {
      const player = market.contracts.find((item) => item.player_id === Number(button.dataset.contractWaive));
      if (!window.confirm(`Waive ${player.name}? Guaranteed salary will remain as dead money.`)) return;
      await runContractAction(
        "/api/franchise/waive-player",
        { player_id: player.player_id },
        button,
        "Waiving…",
        `${player.name} was waived and entered the free-agent pool.`,
      );
    });
  });
}

function syncExtensionAsk(force = true) {
  const market = state.franchise?.contract_market;
  const playerId = Number($("#contract-extension-player").value);
  const player = market?.contracts?.find((item) => item.player_id === playerId);
  if (!player) return;
  if (force || !$("#contract-extension-salary").value) {
    $("#contract-extension-salary").value = (player.asking_salary / 1_000_000).toFixed(2);
  }
}

function syncFreeAgentAsk(force = true) {
  const market = state.franchise?.contract_market;
  const playerId = Number($("#free-agent-player").value);
  const player = market?.free_agents?.find((item) => item.player_id === playerId);
  if (!player) return;
  if (force || !$("#free-agent-salary").value) {
    $("#free-agent-salary").value = (player.asking_salary / 1_000_000).toFixed(2);
  }
}

function renderContractOfferResult(root, evaluation) {
  const successful = evaluation.can_sign;
  root.innerHTML = `<div class="contract-offer-status ${successful ? "accepted" : "declined"}">
    <div><p class="eyebrow">${successful ? "Agreement ready" : "Not there yet"}</p><h3>${escapeHtml(evaluation.player_name)}</h3></div>
    <strong>${number(evaluation.interest, 0)}<small>interest</small></strong>
  </div>
  <p>${escapeHtml(evaluation.explanation)}</p>
  <div class="contract-offer-facts"><span>Ask <strong>${money(evaluation.asking_salary, 1)}</strong></span><span>Offer <strong>${money(evaluation.annual_salary, 1)}</strong></span>${evaluation.mechanism ? `<span>Path <strong>${escapeHtml(evaluation.mechanism.replaceAll("_", " "))}</strong></span>` : ""}</div>
  ${evaluation.blockers?.length ? `<ul>${evaluation.blockers.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}`;
}

function renderFranchiseLifecycle(result) {
  if (!result || !result.player_lifecycle) return;
  const lifecycle = result.player_lifecycle;
  $("#lifecycle-initialize-card").classList.toggle("hidden", lifecycle.ready);
  $("#development-ready").classList.toggle("hidden", !lifecycle.ready);
  if (!lifecycle.ready) return;
  renderCareerLedger(result.player_careers);

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

function renderCareerLedger(careers) {
  if (!careers) return;
  $("#career-ledger-count").textContent =
    `${careers.retired_players} retired · ${careers.career_decisions} decisions`;
  const recent = careers.recent_decisions || [];
  const retired = (careers.records || [])
    .filter((record) => record.status === "retired")
    .slice(0, 8);
  const rows = recent.length
    ? recent.map((decision) => ({
        name: decision.name,
        team: decision.last_team,
        outcome: decision.outcome,
        season: decision.season,
        overall: decision.overall,
        detail:
          decision.outcome === "returned"
            ? "Entered free agency"
            : escapeHtml(decision.reason.replaceAll("_", " ")),
      }))
    : retired.map((record) => ({
        name: record.name,
        team: record.last_team,
        outcome: "retired",
        season: record.retirement?.season || "Career record",
        overall: record.overall,
        detail: `${number(record.career_totals.games, 0)} GP · ${number(record.career_totals.points, 0)} PTS · ${record.awards.length} honors`,
      }));
  $("#career-ledger-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
            <div class="career-ledger-row">
              <span class="career-status-mark ${row.outcome}">${row.outcome === "returned" ? "↗" : "◇"}</span>
              <div><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.team)} · ${escapeHtml(row.season)} · ${row.detail}</small></div>
              <em>${row.overall === null ? "—" : number(row.overall, 1)}<small>OVR</small></em>
            </div>`,
        )
        .join("")
    : `<div class="empty-state inline"><p class="eyebrow">No career decisions yet</p><p>The first permanent decisions are recorded during offseason player progression.</p></div>`;
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
    ${selected.injury ? `<div class="health-active-injury"><span>${escapeHtml(selected.injury.severity.replaceAll("_", " "))}</span><strong>${escapeHtml(selected.injury.description)}</strong><em>${selected.injury.expected_return ? `Estimated return ${formatFranchiseDate(selected.injury.expected_return)}` : "Return date under evaluation"}</em></div>` : ""}
    <p class="health-boundary">${escapeHtml(health.interpretation)} Last load: ${selected.last_load_date ? formatFranchiseDate(selected.last_load_date) : "no session recorded in this save"}.</p>`;

  const injuryHistory = (health.injuries || []).filter((item) => item.player_id === selected.player_id);
  $("#health-injury-summary").textContent = injuryHistory.length
    ? `${injuryHistory.length} event${injuryHistory.length === 1 ? "" : "s"} · ${injuryHistory.reduce((sum, item) => sum + Number(item.games_missed || 0), 0)} games missed`
    : "No injuries in this save";
  $("#health-injury-list").innerHTML = injuryHistory.length
    ? injuryHistory.map((injury) => `<article class="${escapeHtml(injury.status)}"><div><span>${escapeHtml(injury.status)}</span><strong>${escapeHtml(injury.description)}</strong><small>${formatFranchiseDate(injury.started_on)} · ${escapeHtml(injury.severity.replaceAll("_", " "))} · ${escapeHtml(injury.body_area || "unspecified")}</small></div><em>${injury.status === "cleared" ? `Cleared ${injury.resolved_on ? formatFranchiseDate(injury.resolved_on) : ""}` : injury.expected_return ? `Est. return ${formatFranchiseDate(injury.expected_return)}` : "Under evaluation"}<small>${injury.games_missed} game${injury.games_missed === 1 ? "" : "s"} missed</small></em></article>`).join("")
    : `<div class="empty-state inline"><p>No recorded injuries for ${escapeHtml(selected.name)} on this timeline.</p></div>`;

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

function renderGeneralManager(result) {
  const gm = result?.general_manager;
  const ready = Boolean(gm?.ready);
  $("#gm-initialize-card").classList.toggle("hidden", ready);
  $("#gm-ready").classList.toggle("hidden", !ready);
  if (!ready || !gm.user_plan) return;
  const plan = gm.user_plan;
  const directionCopy = {
    contend: ["Championship window", "Spend present assets only when the return materially raises the title ceiling."],
    compete: ["Competitive build", "Protect the core while improving fit without sacrificing every future option."],
    retool: ["Active retool", "Change the supporting structure while preserving the assets that still fit the next winning group."],
    rebuild: ["Long-horizon rebuild", "Prioritize development, young value, flexibility, and draft outcomes over short-term wins."],
  }[plan.direction];
  $("#gm-plan-kicker").textContent =
    `${plan.team} front office · ${plan.automation_enabled ? "automatic" : "manual mandate"}`;
  $("#gm-plan-title").textContent = directionCopy[0];
  $("#gm-plan-copy").textContent = directionCopy[1];
  $("#gm-command-metrics").innerHTML = `
    <div><span>Current record</span><strong>${escapeHtml(plan.record)}</strong></div>
    <div><span>Strength rank</span><strong>#${plan.strength_rank}</strong></div>
    <div><span>Win target</span><strong>${plan.target_wins}</strong></div>`;
  $("#gm-horizon").textContent = `${plan.evaluation_horizon}-season window`;
  const priorityRows = [
    ["Win now", plan.priorities.win_now],
    ["Development", plan.priorities.development],
    ["Cap flexibility", plan.priorities.flexibility],
    ["Draft capital", plan.priorities.draft_capital],
  ];
  $("#gm-priorities").innerHTML = priorityRows.map(([label, value]) => `
    <div><span>${label}</span><i><b style="width:${Number(value) * 100}%"></b></i><strong>${pct(value, 0)}</strong></div>`).join("");
  $("#gm-rationale").innerHTML = plan.rationale
    .map((item, index) => `<div><span>${String(index + 1).padStart(2, "0")}</span><p>${escapeHtml(item)}</p></div>`)
    .join("");
  $("#gm-market-size").textContent = `${plan.market_size} market`;
  $("#gm-ownership-metrics").innerHTML = `
    <div><span>Job security</span><strong>${number(plan.job_security, 0)}</strong><i><b style="width:${plan.job_security}%"></b></i></div>
    <div><span>Ownership patience</span><strong>${number(plan.ownership_patience, 0)}</strong><i><b style="width:${plan.ownership_patience}%"></b></i></div>
    <div><span>Budget willingness</span><strong>${number(plan.budget_willingness, 0)}</strong><i><b style="width:${plan.budget_willingness}%"></b></i></div>
    <div><span>Payroll ceiling</span><strong>${money(plan.payroll_ceiling, 1)}</strong><small>${money(plan.payroll, 1)} currently committed</small></div>`;
  $("#gm-triggers").innerHTML = `
    <p class="eyebrow">Live change triggers</p>
    ${plan.triggers.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}`;
  $("#gm-needs").textContent = `Needs ${plan.needs.join(" / ")}`;
  const assetGroup = (label, values, empty) => `
    <div><p class="eyebrow">${label}</p>${values.length
      ? values.map((item) => `<span>${escapeHtml(item)}</span>`).join("")
      : `<small>${empty}</small>`}</div>`;
  $("#gm-assets").innerHTML =
    assetGroup("Protected core", plan.core, "No player is currently protected from market calls.")
    + assetGroup("Actively available", plan.trade_block, "No player is being actively shopped.");

  $("#gm-automation").value = String(plan.automation_enabled);
  $("#gm-direction").value = plan.direction;
  $("#gm-evaluation-horizon").value = String(plan.evaluation_horizon);
  $("#gm-weight-win").value = Math.round(plan.priorities.win_now * 100);
  $("#gm-weight-development").value = Math.round(plan.priorities.development * 100);
  $("#gm-weight-flexibility").value = Math.round(plan.priorities.flexibility * 100);
  $("#gm-weight-draft").value = Math.round(plan.priorities.draft_capital * 100);

  const counts = gm.direction_counts;
  $("#gm-league-summary").textContent =
    `${counts.contend} contend · ${counts.rebuild} rebuild`;
  $("#gm-league-table").innerHTML = `
    <div class="gm-league-header"><span>Team</span><span>Direction</span><span>Record</span><span>Rank</span><span>Age</span><span>Security</span><span>Core</span></div>
    ${gm.league.map((team) => `
      <div class="gm-league-row ${team.team === gm.team ? "user" : ""}">
        <strong>${team.team}</strong>
        <span class="direction-${team.direction}">${escapeHtml(team.direction)}</span>
        <span>${escapeHtml(team.record)}</span>
        <span>#${team.strength_rank}</span>
        <span>${number(team.average_age, 1)}</span>
        <span>${number(team.job_security, 0)}</span>
        <small title="${escapeHtml(team.core.join(", "))}">${team.core.length ? escapeHtml(team.core.join(", ")) : "Open"}</small>
      </div>`).join("")}`;
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
    state.tradeFinder = null;
    clearTradeProposal();
  }
  $("#trade-run-market").disabled = !center.policy.ai_to_ai_trades;
}

async function loadTradeBoard(force = false) {
  if (!state.franchise?.trade_center?.ready) return;
  const saveId = state.franchise.save.save_id;
  if (!force && state.tradeBoardSaveId === saveId && state.tradeBoard) {
    renderTradeFinderAssetOptions();
    renderTradeFinderResults();
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
    populateThirdTradeTeams();
    $("#trade-salary-note").textContent = state.tradeBoard.salary_note;
    if (!Object.keys(state.tradeSelections).length) clearTradeProposal();
    renderTradeFinderAssetOptions();
    renderTradeFinderResults();
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

function populateThirdTradeTeams() {
  if (!state.tradeBoard || !state.franchise) return;
  const userTeam = state.franchise.summary.user_team;
  const partner = $("#trade-partner").value;
  const third = $("#trade-third-team");
  const current = third.value;
  third.innerHTML = Object.keys(state.tradeBoard.strategies)
    .filter((team) => team !== userTeam && team !== partner)
    .sort()
    .map((team) => `<option value="${team}">${team} · ${escapeHtml(state.tradeBoard.strategies[team])}</option>`)
    .join("");
  if ([...third.options].some((option) => option.value === current)) third.value = current;
  const thirdEnabled = $("#trade-third-enabled").checked;
  third.classList.toggle("hidden", !thirdEnabled);
  $("#trade-fourth-control").classList.toggle("hidden", !thirdEnabled);
  const fourth = $("#trade-fourth-team");
  const currentFourth = fourth.value;
  fourth.innerHTML = Object.keys(state.tradeBoard.strategies)
    .filter((team) => team !== userTeam && team !== partner && team !== third.value)
    .sort()
    .map((team) => `<option value="${team}">${team} · ${escapeHtml(state.tradeBoard.strategies[team])}</option>`)
    .join("");
  if ([...fourth.options].some((option) => option.value === currentFourth)) fourth.value = currentFourth;
  fourth.classList.toggle("hidden", !thirdEnabled || !$("#trade-fourth-enabled").checked);
}

function activeTradeTeams() {
  const teams = [state.franchise.summary.user_team, $("#trade-partner").value];
  if ($("#trade-third-enabled").checked && $("#trade-third-team").value) {
    teams.push($("#trade-third-team").value);
  }
  if ($("#trade-fourth-enabled").checked && $("#trade-fourth-team").value) {
    teams.push($("#trade-fourth-team").value);
  }
  return [...new Set(teams.filter(Boolean))];
}

function tradeSelection(team) {
  if (!state.tradeSelections[team]) {
    state.tradeSelections[team] = {
      player_ids: [],
      asset_ids: [],
      player_destinations: {},
      asset_destinations: {},
    };
  }
  state.tradeSelections[team].player_destinations ||= {};
  state.tradeSelections[team].asset_destinations ||= {};
  return state.tradeSelections[team];
}

function selectedTradePackages() {
  return activeTradeTeams().map((team) => {
    const selection = tradeSelection(team);
    return {
      team,
      player_ids: [...selection.player_ids],
      asset_ids: [...selection.asset_ids],
      player_destinations: { ...selection.player_destinations },
      asset_destinations: { ...selection.asset_destinations },
    };
  });
}

function tradeProposalHasAssets() {
  return selectedTradePackages().some(
    (item) => item.player_ids.length || item.asset_ids.length,
  );
}

function renderTradeFinderAssetOptions() {
  if (!state.tradeBoard || !state.franchise) return;
  const mode = $("#trade-finder-mode").value;
  const userTeam = state.franchise.summary.user_team;
  const select = $("#trade-finder-asset");
  const current = new Set([...select.selectedOptions].map((option) => option.value));
  const players = state.tradeBoard.players
    .filter((player) => mode === "shop" ? player.team === userTeam : player.team !== userTeam)
    .sort((a, b) =>
      mode === "shop"
        ? b.trade_value - a.trade_value
        : a.team.localeCompare(b.team) || b.trade_value - a.trade_value,
    );
  const picks = state.tradeBoard.assets
    .filter((asset) => mode === "shop" ? asset.current_team === userTeam : asset.current_team !== userTeam)
    .sort((a, b) =>
      a.current_team.localeCompare(b.current_team) ||
      a.draft_year - b.draft_year || a.round - b.round,
    );
  const playerGroups = Object.groupBy
    ? Object.groupBy(players, (player) => player.team)
    : players.reduce((groups, player) => {
        (groups[player.team] ||= []).push(player);
        return groups;
      }, {});
  const pickGroups = Object.groupBy
    ? Object.groupBy(picks, (asset) => asset.current_team)
    : picks.reduce((groups, asset) => {
        (groups[asset.current_team] ||= []).push(asset);
        return groups;
      }, {});
  select.innerHTML = [
    ...Object.keys(playerGroups).sort().map((team) => `
      <optgroup label="${team} players">
        ${playerGroups[team].map((player) => `<option value="player:${player.player_id}">${escapeHtml(player.name)} · ${number(player.overall, 0)} OVR · ${escapeHtml(player.market_status)}</option>`).join("")}
      </optgroup>`),
    ...Object.keys(pickGroups).sort().map((team) => `
      <optgroup label="${team} picks">
        ${pickGroups[team].map((asset) => `<option value="pick:${escapeHtml(asset.asset_id)}">${asset.draft_year} R${asset.round} ${escapeHtml(asset.original_team)} · ${asset.protection ? escapeHtml(asset.protection) : "unprotected"}</option>`).join("")}
      </optgroup>`),
  ].join("");
  [...select.options].forEach((option) => { option.selected = current.has(option.value); });
  if (![...select.selectedOptions].length && select.options.length) select.options[0].selected = true;
  $("#trade-finder-asset-label").textContent =
    mode === "shop" ? "Package to shop" : "Package to acquire";
  $("#trade-finder-asset-help").textContent = mode === "shop"
    ? "Select up to six of your players and picks. Use Ctrl/⌘ to choose more than one."
    : "Select up to six assets owned by the same team. Use Ctrl/⌘ to choose more than one.";
  renderTradeFinderContext();
}

function renderTradeFinderContext() {
  if (!state.tradeBoard || !state.franchise) return;
  const selectedValues = [...$("#trade-finder-asset").selectedOptions].map((option) => option.value);
  const mode = $("#trade-finder-mode").value;
  if (!selectedValues.length) return;
  const selected = selectedValues[0];
  const [type, rawId] = selected.split(":", 2);
  const item = type === "player"
    ? state.tradeBoard.players.find((player) => player.player_id === Number(rawId))
    : state.tradeBoard.assets.find((asset) => asset.asset_id === rawId);
  const team = type === "player" ? item?.team : item?.current_team;
  const office = state.tradeBoard.front_offices?.[team];
  if (!office) return;
  const needs = office.needs.map((need) => need.replaceAll("_", " ")).join(", ");
  $("#trade-finder-context").innerHTML = `
    <strong>${escapeHtml(team)} · ${escapeHtml(office.strategy)}</strong>
    <span>${selectedValues.length} asset${selectedValues.length === 1 ? "" : "s"} selected · ${office.strength_rank}${ordinalSuffix(office.strength_rank)} in roster strength · needs ${escapeHtml(needs)} · ${office.untouchables.length} protected core player${office.untouchables.length === 1 ? "" : "s"}</span>
    <small>${mode === "shop" ? "The package is valued together, including consolidation discounts and star scarcity." : "All selected targets must belong to this team; protected stars carry a nonlinear premium."}</small>`;
}

function ordinalSuffix(value) {
  const numberValue = Number(value);
  const mod100 = numberValue % 100;
  if (mod100 >= 11 && mod100 <= 13) return "th";
  return { 1: "st", 2: "nd", 3: "rd" }[numberValue % 10] || "th";
}

function renderTradeFinderResults() {
  const root = $("#trade-finder-results");
  const result = state.tradeFinder;
  if (!result) {
    root.innerHTML = `<div class="empty-state inline"><p class="eyebrow">No search yet</p><p>Pick an asset above to call the entire league at once.</p></div>`;
    return;
  }
  if (!result.offers.length) {
    root.innerHTML = `<div class="empty-state inline"><p class="eyebrow">Market checked · ${result.teams_searched} teams</p><h3>No credible offer right now</h3><p>${escapeHtml(result.empty_message)}</p></div>`;
    return;
  }
  root.innerHTML = `
    <div class="trade-finder-results-heading"><div><p class="eyebrow">${result.teams_searched} front offices checked</p><h3>${result.offers.length} accepted offer${result.offers.length === 1 ? "" : "s"}</h3></div><span>Ranked for ${escapeHtml(result.objective.replaceAll("_", " "))}</span></div>
    <div class="trade-offer-grid">
      ${result.offers.map((offer) => `
        <article class="trade-offer-card">
          <header><span class="trade-offer-rank">#${offer.rank}</span><div><p class="eyebrow">${escapeHtml(offer.partner)} · ${escapeHtml(offer.partner_plan.strategy)}</p><h3>${escapeHtml(offer.headline)}</h3></div><span class="trade-fairness">${number(offer.fairness, 0)}<small>fit</small></span></header>
          <div class="trade-offer-sides">
            <div><span>You send</span>${renderTradeOfferAssets(offer.you_send)}</div>
            <div><span>You receive</span>${renderTradeOfferAssets(offer.you_receive)}</div>
          </div>
          <div class="trade-offer-reasons">
            ${offer.why_it_works.slice(0, 3).map((reason) => `<span class="${escapeHtml(reason.tone)}"><strong>${escapeHtml(reason.label)}</strong>${escapeHtml(reason.detail)}</span>`).join("")}
          </div>
          <button class="quiet-button full" type="button" data-trade-finder-open="${escapeHtml(offer.offer_id)}">Review this offer →</button>
        </article>`).join("")}
    </div>`;
  $$('[data-trade-finder-open]', root).forEach((button) => {
    button.addEventListener("click", () => {
      const offer = result.offers.find((item) => item.offer_id === button.dataset.tradeFinderOpen);
      if (!offer) return;
      applyTradePackages(offer.packages, offer.evaluation);
      const manual = $(".trade-manual-shell");
      manual.open = true;
      manual.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function renderTradeOfferAssets(assets) {
  return assets.map((asset) => `
    <div class="trade-offer-asset ${escapeHtml(asset.type)}">
      <strong>${escapeHtml(asset.name)}</strong>
      <small>${asset.type === "player"
        ? `${number(asset.overall, 0)} OVR${asset.age ? ` · age ${number(asset.age, 0)}` : ""} · ${money(asset.salary, 1)}`
        : escapeHtml(asset.protection)}</small>
    </div>`).join("");
}

function applyTradePackages(packages, evaluation) {
  const userTeam = state.franchise.summary.user_team;
  const cpuPackages = packages.filter((item) => item.team !== userTeam);
  const partnerPackage = cpuPackages[0];
  if (!partnerPackage) return;
  $("#trade-partner").value = partnerPackage.team;
  $("#trade-third-enabled").checked = cpuPackages.length > 1;
  populateThirdTradeTeams();
  if (cpuPackages[1]) $("#trade-third-team").value = cpuPackages[1].team;
  $("#trade-fourth-enabled").checked = cpuPackages.length > 2;
  populateThirdTradeTeams();
  if (cpuPackages[2]) $("#trade-fourth-team").value = cpuPackages[2].team;
  state.tradeSelections = {};
  packages.forEach((item) => {
    state.tradeSelections[item.team] = {
      player_ids: [...item.player_ids],
      asset_ids: [...item.asset_ids],
      player_destinations: { ...(item.player_destinations || {}) },
      asset_destinations: { ...(item.asset_destinations || {}) },
    };
  });
  state.tradeEvaluation = evaluation || null;
  renderTradeBuilder();
  if (evaluation) renderTradeEvaluation();
}

function renderTradeBuilder() {
  if (!state.tradeBoard || !state.franchise) return;
  const userTeam = state.franchise.summary.user_team;
  const partner = $("#trade-partner").value;
  if (!partner) return;
  const teams = activeTradeTeams();
  const third = teams.length > 2 ? teams[2] : null;
  const fourth = teams.length > 3 ? teams[3] : null;
  $("#trade-user-package-title").textContent =
    `${userTeam} · ${escapeHtml(state.tradeBoard.strategies[userTeam])}`;
  $("#trade-partner-package-title").textContent =
    `${partner} · ${escapeHtml(state.tradeBoard.strategies[partner])}`;
  renderTradeAssets(userTeam, $("#trade-user-assets"));
  renderTradeAssets(partner, $("#trade-partner-assets"));
  $("#trade-third-package").classList.toggle("hidden", !third);
  $(".trade-builder-grid").classList.toggle("three-team", Boolean(third));
  $("#trade-fourth-package").classList.toggle("hidden", !fourth);
  $(".trade-builder-grid").classList.toggle("four-team", Boolean(fourth));
  if (third) {
    $("#trade-third-package-title").textContent =
      `${third} · ${escapeHtml(state.tradeBoard.strategies[third])}`;
    renderTradeAssets(third, $("#trade-third-assets"));
  }
  if (fourth) {
    $("#trade-fourth-package-title").textContent =
      `${fourth} · ${escapeHtml(state.tradeBoard.strategies[fourth])}`;
    renderTradeAssets(fourth, $("#trade-fourth-assets"));
  }
  updateTradePackageCounts();
}

function renderTradeAssets(team, root) {
  const selection = tradeSelection(team);
  const teams = activeTradeTeams();
  const destinations = teams.filter((item) => item !== team);
  const routeSelect = (kind, id) => {
    if (teams.length < 3) return "";
    const routes = kind === "player" ? selection.player_destinations : selection.asset_destinations;
    const destination = routes[id] && destinations.includes(routes[id]) ? routes[id] : destinations[0];
    routes[id] = destination;
    return `<select class="trade-route-select" data-trade-route="${kind}" data-trade-team="${team}" data-trade-id="${escapeHtml(String(id))}" aria-label="Send asset to">${destinations.map((item) => `<option value="${item}" ${item === destination ? "selected" : ""}>Send to ${item}</option>`).join("")}</select>`;
  };
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
          ${selection.player_ids.includes(player.player_id) ? routeSelect("player", player.player_id) : ""}
        </label>`).join("")}
    </div>
    <div class="trade-asset-section">
      <p class="eyebrow">Draft assets · ${picks.length}</p>
      ${picks.map((asset) => `
        <label class="trade-asset-row pick">
          <input type="checkbox" data-trade-asset="pick" data-trade-team="${team}" value="${escapeHtml(asset.asset_id)}" ${selection.asset_ids.includes(asset.asset_id) ? "checked" : ""} />
          <div><strong>${asset.draft_year} round ${asset.round}</strong><span>${asset.original_team === team ? "Own selection" : `Via ${escapeHtml(asset.original_team)}`} · ${asset.protection ? escapeHtml(asset.protection) : "unprotected"}</span></div>
          <span><strong>${number(asset.trade_value, 0)}</strong><small>asset value</small></span>
          ${selection.asset_ids.includes(asset.asset_id) ? routeSelect("pick", asset.asset_id) : ""}
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
      const routeKey = key === "player_ids" ? "player_destinations" : "asset_destinations";
      if (input.checked && activeTradeTeams().length > 2) {
        selected[routeKey][value] = activeTradeTeams().find((team) => team !== input.dataset.tradeTeam);
      } else if (!input.checked) {
        delete selected[routeKey][value];
      }
      state.tradeEvaluation = null;
      $("#trade-evaluation").innerHTML =
        `<div class="empty-state inline"><p class="eyebrow">Proposal changed</p><p>Evaluate again to refresh legality and team acceptance.</p></div>`;
      renderTradeBuilder();
    });
  });
  $$('[data-trade-route]', root).forEach((select) => {
    select.addEventListener("change", () => {
      const selected = tradeSelection(select.dataset.tradeTeam);
      const key = select.dataset.tradeRoute === "player"
        ? "player_destinations" : "asset_destinations";
      selected[key][select.dataset.tradeId] = select.value;
      state.tradeEvaluation = null;
      $("#trade-evaluation").innerHTML = `<div class="empty-state inline"><p class="eyebrow">Routes changed</p><p>Evaluate again so every team's legality and acceptance can be refreshed.</p></div>`;
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
  const third = activeTradeTeams()[2];
  if (third) {
    const thirdCount = count(third);
    $("#trade-third-package-count").textContent =
      `${thirdCount} asset${thirdCount === 1 ? "" : "s"}`;
  }
  const fourth = activeTradeTeams()[3];
  if (fourth) {
    const fourthCount = count(fourth);
    $("#trade-fourth-package-count").textContent =
      `${fourthCount} asset${fourthCount === 1 ? "" : "s"}`;
  }
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
  const frontOfficeFog = state.franchise?.experience?.information_level === "front_office_fog";
  const title = !evaluation.legal
    ? "League office blocked the trade"
    : evaluation.accepted
      ? "The trade can be completed"
      : "The partner wants more value";
  const status = !evaluation.legal ? "blocked" : evaluation.accepted ? "accepted" : "counter";
  $("#trade-evaluation").innerHTML = `
    <div class="trade-evaluation-heading ${status}">
      <div><p class="eyebrow">${evaluation.legal ? "Legal construction" : "Illegal construction"} · ${evaluation.team_count || 2} teams</p><h2>${title}</h2></div>
      <span>${evaluation.blockers.length} blocker${evaluation.blockers.length === 1 ? "" : "s"}</span>
    </div>
    <div class="trade-team-evaluations">
      ${evaluation.teams.map((team) => `
        <div>
          <p class="eyebrow">${escapeHtml(team.team)} · ${escapeHtml(team.strategy)}</p>
          <h3>${team.accepts ? "Accepts" : "Declines"} <small>${frontOfficeFog ? (team.accepts ? "value clears their range" : "value remains short") : `${team.value_delta >= 0 ? "+" : ""}${number(team.value_delta, 1)} value`}</small></h3>
          <p>${escapeHtml(team.acceptance_copy)}</p>
          <div class="trade-decision-factors">
            ${(team.decision_factors || []).map((factor) => `<span class="${escapeHtml(factor.tone)}"><strong>${escapeHtml(factor.label)}</strong>${escapeHtml(factor.detail)}</span>`).join("")}
          </div>
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
    ${evaluation.legal && !evaluation.accepted && (evaluation.team_count || 2) === 2 ? `<button class="quiet-button full" id="trade-counter" type="button"><span>Ask for a counteroffer</span><span>↗</span></button>` : ""}
    <button class="run-button full" id="trade-execute" type="button" ${evaluation.can_execute ? "" : "disabled"}><span>Accept and complete trade</span><span>→</span></button>`;
  const counter = $("#trade-counter");
  if (counter) counter.addEventListener("click", async () => {
    counter.disabled = true;
    counter.firstElementChild.textContent = "Building minimum counter…";
    try {
      const result = await api("/api/franchise/counter-trade", {
        save_id: state.franchise.save.save_id,
        packages: selectedTradePackages(),
      });
      if (result.changed) {
        applyTradePackages(result.packages, result.evaluation);
      }
      showToast(result.message);
    } catch (error) {
      showToast(error.message);
    } finally {
      if (counter.isConnected) {
        counter.disabled = false;
        counter.firstElementChild.textContent = "Ask for a counteroffer";
      }
    }
  });
  $("#trade-execute").addEventListener("click", async (event) => {
    if (
      state.franchise?.experience?.confirm_consequential_moves &&
      !window.confirm("Complete this trade on the active branch? Player, pick, salary, and roster ownership will be autosaved.")
    ) return;
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
    $("#draft-initialize-year").textContent = `${draft.draft_year} class`;
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
  const outlook = draft.class_outlook;
  $("#draft-class-outlook").innerHTML = outlook ? `
    <div><span>Public outlook</span><strong>${escapeHtml(outlook.label)}</strong><small>${number(outlook.public_strength, 1)} consensus index</small></div>
    <div><span>Average age</span><strong>${number(outlook.average_age, 1)}</strong><small>${outlook.international_prospects} international prospects</small></div>
    <div><span>Position supply</span><strong>${Object.entries(outlook.positions).map(([position, count]) => `${position} ${count}`).join(" · ")}</strong><small>Weighted class population</small></div>
    <p>${escapeHtml(outlook.interpretation)}</p>` : "";
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
        <p class="eyebrow">${draft.draft_year} lottery result</p>
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
  initializeTutorial();
  initializeGuide();
  initializeNavigation();
  initializeMatchup();
  initializeGameDay();
  initializeLeague();
  initializeFranchise();
  initializeCompetitions();
  initializeHealth();
  initializeInterfaceMode();
  try {
    const response = await fetch("/api/metadata");
    if (!response.ok) throw new Error("Could not load simulator data");
    state.metadata = await response.json();
    initializeMetadata();
    if (state.metadata.deployment?.mode !== "vercel-demo") {
      resumeLeagueSimulation();
    }
    openTutorial();
  } catch (error) {
    showToast(error.message);
    $("#data-season").textContent = "Data unavailable";
  }
}

// Presentation preference only. Switching modes never rewrites a franchise's
// simulation, house rules, delegation or random streams.
const INTERFACE_MODE_KEY = "nba-sim-interface-mode-v1";
const NORMAL_TUTORIAL_STEPS = [
  {label:'Welcome', kicker:'Basketball starts here', title:'You can run an NBA team.', copy:'Normal keeps the choices small. Advanced opens the whole toolbox whenever you want it.', body:'<div class="tutorial-rule"><strong>Two places to go</strong><span>Play a game gives you one matchup. Franchise saves a whole league and lets you build your team over time.</span></div>'},
  {label:'Your team', kicker:'Your first decision', title:'Pick your team and create a league.', copy:'Choose Phoenix, or any team you love. Name your league and press Create franchise.', body:'<div class="tutorial-rule"><strong>No setup homework</strong><span>The league, schedule and players are prepared for you. Your progress saves on this computer.</span></div>'},
  {label:'Play', kicker:'Start at Home', title:'One next step. Your whole NBA story.', copy:'Home shows your record, team updates and next matchup. Press Sim next game to play, or Continue offseason when it is time to build for next year.', body:'<div class="tutorial-rule"><strong>Want to jump ahead?</strong><span>Open Calendar to simulate further, follow the progress bar, see standings or open any completed game for its box score.</span></div>'},
  {label:'Build', kicker:'Make the team yours', title:'Improve your roster, one decision at a time.', copy:'My team shows your players. Trade Finder finds offers. Free agency helps you sign players. Draft room introduces your next rookie.', body:'<div class="tutorial-rule"><strong>You choose how hands-on to be</strong><span>In My team, choose Staff handles it and save to delegate rotations. Manual adjustments are optional. Always review a trade or contract before confirming. Advanced keeps the deeper controls.</span></div>'},
  {label:'Ready', kicker:'Your first franchise', title:'Ready to manage the Suns?', copy:'We will select Phoenix for you. You can change the team before you create your league.', final:true, body:'<div class="tutorial-rule"><strong>You can always come back</strong><span>Replay Tutorial from the top bar. Your Normal or Advanced choice is remembered for next time.</span></div>'},
];
let interfaceMode = "normal";
let advancedSimulationMode = 'single';
let normalSetupBusy = false;
const normalCopies = new Map();
const NORMAL_ROOMS = new Set(["season", "roster", "trades", "contracts", "draft", "stats"]);

function normalCopy(selector, text) {
  const node = $(selector);
  if (!node) return;
  if (!normalCopies.has(node)) normalCopies.set(node, [...node.childNodes]);
  node.textContent = text;
}

function applyInterfaceMode(mode) {
  if (interfaceMode === 'advanced' && mode !== 'advanced') advancedSimulationMode = state.mode;
  interfaceMode = mode === "advanced" ? "advanced" : "normal";
  const normal = interfaceMode === "normal";
  document.body.dataset.interface = interfaceMode;
  try { localStorage.setItem(INTERFACE_MODE_KEY, interfaceMode); } catch (_) { /* Session-only when storage is blocked. */ }
  $$('button[data-interface]').forEach(button => button.setAttribute("aria-pressed", String(button.dataset.interface === interfaceMode)));
  for (const [node, children] of normalCopies) node.replaceChildren(...children);
  normalCopies.clear();
  if (normal) {
    normalCopy('#view-franchise > .section-intro .eyebrow', 'Your league');
    normalCopy('#view-matchup .section-intro .eyebrow', 'Quick play');
    normalCopy('.nav-item[data-view="matchup"]', "Play a game");
    normalCopy('#view-matchup .section-intro h1', "Two teams. One game.");
    normalCopy('#view-matchup .section-intro .intro-copy', "Pick your teams and press Simulate game. Every game has a fresh result. Open lineups if you want to choose who plays.");
    normalCopy('#view-franchise > .section-intro h1', "Build your NBA story.");
    normalCopy('#view-franchise > .section-intro .intro-copy', "Choose a team. Play the season. Make trades, sign players and draft your next star. Your progress saves automatically.");
    normalCopy('#franchise-create-form > div:first-child > p:not(.eyebrow)', "Name your league and choose your team. We will prepare the league for you.");
    const labels = {season: "Season", roster: "My players", trades: "Trades", contracts: "Sign players", draft: "Draft"};
    for (const [key, label] of Object.entries(labels)) normalCopy(`[data-franchise-tab="${key}"]`, label);
    normalCopy('#free-agency-empty span', "No free agents are available right now. Check again as the league moves through the season and offseason.");
    normalCopy('.free-agency-heading p', 'Choose an available player and make an offer. We check the rules and show the price before you decide.');
    $('.mode-option[data-mode="single"]').click();
    if ($('#matchup-result .result-tab.active')?.dataset.tab === 'raw') $('#matchup-result .result-tab[data-tab="box"]')?.click();
    if (!['matchup', 'franchise'].includes($('.nav-item.active')?.dataset.view)) $('.nav-item[data-view="matchup"]').click();
    if (!NORMAL_ROOMS.has($('.franchise-workspace-tab.active')?.dataset.franchiseTab)) $('[data-franchise-tab="season"]').click();
  }
  if (state.franchise) renderNormalHome(state.franchise);
  if (!normal) $(`.mode-option[data-mode="${advancedSimulationMode}"]`).click();
}

function renderNormalHome(result) {
  renderFranchiseLobby(result);
  const summary = result.summary;
  const hub = result.season_hub || {};
  $('#normal-team-title').textContent = `${summary.user_team} · ${summary.season}`;
  $('#normal-next-copy').textContent = result.offseason_hub?.active
    ? `Up next: ${result.offseason_hub.current_label}. Your Season screen walks you through each decision.`
    : hub.status === 'postseason'
      ? 'The playoffs are here. Open your season to chase the championship.'
      : 'Ready for the next game? Open Season to play, check the standings, or simulate ahead.';
  $('#season-hub-ready').classList.toggle('normal-offseason-active', Boolean(result.offseason_hub?.active));
  const plan = result.roster_operations;
  $('#normal-staff-copy').textContent = plan?.delegation === 'manual'
    ? 'Your saved rotation is under manual control. Open My players to review it. Advanced contains all staff settings.'
    : 'Your saved staff settings and league rules still apply. Trades and contracts are checked before you confirm them.';
}

async function prepareNormalRoom(room) {
  if (interfaceMode !== 'normal' || !state.franchise || normalSetupBusy) return;
  const setup = {
    season: ['season_hub', '/api/franchise/initialize-season'],
    contracts: ['contract_market', '/api/franchise/initialize-contracts'],
    trades: ['trade_center', '/api/franchise/initialize-trades'],
    roster: ['roster_operations', '/api/franchise/initialize-roster-operations'],
    draft: ['draft', '/api/franchise/initialize-draft'],
  }[room];
  if (!setup || state.franchise[setup[0]]?.ready) return;
  const saveId = state.franchise.save.save_id;
  normalSetupBusy = true;
  showToast('Preparing this part of your league…');
  try {
    const result = await api(setup[1], { save_id: saveId });
    if (state.franchise?.save.save_id !== saveId) return;
    state.franchise = result;
    renderFranchise(result);
    if (room === 'trades') await loadTradeBoard();
    showToast('Ready to go.');
  } catch (error) {
    showToast(`Could not prepare this screen: ${error.message}. Reopen the tab to retry.`);
  } finally { normalSetupBusy = false; }
}

function initializeInterfaceMode() {
  // Preserve existing elements and handlers, including all Advanced controls.
  const lineups = document.createElement('details');
  lineups.className = 'normal-lineups';
  lineups.innerHTML = '<summary>Lineups & availability <span>Optional</span></summary>';
  const rotations = $('#matchup-form .rotation-grid');
  rotations.before(lineups);
  lineups.append(rotations, $('#matchup-form .rotation-actions'));
  $$('button[data-interface]').forEach(button => button.addEventListener('click', () => {
    applyInterfaceMode(button.dataset.interface);
    lineups.open = interfaceMode === 'advanced';
  }));
  $$('[data-franchise-tab]').forEach(button => button.addEventListener('click', () => prepareNormalRoom(button.dataset.franchiseTab)));
  $('#normal-next').addEventListener('click', () => {
    $('[data-franchise-tab="season"]').click();
    const target = state.franchise?.offseason_hub?.active ? $('#season-offseason-card') : $('#season-hub-ready');
    target.scrollIntoView({block:'start', behavior:'smooth'});
  });
  $$('[data-normal-room]').forEach(button => button.addEventListener('click', () => $(`[data-franchise-tab="${button.dataset.normalRoom}"]`).click()));
  // Keyboard traversal must skip the tabs hidden by Normal mode.
  for (const selector of ['.primary-nav', '.franchise-workspace-tabs']) {
    const nav = $(selector);
    if (!nav) continue;
    nav.addEventListener('keydown', event => {
      if (interfaceMode !== 'normal' || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const buttons = $$('button', nav).filter(button => button.getClientRects().length);
      if (!buttons.includes(event.target)) return;
      event.preventDefault(); event.stopImmediatePropagation();
      const index = buttons.indexOf(event.target);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus(); buttons[next].click();
    }, true);
  }
  let saved = 'normal';
  try { saved = localStorage.getItem(INTERFACE_MODE_KEY) || 'normal'; } catch (_) { /* Use Normal by default. */ }
  applyInterfaceMode(saved);
  lineups.open = interfaceMode === 'advanced';
  for (const [selector, label] of [
    ['#season-playoff-bracket', 'Playoff bracket & results'],
    ['#season-honors', 'Awards & All-NBA teams'],
    ['#season-playoff-performers', 'Playoff performances'],
    ['#season-conferences', 'League standings'],
    ['#season-leaders', 'League leaders'],
    ['.contract-main-grid', 'Keep or release current players'],
    ['.roster-operations-grid', 'Adjust rotation & see staff advice'],
  ]) {
    const content = $(selector);
    const section = ['#season-playoff-bracket', '.contract-main-grid', '.roster-operations-grid'].includes(selector) ? content : content?.closest('section');
    if (!section) continue;
    const shell = document.createElement('details');
    shell.className = 'normal-disclosure';
    const summary = document.createElement('summary'); summary.textContent = label;
    shell.append(summary); section.before(shell); shell.append(section);
    shell.open = interfaceMode === 'advanced';
  }
  $$('button[data-interface]').forEach(button => button.addEventListener('click', () => {
    $$('.normal-disclosure').forEach(shell => { shell.open = interfaceMode === 'advanced'; });
  }));
  initializeNormalSigning();
  initializeFranchiseLobby();
  initializeFranchiseStats();
}

const LOBBY_ROOMS = [
  ['home', '01', 'Home', 'Your next move'],
  ['season', '02', 'Calendar', 'Games & league'],
  ['stats', '03', 'Stats', 'Players & teams'],
  ['roster', '03', 'My team', 'Players & rotation'],
  ['trades', '04', 'Trade Finder', 'Find a better fit'],
  ['contracts', '05', 'Free agency', 'Sign & keep players'],
  ['draft', '06', 'Draft room', 'Build your future'],
];

function openLobbyRoom(room) {
  if (!LOBBY_ROOMS.some(item => item[0] === room)) return;
  const workspace = $('#franchise-workspace');
  workspace.dataset.lobbyRoom = room;
  if (room !== 'home') $(`[data-franchise-tab="${room}"]`).click();
  $$('[data-lobby-nav]').forEach(button => {
    const active = button.dataset.lobbyNav === room;
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
  const description = LOBBY_ROOMS.find(item => item[0] === room);
  $('#lobby-screen-title').textContent = description[2];
  $('#lobby-screen-subtitle').textContent = description[3];
  window.scrollTo({top:0, behavior:'instant'});
}

function initializeFranchiseLobby() {
  // Keep the existing trade form as the source of truth; Normal replaces only
  // its multi-select interaction, without changing the submitted package.
  const tradeSelect = $('#trade-finder-asset');
  const picker = document.createElement('div');
  picker.className = 'normal-only lobby-asset-picker trade-finder-asset-field';
  picker.innerHTML = '<label><span>Find a player or pick</span><input type="search" placeholder="Search your assets" aria-label="Search trade assets"></label><p>Select players and picks. No keyboard shortcuts needed.</p><p class="lobby-asset-selected" aria-live="polite"></p><button type="button" class="quiet-button lobby-clear-assets">Clear selection</button><div class="lobby-asset-options"></div>';
  tradeSelect.closest('label').after(picker);
  const paintAssets = () => {
    const query = $('input', picker).value.toLowerCase();
    $('.lobby-asset-selected', picker).textContent = tradeSelect.selectedOptions.length ? `Selected (${tradeSelect.selectedOptions.length}/6): ${[...tradeSelect.selectedOptions].map(option => option.textContent).join('; ')}` : 'No assets selected.';
    $('.lobby-asset-options', picker).innerHTML = [...tradeSelect.options].map((option,index) => ({option,index})).filter(({option}) => option.textContent.toLowerCase().includes(query)).map(({option,index}) => `<label><input type="checkbox" data-asset-index="${index}" ${option.selected ? 'checked' : ''} ${option.disabled ? 'disabled' : ''}><span>${escapeHtml(option.textContent)}</span></label>`).join('') || '<p>No matching assets.</p>';
  };
  $('input', picker).addEventListener('input', paintAssets);
  $('.lobby-clear-assets', picker).addEventListener('click', () => {
    [...tradeSelect.options].forEach(option => { option.selected = false; });
    tradeSelect.dispatchEvent(new Event('change', {bubbles:true}));
  });
  picker.addEventListener('change', event => {
    const index = event.target.dataset.assetIndex;
    if (index === undefined) return;
    if (event.target.checked && tradeSelect.selectedOptions.length >= 6) {
      event.target.checked = false;
      showToast('Choose up to six players and picks.');
      return;
    }
    tradeSelect.options[Number(index)].selected = event.target.checked;
    tradeSelect.dispatchEvent(new Event('change', {bubbles:true}));
  });
  tradeSelect.addEventListener('change', paintAssets);
  new MutationObserver(paintAssets).observe(tradeSelect, {childList:true});
  paintAssets();
  const rosterCards = document.createElement('section');
  rosterCards.className = 'normal-only lobby-team-roster';
  rosterCards.id = 'lobby-team-roster';
  $('#roster-operations-metrics').after(rosterCards);
  const workspace = $('#franchise-workspace');
  workspace.dataset.lobbyRoom = 'home';
  const chrome = document.createElement('div');
  chrome.id = 'franchise-lobby-chrome'; chrome.className = 'normal-only';
  chrome.innerHTML = `<aside class="lobby-sidebar"><div class="lobby-team-badge" id="lobby-badge">NBA</div><p class="lobby-league-name" id="lobby-league-name">My franchise</p><nav aria-label="Franchise menu">${LOBBY_ROOMS.map(([key, number, title, copy]) => `<button type="button" data-lobby-nav="${key}" aria-current="${key === 'home' ? 'page' : 'false'}"><span>${number}</span><div><strong>${title}</strong><small>${copy}</small></div></button>`).join('')}</nav><p class="lobby-sidebar-note">Your league. Your decisions.<br>Progress saves automatically.</p></aside>
    <header class="lobby-screen-heading"><div><p id="lobby-screen-subtitle">Your next move</p><h1 id="lobby-screen-title">Home</h1></div><div id="lobby-record"></div></header>
    <section id="franchise-lobby" aria-label="Franchise home">
      <article class="lobby-feature"><div class="lobby-court" aria-hidden="true"></div><div class="lobby-feature-copy"><p class="eyebrow" id="lobby-stage">Your season</p><h2 id="lobby-headline">Your next chapter.</h2><p id="lobby-game-copy"></p><button class="run-button" type="button" id="lobby-continue">Continue →</button><p class="lobby-helper" id="lobby-continue-help"></p></div><div class="lobby-team-monogram" aria-hidden="true" id="lobby-monogram">NBA</div></article>
      <div class="lobby-bottom-grid"><article class="lobby-card"><header><h3>On your radar</h3><span>Team updates</span></header><div id="lobby-inbox"></div></article><article class="lobby-card"><header><h3>Your core</h3><button type="button" class="text-button" data-lobby-open="roster">View team →</button></header><div id="lobby-core"></div></article></div>
      <article class="lobby-card lobby-calendar"><header><h3>Next on the calendar</h3><button type="button" class="text-button" data-lobby-open="season">Full calendar →</button></header><div id="lobby-schedule"></div></article>
      <div class="lobby-quick-actions"><button type="button" data-lobby-open="trades"><strong>Make a move ↗</strong><span>Find trade offers across the league</span></button><button type="button" data-lobby-open="contracts"><strong>Find your missing piece ↗</strong><span>Explore available free agents</span></button><button type="button" data-lobby-open="draft"><strong>Build for tomorrow ↗</strong><span>Meet the next draft class</span></button></div>
    </section>`;
  workspace.prepend(chrome);
  $$('[data-lobby-nav]').forEach(button => button.addEventListener('click', () => openLobbyRoom(button.dataset.lobbyNav)));
  $$('[data-lobby-open]').forEach(button => button.addEventListener('click', () => openLobbyRoom(button.dataset.lobbyOpen)));
  $$('[data-franchise-tab]').forEach(button => button.addEventListener('click', () => {
    if (interfaceMode !== 'normal') return;
    const room = button.dataset.franchiseTab;
    workspace.dataset.lobbyRoom = room;
    const description = LOBBY_ROOMS.find(item => item[0] === room);
    if (description) {
      $('#lobby-screen-title').textContent = description[2];
      $('#lobby-screen-subtitle').textContent = description[3];
      $$('[data-lobby-nav]').forEach(node => node.setAttribute('aria-current', node.dataset.lobbyNav === room ? 'page' : 'false'));
    }
  }));
  $('#lobby-continue').addEventListener('click', () => {
    if (!state.franchise) return;
    const result = state.franchise;
    openLobbyRoom('season');
    if (state.franchiseSeasonJobId) return;
    if (result.offseason_hub?.active) {
      $('#season-offseason-card').scrollIntoView({block:'start'});
    } else if (result.season_hub?.status === 'postseason') {
      $('#season-playoff-next').click();
    } else if (['preseason', 'regular_season'].includes(result.season_hub?.status)) {
      $('#season-scope').value = 'next_user_game';
      $('#season-simulate').click();
    }
  });
  if (state.franchise) renderFranchiseLobby(state.franchise);
}

function renderFranchiseLobby(result) {
  if (!$('#franchise-lobby')) return;
  const team = result.summary.user_team;
  const hub = result.season_hub || {};
  const standing = (hub.standings || []).find(row => row.team === team);
  const next = hub.upcoming_user_games?.[0];
  $('#lobby-badge').textContent = team;
  $('#lobby-monogram').textContent = team;
  $('#lobby-league-name').textContent = result.summary.league_name;
  $('#lobby-record').textContent = `${result.summary.season}  /  ${standing ? `${standing.wins} W · ${standing.losses} L` : 'Opening season'}`;
  $('#lobby-stage').textContent = result.offseason_hub?.active ? 'The offseason' : hub.status === 'postseason' ? 'Chase the championship' : 'Next game';
  $('#lobby-headline').textContent = result.offseason_hub?.active ? result.offseason_hub.current_label : next ? `${team} ${next.home_team === team ? 'vs' : 'at'} ${next.home_team === team ? next.away_team : next.home_team}` : hub.status === 'postseason' ? 'Win. Advance. Repeat.' : 'A new season awaits.';
  $('#lobby-game-copy').textContent = result.offseason_hub?.active ? 'Make the next decision for your team. We will take you to the right step.' : next ? `${formatFranchiseDate(next.date)} · ${next.home_team === team ? 'Home court' : 'On the road'}` : 'Your schedule and league results are in Calendar.';
  $('#lobby-continue').textContent = state.franchiseSeasonJobId ? 'View simulation →' : result.offseason_hub?.active ? 'Continue offseason →' : hub.status === 'postseason' ? 'Sim next round →' : next ? 'Sim next game →' : 'Open calendar →';
  $('#lobby-continue-help').textContent = next && !result.offseason_hub?.active ? 'Plays every league game up to your next result. Full box scores are saved.' : 'You stay in control of team decisions.';
  const rows = [...(result.roster_operations?.assignments || [])].sort((a,b) => (b.overall || 0) - (a.overall || 0)).slice(0,5);
  $('#lobby-core').innerHTML = rows.length ? rows.map((player, index) => `<div class="lobby-player"><span class="lobby-shirt">${index+1}</span><div><strong>${escapeHtml(player.name)}</strong><small>${escapeHtml(player.position || 'Player')} · ${escapeHtml((player.availability || 'available').replaceAll('_',' '))}</small></div><b>${player.overall == null ? '—' : Math.round(player.overall)}<small>OVR</small></b></div>`).join('') : '<p>Open My team to see your players and staff plan.</p>';
  const injuries = (result.player_health?.records || []).filter(row => row.availability && row.availability !== 'available');
  $('#lobby-team-roster').innerHTML = `<div class="lobby-card-heading"><h3>Your players</h3><span>Current saved rotation</span></div><div class="lobby-roster-cards">${(result.roster_operations?.assignments || []).map(player => `<article><div class="lobby-roster-rating">${player.overall == null ? '—' : Math.round(player.overall)}<small>OVR</small></div><div><strong>${escapeHtml(player.name)}</strong><p>${escapeHtml(player.position || 'Player')} · ${player.target_minutes > 0 ? `${number(player.target_minutes,1)} min` : 'Outside rotation'}</p><span>${escapeHtml((player.availability || 'available').replaceAll('_',' '))}</span></div></article>`).join('')}</div>`;
  const market = result.contract_market;
  const alerts = [
    [result.offseason_hub?.active ? 'Your next decision' : 'Season update', result.offseason_hub?.active ? result.offseason_hub.current_label : standing ? `${standing.wins} wins through ${standing.games} games.` : 'Opening night is ahead.'],
    ['Health report', injuries.length ? `${injuries.length} player${injuries.length === 1 ? '' : 's'} on your injury report. Review availability in My team.` : 'No active injuries listed for your team.'],
    ['Roster management', result.roster_operations?.delegation === 'automatic' ? 'Staff manages your rotation. You can take control in My team.' : 'Your saved rotation settings are in My team.'],
    ['Available players', market?.free_agents?.length ? `${market.free_agents.length} free agents to explore.` : 'No free agents currently available.'],
  ];
  $('#lobby-inbox').innerHTML = alerts.map(([title,copy]) => `<div class="lobby-alert"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></div>`).join('');
  $('#lobby-schedule').innerHTML = (hub.upcoming_user_games || []).slice(0,4).map(game => `<div><small>${escapeHtml(formatFranchiseDate(game.date))}</small><strong>${game.home_team === team ? 'vs' : 'at'} ${escapeHtml(game.home_team === team ? game.away_team : game.home_team)}</strong><span>${game.home_team === team ? 'Home' : 'Away'}</span></div>`).join('') || '<p>Your regular-season schedule is complete. Continue through the playoffs and offseason from Calendar.</p>';
}

const franchiseStats = {data:null, saveId:null, view:'my_team', sort:'points', ascending:false, page:0, request:0, detailRequest:0};

function initializeFranchiseStats() {
  $$('[data-stats-view]').forEach(button => button.addEventListener('click', () => {
    if ((franchiseStats.view === 'teams') !== (button.dataset.statsView === 'teams')) {
      $('#stats-search').value = '';
      franchiseStats.sort = 'points';
      franchiseStats.ascending = false;
    }
    ++franchiseStats.detailRequest;
    franchiseStats.view = button.dataset.statsView;
    franchiseStats.page = 0;
    $('#stats-team').value = 'all';
    $('#stats-player-detail').classList.add('hidden');
    renderFranchiseStats();
  }));
  for (const selector of ['#stats-season', '#stats-stage']) $(selector).addEventListener('change', () => loadFranchiseStats());
  for (const selector of ['#stats-team', '#stats-basis', '#stats-search']) $(selector).addEventListener('input', () => { franchiseStats.page = 0; renderFranchiseStats(); });
  $('#stats-refresh').addEventListener('click', () => loadFranchiseStats());
  $('#stats-prev').addEventListener('click', () => { franchiseStats.page--; renderFranchiseStats(); });
  $('#stats-next').addEventListener('click', () => { franchiseStats.page++; renderFranchiseStats(); });
  $('#stats-table').addEventListener('click', event => {
    const sort = event.target.closest('[data-stat-sort]');
    if (sort) {
      franchiseStats.ascending = franchiseStats.sort === sort.dataset.statSort ? !franchiseStats.ascending : false;
      franchiseStats.sort = sort.dataset.statSort;
      franchiseStats.page = 0; renderFranchiseStats();
    }
    const player = event.target.closest('[data-stat-player]');
    if (player) loadStatsPlayer(Number(player.dataset.statPlayer), player.textContent);
  });
}

async function loadFranchiseStats() {
  if (!state.franchise) return;
  const saveId = state.franchise.save.save_id;
  const changedSave = franchiseStats.saveId !== saveId;
  const request = ++franchiseStats.request;
  ++franchiseStats.detailRequest;
  franchiseStats.saveId = saveId;
  franchiseStats.data = null;
  $('#stats-status').textContent = 'Loading saved game stats…';
  $('#stats-table').replaceChildren();
  $('#stats-summary').replaceChildren();
  $('#stats-page').textContent = '';
  $('#stats-prev').disabled = $('#stats-next').disabled = true;
  $('#stats-player-detail').classList.add('hidden');
  try {
    const selectedSeason = $('#stats-season').value;
    const data = await api('/api/franchise/stats', {save_id:saveId, season:changedSave || !/^\d{4}-\d{2}$/.test(selectedSeason) ? null : selectedSeason, stage:$('#stats-stage').value});
    if (request !== franchiseStats.request || state.franchise?.save.save_id !== saveId) return;
    franchiseStats.data = data;
    franchiseStats.page = 0;
    $('#stats-season').innerHTML = data.seasons.map(season => `<option ${season === data.season ? 'selected' : ''}>${escapeHtml(season)}</option>`).join('') || '<option>No season yet</option>';
    const selected = changedSave ? 'all' : $('#stats-team').value;
    $('#stats-team').innerHTML = '<option value="all">All teams</option>' + data.teams.map(team => `<option value="${team.team}">${team.team}</option>`).join('');
    $('#stats-team').value = selected;
    renderFranchiseStats();
  } catch (error) {
    if (request === franchiseStats.request) $('#stats-status').textContent = `Could not load stats: ${error.message}. Try Refresh stats.`;
  }
}

function renderFranchiseStats() {
  const data = franchiseStats.data;
  if (!data) return;
  const teamsView = franchiseStats.view === 'teams';
  const myTeam = franchiseStats.view === 'my_team';
  const team = myTeam ? data.user_team : $('#stats-team').value;
  const perGame = $('#stats-basis').value === 'per_game';
  const query = $('#stats-search').value.trim().toLowerCase();
  $$('[data-stats-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.statsView === franchiseStats.view)));
  $('#stats-team').disabled = myTeam;
  if (myTeam) $('#stats-team').value = data.user_team;
  const source = teamsView ? data.teams : team === 'all' ? data.players : data.player_stints;
  let rows = source.filter(row => (team === 'all' || row.team === team) && `${row.name || ''} ${row.team}`.toLowerCase().includes(query));
  const columns = [
    ['games','GP'], ...(teamsView ? [['wins','W'],['losses','L']] : [['minutes','MIN']]),
    ['points','PTS'], ...(teamsView ? [['points_against','OPP']] : []),
    ['rebounds','REB'], ['assists','AST'], ['steals','STL'], ['blocks','BLK'], ['turnovers','TO'],
    ['field_goals_made','FGM'],['field_goals_attempted','FGA'],['fg_pct','FG%'],
    ['threes_made','3PM'],['threes_attempted','3PA'],['three_pct','3P%'],
    ['free_throws_made','FTM'],['free_throws_attempted','FTA'],['ft_pct','FT%'],
    ['offensive_rebounds','OREB'],['defensive_rebounds','DREB'],['personal_fouls','PF'],
  ];
  const value = (row,key) => {
    if (row[key] == null) return null;
    if (key.endsWith('_pct') || ['games','wins','losses'].includes(key)) return row[key];
    const denominator = teamsView && !['points','points_against'].includes(key) ? row.box_score_games : row.games;
    return perGame ? denominator ? row[key] / denominator : null : row[key];
  };
  rows.sort((a,b) => {
    const av = value(a,franchiseStats.sort), bv = value(b,franchiseStats.sort);
    if (av == null) return bv == null ? 0 : 1;
    if (bv == null) return -1;
    return (av-bv)*(franchiseStats.ascending ? 1 : -1) || (a.name || a.team).localeCompare(b.name || b.team);
  });
  const pageSize = 25, pages = Math.max(1, Math.ceil(rows.length / pageSize));
  franchiseStats.page = Math.max(0, Math.min(franchiseStats.page, pages-1));
  const display = rows.slice(franchiseStats.page*pageSize, (franchiseStats.page+1)*pageSize);
  const format = (row,key) => {
    const val = value(row,key);
    return val == null ? '—' : key.endsWith('_pct') ? number(val*100,1) : number(val, perGame && !['games','wins','losses'].includes(key) || key === 'minutes' ? 1 : 0);
  };
  $('#stats-table').innerHTML = rows.length ? `<table><thead><tr><th scope="col">#</th><th scope="col">${teamsView ? 'Team' : 'Player'}</th>${teamsView ? '' : '<th scope="col">Team</th>'}${columns.map(([key,label]) => `<th scope="col" aria-sort="${franchiseStats.sort === key ? franchiseStats.ascending ? 'ascending' : 'descending' : 'none'}"><button type="button" data-stat-sort="${key}" title="Sort by ${label}">${label}${franchiseStats.sort === key ? franchiseStats.ascending ? ' ↑' : ' ↓' : ''}</button></th>`).join('')}</tr></thead><tbody>${display.map((row,index) => `<tr class="${row.team === data.user_team ? 'stats-user-team' : ''}"><td>${franchiseStats.page*pageSize+index+1}</td><th scope="row">${teamsView ? escapeHtml(row.team) : `<button type="button" data-stat-player="${row.player_id}">${escapeHtml(row.name)}</button>`}</th>${teamsView ? '' : `<td title="${escapeHtml((row.teams || [row.team]).join(', '))}">${escapeHtml(row.team)}</td>`}${columns.map(([key]) => `<td>${format(row,key)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<div class="stats-empty"><h3>No stats to show yet</h3><p>Play games in Calendar, or try a different season, competition or search.</p></div>';
  $('#stats-status').textContent = `${data.completed_games} completed games · ${rows.length} ${teamsView ? 'teams' : 'players'} · ${perGame ? 'Per-game averages' : 'Season totals'}`;
  $('#stats-page').textContent = `Page ${franchiseStats.page+1} of ${pages}`;
  $('#stats-prev').disabled = franchiseStats.page === 0;
  $('#stats-next').disabled = franchiseStats.page === pages-1;
  const record = data.teams.find(row => row.team === (team === 'all' ? data.user_team : team));
  $('#stats-summary').innerHTML = record ? [
    [record.team, `${record.wins}–${record.losses}`, 'Record'],
    ['Scoring',record.games ? number(record.points/record.games,1) : '—','Points per game'],
    ['Defense',record.games ? number(record.points_against/record.games,1) : '—','Opponent points per game'],
    ['Differential',record.games ? number((record.points-record.points_against)/record.games,1) : '—','Points per game'],
  ].map(([label,stat,copy]) => `<article><span>${escapeHtml(label)}</span><strong>${stat}</strong><small>${copy}</small></article>`).join('') : '';
}

async function loadStatsPlayer(playerId, name) {
  const data = franchiseStats.data;
  if (!data) return;
  const request = ++franchiseStats.detailRequest;
  const target = $('#stats-player-detail');
  target.classList.remove('hidden');
  target.textContent = 'Loading game log…';
  try {
    const result = await api('/api/franchise/stats', {save_id:franchiseStats.saveId, season:data.season, stage:data.stage, player_id:playerId});
    if (request !== franchiseStats.detailRequest) return;
    target.innerHTML = `<header><div><p class="eyebrow">${escapeHtml(data.season)} · Game log</p><h3>${escapeHtml(name)}</h3></div><button class="quiet-button" type="button" id="stats-close-log">Close</button></header><div class="stats-table-scroll"><table><thead><tr>${['Date','Team','Opponent','Result','MIN','PTS','REB','AST','STL','BLK','TO'].map(text => `<th scope="col">${text}</th>`).join('')}</tr></thead><tbody>${result.game_log.map(row => `<tr><td>${escapeHtml(formatFranchiseDate(row.date))}</td><td>${row.team}</td><td>${row.home ? 'vs' : 'at'} ${row.opponent}</td><td>${row.result}</td>${['minutes','points','rebounds','assists','steals','blocks','turnovers'].map(key => `<td>${number(row[key],key === 'minutes' ? 1 : 0)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    $('#stats-close-log').addEventListener('click', () => target.classList.add('hidden'));
    target.scrollIntoView({block:'start', behavior:'smooth'});
  } catch (error) { if (request === franchiseStats.detailRequest) target.textContent = `Could not load game log: ${error.message}`; }
}

function initializeNormalSigning() {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'run-button normal-only';
  button.id = 'normal-sign-player'; button.textContent = 'Make an offer';
  $('#free-agent-form').append(button);
  const help = document.createElement('p');
  help.className = 'normal-only normal-sign-help';
  help.textContent = 'Pick a player. We will check a two-year offer at his asking price. You see the cost and decide before anyone signs.';
  $('#free-agent-form').before(help);
  button.addEventListener('click', async () => {
    if (!state.franchise) return;
    const playerId = Number($('#free-agent-player').value);
    const player = state.franchise.contract_market?.free_agents.find(row => row.player_id === playerId);
    if (!player) return showToast('Choose an available player first.');
    const saveId = state.franchise.save.save_id;
    const payload = {save_id: saveId, player_id: playerId, years: 2, annual_salary: player.asking_salary, role: 'rotation'};
    setBusy(button, true, 'Checking offer…');
    try {
      const response = await api('/api/franchise/evaluate-free-agent', payload);
      if (state.franchise?.save.save_id !== saveId) return;
      const offer = response.evaluation;
      if (!offer.can_sign) {
        $('#free-agent-result').textContent = offer.blockers?.length ? offer.blockers.join(' ') : `${player.name} wants a different offer. Advanced mode lets you negotiate the salary, years and role.`;
        return;
      }
      if (!window.confirm(`Sign ${player.name} for two years, starting at ${money(player.asking_salary, 2)} per year? Annual raises apply. He will join your rotation. Your progress will be saved.`)) return;
      state.franchise = await api('/api/franchise/sign-free-agent', payload);
      renderFranchise(state.franchise);
      showToast(`${player.name} has joined your team.`);
    } catch (error) { showToast(error.message); }
    finally { setBusy(button, false); }
  });
}

document.addEventListener("DOMContentLoaded", initialize);
