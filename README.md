# On-Brand

**Brand voice and compliance rules Hermes can't break.**

A prompt can *ask* a model to write in a brand's voice. It still slips: a "we" in a third-person
brand, a banned buzzword, a misspelled product name, "guaranteed returns" in a crypto post, a
missing NFA. Someone has to catch it by hand, every time.

On-Brand moves those rules out of the prompt and into Hermes itself. Every draft is scored by a
deterministic linter before you see it, rewritten by your own model until it passes, and anything
Hermes tries to post through a tool is checked at the door.

```
you    ›  /onbrand use nimbus
you    ›  rewrite this intern draft for Nimbus: "We're going to the moon!!! 🚀🚀🚀 Stake now
          for GUARANTEED 50% returns, zero risk. LFG #staking #crypto #moon"

hermes ›  ```copy
          Nimbus Protocol has launched its new staking feature. Returns are not guaranteed
          and vary with market conditions. NFA. #Nimbus
          ```

you    ›  /onbrand check We're going to the moon!!! 🚀🚀🚀 GUARANTEED 50% returns, zero risk. LFG
on-brand › Nimbus Protocol: 0/100: banned word 'to the moon'; banned word 'LFG'; 3 emoji, limit
          is 1; 3 exclamation marks, limit is 0; promises guaranteed returns; claims no risk;
          hype price prediction; add 'NFA' or 'DYOR' when talking about price, tokens or returns
```

### Why this is a plugin, not a prompt

A system prompt is a request the model can ignore, forget or misread. On-Brand adds three
things a prompt cannot:

1. **An independent judge.** A rule-based linter scores every draft 0-100. The same text always
   gets the same verdict, and the model never grades its own work.
2. **A repair loop.** Drafts that fail go back to your model with the exact problems, and the
   result is checked again before it can replace the original.
3. **A gate on actions.** If Hermes tries to send, post or publish off-brand copy through any
   tool, the call is stopped before it leaves the machine.

In practice a good model often follows the rules on the first try, because On-Brand also gives it
the rules each turn. The linter, the log and the gate are what make that a guarantee instead of a
hope: you can see every check in `/onbrand log` and the Desktop feed.

## What it does

| | |
|---|---|
| **Brand profiles** | Person (third / first / any), tone, banned words, exact spellings, required tags, character / hashtag / emoji / exclamation limits, sample lines. |
| **Compliance packs** | `crypto`: no guaranteed returns, no "risk-free", no "100x" or "to the moon", NFA/DYOR required when copy talks price, tokens, yield or airdrops. `health`: no cure claims or rapid weight-loss promises, disclaimer required. |
| **Starts on brand** | While a brand is active, its rules are added to each turn, and Hermes is asked to put copy in ` ```copy ` blocks (copy-ready boxes in every Hermes surface). |
| **Checks every draft** | Each ` ```copy ` block is scored 0-100 by a rule-based linter. Same input, same verdict, every time. The model never grades its own work. |
| **Fixes what fails** | Exact spellings are corrected instantly. Anything else goes back to your active model with the rules and the specific problems, up to two rewrites, re-checked each time. Hermes' own chatter around the drafts is never touched. |
| **Says what it couldn't fix** | A draft that still fails comes back with a note listing exactly what is still wrong. Nothing is silently passed. |
| **Blocks off-brand posts** | When a tool that sends, posts, tweets, publishes or DMs is called with copy that breaks a hard rule, the call is blocked and Hermes is told what to fix. It rewrites and retries; clean copy goes through. |
| **Learns a brand** | Paste three or more approved posts and `onbrand_learn` drafts a profile for you to review. |
| **Voiceover mode** | `onbrand_voiceover` turns approved copy into a script that reads naturally aloud: no markdown or links, numbers and money spelled out, short sentences, optional SSML pauses. |
| **Desktop pane** | Brand switcher, enforcement toggles, totals, a quick-check box and a live feed of every fix and block with before/after scores. Status-bar chip shows the active brand. |

Hard rules (person, banned words, required phrases, length, compliance) fail a draft. Soft rules
(spellings, hashtag/emoji/exclamation limits) lower the score and are fixed when possible.

## Install

From the catalog (once listed):

```bash
hermes plugins install on-brand --enable
```

Straight from GitHub:

```bash
hermes plugins install Mhiah/On-Brand --enable
```

Restart Hermes (or the gateway) after installing. Then, in any Hermes chat:

```
/onbrand starter          # adds two example brands to try
/onbrand use nimbus       # turn enforcement on
```

Or just tell Hermes about a brand: *"Set up an On-Brand profile for Acme Labs: third person,
calm and precise, never say synergy or game-changer, max 280 characters, crypto compliance."*
Hermes calls `onbrand_rules` and saves it.

## Where it works

On-Brand runs inside Hermes itself, so it works on every surface Hermes serves. You install it
once; every surface below uses the same brands and settings.

| Surface | How to use it |
|---|---|
| **Terminal (CLI / TUI)** | Run `hermes`, then type `/onbrand ...` commands or ask for copy in plain English. Checks, fixes and blocks show as `/onbrand` notes under the reply. |
| **Hermes Desktop** | Same chat commands. Turn on the plugin's Desktop half under **Capabilities → Plugins → On-Brand** to get the status-bar chip (*On-Brand: Nimbus Protocol*) and the On-Brand pane: brand switcher, toggles, totals, quick check and a live feed of fixes and blocks. |
| **Telegram, Discord, Slack, WhatsApp and other messaging apps** | Connect the app with `hermes gateway setup`, then start the gateway (`hermes gateway start`). Message your bot as usual: `/onbrand` works there too and appears in Telegram's command menu. Replies are checked before they are sent. Turn on `hold_stream` (below) so off-brand text is never shown even briefly. |
| **API server (OpenAI-compatible `/v1/chat/completions`)** | Apps that talk to Hermes over its API get checked replies with no extra setup. With `hold_stream` on, the response stream carries only the checked text. |
| **Scheduled jobs and automations** | Copy written by cron jobs or other automations passes through the same checks, and their posting tools hit the same gate. |
| **Agent tools** | Hermes can call `onbrand_check`, `onbrand_rules`, `onbrand_learn` and `onbrand_voiceover` itself, on any surface, when you ask it to check, set up or learn a brand. |

### Good to know

- **One active brand per Hermes profile.** `/onbrand use <brand>` applies to every chat that
  profile serves, on every surface. To run two brands at once (say, two client Telegram groups),
  give each its own Hermes profile.
- **Streaming.** With `hold_stream` off (the default), a reply can stream in and then be replaced
  by its fixed version when the turn ends. With it on, users only ever see the checked version.
  For messaging apps and anything client-facing, turn it on.

## `/onbrand`

```
/onbrand                      status: active brand, settings, totals
/onbrand list                 all brand profiles
/onbrand use <brand> | off    turn enforcement on for a brand, or off
/onbrand show [brand]         a brand's rules
/onbrand new <brand>          create an empty profile
/onbrand set <brand> <field> <value>   person, tone, max_chars, max_hashtags, max_emojis, max_exclamations
/onbrand ban <brand> <word…>  /onbrand unban <brand> <word>
/onbrand spell <brand> <wrong> <right>
/onbrand require <brand> <phrase>
/onbrand pack <brand> crypto|health [off]
/onbrand check <text>         score text against the active brand
/onbrand log                  recent checks, fixes and blocks
/onbrand scope drafts|all     check ```copy blocks only (default) or whole replies
/onbrand autofix on|off       rewrite failing drafts automatically
/onbrand gate on|off          block off-brand outbound posts
/onbrand delete <brand>
```

## Agent tools

| Tool | What Hermes uses it for |
|---|---|
| `onbrand_check` | Score copy against a brand and list every rule it breaks; `fix: true` returns a corrected version. |
| `onbrand_rules` | Create or update a brand profile from a description. |
| `onbrand_learn` | Draft a profile from sample posts. |
| `onbrand_voiceover` | Turn on-brand copy into a read-aloud script. |

## Settings

Under **Settings → Plugins → On-Brand** in Desktop, or in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    on-brand:
      settings:
        hold_stream: true
```

| Key | Default | |
|---|---|---|
| `hold_stream` | `false` | Show replies only after On-Brand has checked them, so off-brand text never appears even briefly. Holds **every** reply in the profile while the plugin is enabled (no token streaming). Restart after changing. |
| `repair_timeout` | `12` | Seconds per model rewrite (3-20). All rewrites in one reply share a 24-second budget, inside Hermes' hook timeout. |

## How it works

| Hermes surface | Use |
|---|---|
| `pre_llm_call` hook | Adds the active brand's rules to the turn (only while a brand is active). |
| `transform_llm_output` hook | Finds ` ```copy ` drafts in the final reply, lints, repairs and re-lints them. |
| `pre_tool_call` hook | Blocks outbound tool calls whose copy breaks a hard rule. |
| `ctx.llm` | Rewrites failing drafts with the user's active model. |
| `ctx.register_tool` / `register_command` | The four tools and `/onbrand`. |
| `dashboard/plugin_api.py` + `desktop/plugin.js` | The Desktop pane, through `ctx.rest` and `plugin.on-brand.*` events. |

The verdict is always the linter's, never the model's: the model only proposes rewrites, and
each one is checked again before it can replace your draft.

## Disclosure

- **No network calls of its own, no telemetry, no credentials.** On-Brand never contacts any
  service directly.
- **Your active model sees drafts that need fixing.** Rewrites and `onbrand_learn` go through
  Hermes' `ctx.llm`, which sends the draft, the brand rules and the problems found to the provider
  and model you already use in Hermes.
- **It can block tool calls.** While a brand is active and the gate is on, outbound tools
  (names containing send, post, tweet, publish, reply, cast, dm, broadcast, announce, webhook, create_message, discord, telegram, slack) that carry
  copy breaking a hard rule are refused with an explanation. `/onbrand gate off` disables this.
- **It can change replies.** While a brand is active, ` ```copy ` blocks in Hermes' replies are
  replaced with corrected versions (`/onbrand autofix off` reports problems without rewriting).
- **Local storage:** profiles, settings and the last 60 checks (including draft text, up to 600
  characters each) are kept as JSON in `<HERMES_HOME>/plugin-data/on-brand/`.
- No shell commands, no background processes, no reads outside its own data folder.

## Development

```bash
git clone https://github.com/Mhiah/On-Brand && cd On-Brand
python -m pytest -c tests/pytest.ini --rootdir tests tests      # core + Hermes integration tests
hermes plugins validate . --install-deps                         # the catalog's own checks
```

The Hermes integration tests load the plugin through Hermes' real `PluginManager` and run when
`hermes_cli` is importable (they are skipped otherwise).

## License

MIT
