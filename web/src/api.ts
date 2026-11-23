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

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function fetchSpaces(): Promise<SpacesListResponse> {
  return getJson<SpacesListResponse>('/api/spaces');
}

export function fetchSpaceDetail(name: string): Promise<SpaceDetailResponse> {
  return getJson<SpaceDetailResponse>(`/api/spaces/${encodeURIComponent(name)}`);
}

export function fetchSpaceLint(name: string): Promise<LintReportResponse> {
  return getJson<LintReportResponse>(`/api/spaces/${encodeURIComponent(name)}/lint`);
}

export function fetchSpaceRuns(name: string): Promise<{ space_name: string; runs: BenchmarkRunRecord[] }> {
  return getJson(`/api/spaces/${encodeURIComponent(name)}/runs`);
}

export function fetchRunDetail(
  name: string,
  runId: string
): Promise<{ run: BenchmarkRunRecord; regression_diff: RegressionDiff | null }> {
  return getJson(`/api/spaces/${encodeURIComponent(name)}/runs/${encodeURIComponent(runId)}`);
}

export function fetchDiagnose(name: string, runId?: string): Promise<DiagnoseResponse> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
  return getJson<DiagnoseResponse>(`/api/spaces/${encodeURIComponent(name)}/diagnose${q}`);
}

export function triggerOfflineBenchmark(
  name: string,
  env = 'dev',
  options?: { label?: string; expand_paraphrases?: boolean }
): Promise<{ run: BenchmarkRunRecord; regression_diff: RegressionDiff | null }> {
  return getJson(`/api/spaces/${encodeURIComponent(name)}/benchmark/offline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      env,
      label: options?.label ?? '',
      expand_paraphrases: options?.expand_paraphrases ?? false,
    }),
  });
}

export function fetchDeltaPreview(
  name: string,
  catalog: string,
  schema: string,
  schemaMode: 'four_tables' | 'events'
): Promise<DeltaExportPreviewResponse> {
  const params = new URLSearchParams({
    catalog,
    schema,
    schema_mode: schemaMode,
  });
  return getJson<DeltaExportPreviewResponse>(
    `/api/spaces/${encodeURIComponent(name)}/export-delta/preview?${params.toString()}`
  );
}

export async function streamAgentQuestion(
  name: string,
  payload: {
    question: string;
    env: string;
    execution_mode: 'STANDARD' | 'FLASH';
    live_mode: boolean;
    judge_provider: 'heuristic' | 'databricks' | 'openai';
    evaluation_note?: string;
  },
  callbacks: {
    onEvent: (ev: StreamedAgentEvent) => void;
    onVerdict: (verdict: JudgeVerdict) => void;
  }
): Promise<void> {
  const res = await fetch(`/api/spaces/${encodeURIComponent(name)}/agent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    throw new Error(`Falha ao abrir stream SSE (HTTP ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const dispatchFrame = (frame: string) => {
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const rawLine of frame.split(/\r?\n/)) {
      if (rawLine.startsWith('event:')) {
        eventName = rawLine.slice(6).trim();
      } else if (rawLine.startsWith('data:')) {
        dataLines.push(rawLine.slice(5).trim());
      }
    }
    if (!dataLines.length) return;
    const raw = dataLines.join('\n');
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      if (eventName === 'judge.verdict') {
        callbacks.onVerdict(parsed as unknown as JudgeVerdict);
      } else {
        callbacks.onEvent({
          event: eventName,
          timestamp_ms: typeof parsed.timestamp_ms === 'number' ? parsed.timestamp_ms : undefined,
          payload: (parsed.payload as Record<string, unknown>) || parsed,
        });
      }
    } catch {
      // ignora frames não JSON
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      if (part.trim()) dispatchFrame(part);
    }
  }
  if (buffer.trim()) {
    dispatchFrame(buffer);
  }
}
