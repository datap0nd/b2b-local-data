import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {X} from 'lucide-react';
import {cn} from '@/lib/utils';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

/** Centered dialog (login) or right-hand panel (details) sharing one accessible primitive. */
export function DialogContent({className, side = 'center', children, title, ...props}: React.ComponentProps<typeof DialogPrimitive.Content> & {side?: 'center' | 'right'; title: string}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30" />
      <DialogPrimitive.Content
        className={cn('fixed z-50 bg-canvas shadow-xl focus:outline-none', side === 'center' ? 'left-1/2 top-1/2 w-[min(420px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-card border border-line p-6' : 'inset-y-0 right-0 flex w-[min(440px,100vw)] flex-col border-l border-line', className)}
        {...props}>
        <div className={cn('flex items-start justify-between gap-4', side === 'right' && 'border-b border-line px-5 py-4')}>
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Close className="rounded-md p-1 text-ink-3 hover:bg-surface hover:text-ink" aria-label="Close"><X className="size-4" /></DialogPrimitive.Close>
        </div>
        <div className={cn(side === 'right' ? 'flex-1 overflow-auto px-5 py-4 scroll-thin' : 'mt-3')}>{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
