import dayjs from 'dayjs';

function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

export function buildTrendLabel(value = new Date()) {
  return dayjs(value).format('HH:mm:ss');
}

export function appendMetricHistory(history, sample, limit = 12) {
  if (!sample || typeof sample !== 'object') return history || [];

  const next = { label: sample.label || buildTrendLabel() };
  let hasNumericValue = false;

  Object.entries(sample).forEach(([key, value]) => {
    if (key === 'label') return;
    const numeric = toNumber(value);
    next[key] = numeric;
    if (numeric !== null) hasNumericValue = true;
  });

  if (!hasNumericValue) return history || [];

  return [...(history || []), next].slice(-Math.max(1, limit));
}

export function buildSparklineGeometry(history, dataKey, options = {}) {
  const width = options.width || 220;
  const height = options.height || 72;
  const paddingX = options.paddingX || 6;
  const paddingY = options.paddingY || 8;

  const validPoints = (history || [])
    .map((item, index) => ({
      index,
      value: toNumber(item?.[dataKey]),
    }))
    .filter(item => item.value !== null);

  if (validPoints.length === 0) {
    return {
      linePoints: '',
      areaPoints: '',
      lastPoint: null,
      min: null,
      max: null,
    };
  }

  const values = validPoints.map(item => item.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const innerWidth = width - paddingX * 2;
  const innerHeight = height - paddingY * 2;
  const constantSeries = min === max;

  const svgPoints = validPoints.map((item, pointIndex) => {
    const x = validPoints.length === 1
      ? width / 2
      : paddingX + (innerWidth * pointIndex) / (validPoints.length - 1);
    const y = constantSeries
      ? paddingY + innerHeight / 2
      : paddingY + innerHeight - ((item.value - min) / (max - min)) * innerHeight;
    return {
      x: Number(x.toFixed(2)),
      y: Number(y.toFixed(2)),
      value: item.value,
    };
  });

  const linePoints = svgPoints.map(point => `${point.x},${point.y}`).join(' ');
  const areaPoints = [
    `${svgPoints[0].x},${height - paddingY}`,
    ...svgPoints.map(point => `${point.x},${point.y}`),
    `${svgPoints[svgPoints.length - 1].x},${height - paddingY}`,
  ].join(' ');

  return {
    linePoints,
    areaPoints,
    lastPoint: svgPoints[svgPoints.length - 1],
    min,
    max,
  };
}

export function getTrendDelta(history, dataKey) {
  const values = (history || [])
    .map(item => toNumber(item?.[dataKey]))
    .filter(value => value !== null);

  if (values.length < 2) return null;
  return values[values.length - 1] - values[0];
}
