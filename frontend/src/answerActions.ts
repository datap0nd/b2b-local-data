import type {ConversationTurn, PresentationName, TablePayload, ViewName} from './types';

/** Shared ordinary/test answer interactions. Only the saved-answer API scope varies. */
export async function changeAnswerView(turn: ConversationTurn, view: ViewName, apply: (next: ConversationTurn) => void,
  load: () => Promise<{table: TablePayload}>) {
  if (turn.assistant.status !== 'answer' || turn.assistant.view === view) return;
  const current = turn.assistant;
  const local = current.answer.variants?.[view];
  if (local && 'rows' in local) { apply({...turn, assistant: {...current, shown: local as TablePayload, view, presentation: 'table'}}); return; }
  apply({...turn, assistant: {...current, loading: true}});
  try {
    const reply = await load();
    apply({...turn, assistant: {...current, shown: reply.table, view, loading: false, answer: {...current.answer, variants: {...current.answer.variants, [view]: reply.table}}}});
  } catch (error) {
    apply({...turn, assistant: {...current, loading: false, notice: error instanceof Error ? error.message : 'That view is not available.'}});
  }
}

export function changeAnswerPresentation(turn: ConversationTurn, presentation: PresentationName): ConversationTurn {
  return turn.assistant.status === 'answer' ? {...turn, assistant: {...turn.assistant, presentation}} : turn;
}
