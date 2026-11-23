import { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Compass,
  Copy,
  Database,
  FileCode2,
  FolderOpen,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Terminal,
  XCircle,
} from 'lucide-react';
import {
  fetchDeltaPreview,
  fetchDiagnose,
  fetchRunDetail,
  fetchSpaceDetail,
  fetchSpaceLint,
  fetchSpaceRuns,
  fetchSpaces,
  streamAgentQuestion,
  triggerOfflineBenchmark,
} from './api';
import { HomeGuide } from './components/HomeGuide';
import { TrendChart } from './components/TrendChart';
import type {
  BenchmarkRunRecord,
  DeltaExportPreviewResponse,
  DiagnoseResponse,
  JudgeVerdict,
  LintReportResponse,
  RegressionDiff,
  SpaceDetailResponse,
  SpacesListResponse,
  StreamedAgentEvent,
} from './types';

type TabKey = 'overview' | 'benchmarks' | 'diagnose' | 'agent' | 'delta';
type PageView = 'guide' | 'workspace';

export function App() {
  const [pageView, setPageView] = useState<PageView>('guide');
  const [portfolio, setPortfolio] = useState<SpacesListResponse | null>(null);
  const [selectedSpace, setSelectedSpace] = useState<string>('');
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [detail, setDetail] = useState<SpaceDetailResponse | null>(null);
  const [lint, setLint] = useState<LintReportResponse | null>(null);
  const [runs, setRuns] = useState<BenchmarkRunRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRunRecord | null>(null);
  const [runDiff, setRunDiff] = useState<RegressionDiff | null>(null);
  const [diagnose, setDiagnose] = useState<DiagnoseResponse | null>(null);
  const [runningBmk, setRunningBmk] = useState<boolean>(false);
  const [bmkLabel, setBmkLabel] = useState<string>('');
  const [expandParaphrases, setExpandParaphrases] = useState<boolean>(false);
  const [severityFilter, setSeverityFilter] = useState<'ALL' | 'ERROR' | 'WARNING' | 'INFO'>('ALL');

  // Agent Mode SSE Playground state
  const [agentQuestion, setAgentQuestion] = useState<string>(
    'Qual foi a receita líquida por segmento no último trimestre e qual política de desconto se aplica?'
  );
  const [agentModeExec, setAgentModeExec] = useState<'STANDARD' | 'FLASH'>('STANDARD');
  const [agentJudge, setAgentJudge] = useState<'heuristic' | 'databricks' | 'openai'>('heuristic');
  const [agentLiveMode, setAgentLiveMode] = useState<boolean>(false);
  const [streaming, setStreaming] = useState<boolean>(false);
  const [streamEvents, setStreamEvents] = useState<StreamedAgentEvent[]>([]);
  const [judgeVerdict, setJudgeVerdict] = useState<JudgeVerdict | null>(null);

  // UC Delta Export state
  const [ucCatalog, setUcCatalog] = useState<string>('analytics_ops');
  const [ucSchema, setUcSchema] = useState<string>('genieops_audit');
  const [ucMode, setUcMode] = useState<'four_tables' | 'events'>('four_tables');
  const [deltaPreview, setDeltaPreview] = useState<DeltaExportPreviewResponse | null>(null);
  const [copiedSql, setCopiedSql] = useState<boolean>(false);

  const loadPortfolio = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSpaces();
      setPortfolio(data);
      if (data.spaces.length > 0 && !selectedSpace) {
        setSelectedSpace(data.spaces[0].name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadSpaceData = async (name: string) => {
    if (!name) return;
    try {
      const [det, lintRep, runsRes, diagRes] = await Promise.all([
        fetchSpaceDetail(name),
        fetchSpaceLint(name),
        fetchSpaceRuns(name),
        fetchDiagnose(name),
      ]);
      setDetail(det);
      setLint(lintRep);
      setRuns(runsRes.runs);
      setDiagnose(diagRes);
      if (runsRes.runs.length > 0) {
        const latestDetail = await fetchRunDetail(name, runsRes.runs[0].run_id);
        setSelectedRun(latestDetail.run);
        setRunDiff(latestDetail.regression_diff);
      } else {
        setSelectedRun(null);
        setRunDiff(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void loadPortfolio();
  }, []);

  useEffect(() => {
    if (selectedSpace) {
      void loadSpaceData(selectedSpace);
    }
  }, [selectedSpace]);

  useEffect(() => {
    if (activeTab === 'delta' && selectedSpace) {
      void fetchDeltaPreview(selectedSpace, ucCatalog, ucSchema, ucMode)
        .then(setDeltaPreview)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }
  }, [activeTab, selectedSpace, ucCatalog, ucSchema, ucMode]);

  const handleRunOffline = async () => {
    if (!selectedSpace) return;
    setRunningBmk(true);
    try {
      const res = await triggerOfflineBenchmark(selectedSpace, detail?.space.default_env || 'dev', {
        label: bmkLabel,
        expand_paraphrases: expandParaphrases,
      });
      setSelectedRun(res.run);
      setRunDiff(res.regression_diff);
      await loadPortfolio();
      await loadSpaceData(selectedSpace);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunningBmk(false);
    }
  };

  const handleSelectRun = async (runId: string) => {
    if (!selectedSpace) return;
    const res = await fetchRunDetail(selectedSpace, runId);
    setSelectedRun(res.run);
    setRunDiff(res.regression_diff);
    const diagRes = await fetchDiagnose(selectedSpace, runId);
    setDiagnose(diagRes);
  };

  const handleAgentStream = async () => {
    if (!selectedSpace || !agentQuestion.trim()) return;
    setStreaming(true);
    setStreamEvents([]);
    setJudgeVerdict(null);
    setError(null);
    try {
      await streamAgentQuestion(
        selectedSpace,
        {
          question: agentQuestion.trim(),
          env: detail?.space.default_env || 'dev',
          execution_mode: agentModeExec,
          live_mode: agentLiveMode,
          judge_provider: agentJudge,
        },
        {
          onEvent: (ev) => setStreamEvents((prev) => [...prev, ev]),
          onVerdict: (verdict) => setJudgeVerdict(verdict),
        }
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStreaming(false);
    }
  };

  const scoreColor = (score: number) =>
    score >= 85 ? 'text-emerald-400' : score >= 65 ? 'text-amber-400' : 'text-rose-400';

  const filteredIssues =
    lint?.issues.filter((i) => severityFilter === 'ALL' || i.severity === severityFilter) ?? [];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600/20 text-indigo-400 ring-1 ring-indigo-500/40">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white">Databricks GenieOps</h1>
              <p className="text-xs text-slate-400">
                Painel Web Local • Genie-as-Code • Health Check, Benchmarks, Agent SSE &amp; Delta Export
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <nav className="inline-flex rounded-xl border border-slate-800 bg-slate-900/90 p-1">
              <button
                onClick={() => setPageView('guide')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  pageView === 'guide'
                    ? 'bg-indigo-600 text-white shadow'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                <BookOpen className="h-3.5 w-3.5" />
                Início &amp; Tutorial
              </button>
              <button
                onClick={() => setPageView('workspace')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  pageView === 'workspace'
                    ? 'bg-indigo-600 text-white shadow'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                <Compass className="h-3.5 w-3.5" />
                Painel de Spaces
              </button>
            </nav>
            <button
              onClick={() => {
                void loadPortfolio();
                if (selectedSpace) void loadSpaceData(selectedSpace);
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-indigo-500 hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Atualizar
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {error && (
          <div className="mb-4 flex items-center justify-between rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-xs underline">
              Fechar
            </button>
          </div>
        )}

        {pageView === 'guide' ? (
          <HomeGuide
            portfolio={portfolio}
            onOpenDashboard={(spaceName) => {
              if (spaceName) setSelectedSpace(spaceName);
              setPageView('workspace');
            }}
          />
        ) : (
          <>
        {/* Portfolio KPIs */}
        {portfolio && (
          <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs font-medium text-slate-400">Genie Spaces Registrados</div>
              <div className="mt-1 text-2xl font-bold text-white">{portfolio.summary.total_spaces}</div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs font-medium text-slate-400">Health Score Médio</div>
              <div className={`mt-1 text-2xl font-bold ${scoreColor(portfolio.summary.avg_health_score)}`}>
                {portfolio.summary.avg_health_score}/100
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs font-medium text-slate-400">Assertividade Média (Último Run)</div>
              <div className="mt-1 text-2xl font-bold text-indigo-400">
                {portfolio.summary.avg_accuracy_pct !== null
                  ? `${portfolio.summary.avg_accuracy_pct}%`
                  : '—'}
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs font-medium text-slate-400">Casos de Benchmark Totais</div>
              <div className="mt-1 text-2xl font-bold text-white">{portfolio.summary.total_benchmarks}</div>
            </div>
          </section>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Sidebar Spaces */}
          <aside className="lg:col-span-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Spaces em spaces/
              </h2>
              {loading && !portfolio ? (
                <div className="text-sm text-slate-400">Carregando...</div>
              ) : (
                <div className="space-y-2">
                  {portfolio?.spaces.map((sp) => {
                    const active = sp.name === selectedSpace;
                    return (
                      <button
                        key={sp.name}
                        onClick={() => setSelectedSpace(sp.name)}
                        className={`w-full rounded-lg border p-3 text-left transition ${
                          active
                            ? 'border-indigo-500 bg-indigo-950/40'
                            : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-semibold text-white">{sp.name}</span>
                          <span className={`text-xs font-bold ${scoreColor(sp.health.score)}`}>
                            {sp.health.score}
                          </span>
                        </div>
                        <div className="mt-0.5 truncate text-xs text-slate-400">{sp.title}</div>
                        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-300">
                          <span className="rounded bg-slate-800 px-1.5 py-0.5">
                            {sp.counts.tables + sp.counts.metric_views} fontes
                          </span>
                          <span className="rounded bg-slate-800 px-1.5 py-0.5">
                            {sp.counts.benchmarks} bmks
                          </span>
                          {sp.latest_run && (
                            <span className="rounded bg-indigo-950 px-1.5 py-0.5 text-indigo-300">
                              {sp.latest_run.accuracy_pct}%
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </aside>

          {/* Main Workspace */}
          <section className="lg:col-span-9">
            {detail && (
              <div className="mb-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-xl font-bold text-white">{detail.space.title}</h2>
                      <span className="rounded-md bg-slate-800 px-2 py-0.5 font-mono text-xs text-slate-300">
                        {detail.space.name}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-400">{detail.space.description}</p>
                  </div>
                  <div className="text-right font-mono text-xs text-slate-400">
                    <div>config_hash: {detail.config_hash.slice(0, 12)}</div>
                    <div className="mt-0.5">owner: {detail.space.owner || '—'}</div>
                  </div>
                </div>

                {/* Tabs */}
                <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-800 pt-4">
                  {(
                    [
                      ['overview', 'Health Check & Fontes', ShieldCheck],
                      ['benchmarks', 'Benchmarks & Regressões', Activity],
                      ['diagnose', 'Diagnóstico (Causa Raiz)', Stethoscope],
                      ['agent', 'Agent Mode SSE + Judge', Terminal],
                      ['delta', 'Exportação Delta (UC)', Database],
                    ] as const
                  ).map(([key, label, Icon]) => (
                    <button
                      key={key}
                      onClick={() => setActiveTab(key)}
                      className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                        activeTab === key
                          ? 'bg-indigo-600 text-white shadow'
                          : 'bg-slate-800/70 text-slate-300 hover:bg-slate-800 hover:text-white'
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* TAB 1: Overview & Health Check */}
            {activeTab === 'overview' && lint && detail && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <div className="text-xs text-slate-400">Genie Health Score</div>
                    <div className={`mt-1 text-3xl font-extrabold ${scoreColor(lint.health_score)}`}>
                      {lint.health_score}/100
                    </div>
                    <div className="mt-2 flex gap-2 text-xs">
                      <span className="text-rose-400">{lint.error_count} erros</span>
                      <span className="text-amber-400">{lint.warning_count} avisos</span>
                      <span className="text-sky-400">{lint.info_count} infos</span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 md:col-span-2">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Inventário de Fontes Governadas
                    </div>
                    <div className="space-y-1.5 text-xs">
                      {detail.sources.tables.map((t) => (
                        <div key={t.identifier} className="flex items-center justify-between rounded bg-slate-950/60 px-2.5 py-1.5">
                          <span className="font-mono text-slate-200">{t.identifier}</span>
                          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
                            Table • {t.column_configs.length} cols
                          </span>
                        </div>
                      ))}
                      {detail.sources.metric_views.map((mv) => (
                        <div key={mv.identifier} className="flex items-center justify-between rounded bg-slate-950/60 px-2.5 py-1.5">
                          <span className="font-mono text-indigo-300">{mv.identifier}</span>
                          <span className="rounded bg-indigo-950 px-1.5 py-0.5 text-indigo-300">Metric View</span>
                        </div>
                      ))}
                      {detail.sources.volumes.map((v) => (
                        <div key={v.path} className="flex items-center justify-between rounded bg-slate-950/60 px-2.5 py-1.5">
                          <span className="inline-flex items-center gap-1.5 font-mono text-emerald-300">
                            <FolderOpen className="h-3.5 w-3.5" />
                            {v.path}
                          </span>
                          <span className="rounded bg-emerald-950 px-1.5 py-0.5 text-emerald-300">UC Volume</span>
                        </div>
                      ))}
                      {(detail.instructions.sql_functions ?? []).map((fn) => (
                        <div key={fn.identifier} className="flex items-center justify-between rounded bg-slate-950/60 px-2.5 py-1.5">
                          <span className="inline-flex items-center gap-1.5 font-mono text-amber-300">
                            <FileCode2 className="h-3.5 w-3.5" />
                            {fn.identifier}
                          </span>
                          <span className="rounded bg-amber-950 px-1.5 py-0.5 text-amber-300">Trusted Asset UDF</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Lint Findings */}
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-white">Achados do Linter ({filteredIssues.length})</h3>
                    <div className="flex gap-1.5">
                      {(['ALL', 'ERROR', 'WARNING', 'INFO'] as const).map((sev) => (
                        <button
                          key={sev}
                          onClick={() => setSeverityFilter(sev)}
                          className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                            severityFilter === sev
                              ? 'bg-indigo-600 text-white'
                              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          }`}
                        >
                          {sev}
                        </button>
                      ))}
                    </div>
                  </div>
                  {filteredIssues.length === 0 ? (
                    <div className="flex items-center gap-2 rounded-lg bg-emerald-950/30 p-3 text-sm text-emerald-300">
                      <CheckCircle2 className="h-4 w-4" />
                      Nenhum achado para o filtro selecionado.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filteredIssues.map((iss, idx) => (
                        <div
                          key={`${iss.code}-${idx}`}
                          className="rounded-lg border border-slate-800 bg-slate-950/60 p-3"
                        >
                          <div className="flex items-center gap-2 text-xs">
                            <span
                              className={`rounded px-1.5 py-0.5 font-bold ${
                                iss.severity === 'ERROR'
                                  ? 'bg-rose-950 text-rose-300'
                                  : iss.severity === 'WARNING'
                                    ? 'bg-amber-950 text-amber-300'
                                    : 'bg-sky-950 text-sky-300'
                              }`}
                            >
                              {iss.severity}
                            </span>
                            <span className="font-mono text-slate-400">{iss.code}</span>
                            <span className="font-mono text-indigo-300">{iss.surface}</span>
                          </div>
                          <p className="mt-1.5 text-sm text-slate-200">{iss.message}</p>
                          {iss.recommendation && (
                            <p className="mt-1 text-xs text-slate-400">Recomendação: {iss.recommendation}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: Benchmarks & Regressions */}
            {activeTab === 'benchmarks' && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex items-center gap-3">
                    <label className="text-xs font-medium text-slate-400">Rodada:</label>
                    <select
                      value={selectedRun?.run_id || ''}
                      onChange={(e) => void handleSelectRun(e.target.value)}
                      className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200"
                    >
                      {runs.map((r) => (
                        <option key={r.run_id} value={r.run_id}>
                          {r.label ? `[${r.label}] ` : ''}
                          {r.run_id} • {r.mode}/{r.env} • {r.accuracy_pct}% ({r.created_at})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={bmkLabel}
                      onChange={(e) => setBmkLabel(e.target.value)}
                      placeholder="Rótulo da rodada (ex.: Rodada 0)"
                      className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-500"
                    />
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-300">
                      <input
                        type="checkbox"
                        checked={expandParaphrases}
                        onChange={(e) => setExpandParaphrases(e.target.checked)}
                        className="rounded border-slate-700"
                      />
                      Paráfrases
                    </label>
                    <button
                      onClick={() => void handleRunOffline()}
                      disabled={runningBmk}
                      className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-60"
                    >
                      <Play className="h-3.5 w-3.5" />
                      {runningBmk ? 'Executando...' : 'Executar Benchmark Offline'}
                    </button>
                  </div>
                </div>

                <TrendChart runs={runs} />

                {runDiff && (
                  <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-xs">
                    <span className="font-semibold text-slate-300">
                      Regressão vs {runDiff.previous_run_id}:
                    </span>
                    <span
                      className={`font-bold ${
                        runDiff.delta_accuracy >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      {runDiff.delta_accuracy >= 0 ? '+' : ''}
                      {runDiff.delta_accuracy}pp
                    </span>
                    <span className="rounded bg-emerald-950 px-2 py-0.5 text-emerald-300">
                      FIXED: {runDiff.fixed.length}
                    </span>
                    <span className="rounded bg-rose-950 px-2 py-0.5 text-rose-300">
                      REGRESSED: {runDiff.regressed.length}
                    </span>
                    <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">
                      UNCHANGED: {runDiff.unchanged.length}
                    </span>
                  </div>
                )}

                {selectedRun && (
                  <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-slate-800 bg-slate-950/70 text-slate-400">
                        <tr>
                          <th className="px-4 py-3">Case</th>
                          <th className="px-4 py-3">Pergunta</th>
                          <th className="px-4 py-3">Modo</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3 text-right">Latência</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/80">
                        {selectedRun.items.map((it) => (
                          <tr key={it.case_id} className="hover:bg-slate-800/30">
                            <td className="px-4 py-3 font-mono text-slate-300">{it.case_id}</td>
                            <td className="px-4 py-3 text-slate-200">
                              <div>{it.question}</div>
                              {it.error_message && (
                                <div className="mt-1 text-[11px] text-rose-300">{it.error_message}</div>
                              )}
                            </td>
                            <td className="px-4 py-3 uppercase text-slate-400">{it.mode}</td>
                            <td className="px-4 py-3">
                              <span
                                className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-semibold ${
                                  it.status === 'GOOD'
                                    ? 'bg-emerald-950 text-emerald-300'
                                    : it.status === 'BAD'
                                      ? 'bg-rose-950 text-rose-300'
                                      : 'bg-amber-950 text-amber-300'
                                }`}
                              >
                                {it.status === 'GOOD' ? (
                                  <CheckCircle2 className="h-3 w-3" />
                                ) : it.status === 'BAD' ? (
                                  <XCircle className="h-3 w-3" />
                                ) : (
                                  <AlertTriangle className="h-3 w-3" />
                                )}
                                {it.status}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-slate-400">
                              {it.latency_ms.toFixed(1)} ms
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: Root-Cause Diagnosis */}
            {activeTab === 'diagnose' && diagnose && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="space-y-3 lg:col-span-8">
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <h3 className="text-sm font-semibold text-white">
                      Diagnóstico de Falhas ({diagnose.total_failures}) — Run {diagnose.run_id || 'N/A'}
                    </h3>
                    {diagnose.total_failures === 0 ? (
                      <div className="mt-3 flex items-center gap-2 rounded-lg bg-emerald-950/30 p-3 text-sm text-emerald-300">
                        <CheckCircle2 className="h-4 w-4" />
                        Nenhuma falha (status=BAD) encontrada nesta rodada.
                      </div>
                    ) : (
                      <div className="mt-3 space-y-3">
                        {diagnose.diagnoses.map((d) => (
                          <div key={d.case_id} className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-xs font-bold text-rose-300">
                                {d.case_id} • {d.root_cause_class}
                              </span>
                              <span className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
                                Confiança: {d.confidence}
                              </span>
                            </div>
                            <p className="mt-1 text-sm text-slate-200">{d.question}</p>
                            <div className="mt-2 rounded bg-emerald-950/30 p-2 text-xs text-emerald-300">
                              <strong>Alavanca recomendada:</strong> {d.recommended_lever} — {d.proposed_action}
                            </div>
                            <div className="mt-1.5 text-xs text-amber-300">
                              <strong>Evitar:</strong> {d.avoid_antipattern}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="lg:col-span-4">
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-indigo-300">
                      Hierarquia Oficial Databricks
                    </h3>
                    <p className="mt-1 text-xs text-slate-400">
                      Corrija sempre pela menor superfície estruturada; text_instructions é último recurso.
                    </p>
                    <ol className="mt-3 space-y-2 text-xs text-slate-300">
                      {diagnose.hierarchy.map((step) => (
                        <li key={step} className="rounded-lg bg-slate-950/70 px-2.5 py-2">
                          {step}
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 4: Agent Mode SSE Playground + LLM-as-a-Judge */}
            {activeTab === 'agent' && (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-white">
                      Agent Mode API Streaming (SSE) + LLM-as-a-Judge Plugável
                    </h3>
                    <label className="inline-flex items-center gap-2 text-xs text-slate-300">
                      <input
                        type="checkbox"
                        checked={agentLiveMode}
                        onChange={(e) => setAgentLiveMode(e.target.checked)}
                        className="rounded border-slate-700"
                      />
                      Conectar ao Databricks real (requer perfil autenticado + space_id)
                    </label>
                  </div>

                  <textarea
                    rows={2}
                    value={agentQuestion}
                    onChange={(e) => setAgentQuestion(e.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    placeholder="Digite uma pergunta analítica ou documental para o Genie Agent..."
                  />

                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-3 text-xs">
                      <select
                        value={agentModeExec}
                        onChange={(e) => setAgentModeExec(e.target.value as 'STANDARD' | 'FLASH')}
                        className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-200"
                      >
                        <option value="STANDARD">Execution: STANDARD</option>
                        <option value="FLASH">Execution: FLASH</option>
                      </select>
                      <select
                        value={agentJudge}
                        onChange={(e) =>
                          setAgentJudge(e.target.value as 'heuristic' | 'databricks' | 'openai')
                        }
                        className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-200"
                      >
                        <option value="heuristic">Judge: Heuristic Rubric (Local)</option>
                        <option value="databricks">Judge: Databricks FMAPI</option>
                        <option value="openai">Judge: OpenAI-Compatible</option>
                      </select>
                    </div>
                    <button
                      onClick={() => void handleAgentStream()}
                      disabled={streaming}
                      className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-60"
                    >
                      <Play className="h-3.5 w-3.5" />
                      {streaming ? 'Streaming SSE...' : 'Executar Stream SSE'}
                    </button>
                  </div>
                </div>

                {judgeVerdict && (
                  <div
                    className={`rounded-xl border p-4 ${
                      judgeVerdict.passed
                        ? 'border-emerald-500/40 bg-emerald-950/30'
                        : 'border-rose-500/40 bg-rose-950/30'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-bold text-white">
                        Veredito LLM-as-a-Judge ({judgeVerdict.provider}/{judgeVerdict.model})
                      </span>
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-bold ${
                          judgeVerdict.passed
                            ? 'bg-emerald-900 text-emerald-200'
                            : 'bg-rose-900 text-rose-200'
                        }`}
                      >
                        {judgeVerdict.passed ? 'APROVADO' : 'REPROVADO'} • {judgeVerdict.score}/100
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs text-slate-200">{judgeVerdict.reasoning}</p>
                  </div>
                )}

                {streamEvents.length > 0 && (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Linha do Tempo de Eventos SSE ({streamEvents.length})
                    </h4>
                    <div className="space-y-2">
                      {streamEvents.map((ev, idx) => (
                        <div key={idx} className="rounded-lg border border-slate-800 bg-slate-950/80 p-3">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-mono font-semibold text-indigo-300">{ev.event}</span>
                            {ev.timestamp_ms !== undefined && (
                              <span className="font-mono text-slate-500">{ev.timestamp_ms} ms</span>
                            )}
                          </div>
                          <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-slate-300">
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 5: UC Delta Export */}
            {activeTab === 'delta' && (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex flex-wrap items-end gap-3">
                    <div>
                      <label className="block text-xs text-slate-400">Catalog UC</label>
                      <input
                        value={ucCatalog}
                        onChange={(e) => setUcCatalog(e.target.value)}
                        className="mt-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-100"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-slate-400">Schema UC</label>
                      <input
                        value={ucSchema}
                        onChange={(e) => setUcSchema(e.target.value)}
                        className="mt-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-100"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-slate-400">Schema Oficial Databricks</label>
                      <select
                        value={ucMode}
                        onChange={(e) => setUcMode(e.target.value as 'four_tables' | 'events')}
                        className="mt-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100"
                      >
                        <option value="four_tables">4 Tabelas (runs / config / eval / repair)</option>
                        <option value="events">Tabela Única Append-Only (genie_opt_events)</option>
                      </select>
                    </div>
                    {deltaPreview && (
                      <button
                        onClick={() => {
                          void navigator.clipboard.writeText(deltaPreview.sql);
                          setCopiedSql(true);
                          setTimeout(() => setCopiedSql(false), 1800);
                        }}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
                      >
                        <Copy className="h-3.5 w-3.5" />
                        {copiedSql ? 'Copiado!' : 'Copiar SQL'}
                      </button>
                    )}
                  </div>
                </div>

                {deltaPreview && (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
                      <span className="inline-flex items-center gap-1.5 font-semibold text-slate-200">
                        <FileCode2 className="h-4 w-4 text-indigo-400" />
                        Preview SQL Delta ({deltaPreview.ddl_count} DDL, {deltaPreview.dml_count} MERGE,{' '}
                        {deltaPreview.runs_exported} rodadas)
                      </span>
                      <span className="font-mono">
                        CLI: genieops export-delta {selectedSpace} --catalog {ucCatalog} --schema {ucSchema}
                      </span>
                    </div>
                    <pre className="max-h-[460px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-4 font-mono text-[11px] leading-relaxed text-emerald-300">
                      {deltaPreview.sql}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
