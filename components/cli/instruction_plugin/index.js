import { createHash } from "node:crypto"

// Only context text is changed. Provider settings, headers and tools are untouched.
export default {
  id: "keeplane.explicit-instructions",
  async setup(context) {
    const { directory, sources } = context.options
    const hook = await context.session.hook("context", input => {
      if (context.location.directory !== directory) throw new Error("Instruction directory changed")
      for (const { path, sha256, content } of sources) {
        if (createHash("sha256").update(content, "utf8").digest("hex") !== sha256) {
          throw new Error("Instruction snapshot changed")
        }
        input.system.push({ type: "text", text: `Repository instruction: ${path} (SHA-256 ${sha256})\n${content}` })
      }
    }, { providerID: "keeplane" })
    return () => hook.dispose()
  },
}
