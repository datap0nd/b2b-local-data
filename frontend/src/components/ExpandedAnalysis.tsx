import {useEffect} from 'react';
import {X} from 'lucide-react';
import {Button} from './ui/button';
import {ResultCard, type ResultCardProps} from './ResultCard';

/** Expanded workspace uses the same exclusive chart/data presentation as the answer. */
export function ExpandedAnalysis({onClose, children, ...card}: ResultCardProps & {onClose: () => void; children?: React.ReactNode}) {
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !document.querySelector('[role="dialog"]')) onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  return <div className="flex h-full flex-col" data-testid="expanded">
    <div className="flex items-center gap-3 border-b border-line bg-canvas px-4 py-2"><span className="text-sm font-medium">Analysis</span><span className="text-xs text-ink-3">Esc closes</span><Button variant="ghost" size="sm" className="ml-auto" onClick={onClose} aria-label="Close analysis"><X />Close</Button></div>
    <div className="flex-1 overflow-auto px-4 py-5 scroll-thin"><div className="mx-auto w-full max-w-[1200px]"><ResultCard {...card} expanded /></div></div>
    {children && <div className="border-t border-line bg-canvas px-4 py-3">{children}</div>}
  </div>;
}
