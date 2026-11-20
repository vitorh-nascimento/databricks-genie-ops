import type { BenchmarkRunRecord } from '../types';

interface Props {
  runs: BenchmarkRunRecord[];
}

export function TrendChart({ runs }: Props) {
  const ordered = [...runs].reverse();
  if (ordered.length === 0) {
    return (
      <div className="flex h-44 items-center justify-center rounded-xl border border-slate-800 bg-slate-900/50 text-sm text-slate-400">
        Execute um benchmark para visualizar a tendência histórica de assertividade e latência.
      </div>
    );
  }

  const width = 640;
  const height = 180;
  const padX = 44;
  const padY = 22;
  const plotW = width - padX * 2;
  const plotH = height - padY * 2;

  const points = ordered.map((run, idx) => {
    const x = ordered.length === 1 ? padX + plotW / 2 : padX + (idx / (ordered.length - 1)) * plotW;
    const y = padY + plotH - (Math.max(0, Math.min(100, run.accuracy_pct)) / 100) * plotH;
    return { x, y, run };
  });

  const pathD = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const areaD =
    points.length > 1
      ? `${pathD} L ${points[points.length - 1].x.toFixed(1)} ${(padY + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padY + plotH).toFixed(1)} Z`
      : '';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Tendência de Assertividade (%) — Últimas {ordered.length} Execuções
        </span>
        <span className="text-xs text-emerald-400">Meta Prod: &gt;= 90%</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full">
        <defs>
          <linearGradient id="accGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {[0, 50, 90, 100].map((tick) => {
          const y = padY + plotH - (tick / 100) * plotH;
          return (
            <g key={tick}>
              <line
                x1={padX}
                x2={width - padX}
                y1={y}
                y2={y}
                stroke={tick === 90 ? '#10b981' : '#1e293b'}
                strokeDasharray={tick === 90 ? '4 4' : undefined}
                strokeWidth="1"
              />
              <text x={padX - 8} y={y + 4} textAnchor="end" className="fill-slate-400 text-[10px]">
                {tick}%
              </text>
            </g>
          );
        })}

        {areaD && <path d={areaD} fill="url(#accGrad)" />}
        {points.length > 1 && (
          <path d={pathD} fill="none" stroke="#818cf8" strokeWidth="2.5" strokeLinejoin="round" />
        )}

        {points.map((pt) => (
          <g key={pt.run.run_id}>
            <circle cx={pt.x} cy={pt.y} r="4.5" fill="#6366f1" stroke="#e0e7ff" strokeWidth="1.5" />
            <title>
              {`${pt.run.run_id} (${pt.run.mode}/${pt.run.env}): ${pt.run.accuracy_pct}% | P50=${pt.run.p50_latency_ms}ms`}
            </title>
          </g>
        ))}
      </svg>
    </div>
  );
}
