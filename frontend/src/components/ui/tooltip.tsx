import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import {cn} from '@/lib/utils';

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({className, sideOffset = 6, ...props}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content sideOffset={sideOffset} className={cn('z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-white shadow-md', className)} {...props} />
    </TooltipPrimitive.Portal>
  );
}

/** Small helper: wraps children with a tooltip that also works for keyboard focus. */
export function Hint({text, children}: {text: React.ReactNode; children: React.ReactElement}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}
