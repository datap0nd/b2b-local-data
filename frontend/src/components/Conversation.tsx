import {memo, useEffect, useRef, useState} from 'react';
import {ArrowDown, RotateCcw} from 'lucide-react';
import {Button} from './ui/button';
import {ResultCard} from './ResultCard';
import type {ConversationTurn, PresentationName, ViewName} from '@/types';

interface Props {
  turns: ConversationTurn[];
  onView: (turn: ConversationTurn, view: ViewName) => void;
  onPresentation: (turn: ConversationTurn, presentation: PresentationName) => void;
  onExplore: (turn: ConversationTurn) => void;
  onSuggestion: (text: string) => void;
  onRunWithCurrent: (turn: ConversationTurn) => void;
  samples?: React.ReactNode;
  empty: boolean;
}

interface TurnProps { turn: ConversationTurn; onView: Props['onView']; onPresentation: Props['onPresentation']; onExplore: Props['onExplore']; onSuggestion: Props['onSuggestion']; onRunWithCurrent: Props['onRunWithCurrent'] }

/** One question with its answer. Memoized so a view or presentation change in one turn does not re-render the others
 *  (their tables and charts), which keeps result controls responsive in long conversations. */
const Turn = memo(function Turn({turn, onView, onPresentation, onExplore, onSuggestion, onRunWithCurrent}: TurnProps) {
  return (
    <article key={turn.id} className="flex flex-col gap-3" data-testid="turn">
      <div className="flex justify-end"><p className="max-w-[780px] whitespace-pre-wrap rounded-2xl bg-surface px-4 py-2.5 text-[15px]" data-testid="user-turn">{turn.question}</p></div>
      <div className="max-w-full" data-testid="assistant-turn" data-status={turn.assistant.status}>
        {turn.assistant.status === 'pending' && (
          <div className="flex items-center gap-2 text-sm text-ink-2" role="status" aria-live="polite">
            <span className="inline-flex gap-1" aria-hidden="true"><i className="size-1.5 animate-pulse rounded-full bg-ink-3" /><i className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:150ms]" /><i className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:300ms]" /></span>
            Working on it
          </div>
        )}
        {turn.assistant.status === 'error' && (
          <div className="max-w-[780px] rounded-xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
            <p>{turn.assistant.message}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={turn.assistant.retry}><RotateCcw />Retry</Button>
          </div>
        )}
        {turn.assistant.status === 'clarify' && (
          <div className="max-w-[780px]">
            <p className="whitespace-pre-wrap text-[15px]">{turn.assistant.text}</p>
            {turn.assistant.suggestions.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{turn.assistant.suggestions.map(s => <button key={s} type="button" onClick={() => onSuggestion(s)} className="rounded-full border border-line px-3 py-1 text-[13px] text-ink-2 hover:bg-surface hover:text-ink">{s}</button>)}</div>}
          </div>
        )}
        {turn.assistant.status === 'missing' && (
          <div className="max-w-[780px] rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-2">
            <p>{turn.assistant.message}</p>
            {turn.assistant.canRerun && <Button variant="outline" size="sm" className="mt-2" onClick={() => onRunWithCurrent(turn)}>Run with current data</Button>}
          </div>
        )}
        {turn.assistant.status === 'answer' && (
          <ResultCard answer={turn.assistant.answer} shown={turn.assistant.shown} view={turn.assistant.view} presentation={turn.assistant.presentation} loading={turn.assistant.loading} notice={turn.assistant.notice}
            onView={v => onView(turn, v)} onPresentation={p => onPresentation(turn, p)} onExplore={() => onExplore(turn)} onSuggestion={onSuggestion} />
        )}
      </div>
    </article>
  );
});

/** Real user and assistant turns. New answers scroll into view only while the reader follows the latest turn;
 *  otherwise a "New answer" control appears and the reading position is kept. */
export function Conversation({turns, onView, onPresentation, onExplore, onSuggestion, onRunWithCurrent, samples, empty}: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [unseen, setUnseen] = useState(false);
  const lastCount = useRef(turns.length);
  const lastKey = useRef('');
  const ignoreScrollUntil = useRef(0);   // programmatic smooth scrolls must not flip the follow state
  const followingRef = useRef(true);
  useEffect(() => { followingRef.current = following; }, [following]);
  // While the reader follows the latest turn, content that grows later (restored results, charts) keeps the end in view.
  useEffect(() => {
    const el = scroller.current; const inner = el?.firstElementChild; if (!el || !inner) return;
    const observer = new ResizeObserver(() => { if (followingRef.current && el.scrollHeight - el.scrollTop - el.clientHeight > 1) { ignoreScrollUntil.current = Date.now() + 250; el.scrollTop = el.scrollHeight; } });
    observer.observe(inner); return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = scroller.current; if (!el) return;
    const key = turns.map(t => `${t.id}:${t.assistant.status}`).join('|');
    const grew = turns.length > lastCount.current || key !== lastKey.current;
    const previousKey = lastKey.current;
    lastCount.current = turns.length; lastKey.current = key;
    if (!grew) return;
    const last = turns[turns.length - 1];
    const submitted = last?.assistant.status === 'pending';   // the reader just asked: always show their question
    const restored = previousKey === '';  // first render of a loaded conversation
    if (following || submitted || restored) {
      if (!following) { setFollowing(true); setUnseen(false); }
      ignoreScrollUntil.current = Date.now() + 900;
      requestAnimationFrame(() => el.scrollTo({top: el.scrollHeight, behavior: restored || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}));
    } else setUnseen(true);
  }, [turns, following]);

  function onScroll() {
    const el = scroller.current; if (!el || Date.now() < ignoreScrollUntil.current) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setFollowing(atBottom); if (atBottom) setUnseen(false);
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={scroller} onScroll={onScroll} className="h-full overflow-y-auto scroll-thin" data-testid="conversation">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-4 py-6 md:px-6">
          {empty && (
            <div className="mx-auto mt-[12vh] max-w-[620px] text-center">
              <h1 className="text-[26px] font-semibold tracking-tight">What would you like to understand?</h1>
              <p className="mt-2 text-[15px] text-ink-2">Ask about opportunities, products, owners, stages, and amounts. Every answer shows its numbers, its data, and when the data was updated.</p>
              {samples && <div className="mt-6">{samples}</div>}
            </div>
          )}
          {turns.map(turn => <Turn key={turn.id} turn={turn} onView={onView} onPresentation={onPresentation} onExplore={onExplore} onSuggestion={onSuggestion} onRunWithCurrent={onRunWithCurrent} />)}
        </div>
      </div>
      {unseen && !following && (
        <Button size="sm" className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full shadow-lg" onClick={() => { scroller.current?.scrollTo({top: scroller.current.scrollHeight, behavior: 'smooth'}); setUnseen(false); setFollowing(true); }} data-testid="new-answer">
          <ArrowDown />New answer
        </Button>
      )}
    </div>
  );
}
