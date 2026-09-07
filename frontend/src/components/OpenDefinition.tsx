import {useState} from 'react';
import {Tooltip, TooltipContent, TooltipTrigger} from './ui/tooltip';
import {Info} from 'lucide-react';

/** Status definitions stay reachable by mouse, keyboard and touch. */
export function OpenDefinition() {
  const [open, setOpen] = useState(false);
  return <Tooltip open={open} onOpenChange={setOpen}><TooltipTrigger asChild><button type="button" aria-label="What does Open mean?" onClick={event => { event.preventDefault(); setOpen(value => !value); }} className="rounded-full p-1 text-ink-3 hover:text-accent"><Info className="size-4" /></button></TooltipTrigger><TooltipContent>Open opportunities are in the Identified, Qualified or Negotiation stage. Having a closing date does not determine whether an opportunity is open.</TooltipContent></Tooltip>;
}
