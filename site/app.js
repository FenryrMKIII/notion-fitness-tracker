/* Fitness Dashboard — Chart.js rendering + time range filtering */

let allData = null;
let charts = {};
let currentRange = '3m';

// Color palette
const COLORS = {
  green: '#3fb950',
  red: '#f85149',
  blue: '#58a6ff',
  purple: '#bc8cff',
  orange: '#f0883e',
  yellow: '#d29922',
  gray: '#8b949e',
  text: '#e6edf3',
  textSecondary: '#8b949e',
  grid: '#30363d',
  bgCard: '#161b22',
};

const TYPE_COLORS = {
  'Running': COLORS.green,
  'Gym-Strength': COLORS.blue,
  'Gym-Crossfit': COLORS.purple,
  'Mobility': COLORS.orange,
  'Specifics': COLORS.yellow,
};

const FEELING_COLORS = {
  'Great': COLORS.green,
  'Good': COLORS.blue,
  'Okay': COLORS.yellow,
  'Tired': COLORS.orange,
  'Exhausted': COLORS.red,
};

// Chart.js defaults
Chart.defaults.color = COLORS.textSecondary;
Chart.defaults.borderColor = COLORS.grid;
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

const COMMON_OPTIONS = {
  responsive: true,
  aspectRatio: 1.8,
  plugins: {
    legend: { labels: { color: COLORS.text, boxWidth: 12, padding: 16 } },
    tooltip: { mode: 'index', intersect: false },
  },
  scales: {
    x: {
      grid: { color: COLORS.grid },
      ticks: { color: COLORS.textSecondary, maxRotation: 45 },
    },
    y: {
      grid: { color: COLORS.grid },
      ticks: { color: COLORS.textSecondary },
    },
  },
};

const TIME_OPTIONS = {
  ...COMMON_OPTIONS,
  scales: {
    ...COMMON_OPTIONS.scales,
    x: {
      ...COMMON_OPTIONS.scales.x,
      type: 'time',
      time: { unit: 'week', tooltipFormat: 'MMM d, yyyy' },
    },
  },
};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  try {
    const resp = await fetch('data.json');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    allData = await resp.json();
  } catch (err) {
    document.querySelector('main').innerHTML =
      `<div style="text-align:center;padding:3rem;color:${COLORS.red}">
        <h2>Failed to load data</h2>
        <p>${err.message}</p>
        <p style="color:${COLORS.textSecondary}">Run generate_charts_data.py to create data.json</p>
      </div>`;
    return;
  }

  document.getElementById('lastUpdated').textContent =
    `Updated: ${new Date(allData.generated_at).toLocaleDateString()}`;

  setupFilterButtons();
  renderAll();
}

// ---------------------------------------------------------------------------
// Time range filtering
// ---------------------------------------------------------------------------

function setupFilterButtons() {
  document.querySelectorAll('#rangeFilter button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelector('#rangeFilter .active').classList.remove('active');
      btn.classList.add('active');
      currentRange = btn.dataset.range;
      renderAll();
    });
  });
}

function getCutoffDate() {
  if (!allData || currentRange === 'all') return null;
  const latest = allData.meta.latest;
  if (!latest) return null;
  const d = new Date(latest + 'T00:00:00');
  switch (currentRange) {
    case '4w': d.setDate(d.getDate() - 28); break;
    case '3m': d.setMonth(d.getMonth() - 3); break;
    case '6m': d.setMonth(d.getMonth() - 6); break;
    case '1y': d.setFullYear(d.getFullYear() - 1); break;
  }
  return d.toISOString().slice(0, 10);
}

function filterByDate(arr, dateField) {
  const cutoff = getCutoffDate();
  if (!cutoff) return arr;
  return arr.filter(r => r[dateField] && r[dateField] >= cutoff);
}

// ---------------------------------------------------------------------------
// Render orchestrator
// ---------------------------------------------------------------------------

function renderAll() {
  // Destroy existing charts
  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  if (!allData || !allData.meta.total_training) return;

  const sessions = filterByDate(allData.sessions, 'date');
  const health = filterByDate(allData.health, 'date');
  const wTraining = filterByDate(allData.weekly.training, 'week_start');
  const wHealth = filterByDate(allData.weekly.health, 'week_start');
  const wRunning = filterByDate(allData.weekly.running, 'week_start');
  const wLoad = filterByDate(allData.weekly.load, 'week_start');

  // Performance
  renderPowerTrend(sessions);
  renderPowerHr(sessions);

  // Training Load
  renderWeeklyRss(wRunning);
  renderWeeklyDistance(wRunning);
  renderDurationByType(wTraining, sessions);
  renderAcwrTrend(wLoad);

  // Running Form
  renderCadenceTrend(sessions);
  renderGctTrend(sessions);
  renderVoscTrend(sessions);

  // Balance
  renderTypeDistribution(sessions);
  renderFeelingDistribution(sessions);

  // Recovery
  renderSleepTrend(health);
  renderRestingHrTrend(health);
  renderBodyBatteryTrend(health);

  // Activity
  renderStepsTrend(health);
}

// ---------------------------------------------------------------------------
// Performance charts
// ---------------------------------------------------------------------------

function renderPowerTrend(sessions) {
  const runs = sessions.filter(s => s.training_type === 'Running' && s.power_w);
  if (!runs.length) return;

  charts.powerTrend = new Chart(document.getElementById('powerTrend'), {
    type: 'line',
    data: {
      labels: runs.map(r => r.date),
      datasets: [{
        label: 'Power (W)',
        data: runs.map(r => r.power_w),
        borderColor: COLORS.green,
        backgroundColor: COLORS.green + '20',
        tension: 0.3,
        fill: false,
        pointRadius: 3,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderPowerHr(sessions) {
  const runs = sessions.filter(s => s.training_type === 'Running' && s.power_w && s.avg_hr);
  if (!runs.length) return;

  charts.powerHr = new Chart(document.getElementById('powerHr'), {
    type: 'line',
    data: {
      labels: runs.map(r => r.date),
      datasets: [
        {
          label: 'Power (W)',
          data: runs.map(r => r.power_w),
          borderColor: COLORS.green,
          tension: 0.3,
          fill: false,
          pointRadius: 3,
          yAxisID: 'y',
        },
        {
          label: 'Heart Rate',
          data: runs.map(r => r.avg_hr),
          borderColor: COLORS.red,
          tension: 0.3,
          fill: false,
          pointRadius: 3,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      ...TIME_OPTIONS,
      scales: {
        ...TIME_OPTIONS.scales,
        y: {
          ...TIME_OPTIONS.scales.y,
          position: 'left',
          title: { display: true, text: 'Power (W)', color: COLORS.green },
        },
        y1: {
          grid: { drawOnChartArea: false, color: COLORS.grid },
          ticks: { color: COLORS.textSecondary },
          position: 'right',
          title: { display: true, text: 'Heart Rate', color: COLORS.red },
        },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Training Load charts
// ---------------------------------------------------------------------------

function renderWeeklyRss(wRunning) {
  if (!wRunning.length) return;

  charts.weeklyRss = new Chart(document.getElementById('weeklyRss'), {
    type: 'bar',
    data: {
      labels: wRunning.map(w => w.week_start),
      datasets: [{
        label: 'Total RSS',
        data: wRunning.map(w => w.total_rss),
        backgroundColor: COLORS.red + 'cc',
        borderColor: COLORS.red,
        borderWidth: 1,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderWeeklyDistance(wRunning) {
  if (!wRunning.length) return;

  charts.weeklyDistance = new Chart(document.getElementById('weeklyDistance'), {
    type: 'bar',
    data: {
      labels: wRunning.map(w => w.week_start),
      datasets: [{
        label: 'Distance (km)',
        data: wRunning.map(w => w.total_km),
        backgroundColor: COLORS.green + 'cc',
        borderColor: COLORS.green,
        borderWidth: 1,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderDurationByType(wTraining, sessions) {
  if (!wTraining.length) return;

  // Compute duration by type per week from sessions
  const types = [...new Set(sessions.map(s => s.training_type).filter(Boolean))];
  const weekMap = {};
  wTraining.forEach(w => { weekMap[w.week_start] = {}; });

  sessions.forEach(s => {
    if (!s.date || !s.training_type || !s.duration_min) return;
    // Find which week this session belongs to (timezone-safe)
    const parts = s.date.split('-');
    const sessionDate = new Date(parts[0], parts[1] - 1, parts[2]);
    const day = sessionDate.getDay();
    const monday = new Date(sessionDate);
    monday.setDate(monday.getDate() - ((day + 6) % 7));
    const weekStart = monday.getFullYear() + '-' +
      String(monday.getMonth() + 1).padStart(2, '0') + '-' +
      String(monday.getDate()).padStart(2, '0');
    if (weekMap[weekStart]) {
      weekMap[weekStart][s.training_type] = (weekMap[weekStart][s.training_type] || 0) + s.duration_min;
    }
  });

  const weekStarts = wTraining.map(w => w.week_start);
  const datasets = types.map(type => ({
    label: type,
    data: weekStarts.map(ws => (weekMap[ws] && weekMap[ws][type]) || 0),
    backgroundColor: (TYPE_COLORS[type] || COLORS.gray) + 'cc',
    borderColor: TYPE_COLORS[type] || COLORS.gray,
    borderWidth: 1,
  }));

  charts.durationByType = new Chart(document.getElementById('durationByType'), {
    type: 'bar',
    data: { labels: weekStarts, datasets },
    options: {
      ...TIME_OPTIONS,
      scales: {
        ...TIME_OPTIONS.scales,
        x: { ...TIME_OPTIONS.scales.x, stacked: true },
        y: { ...TIME_OPTIONS.scales.y, stacked: true, title: { display: true, text: 'Minutes', color: COLORS.textSecondary } },
      },
    },
  });
}

function renderAcwrTrend(wLoad) {
  if (!wLoad.length) return;

  // ACWR zone band plugin
  const acwrZonePlugin = {
    id: 'acwrZones',
    beforeDraw(chart) {
      const { ctx, chartArea: { left, right, top, bottom }, scales: { y } } = chart;
      const zones = [
        { min: 0, max: 0.8, color: '#8b949e18' },
        { min: 0.8, max: 1.3, color: '#3fb95018' },
        { min: 1.3, max: 1.5, color: '#d2992218' },
        { min: 1.5, max: 3, color: '#f8514918' },
      ];
      zones.forEach(zone => {
        const yTop = y.getPixelForValue(Math.min(zone.max, y.max));
        const yBot = y.getPixelForValue(Math.max(zone.min, y.min));
        if (yTop < bottom && yBot > top) {
          ctx.fillStyle = zone.color;
          ctx.fillRect(left, Math.max(yTop, top), right - left, Math.min(yBot, bottom) - Math.max(yTop, top));
        }
      });
    },
  };

  charts.acwrTrend = new Chart(document.getElementById('acwrTrend'), {
    type: 'line',
    data: {
      labels: wLoad.map(w => w.week_start),
      datasets: [{
        label: 'ACWR',
        data: wLoad.map(w => w.acwr),
        borderColor: COLORS.yellow,
        backgroundColor: COLORS.yellow + '20',
        tension: 0.3,
        fill: false,
        pointRadius: 4,
        pointBackgroundColor: wLoad.map(w => {
          if (w.load_status === 'optimal') return COLORS.green;
          if (w.load_status === 'caution') return COLORS.yellow;
          if (w.load_status === 'danger') return COLORS.red;
          return COLORS.gray;
        }),
      }],
    },
    plugins: [acwrZonePlugin],
    options: {
      ...TIME_OPTIONS,
      scales: {
        ...TIME_OPTIONS.scales,
        y: {
          ...TIME_OPTIONS.scales.y,
          suggestedMin: 0,
          suggestedMax: 2,
          title: { display: true, text: 'ACWR', color: COLORS.textSecondary },
        },
      },
      plugins: {
        ...TIME_OPTIONS.plugins,
        legend: { display: false },
        annotation: {},
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Running Form charts
// ---------------------------------------------------------------------------

function renderCadenceTrend(sessions) {
  const runs = sessions.filter(s => s.training_type === 'Running' && s.cadence_spm);
  if (!runs.length) return;

  charts.cadenceTrend = new Chart(document.getElementById('cadenceTrend'), {
    type: 'line',
    data: {
      labels: runs.map(r => r.date),
      datasets: [{
        label: 'Cadence (spm)',
        data: runs.map(r => r.cadence_spm),
        borderColor: COLORS.blue,
        tension: 0.3,
        fill: false,
        pointRadius: 3,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderGctTrend(sessions) {
  const runs = sessions.filter(s => s.training_type === 'Running' && s.ground_contact_ms);
  if (!runs.length) return;

  charts.gctTrend = new Chart(document.getElementById('gctTrend'), {
    type: 'line',
    data: {
      labels: runs.map(r => r.date),
      datasets: [{
        label: 'Ground Contact (ms)',
        data: runs.map(r => r.ground_contact_ms),
        borderColor: COLORS.orange,
        tension: 0.3,
        fill: false,
        pointRadius: 3,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderVoscTrend(sessions) {
  const runs = sessions.filter(s => s.training_type === 'Running' && s.vertical_oscillation_cm);
  if (!runs.length) return;

  charts.voscTrend = new Chart(document.getElementById('voscTrend'), {
    type: 'line',
    data: {
      labels: runs.map(r => r.date),
      datasets: [{
        label: 'Vertical Oscillation (cm)',
        data: runs.map(r => r.vertical_oscillation_cm),
        borderColor: COLORS.purple,
        tension: 0.3,
        fill: false,
        pointRadius: 3,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

// ---------------------------------------------------------------------------
// Balance charts (donuts)
// ---------------------------------------------------------------------------

function renderTypeDistribution(sessions) {
  const counts = {};
  sessions.forEach(s => {
    if (s.training_type) counts[s.training_type] = (counts[s.training_type] || 0) + 1;
  });
  const labels = Object.keys(counts);
  if (!labels.length) return;

  charts.typeDistribution = new Chart(document.getElementById('typeDistribution'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: labels.map(l => counts[l]),
        backgroundColor: labels.map(l => (TYPE_COLORS[l] || COLORS.gray) + 'cc'),
        borderColor: labels.map(l => TYPE_COLORS[l] || COLORS.gray),
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      aspectRatio: 1.8,
      plugins: {
        legend: { position: 'right', labels: { color: COLORS.text, padding: 12 } },
      },
    },
  });
}

function renderFeelingDistribution(sessions) {
  const counts = {};
  sessions.forEach(s => {
    if (s.feeling) counts[s.feeling] = (counts[s.feeling] || 0) + 1;
  });
  const order = ['Great', 'Good', 'Okay', 'Tired', 'Exhausted'];
  const labels = order.filter(f => counts[f]);
  if (!labels.length) return;

  charts.feelingDistribution = new Chart(document.getElementById('feelingDistribution'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: labels.map(l => counts[l]),
        backgroundColor: labels.map(l => (FEELING_COLORS[l] || COLORS.gray) + 'cc'),
        borderColor: labels.map(l => FEELING_COLORS[l] || COLORS.gray),
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      aspectRatio: 1.8,
      plugins: {
        legend: { position: 'right', labels: { color: COLORS.text, padding: 12 } },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Recovery charts
// ---------------------------------------------------------------------------

function renderSleepTrend(health) {
  const data = health.filter(h => h.sleep_hours);
  if (!data.length) return;

  // 7h reference line plugin
  const sleepRefPlugin = {
    id: 'sleepRef',
    beforeDraw(chart) {
      const { ctx, chartArea: { left, right }, scales: { y } } = chart;
      const yPos = y.getPixelForValue(7);
      ctx.save();
      ctx.strokeStyle = COLORS.textSecondary + '60';
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(left, yPos);
      ctx.lineTo(right, yPos);
      ctx.stroke();
      ctx.restore();
    },
  };

  charts.sleepTrend = new Chart(document.getElementById('sleepTrend'), {
    type: 'line',
    plugins: [sleepRefPlugin],
    data: {
      labels: data.map(h => h.date),
      datasets: [{
        label: 'Sleep (h)',
        data: data.map(h => h.sleep_hours),
        borderColor: COLORS.blue,
        backgroundColor: COLORS.blue + '20',
        tension: 0.3,
        fill: true,
        pointRadius: 2,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
      scales: {
        ...TIME_OPTIONS.scales,
        y: { ...TIME_OPTIONS.scales.y, suggestedMin: 5, suggestedMax: 10 },
      },
    },
  });
}

function renderRestingHrTrend(health) {
  const data = health.filter(h => h.resting_hr);
  if (!data.length) return;

  charts.restingHrTrend = new Chart(document.getElementById('restingHrTrend'), {
    type: 'line',
    data: {
      labels: data.map(h => h.date),
      datasets: [{
        label: 'Resting HR (bpm)',
        data: data.map(h => h.resting_hr),
        borderColor: COLORS.red,
        tension: 0.3,
        fill: false,
        pointRadius: 2,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

function renderBodyBatteryTrend(health) {
  const data = health.filter(h => h.body_battery);
  if (!data.length) return;

  charts.bodyBatteryTrend = new Chart(document.getElementById('bodyBatteryTrend'), {
    type: 'line',
    data: {
      labels: data.map(h => h.date),
      datasets: [{
        label: 'Body Battery',
        data: data.map(h => h.body_battery),
        borderColor: COLORS.blue,
        backgroundColor: COLORS.blue + '15',
        tension: 0.3,
        fill: true,
        pointRadius: 2,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
      scales: {
        ...TIME_OPTIONS.scales,
        y: { ...TIME_OPTIONS.scales.y, suggestedMin: 0, suggestedMax: 100 },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Activity chart
// ---------------------------------------------------------------------------

function renderStepsTrend(health) {
  const data = health.filter(h => h.steps);
  if (!data.length) return;

  charts.stepsTrend = new Chart(document.getElementById('stepsTrend'), {
    type: 'bar',
    data: {
      labels: data.map(h => h.date),
      datasets: [{
        label: 'Steps',
        data: data.map(h => h.steps),
        backgroundColor: COLORS.gray + '80',
        borderColor: COLORS.gray,
        borderWidth: 1,
      }],
    },
    options: {
      ...TIME_OPTIONS,
      aspectRatio: 3,
      plugins: { ...TIME_OPTIONS.plugins, legend: { display: false } },
    },
  });
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
