import {useMemo, useState} from 'react';
import {MoreHorizontal, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Search, Trash2} from 'lucide-react';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger} from './ui/dropdown-menu';
import {Hint} from './ui/tooltip';
import {Freshness} from './Freshness';
import {cn} from '@/lib/utils';
import type {Freshness as FreshnessInfo, SessionSummary} from '@/types';

interface Props {
  sessions: SessionSummary[];
  currentId: string | null;
  collapsed: boolean;
  overlay: boolean;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  devEntry?: React.ReactNode;
  freshness?: FreshnessInfo | null;
}

function groupLabel(iso: string): string {
  const date = new Date(iso); if (Number.isNaN(date.getTime())) return 'Earlier';
  const now = new Date(); const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = 86400000; const diff = start.getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  if (diff < day) return 'Today'; if (diff < 2 * day) return 'Yesterday'; if (diff < 7 * day) return 'Previous 7 days'; if (diff < 30 * day) return 'Previous 30 days';
  return new Intl.DateTimeFormat(undefined, {month: 'long', year: 'numeric'}).format(date);
}

export function Sidebar({sessions, currentId, collapsed, overlay, open, onToggle, onClose, onNew, onSelect, onRename, onDelete, devEntry, freshness}: Props) {
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState<{id: string; title: string} | null>(null);
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? sessions.filter(s => s.title.toLowerCase().includes(q)) : sessions;
    const out: {label: string; items: SessionSummary[]}[] = [];
    for (const s of list) { const label = groupLabel(s.updated_at); const group = out.find(g => g.label === label); if (group) group.items.push(s); else out.push({label, items: [s]}); }
    return out;
  }, [sessions, query]);

  const rail = collapsed && !overlay;
  return (
    <>
      {overlay && open && <div className="fixed inset-0 z-30 bg-ink/30" onClick={onClose} aria-hidden="true" />}
      <aside
        aria-label="Conversation history"
        inert={overlay && !open}
        aria-hidden={overlay && !open}
        data-rail={rail}
        className={cn('flex h-full flex-col border-r border-line bg-surface transition-[width,transform] duration-200',
          overlay ? cn('fixed inset-y-0 left-0 z-40 w-[248px]', open ? 'visible translate-x-0' : 'invisible -translate-x-full') : rail ? 'w-[52px]' : 'w-[248px]')}>
        <div className={cn('flex items-center gap-2 px-3 py-3', rail && 'flex-col px-1.5')}>
          <span className={cn('flex items-center text-[15px] font-semibold tracking-tight', rail && 'flex-col')}><span className={cn('text-accent', rail ? 'text-xs' : 'pl-1')}>B2B</span><Freshness freshness={freshness} /></span>
          <div className={cn('ml-auto flex items-center gap-1', rail && 'ml-0 flex-col')}>
            <Hint text={rail ? 'Show history' : 'Hide history'}><Button variant="ghost" size="icon-sm" onClick={overlay ? onClose : onToggle} aria-label={rail ? 'Show history' : 'Hide history'} aria-expanded={!rail}>{rail ? <PanelLeftOpen /> : <PanelLeftClose />}</Button></Hint>
            <Hint text="New chat"><Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New chat"><Plus /></Button></Hint>
          </div>
        </div>
        {!rail && (
          <>
            <div className="px-3 pb-2">
              <label className="relative block">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-3" aria-hidden="true" />
                <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search conversations" aria-label="Search conversations"
                  className="h-8 w-full rounded-md border border-line bg-canvas pl-8 pr-2 text-[13px] outline-none placeholder:text-ink-3 focus:border-line-2" />
              </label>
            </div>
            <nav className="flex-1 overflow-y-auto px-2 pb-3 scroll-thin" aria-label="Conversations">
              {groups.length === 0 && <p className="px-2 py-3 text-[13px] text-ink-3">{query ? 'No conversations match.' : 'No conversations yet.'}</p>}
              {groups.map(group => (
                <div key={group.label} className="mb-2">
                  <p className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">{group.label}</p>
                  <ul className="flex flex-col gap-px">
                    {group.items.map(s => (
                      <li key={s.id} className={cn('group flex items-center rounded-md', s.id === currentId ? 'bg-canvas shadow-card' : 'hover:bg-canvas/70')}>
                        {renaming?.id === s.id ? (
                          <form className="flex flex-1 items-center" onSubmit={e => { e.preventDefault(); if (renaming.title.trim()) onRename(s.id, renaming.title.trim()); setRenaming(null); }}>
                            <input autoFocus value={renaming.title} onChange={e => setRenaming({id: s.id, title: e.target.value})} onBlur={() => setRenaming(null)} onKeyDown={e => { if (e.key === 'Escape') setRenaming(null); }}
                              aria-label="Conversation title" className="h-8 w-full rounded-md border border-line-2 bg-canvas px-2 text-[13px] outline-none" />
                          </form>
                        ) : (
                          <>
                            <button type="button" onClick={() => onSelect(s.id)} aria-current={s.id === currentId ? 'page' : undefined}
                              className={cn('min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[13px]', s.id === currentId ? 'font-medium text-ink' : 'text-ink-2')}>
                              {s.title}
                            </button>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button type="button" aria-label={`Actions for ${s.title}`} className="mr-1 rounded p-1 text-ink-3 opacity-0 hover:bg-surface-2 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"><MoreHorizontal className="size-4" /></button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onSelect={() => setRenaming({id: s.id, title: s.title})}><Pencil className="size-3.5" />Rename</DropdownMenuItem>
                                <DropdownMenuItem danger onSelect={() => onDelete(s.id)}><Trash2 className="size-3.5" />Delete</DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </nav>
          </>
        )}
        {devEntry && <div className={cn('mt-auto border-t border-line py-3', rail ? 'px-1' : 'px-3')}>{devEntry}</div>}
      </aside>
    </>
  );
}
