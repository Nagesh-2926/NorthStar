import {
  ArcElement, BarElement, CategoryScale, Chart as ChartJS, Filler, Legend,
  LinearScale, LineElement, PointElement, Tooltip,
} from 'chart.js';
import { Bar, Doughnut, Line } from 'react-chartjs-2';
import { Card } from './Primitives';
import { EmptyState } from './States';

ChartJS.register(ArcElement, BarElement, CategoryScale, Filler, Legend,
  LinearScale, LineElement, PointElement, Tooltip);

const palette = ['#315f55', '#94aa88', '#d0a36c', '#7f9ab0', '#bf766b', '#71817c', '#d2c9b5'];
const baseOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, padding: 18, color: '#56645f', font: { family: 'Inter, system-ui, sans-serif', size: 11 } } } },
  scales: {
    x: { grid: { display: false }, border: { display: false }, ticks: { color: '#73807b', maxRotation: 0, autoSkip: true } },
    y: { beginAtZero: true, grid: { color: '#edf0ed' }, border: { display: false }, ticks: { color: '#73807b', precision: 0 } },
  },
};

export function lineData(labels, series) {
  return { labels, datasets: series.map((item, index) => ({
    label: item.label,
    data: item.values,
    borderColor: item.color || palette[index % palette.length],
    backgroundColor: item.fill ? `${item.color || palette[index % palette.length]}22` : 'transparent',
    borderWidth: 2,
    pointRadius: 3,
    pointHoverRadius: 5,
    tension: 0.28,
    fill: Boolean(item.fill),
  })) };
}

export function barData(labels, series) {
  return { labels, datasets: series.map((item, index) => ({
    label: item.label,
    data: item.values,
    backgroundColor: item.color || palette[index % palette.length],
    borderRadius: 5,
    maxBarThickness: 42,
  })) };
}

export function ChartCard({ title, detail, data, type = 'line', emptyDescription = 'No records are available for this chart yet.' }) {
  const hasValues = data?.datasets?.some((dataset) => dataset.data?.length &&
    (type !== 'doughnut' || dataset.data.some((value) => Number(value) > 0)));
  const hasData = Boolean(data?.labels?.length && hasValues);
  const options = { ...baseOptions, plugins: { ...baseOptions.plugins,
    legend: { ...baseOptions.plugins.legend, display: (data?.datasets?.length || 0) > 1 || type === 'doughnut' } } };
  return (
    <Card className="chart-card">
      <div className="chart-heading"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div></div>
      {hasData ? <div className={`chart-area chart-${type}`}>
        {type === 'bar' ? <Bar data={data} options={options} aria-label={title} role="img" />
          : type === 'doughnut' ? <Doughnut data={data} options={{ ...options, cutout: '66%', scales: {} }} aria-label={title} role="img" />
            : <Line data={data} options={options} aria-label={title} role="img" />}
      </div> : <EmptyState title="No chart data yet" description={emptyDescription} />}
    </Card>
  );
}

export function doughnutData(labels, values) {
  return { labels, datasets: [{ data: values, backgroundColor: palette.slice(0, labels.length), borderWidth: 0, hoverOffset: 4 }] };
}
