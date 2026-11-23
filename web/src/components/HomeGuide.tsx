import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  Compass,
  Copy,
  Database,
  FileCode2,
  GitBranch,
  Layers,
  Lock,
  Rocket,
  ShieldCheck,
  Sparkles,
  Terminal,
} from 'lucide-react';
import type { SpacesListResponse } from '../types';

interface HomeGuideProps {
  portfolio: SpacesListResponse | null;
  onOpenDashboard: (spaceName?: string) => void;
}

interface CommandSnippet {
  phase: 'Setup' | 'Curadoria' | 'Benchmark' | 'Deploy & Prod';
  title: string;
  command: string;
  description: string;
}

const CLI_COMMANDS: CommandSnippet[] = [
  {
    phase: 'Setup',
    title: 'Autenticar workspace da empresa (OAuth CLI)',
    command: 'databricks auth login --host https://SEU-WORKSPACE.cloud.databricks.com --profile empresa-dev',
    description: 'Grava o perfil no ~/.databrickscfg local sem nunca salvar tokens ou senhas no Git.',
  },
  {
    phase: 'Setup',
    title: 'Importar um Genie Space já existente',
    command: 'genieops pull <SPACE_ID> --profile empresa-dev --name meu_dominio',
    description: 'Baixa o Space atual do Databricks e gera automaticamente os 4 arquivos YAML em spaces/meu_dominio/.',
  },
  {
    phase: 'Setup',
    title: 'Criar um Genie Space declarativo do zero',
    command: 'genieops init meu_dominio --title "Vendas Corporativas" --catalog prod_cat --schema gold_vendas',
    description: 'Gera scaffold completo (space.yaml, sources.yaml, instructions.yaml, benchmarks.yaml).',
  },
  {
    phase: 'Curadoria',
    title: 'Profiling read-only + AST de queries reais',
    command: 'genieops profile meu_dominio --env dev --query-history',
    description: 'Analisa cardinalidade e faz parsing AST (sqlglot) em system.query.history sugerindo joins, filtros e entity matching.',
  },
  {
    phase: 'Curadoria',
    title: 'Gerar COMMENTs para o Unity Catalog',
    command: 'genieops uc-comments meu_dominio --env dev -o .genieops/staging/uc_comments.sql',
    description: 'Gera script SQL revisável (COMMENT ON TABLE / ALTER COLUMN COMMENT) a partir de sources.yaml.',
  },
  {
    phase: 'Curadoria',
    title: 'Gerar kit de estudo Star Schema + Trusted Assets',
    command: 'genieops seed-star-schema --catalog analytics_dev --schema sales_gold -o examples/meu_estudo',
    description: 'Cria gerador de base fictícia com armadilhas de negócio, DDL de COMMENTs, SQL Functions e playbook 0→4.',
  },
  {
    phase: 'Curadoria',
    title: 'Genie Health Check (Linter + EXPLAIN real)',
    command: 'genieops lint meu_dominio --validate-sql --env dev --strict',
    description: 'Audita boas práticas, colunas nuas, Metric Views, sql_functions, Benchmark Leakage e executa EXPLAIN read-only.',
  },
  {
    phase: 'Benchmark',
    title: 'Rodar benchmark offline (CI / custo zero)',
    command: 'genieops benchmark meu_dominio --env dev --mode offline --expand-paraphrases --label "CI Check"',
    description: 'Valida estrutura e referências dos SQLs e paráfrases sem custo de warehouse.',
  },
  {
    phase: 'Benchmark',
    title: 'Rodar benchmark real ao vivo (Result Set)',
    command: 'genieops benchmark meu_dominio --env dev --mode live --expand-paraphrases --label "Rodada 2 - +Text Instructions"',
    description: 'Pergunta ao Genie real, executa SQL esperado vs gerado e valida equivalência matemática dos resultados.',
  },
  {
    phase: 'Benchmark',
    title: 'Diagnosticar causa raiz das falhas',
    command: 'genieops diagnose meu_dominio',
    description: 'Classifica cada falha pela hierarquia oficial de 8 camadas Databricks e propõe a menor alavanca estruturada.',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Comparar local vs remoto antes de publicar',
    command: 'genieops diff meu_dominio --env dev',
    description: 'Exibe unified diff estruturado entre o YAML local compilado e o Genie Space publicado no Databricks.',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Publicar com backup automático de rollback',
    command: 'genieops deploy meu_dominio --env dev --persist-id',
    description: 'Valida com linter, salva backup JSON pré-update e executa create-space ou update-space direto pela CLI.',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Promover dev → qa → prod remapeando tudo',
    command: 'genieops migrate meu_dominio --from dev --to prod --deploy',
    description: 'Remapeia catalog, schema, /Volumes/... e sql_functions em todas as superfícies e publica em produção.',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Persistir histórico em tabelas Delta no UC',
    command: 'genieops export-delta meu_dominio --catalog analytics_ops --schema genieops_audit --execute',
    description: 'Executa DDL + MERGE INTO idempotente nas tabelas oficiais genie_opt_* (dry-run por padrão sem --execute).',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Coletar feedbacks negativos de produção',
    command: 'genieops harvest-feedback meu_dominio --env prod --include-audit --days 30',
    description: 'Extrai perguntas que falharam ou receberam thumbs-down (API + system.access.audit) com deduplicação semântica.',
  },
  {
    phase: 'Deploy & Prod',
    title: 'Gerar documentação técnica e executiva',
    command: 'genieops docs meu_dominio',
    description: 'Gera SPEC_TECNICA.md, RELATORIO_EXECUTIVO.md/.html (tabela de evolução da acurácia) e GUIA_USUARIO.md.',
  },
];

const WORKPLACE_STEPS = [
  {
    step: '01',
    title: 'Pré-requisitos & Autenticação Segura (Zero Segredos no Git)',
    subtitle: 'Prepare a máquina local ou esteira CI/CD da empresa em 2 minutos.',
    bullets: [
      'Instale Python 3.12+, Databricks CLI (>= v1.0.0) e clone o repositório com `pip install -e ".[dev]"`.',
      'Autentique via OAuth interativo do Databricks CLI (`databricks auth login --host <URL> --profile empresa-dev`). Tokens ficam apenas no `~/.databrickscfg` local.',
      'Em pipelines CI/CD (GitHub Actions, Azure DevOps, GitLab), use Service Principal (OAuth M2M) via variáveis de ambiente descritas em `.env.example`.',
      'Não é necessário `databricks.yml` (DABs): o `genieops deploy` fala direto com a Genie API via Databricks CLI usando os perfis em `env/*.yaml` e `space.yaml`.',
    ],
    cmd: 'databricks auth login --host https://SEU-WORKSPACE.cloud.databricks.com --profile empresa-dev',
  },
  {
    step: '02',
    title: 'Trazer seu Genie Space para Código (Pull ou Init)',
    subtitle: 'Escolha se vai versionar um Genie já existente na empresa ou começar um domínio novo.',
    bullets: [
      'Já existe um Genie Space no workspace? Use `genieops pull <SPACE_ID> --profile empresa-dev --name vendas_b2b` para converter tudo para os 4 YAMLs automaticamente.',
      'Começando do zero? Rode `genieops init vendas_b2b --catalog cat_dev --schema gold_vendas` e ajuste `space.yaml` com o `warehouse_id` e `parent_path` do seu time.',
      'Acelere a descoberta rodando `genieops profile vendas_b2b --env dev --query-history`: o motor analisa cardinalidade e faz parsing AST (`sqlglot`) nas queries reais dos analistas para sugerir `entity_matching`, colunas a excluir, `join_specs` e medidas.',
    ],
    cmd: 'genieops pull 01ef... --profile empresa-dev --name vendas_b2b',
  },
  {
    step: '03',
    title: 'Organizar Governança em 4 Arquivos YAML Revisáveis em PR',
    subtitle: 'Cada arquivo separa claramente responsabilidade de Engenharia de Dados vs Negócio.',
    bullets: [
      '`space.yaml` — Metadados, dono, público-alvo e mapa de ambientes (`dev`, `qa`, `prod`: `profile`, `warehouse_id`, `catalog`, `schema`, `parent_path`).',
      '`sources.yaml` — Tabelas, Metric Views (`MEASURE()`), UC Volumes (PDFs/manuais) e `column_configs` (descrições, sinônimos, `enable_entity_matching` seletivo e `exclude: true` para colunas técnicas).',
      '`instructions.yaml` — `join_specs`, `sql_snippets` (`measures`/`filters`/`expressions`), `sql_functions` (Trusted Assets UC), `example_question_sqls` (sem leakage!) e `text_instructions` globais curtas.',
      '`benchmarks.yaml` — 30+ perguntas reais de negócio com `ground_truth_sql`, `paraphrases` (2–4 variações por pergunta) e `evaluation_note` para casos documentais em Agent Mode.',
    ],
    cmd: 'genieops lint vendas_b2b --validate-sql --env dev --strict',
  },
  {
    step: '04',
    title: 'Executar Curadoria Científica por Rodadas (Hierarquia Oficial)',
    subtitle: 'Meça cada melhoria objetivamente e nunca introduza regressões silenciosas.',
    bullets: [
      'Rodada 0 (Baseline): publique só as tabelas e rode `genieops benchmark ... --mode live --label "Rodada 0 - Só tabelas"`.',
      'Rodada 1 (+Metadados): gere e aplique `genieops uc-comments` no Unity Catalog + preencha `column_configs` em `sources.yaml`.',
      'Rodada 2 (+Estrutura): adicione `join_specs`, `sql_snippets` e `text_instructions` curtas (sempre preferindo a menor superfície estruturada!).',
      'Rodada 3 & 4 (+Exemplos e Trusted Assets): adicione `example_question_sqls` e `sql_functions` — sempre validando regressão (`regressed = 0`) porque Trusted Assets muito genéricos podem sequestrar perguntas de outro grão!',
    ],
    cmd: 'genieops benchmark vendas_b2b --env dev --mode live --expand-paraphrases --label "Rodada 2 - +Text Instructions"',
  },
  {
    step: '05',
    title: 'Promover com Segurança (dev → qa → prod) e Fechar o Flywheel',
    subtitle: 'Promoção determinística com backup de rollback e melhoria contínua via feedback real.',
    bullets: [
      'Antes de publicar, confira o diff com `genieops diff vendas_b2b --env prod`.',
      'Promova entre workspaces com `genieops migrate vendas_b2b --from dev --to prod --deploy`: o migrador remapeia `catalog`, `schema`, `/Volumes/...` e `sql_functions` em todas as superfícies automaticamente.',
      'Todo `update-space` grava antes um backup JSON completo em `.genieops/backups/<space>/<env>/` para rollback imediato.',
      'Em produção, rode periodicamente `genieops harvest-feedback vendas_b2b --env prod --include-audit` para transformar dúvidas com falha/thumbs-down em novos casos de benchmark.',
    ],
    cmd: 'genieops migrate vendas_b2b --from dev --to prod --deploy',
  },
  {
    step: '06',
    title: 'Auditoria Executiva: Tabelas Delta no UC & Relatórios Automáticos',
    subtitle: 'Entregue governança e transparência para liderança e InfoSec.',
    bullets: [
      'Exporte todas as rodadas do SQLite local (`.genieops/history.db`) para as 4 tabelas Delta oficiais (`genie_opt_runs`, `genie_opt_config_versions`, `genie_opt_eval_results`, `genie_opt_repair_analysis`) com `genieops export-delta ... --execute`.',
      'Gere automaticamente `SPEC_TECNICA.md`, `RELATORIO_EXECUTIVO.md`, `relatorio_executivo.html` (com a Tabela de Evolução da Acurácia por Rodada) e `GUIA_USUARIO.md` via `genieops docs`.',
      'Use o Painel Web Local (`genieops serve` ou `.\\start.ps1`) em reuniões de revisão com o time para inspecionar curvas de acurácia, causas-raiz e testar perguntas em Agent Mode SSE.',
    ],
    cmd: 'genieops export-delta vendas_b2b --catalog analytics_ops --schema genieops_audit --execute && genieops docs vendas_b2b',
  },
];

const OFFICIAL_HIERARCHY = [
  { n: 1, name: 'Escopo & Descrições de Fontes', desc: 'Mantenha <= 5 tabelas/Metric Views focadas por domínio com descrição clara de grão.' },
  { n: 2, name: 'column_configs (Descrições, Sinônimos, Exclude)', desc: 'Oculte IDs/hashes com exclude: true e documente colunas de negócio e sinônimos.' },
  { n: 3, name: 'Entity Matching & Format Assistance Seletivos', desc: 'Ative apenas em dimensões categóricas que usuários filtram pelo nome (nunca em IDs/medidas).' },
  { n: 4, name: 'Metric Views Governadas (MEASURE())', desc: 'Prefira KPIs governados no Unity Catalog em vez de duplicar fórmulas em texto.' },
  { n: 5, name: 'join_specs Validados (PK/FK e Grão)', desc: 'Declare relacionamentos com colunas sempre qualificadas por alias.' },
  { n: 6, name: 'sql_snippets & sql_functions (Trusted Assets)', desc: 'Reutilize filtros/medidas e UDFs para métricas não-aditivas (sempre testando regressão de roteamento!).' },
  { n: 7, name: 'example_question_sqls Representativos', desc: 'Um exemplo por formato de query (sem copiar perguntas/SQLs de benchmarks.yaml).' },
  { n: 8, name: 'text_instructions Globais Curtas (Último Recurso)', desc: 'Apenas regras globais de idioma/desambiguação (máximo 1 bloco; nunca regra hardcoded de valor).' },
];

const PROD_CHECKLIST = [
  { id: 'auth', text: 'Perfil Databricks CLI autenticado via OAuth (ou Service Principal M2M no CI), zero tokens no Git.' },
  { id: 'lint', text: 'genieops lint <space> --validate-sql --env prod --strict com 0 erros e Health Score >= 85/100.' },
  { id: 'uc_comments', text: 'COMMENTs de tabela e coluna aplicados no Unity Catalog (genieops uc-comments).' },
  { id: 'benchmarks', text: 'Suíte com >= 30 perguntas reais + paráfrases (easy/medium/hard) e acurácia >= 90% em modo live/agent.' },
  { id: 'no_reg', text: 'Zero regressões (regressed = 0) frente à última versão homologada.' },
  { id: 'delta_docs', text: 'Histórico exportado para Delta UC (genie_opt_*) e relatórios (SPEC_TECNICA + RELATORIO_EXECUTIVO) revisados no PR.' },
];

const STORAGE_KEY = 'genieops_workplace_checklist_v1';

export function HomeGuide({ portfolio, onOpenDashboard }: HomeGuideProps) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<'Todos' | CommandSnippet['phase']>('Todos');
  const [checkedItems, setCheckedItems] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(checkedItems));
    } catch {
      // ignora erro de storage em modo privado
    }
  }, [checkedItems]);

  const copyText = (key: string, text: string) => {
    void navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey((curr) => (curr === key ? null : curr)), 1800);
  };

  const toggleCheck = (id: string) => {
    setCheckedItems((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const completedChecks = PROD_CHECKLIST.filter((c) => checkedItems[c.id]).length;
  const visibleCommands = CLI_COMMANDS.filter((c) => phaseFilter === 'Todos' || c.phase === phaseFilter);

  return (
    <div className="space-y-8">
      {/* Hero Banner */}
      <section className="relative overflow-hidden rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-slate-900 via-indigo-950/40 to-slate-900 p-6 sm:p-8">
        <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-center">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-3 py-1 text-xs font-semibold text-indigo-300">
              <Sparkles className="h-3.5 w-3.5" />
              Genie-as-Code • Guia Completo de Uso &amp; Adoção Corporativa
            </div>
            <h2 className="mt-3 text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              Bem-vindo ao Databricks GenieOps
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-300">
              Este toolkit transforma <strong>Databricks Genie Spaces / Genie Agents</strong> em código declarativo
              versionado no Git, com auditoria automatizada (Health Check), benchmarks com equivalência matemática de
              Result Sets, controle de regressão por rodada, deploy com backup automático e persistência em tabelas
              Delta no Unity Catalog.
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                onClick={() => onOpenDashboard()}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-900/40 transition hover:bg-indigo-500"
              >
                <Compass className="h-4 w-4" />
                Abrir Painel de Spaces
                <ArrowRight className="h-4 w-4" />
              </button>
              <a
                href="#guia-trabalho"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-indigo-500 hover:text-white"
              >
                <Rocket className="h-4 w-4 text-indigo-400" />
                Como levar para o meu trabalho
              </a>
              <a
                href="#catalogo-cli"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-indigo-500 hover:text-white"
              >
                <Terminal className="h-4 w-4 text-emerald-400" />
                Referência Rápida CLI
              </a>
            </div>
          </div>

          {/* Live Portfolio Status Card */}
          {portfolio && (
            <div className="min-w-[260px] rounded-xl border border-slate-800 bg-slate-950/80 p-4">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Estado Atual deste Workspace
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-slate-900/90 p-2.5">
                  <div className="text-[11px] text-slate-400">Spaces</div>
                  <div className="text-xl font-bold text-white">{portfolio.summary.total_spaces}</div>
                </div>
                <div className="rounded-lg bg-slate-900/90 p-2.5">
                  <div className="text-[11px] text-slate-400">Health Médio</div>
                  <div className="text-xl font-bold text-emerald-400">
                    {portfolio.summary.avg_health_score}/100
                  </div>
                </div>
                <div className="rounded-lg bg-slate-900/90 p-2.5">
                  <div className="text-[11px] text-slate-400">Benchmarks</div>
                  <div className="text-xl font-bold text-indigo-300">{portfolio.summary.total_benchmarks}</div>
                </div>
                <div className="rounded-lg bg-slate-900/90 p-2.5">
                  <div className="text-[11px] text-slate-400">Assertividade</div>
                  <div className="text-xl font-bold text-sky-400">
                    {portfolio.summary.avg_accuracy_pct !== null
                      ? `${portfolio.summary.avg_accuracy_pct}%`
                      : '—'}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Section 1: Mental Model */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-indigo-400" />
          <h3 className="text-lg font-bold text-white">1. Como Funciona (Mapa Mental em 3 Blocos)</h3>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-indigo-300">
              <FileCode2 className="h-4 w-4" />
              Bloco 1 • Código no Seu PC / Git
            </div>
            <h4 className="mt-2 font-semibold text-white">4 YAMLs Declarativos por Space</h4>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              Em vez de editar o Genie manualmente na UI (sem histórico e sem code review), cada domínio vive em{' '}
              <code className="rounded bg-slate-950 px-1 py-0.5 text-indigo-300">spaces/&lt;nome&gt;/</code> dividido em{' '}
              <code>space.yaml</code>, <code>sources.yaml</code>, <code>instructions.yaml</code> e{' '}
              <code>benchmarks.yaml</code>.
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-300">
              <ShieldCheck className="h-4 w-4" />
              Bloco 2 • Motor GenieOps (Local &amp; CI)
            </div>
            <h4 className="mt-2 font-semibold text-white">Linter, Compilador v2 e Benchmark</h4>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              Compila com UUID5 determinístico para o JSON oficial <code>serialized_space</code> v2, valida SQLs via{' '}
              <code>EXPLAIN</code> read-only, bloqueia <em>Benchmark Leakage</em>, compara resultados matematicamente
              (Result Set) e detecta regressões entre rodadas.
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-amber-300">
              <Database className="h-4 w-4" />
              Bloco 3 • Databricks na Nuvem
            </div>
            <h4 className="mt-2 font-semibold text-white">Deploy Direto + Tabelas Delta UC</h4>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              Conecta via perfis do Databricks CLI (sem precisar de <code>databricks.yml</code>), salva backup pré-deploy,
              aplica <code>create-space</code>/<code>update-space</code>, gera <code>COMMENT ON</code> no Unity Catalog e
              exporta todo histórico de acurácia para <code>genie_opt_*</code>.
            </p>
          </div>
        </div>
      </section>

      {/* Section 2: Step-by-Step Workplace Adoption Guide */}
      <section id="guia-trabalho" className="space-y-4 scroll-mt-24">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 text-indigo-400" />
            <h3 className="text-lg font-bold text-white">
              2. Passo a Passo Completo para Levar ao Ambiente de Trabalho
            </h3>
          </div>
          <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
            6 etapas • do zero até produção
          </span>
        </div>

        <div className="space-y-4">
          {WORKPLACE_STEPS.map((st) => (
            <div
              key={st.step}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 transition hover:border-slate-700"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600/20 font-mono text-xs font-extrabold text-indigo-300 ring-1 ring-indigo-500/40">
                    {st.step}
                  </span>
                  <div>
                    <h4 className="text-sm font-bold text-white">{st.title}</h4>
                    <p className="text-xs text-slate-400">{st.subtitle}</p>
                  </div>
                </div>
              </div>

              <ul className="mt-3 space-y-1.5 pl-11 text-xs leading-relaxed text-slate-300">
                {st.bullets.map((b, i) => (
                  <li key={i} className="list-disc">
                    {b}
                  </li>
                ))}
              </ul>

              <div className="mt-3 ml-11 flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950 px-3 py-2">
                <code className="overflow-x-auto font-mono text-[11px] text-sky-300">{st.cmd}</code>
                <button
                  onClick={() => copyText(`step-${st.step}`, st.cmd)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-200 hover:bg-indigo-600 hover:text-white"
                >
                  {copiedKey === `step-${st.step}` ? (
                    <>
                      <Check className="h-3 w-3 text-emerald-300" />
                      Copiado
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" />
                      Copiar
                    </>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Section 3: Official 8-Layer Hierarchy + Security Guarantees */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 lg:col-span-7">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-indigo-400" />
            <h3 className="text-base font-bold text-white">
              3. Hierarquia Oficial de Curadoria (Menor Superfície Primeiro)
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Sempre corrija uma falha na camada mais estruturada possível — deixe <code>text_instructions</code> por
            último para evitar conflitos e “dívida de prompt”.
          </p>
          <ol className="mt-4 space-y-2">
            {OFFICIAL_HIERARCHY.map((layer) => (
              <li
                key={layer.n}
                className="flex items-start gap-3 rounded-lg border border-slate-800/80 bg-slate-950/70 p-2.5 text-xs"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-950 font-mono text-[11px] font-bold text-indigo-300">
                  {layer.n}
                </span>
                <div>
                  <span className="font-semibold text-slate-100">{layer.name}:</span>{' '}
                  <span className="text-slate-400">{layer.desc}</span>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="space-y-4 lg:col-span-5">
          {/* Security Card for InfoSec / Governance */}
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/15 p-5">
            <div className="flex items-center gap-2">
              <Lock className="h-5 w-5 text-emerald-400" />
              <h3 className="text-base font-bold text-white">Segurança &amp; Governança Corporativa</h3>
            </div>
            <p className="mt-1 text-xs text-slate-300">
              Argumentos prontos para aprovação do framework junto aos times de Dados, Arquitetura e Segurança:
            </p>
            <ul className="mt-3 space-y-2 text-xs text-slate-300">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>Zero segredos no código:</strong> autenticação 100% via perfis Databricks CLI ou OAuth M2M.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>Guarda SQL estritamente Read-Only:</strong> profiling, <code>EXPLAIN</code>, auditoria e
                  benchmarks bloqueiam qualquer <code>DROP</code>/<code>DELETE</code>/<code>UPDATE</code>.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>Allowlist de escrita Delta:</strong> <code>export-delta</code> roda em <em>dry-run</em> por
                  padrão e só escreve com <code>--execute</code> exclusivamente nas tabelas <code>genie_opt_*</code>.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>Backup automático pré-deploy:</strong> todo <code>update-space</code> salva snapshot JSON
                  completo para rollback em segundos.
                </span>
              </li>
            </ul>
          </div>

          {/* Interactive Go-Live Checklist */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-indigo-400" />
                <h3 className="text-sm font-bold text-white">Checklist de Go-Live no Trabalho</h3>
              </div>
              <span className="rounded-full bg-indigo-950 px-2.5 py-0.5 font-mono text-[11px] font-bold text-indigo-300">
                {completedChecks}/{PROD_CHECKLIST.length}
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {PROD_CHECKLIST.map((item) => {
                const checked = Boolean(checkedItems[item.id]);
                return (
                  <label
                    key={item.id}
                    className={`flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 text-xs transition ${
                      checked
                        ? 'border-emerald-500/40 bg-emerald-950/20 text-slate-300 line-through'
                        : 'border-slate-800 bg-slate-950/70 text-slate-200 hover:border-slate-700'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleCheck(item.id)}
                      className="mt-0.5 rounded border-slate-600"
                    />
                    <span>{item.text}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Section 4: Cautionary Tip from Real Curations */}
      <section className="rounded-xl border border-amber-500/30 bg-amber-950/15 p-4 text-xs text-amber-100">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
          <div>
            <div className="font-bold text-amber-300">
              Dica de Ouro para o Dia a Dia (Evite Falsos Ganhos e Regressões)
            </div>
            <p className="mt-1 leading-relaxed text-amber-100/90">
              Nunca adicione muitas mudanças de uma vez (instruções + exemplos + SQL Functions) sem rodar benchmark
              entre cada camada. Em testes reais, anexar uma <strong>SQL Function (Trusted Asset)</strong> com descrição
              ampla demais faz o Genie rotear perguntas de grão diferente para ela, derrubando a acurácia. Rode sempre
              um passo por vez com <code>--label &quot;Rodada X&quot;</code> e reverta (<code>ROLL_BACK</code>) se{' '}
              <code>regressed &gt; 0</code>.
            </p>
          </div>
        </div>
      </section>

      {/* Section 5: Quick CLI Reference */}
      <section id="catalogo-cli" className="space-y-4 scroll-mt-24">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="h-5 w-5 text-emerald-400" />
            <h3 className="text-lg font-bold text-white">4. Catálogo Completo de Comandos CLI</h3>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(['Todos', 'Setup', 'Curadoria', 'Benchmark', 'Deploy & Prod'] as const).map((ph) => (
              <button
                key={ph}
                onClick={() => setPhaseFilter(ph)}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  phaseFilter === ph
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                {ph}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {visibleCommands.map((item, idx) => {
            const key = `cmd-${idx}-${item.title}`;
            return (
              <div
                key={key}
                className="flex flex-col justify-between rounded-xl border border-slate-800 bg-slate-900/60 p-4"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-white">{item.title}</span>
                    <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-indigo-300">
                      {item.phase}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{item.description}</p>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-2">
                  <code className="overflow-x-auto font-mono text-[11px] text-emerald-300">{item.command}</code>
                  <button
                    onClick={() => copyText(key, item.command)}
                    className="inline-flex shrink-0 items-center gap-1 rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-200 hover:bg-indigo-600 hover:text-white"
                  >
                    {copiedKey === key ? <Check className="h-3 w-3 text-emerald-300" /> : <Copy className="h-3 w-3" />}
                    {copiedKey === key ? 'OK' : 'Copiar'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Section 6: Direct Jump to Available Spaces */}
      {portfolio && portfolio.spaces.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-bold text-white">5. Explorar Spaces Carregados Neste Projeto</h3>
            <button
              onClick={() => onOpenDashboard()}
              className="text-xs font-semibold text-indigo-400 hover:text-indigo-300"
            >
              Ver todos no Painel Operacional →
            </button>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {portfolio.spaces.map((sp) => (
              <button
                key={sp.name}
                onClick={() => onOpenDashboard(sp.name)}
                className="group rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-left transition hover:border-indigo-500 hover:bg-indigo-950/20"
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-mono text-xs font-bold text-indigo-300">{sp.name}</div>
                    <div className="mt-0.5 text-sm font-bold text-white group-hover:text-indigo-200">
                      {sp.title}
                    </div>
                  </div>
                  <span className="rounded-lg bg-emerald-950 px-2.5 py-1 text-xs font-bold text-emerald-300">
                    Health {sp.health.score}/100
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-xs text-slate-400">{sp.description}</p>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-300">
                  <div className="flex flex-wrap gap-1.5">
                    <span className="rounded bg-slate-800 px-2 py-0.5">
                      {sp.counts.tables + sp.counts.metric_views} fontes
                    </span>
                    <span className="rounded bg-slate-800 px-2 py-0.5">{sp.counts.sql_functions} UDFs</span>
                    <span className="rounded bg-slate-800 px-2 py-0.5">
                      {sp.counts.benchmarks} bmks (+{sp.counts.paraphrases} paráfrases)
                    </span>
                  </div>
                  <span className="inline-flex items-center gap-1 font-semibold text-indigo-400">
                    Abrir Space <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
