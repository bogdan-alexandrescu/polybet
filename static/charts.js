/* Polybet Chart.js utilities */

const COLORS = {
    indigo: 'rgb(99, 102, 241)',
    cyan: 'rgb(34, 211, 238)',
    amber: 'rgb(251, 191, 36)',
    green: 'rgb(74, 222, 128)',
    red: 'rgb(248, 113, 113)',
    purple: 'rgb(192, 132, 252)',
    pink: 'rgb(244, 114, 182)',
    teal: 'rgb(45, 212, 191)',
    blue: 'rgb(96, 165, 250)',
    orange: 'rgb(251, 146, 60)',
};

const PALETTE = [
    COLORS.indigo, COLORS.cyan, COLORS.amber, COLORS.green,
    COLORS.red, COLORS.purple, COLORS.pink, COLORS.teal,
    COLORS.blue, COLORS.orange,
];

function alpha(color, a) {
    return color.replace('rgb(', 'rgba(').replace(')', `, ${a})`);
}

/* Default Chart.js config for dark theme */
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = 'rgba(148, 163, 184, 0.1)';
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.padding = 16;
Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(15, 23, 42, 0.95)';
Chart.defaults.plugins.tooltip.borderColor = 'rgba(99, 102, 241, 0.3)';
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.elements.point.radius = 2;
Chart.defaults.elements.point.hoverRadius = 5;
Chart.defaults.animation.duration = 600;

/* Formatters */
function fmtUSD(val) {
    if (val == null) return '—';
    if (Math.abs(val) >= 1e9) return '$' + (val / 1e9).toFixed(2) + 'B';
    if (Math.abs(val) >= 1e6) return '$' + (val / 1e6).toFixed(2) + 'M';
    if (Math.abs(val) >= 1e3) return '$' + (val / 1e3).toFixed(1) + 'K';
    return '$' + val.toFixed(0);
}

function fmtPct(val) {
    if (val == null) return '—';
    return (val * 100).toFixed(1) + '%';
}

function fmtChange(val) {
    if (val == null) return '—';
    const pct = (val * 100).toFixed(1);
    return val >= 0 ? '+' + pct + '%' : pct + '%';
}

function fmtNum(val) {
    if (val == null) return '—';
    return val.toLocaleString();
}

function fmtDate(val) {
    if (!val) return '—';
    return new Date(val).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
}

/* Chart factories */
function createLineChart(ctx, labels, datasets, opts = {}) {
    return new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: opts.beginAtZero !== false,
                    ticks: { callback: opts.yFmt || (v => v) },
                },
                ...(opts.y2 ? {
                    y2: {
                        position: 'right',
                        beginAtZero: true,
                        grid: { display: false },
                        ticks: { callback: opts.y2Fmt || (v => v) },
                    }
                } : {}),
            },
            plugins: {
                legend: { display: datasets.length > 1 },
                tooltip: { callbacks: { label: opts.tooltipFmt || undefined } },
            },
            ...opts.extra,
        }
    });
}

function createBarChart(ctx, labels, datasets, opts = {}) {
    return new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: opts.horizontal ? 'y' : 'x',
            scales: {
                x: {
                    grid: { display: opts.horizontal || false },
                    ticks: { callback: opts.xFmt || (v => v) },
                    stacked: opts.stacked || false,
                },
                y: {
                    beginAtZero: true,
                    grid: { display: !opts.horizontal },
                    ticks: { callback: opts.yFmt || (v => v) },
                    stacked: opts.stacked || false,
                },
            },
            plugins: {
                legend: { display: datasets.length > 1 },
                tooltip: { callbacks: { label: opts.tooltipFmt || undefined } },
            },
        }
    });
}

function createDoughnutChart(ctx, labels, data, colors) {
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: colors || PALETTE.slice(0, labels.length),
                borderWidth: 0,
                hoverOffset: 8,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: { position: 'bottom' },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((ctx.raw / total) * 100).toFixed(1);
                            return ` ${ctx.label}: ${fmtNum(ctx.raw)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

function createScatterChart(ctx, data, opts = {}) {
    return new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                data,
                backgroundColor: alpha(opts.color || COLORS.indigo, 0.5),
                pointRadius: opts.sizeField ? undefined : 3,
                pointHoverRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: opts.logX ? 'logarithmic' : 'linear',
                    title: { display: true, text: opts.xLabel || 'X' },
                    ticks: { callback: opts.xFmt || (v => v) },
                },
                y: {
                    type: opts.logY ? 'logarithmic' : 'linear',
                    title: { display: true, text: opts.yLabel || 'Y' },
                    ticks: { callback: opts.yFmt || (v => v) },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: opts.tooltipFmt || function(ctx) {
                            return `(${ctx.raw.x}, ${ctx.raw.y})`;
                        }
                    }
                },
            },
        }
    });
}

function createAreaChart(ctx, labels, datasets, opts = {}) {
    datasets.forEach((ds, i) => {
        ds.fill = true;
        ds.backgroundColor = alpha(ds.borderColor || PALETTE[i % PALETTE.length], 0.15);
        ds.borderColor = ds.borderColor || PALETTE[i % PALETTE.length];
        ds.borderWidth = 2;
        ds.tension = 0.3;
    });
    return createLineChart(ctx, labels, datasets, opts);
}

/* Loading state */
function showLoading(containerId) {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = '<div class="flex items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div></div>';
}

function hideLoading(containerId) {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = '';
}

/* Fetch helper */
async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}
