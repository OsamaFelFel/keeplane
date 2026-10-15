import { appendFileSync } from "node:fs"
import { createHash } from "node:crypto"

const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === "object" && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item)
const digest = value => createHash("sha256").update(canonical(value)).digest("hex")
const remainder = ({ temperature, top_p, ...rest }) => rest

// First-party synthetic unsigned-JSON experiment; no provider package or tools.
export default {
  id: "keeplane.research.child-hooks",
  async setup(context) {
    const record = row => appendFileSync(context.options.audit, JSON.stringify(row) + "\n")
    const contextHook = await context.session.hook("context", input => {
      record({ event: "context", sessionID: input.sessionID, agent: input.agent, model: input.model })
    }, { providerID: "keeplane" })
    const httpHook = await context.session.hook("http.request", async input => {
      const original = input.request
      const before = await original.clone().json()
      const values = { build: { temperature: 0.17, top_p: 0.73 }, explore: { temperature: 0.39, top_p: 0.61 } }[input.agent]
      if (input.kind === "primary" && values) {
        const headers = new Headers(original.headers)
        headers.delete("content-length")
        input.request = new Request(original, { headers, body: JSON.stringify({ ...before, ...values }) })
      }
      const after = await input.request.clone().json()
      const a = new Headers(original.headers), b = new Headers(input.request.headers)
      a.delete("content-length"); b.delete("content-length")
      record({ event: "http.request", sessionID: input.sessionID, agent: input.agent, model: input.model,
        kind: input.kind, body_sha256: digest(after), headers_preserved: canonical([...a]) === canonical([...b]),
        remainder_preserved: canonical(remainder(before)) === canonical(remainder(after)) })
    }, { providerID: "keeplane" })
    return async () => { await httpHook.dispose(); await contextHook.dispose() }
  },
}
