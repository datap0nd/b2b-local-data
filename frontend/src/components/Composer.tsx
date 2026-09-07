import {useEffect, useRef, useState} from 'react';
import {ArrowUp} from 'lucide-react';
import {cn} from '@/lib/utils';

interface Props {
  onSubmit: (text: string) => Promise<void> | void;
  busy: boolean;
  compact?: boolean;
  draft: string;
  onDraftChange: (text: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

/** One rounded input surface growing from one to six lines. Enter submits, Shift+Enter inserts a newline,
 *  IME composition is respected, and a submission in flight cannot be duplicated. */
export function Composer({onSubmit, busy, compact, draft, onDraftChange, placeholder, autoFocus}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [composing, setComposing] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.style.height = 'auto';
    const line = 24, max = compact ? line * 4 + 20 : line * 6 + 20;
    el.style.height = Math.min(max, Math.max(line + 20, el.scrollHeight)) + 'px';
  }, [draft, compact]);
  useEffect(() => { if (autoFocus) ref.current?.focus({preventScroll: true}); }, [autoFocus]);

  async function submit() {
    const text = draft.trim();
    if (!text || busy || submitting.current) return;
    submitting.current = true;
    try { await onSubmit(text); } finally { submitting.current = false; }
  }

  return (
    <form className={cn('mx-auto w-full', compact ? 'max-w-[720px]' : 'max-w-[780px]')} onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className={cn('flex items-end gap-2 rounded-2xl border border-line bg-canvas shadow-card transition-colors focus-within:border-line-2', compact ? 'px-3 py-1.5' : 'px-4 py-2')}>
        <textarea
          ref={ref}
          value={draft}
          rows={1}
          maxLength={4000}
          placeholder={placeholder ?? 'Ask about your opportunities'}
          aria-label="Your question"
          onChange={e => onDraftChange(e.target.value)}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={() => setComposing(false)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !composing && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); }
          }}
          className="max-h-[164px] min-h-[44px] flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-6 outline-none placeholder:text-ink-3"
        />
        <button type="submit" aria-label="Send" disabled={busy || !draft.trim()}
          className="mb-1 grid size-9 shrink-0 place-items-center rounded-full bg-ink text-white transition-colors hover:bg-ink/85 disabled:bg-surface-2 disabled:text-ink-3">
          <ArrowUp className="size-4" />
        </button>
      </div>
    </form>
  );
}
