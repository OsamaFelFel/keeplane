import mark from '@/assets/keeplane-mark-reversed.svg'
import { Card } from '@/components/ui/card'
import type { Identity } from './api'

export function DeveloperPage({ identity }: { identity: Identity }) {
  return <div className="min-h-svh bg-background">
    <header className="keeplane-topbar">
      <span className="keeplane-brand"><img src={mark} width="28" height="28" alt="" />Keeplane</span>
      <div className="flex items-center gap-5 text-[14px]">
        <span className="hidden sm:inline">{identity.username}</span>
        <a href="/sign-out">Sign out</a>
      </div>
    </header>
    <main className="flex justify-center px-4 py-8 sm:px-6 sm:py-16">
      <Card className="w-full max-w-[560px] gap-4 rounded-[10px] border-border bg-card p-8 shadow-none">
        <h1 className="text-[26px] leading-[34px] font-semibold">The web UI is for admins</h1>
        <p className="text-[16px] leading-6 text-muted-foreground">
          You're signed in as a developer. You work in Keeplane's CLI.
        </p>
      </Card>
    </main>
  </div>
}
