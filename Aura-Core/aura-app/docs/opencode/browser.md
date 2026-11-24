# OpenCode and browser use (P2-38)

Research only. Written 2026-11-24. Nothing was installed or changed; the pin stays at v2.3.2
(`opencode_version_pin` in `src/aura/config.py`).

## Findings

1. **Built-in browser (v2.4.0, released 2026-11-23).** The release notes list a "Built-In Desktop
   Browser" that imports sign-ins and history from Chrome, Edge, Firefox or Safari, keeps sessions
   across restarts, and lets the agent "read and drive the same signed-in tabs". It is a feature of the
   desktop app. The tools page describes it as "a `browser` Code Mode namespace for the browser attached
   by the OpenCode desktop app". There is no per-call permission prompt; a `browser` deny rule with
   resource `*` removes it. Page content is to be treated as untrusted. The notes do not say it works
   under `opencode serve`, and Aura runs her own `opencode serve` with no desktop app attached. So it
   is probably not usable by Aura even after an upgrade (not confirmed; would need a test).
   Sources: https://api.github.com/repos/sst/opencode/releases/tags/v2.4.0 ,
   https://opencode.ai/docs/tools/
2. **v2.3.2 has no browser tool.** `docs/opencode/openapi-v2.3.2.json` has no browser or playwright
   entries. It does have `/api/websearch` (+ `/api/websearch/provider`) and an `mcp` section (`mcp.list`,
   `mcp.use`, status events), so MCP servers are supported in the pin.
3. **MCP route (works today).** Playwright MCP (`@playwright/mcp`, Microsoft) is the usual browser
   server for OpenCode. Docs describe V2 config: servers go under `mcp.servers`, `type: "local"` with
   `command` as an array (for example `["npx","-y","@playwright/mcp@latest","--headless"]`), optional
   `environment`, `timeout`, `disabled`. `opencode mcp add <name> -- <command>` also works. Use
   `--browser chromium|firefox|webkit|msedge`, `--headless` for unattended runs. Community plugins exist
   (opencode-browser, opencode-browser-mcp) but are unvetted. Which exact config shape v2.3.2 accepts
   was not verified against the binary; the V2 docs may be written for a later build.
   Sources: https://opencode.ai/docs/mcp-servers/ ,
   https://www.opencode.asia/recipes/browser-automation/
4. **Windows needs.** Node.js with `npx` on PATH, network for the first run, and a browser binary (Playwright
   downloads Chromium, or use `--browser msedge` with the installed Edge). First run is slow, so pre-fetch
   with `npx -y @playwright/mcp --help`. Aura loads OpenCode config through its own `XDG_CONFIG_HOME`,
   so the MCP entry would go into Aura's generated config, not `~/.config/opencode/`. Not tested here.
5. **Built-in web tools.** OpenCode has `webfetch` (one URL to markdown/text/HTML, permission checked
   against the URL) and `websearch` (provider-based). Source: https://opencode.ai/docs/tools/

## Comparison with Aura

Aura's `src/aura/tools/web_search.py` calls the Tavily API (key `TAVILY_API_KEY`), returns up to 5
results with an answer, optional raw content, and a recency filter. There is no separate fetch tool in
`src/aura/tools`.

| | Aura web_search (Tavily) | OpenCode webfetch/websearch | Browser (Playwright MCP or desktop) |
|---|---|---|---|
| Who calls it | Aura's own agents | OpenCode coding agents | OpenCode coding agents |
| JavaScript pages | no | no | yes |
| Logins, clicks, forms | no | no | yes |
| Cost / risk | low, API key | low | high: heavy, prompt injection from pages, can act on signed-in sessions |
| Fits Aura's gating | yes, her tools | permission by URL | needs explicit deny/allow and workspace policy |

Browser use matters only for delegated work that must test a running web page or read JS-only sites.
Aura's own research is already covered by web_search; a browser adds risk without helping that.

## Upgrade notes (v2.3.2 to v2.4.x), for reference

From the v2.4.0 notes (v2.4.1 lists none): `experimental_image_generate` renamed `generate_image`
(saved always-allow approvals not carried over); plugins on `@latest` or ranges auto-update; Copilot no
longer reads `GITHUB_TOKEN`; MCP servers without `protocol` try the newest protocol first (set
`protocol: "legacy"` if one misbehaves); Code Mode paths `session_rename`/`session_move` renamed to
`session.rename`/`.move`; SDK plugins load in the background so model/provider/websearch lists can be
empty right after startup (poll or wait for `*.updated`); assistant parts stored as rows
(`experimental.part_rows: false` restores the old way); TUI theme and OpenTUI changes (not relevant
to a headless server). The first one to check against Aura: the `agents` config patch, the saved
openapi spec, and `OpenCodeClient` endpoints would all need re-verifying against a v2.4 spec, and the
managed process currently refuses another major version only (so 2.4 passes that check).

## Recommendation

**Wait; do not upgrade the pin for this.** If Mai wants browser use now, enable Playwright MCP
in v2.3.2 in Aura's own generated config, headless, for one agent only (the coder), after a short
trial on the real binary. The built-in browser is a desktop-app feature and does not obviously help
a headless `opencode serve`. Revisit after v2.4.x has run a few weeks and a v2.4 OpenAPI file has been
diffed against the saved v2.3.2 one (a separate card, not this one).
