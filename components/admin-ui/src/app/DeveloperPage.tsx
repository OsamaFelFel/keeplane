import mark from '@/assets/keeplane-mark-reversed.svg'
import { Card } from '@/components/ui/card'
import type { Identity } from './api'
import { SignOut } from './SignOut'

export function DeveloperPage({ identity }: { identity: Identity }) {
  const server = window.location.origin.replaceAll("'", "'\\''")
  const signInCommand = `mkdir -p "$HOME/.config/keeplane"
keeplane login --server '${server}' \\
  --profile "$HOME/.config/keeplane/account"`

  return <div className="min-h-svh bg-background">
    <header className="keeplane-topbar">
      <span className="keeplane-brand"><img src={mark} width="28" height="28" alt="" />Keeplane</span>
      <div className="flex items-center gap-5 text-[14px]">
        <span className="hidden sm:inline">{identity.username}</span>
        <SignOut />
      </div>
    </header>
    <main className="flex justify-center px-4 py-8 sm:px-6 sm:py-16">
      <Card className="w-full max-w-[560px] gap-4 rounded-[10px] border-border bg-card p-8 shadow-none">
        <h1 className="text-[26px] leading-[34px] font-semibold">The web UI is for admins</h1>
        <p className="text-[16px] leading-6 text-muted-foreground">
          You're signed in as a developer. You work in Keeplane's CLI.
        </p>
        <h2 className="mt-2 text-[18px] leading-[26px] font-semibold">Sign in from the CLI</h2>
        <p className="text-[15px] leading-6">
          Ask your operator for the CLI and confirm CLI sign-in is enabled. Then run this in a terminal:
        </p>
        <pre className="min-w-0 whitespace-pre-wrap break-all rounded-md border border-border bg-background p-3 font-mono text-[14px] leading-6"><code>{signInCommand}</code></pre>
        <p className="text-[15px] leading-6">
          Sign in with your Keeplane account in the browser and allow CLI access.
          If this machine cannot open a browser, add <code className="font-mono">--device</code> to the command.
        </p>
      </Card>
    </main>
  </div>
}
