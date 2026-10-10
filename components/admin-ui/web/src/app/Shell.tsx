import type { CSSProperties, ReactNode } from 'react'
import mark from '@/assets/keeplane-mark-reversed.svg'
import type { Identity } from './api'
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarMenu, SidebarMenuButton,
  SidebarMenuItem, SidebarProvider, SidebarTrigger,
} from '@/components/ui/sidebar'

const links = [
  { label: 'Projects', href: null },
  { label: 'Users', href: '/app/' },
  { label: 'Workflows', href: null },
  { label: 'Agents', href: null },
  { label: 'Models and routing', href: '/app/models' },
  { label: 'Data classes', href: '/app/data-classes' },
  { label: 'Audit', href: '/app/audit' },
  { label: 'Single sign-on', href: null },
  { label: 'Editions', href: '/editions' },
]

export function Shell({ identity, children }: { identity: Identity; children: ReactNode }) {
  return <div className="keeplane-shell">
    <SidebarProvider className="flex-col" style={{ '--sidebar-width': '232px' } as CSSProperties}>
      <header className="keeplane-topbar">
        <div className="flex items-center gap-3">
          <SidebarTrigger aria-label="Menu" className="h-11 w-11 text-white hover:bg-white/10 md:hidden" />
          <span className="keeplane-brand"><img src={mark} width="28" height="28" alt="" /> Keeplane</span>
        </div>
        <div className="flex items-center gap-5 text-[14px]"><span className="hidden md:inline">{identity.username}</span><a href="/sign-out">Sign out</a></div>
      </header>
      <div className="flex min-w-0 flex-1">
      <Sidebar aria-label="Main" className="keeplane-sidebar" collapsible="offcanvas">
        <SidebarContent className="pt-2">
          <SidebarGroup>
            <SidebarMenu className="gap-1">
      {links.map(link => <SidebarMenuItem key={link.label}>
                <SidebarMenuButton asChild isActive={link.href === window.location.pathname || (link.href === '/app/' && window.location.pathname === '/app')} className="h-auto min-h-10 rounded-[6px] px-3 py-2.5 text-[15px] data-[active=true]:bg-[var(--sidebar-accent)] data-[active=true]:font-semibold">
                  {link.href ? <a href={link.href} aria-current={link.href === window.location.pathname ? 'page' : undefined}>{link.label}</a>
                    : <span aria-disabled="true" className="text-muted-foreground">{link.label}</span>}
                </SidebarMenuButton>
              </SidebarMenuItem>)}
            </SidebarMenu>
          </SidebarGroup>
          <div className="mt-auto px-7 pb-6 text-[14px] md:hidden">{identity.username}</div>
        </SidebarContent>
      </Sidebar>
      <div className="min-w-0 flex-1">
        <main className="keeplane-content">{children}</main>
      </div>
      </div>
    </SidebarProvider>
  </div>
}
