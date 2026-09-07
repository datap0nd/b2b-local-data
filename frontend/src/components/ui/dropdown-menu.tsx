import * as React from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({className, sideOffset = 4, ...props}: React.ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content sideOffset={sideOffset} className={cn('z-50 min-w-[10rem] rounded-lg border border-line bg-canvas p-1 text-sm shadow-lg', className)} {...props} />
    </Menu.Portal>
  );
}

export function DropdownMenuItem({className, danger, ...props}: React.ComponentProps<typeof Menu.Item> & {danger?: boolean}) {
  return <Menu.Item className={cn('flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-surface', danger && 'text-danger', className)} {...props} />;
}

export function DropdownMenuCheckboxItem({className, children, ...props}: React.ComponentProps<typeof Menu.CheckboxItem>) {
  return (
    <Menu.CheckboxItem className={cn('flex cursor-pointer select-none items-center gap-2 rounded-md py-1.5 pl-7 pr-2 outline-none data-[highlighted]:bg-surface', className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center"><Menu.ItemIndicator><Check className="size-3.5" /></Menu.ItemIndicator></span>
      {children}
    </Menu.CheckboxItem>
  );
}

export const DropdownMenuSeparator = ({className, ...props}: React.ComponentProps<typeof Menu.Separator>) => <Menu.Separator className={cn('my-1 h-px bg-line', className)} {...props} />;
export const DropdownMenuLabel = ({className, ...props}: React.ComponentProps<typeof Menu.Label>) => <Menu.Label className={cn('px-2 py-1 text-xs font-medium text-ink-3', className)} {...props} />;
