import * as React from 'react';
import {cva, type VariantProps} from 'class-variance-authority';
import {cn} from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'bg-ink text-white hover:bg-ink/90',
        secondary: 'bg-surface text-ink border border-line hover:bg-surface-2',
        ghost: 'text-ink-2 hover:bg-surface hover:text-ink',
        outline: 'border border-line bg-canvas text-ink hover:bg-surface',
        accent: 'bg-accent text-white hover:bg-accent/90',
        link: 'text-accent underline-offset-4 hover:underline',
      },
      size: {default: 'h-9 px-3.5', sm: 'h-8 px-3 text-[13px]', xs: 'h-7 px-2.5 text-xs', icon: 'size-9', 'icon-sm': 'size-8'},
    },
    defaultVariants: {variant: 'default', size: 'default'},
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export function Button({className, variant, size, type = 'button', ...props}: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({variant, size, className}))} {...props} />;
}

export {buttonVariants};
