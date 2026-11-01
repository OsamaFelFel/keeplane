import type { ReactNode } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

// Lucide's circle-alert, drawn as in the design system: 2px stroke in ink.
// Source: lucide-static 1.59.0 icons/circle-alert.svg, ISC (Lucide) and MIT
// (Feather, which it derives from); see licenses/lucide-static-1.59.0.json.
export function CircleAlertIcon({ className }: { className?: string }) {
  return <svg data-icon="circle-alert" className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" /><line x1="12" y1="7" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
}

// The design system's failure message: on ground, a control-border edge, radius-md,
// 14px 16px padding, 15px text, a 20px circle-alert icon and a weight-600 first line.
export function FailureAlert({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return <Alert className={`gap-x-3 gap-y-1 rounded-[8px] border-input bg-background px-4 py-3.5 text-[15px] leading-[22px] text-foreground${children ? '' : ' *:[svg]:row-span-1'}`}>
    <CircleAlertIcon className="size-5" />
    <AlertTitle className="font-semibold wrap-anywhere">{title}</AlertTitle>
    {children && <AlertDescription className="text-[15px] leading-[22px] text-foreground">{children}</AlertDescription>}
  </Alert>
}
