interface Comparison {
  ok: boolean;
  checks?: Record<string, boolean>;
  differences?: unknown[];
  supporting?: {ok: boolean; checks?: Record<string, boolean>; views?: Record<string, Comparison>};
}
export interface VerdictStep {
  id: string;
  status: string;
  error?: string | null;
  interpretation?: {ok: boolean; problems: string[]};
  data?: Comparison;
}

/** Keep interpretation, values and supporting evidence independently inspectable. */
export function TestVerdict({step}: {step: VerdictStep}) {
  const data = step.data;
  const primary = Object.entries(data?.checks ?? {}).filter(([key]) => key !== 'supporting_rows');
  const primaryState = primary.length ? (primary.every(([, ok]) => ok) ? 'pass' : 'fail') : 'not checked';
  const failures = primary.filter(([, ok]) => !ok).map(([key]) => key);
  const supporting = data?.supporting;
  for (const [view, result] of Object.entries(supporting?.views ?? {})) {
    failures.push(...Object.entries(result.checks ?? {}).filter(([, ok]) => !ok).map(([key]) => `Supporting ${view}: ${key}`));
  }
  failures.push(...Object.entries(supporting?.checks ?? {}).filter(([, ok]) => !ok).map(([key]) => `Supporting: ${key}`));
  return <details className="max-h-40 overflow-auto border-b border-line bg-canvas px-3 py-2 text-xs" data-testid="test-verdict">
    <summary>{step.id} · {step.status} · Interpretation: {step.interpretation ? (step.status === 'review' ? 'review' : step.interpretation.ok ? 'pass' : 'fail') : 'not checked'} · Result checks: {primaryState} · Supporting records: {supporting ? (supporting.ok ? 'pass' : 'fail') : 'not checked'}{failures.length > 0 && ` · Failed: ${failures.join(', ')}`}</summary>
    {step.error && <p>{step.error}</p>}
    {step.interpretation?.problems.map((problem, i) => <p key={i}>{problem}</p>)}
    <pre className="whitespace-pre-wrap break-words">{JSON.stringify({resultDifferences: data?.differences, supporting: supporting?.views}, null, 2)}</pre>
  </details>;
}
