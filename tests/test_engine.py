import time

from onbrand import engine
from onbrand.rules import Profile


def nimbus():
    return Profile(name="nimbus", display_name="Nimbus Protocol", person="third",
                   banned=["revolutionary"], preferred={"NIMBUS": "Nimbus"}, packs=["crypto"],
                   max_chars=280)


GOOD = "Nimbus Protocol opened its testnet today. The team invites builders to try it. NFA."


def fake_llm(output, calls=None):
    def llm(messages, timeout):
        if calls is not None:
            calls.append(messages)
        return output() if callable(output) else output
    return llm


def test_reply_without_drafts_untouched():
    r = engine.enforce("Here's my plan for the week.", nimbus(), fake_llm(GOOD))
    assert not r.changed and r.drafts == []


def test_bad_draft_is_fixed_and_chatter_kept():
    reply = "Here you go:\n```copy\nWe are launching our revolutionary token!\n```\nWant more?"
    calls = []
    r = engine.enforce(reply, nimbus(), fake_llm(GOOD, calls))
    assert r.changed and GOOD in r.text
    assert r.text.startswith("Here you go:") and r.text.endswith("Want more?")
    assert r.drafts[0].outcome == "fixed" and r.drafts[0].verdict_after.passed
    assert "PROBLEMS FOUND" in calls[0][1]["content"]


def test_mechanical_only_fix_needs_no_model():
    reply = "```copy\nNIMBUS Protocol opened its testnet today.\n```"
    r = engine.enforce(reply, nimbus(), None)
    assert "Nimbus Protocol opened" in r.text and r.drafts[0].outcome == "fixed"


def test_unfixable_draft_is_flagged():
    reply = "```copy\nWe will 100x, guaranteed returns!\n```"
    r = engine.enforce(reply, nimbus(), fake_llm("We will 100x for sure"))
    assert r.drafts[0].outcome == "flagged"
    assert "On-Brand: still off brand" in r.text


def test_model_error_fails_open():
    def broken(messages, timeout):
        raise TimeoutError("slow")
    reply = "```copy\nWe are revolutionary\n```"
    r = engine.enforce(reply, nimbus(), broken)
    assert r.drafts[0].outcome == "flagged" and "repair unavailable" in r.drafts[0].note


def test_time_budget_is_respected():
    def slow(messages, timeout):
        time.sleep(0.05)
        return "We are still revolutionary"
    reply = "\n".join(f"```copy\nWe are revolutionary {i}\n```" for i in range(5))
    start = time.monotonic()
    r = engine.enforce(reply, nimbus(), slow, budget_s=3.2, max_repairs=2)
    assert time.monotonic() - start < 3.5
    assert any(d.note == "time budget used up" for d in r.drafts)


def test_autofix_off_only_flags():
    reply = "```copy\nWe are revolutionary\n```"
    r = engine.enforce(reply, nimbus(), fake_llm(GOOD), auto_fix=False)
    assert GOOD not in r.text and "still off brand" in r.text


def test_scope_all():
    r = engine.enforce("We are revolutionary", nimbus(), fake_llm(GOOD), scope="all")
    assert r.text == GOOD


def test_model_output_fences_and_quotes_stripped():
    r = engine.enforce("```copy\nWe rock\n```", nimbus(), fake_llm(f'"{GOOD}"'))
    assert f"```copy\n{GOOD}\n```" in r.text


def test_gate_helpers():
    assert engine.is_outbound("send_message")
    assert engine.is_outbound("x_post_tweet")
    assert engine.is_outbound("telegram_dm")
    assert not engine.is_outbound("read_file")
    assert not engine.is_outbound("gmail_search")
    assert not engine.is_outbound("onbrand_check")
    args = {"chat_id": 5, "message": "hello", "meta": {"caption": "pic"}}
    assert engine.outbound_text(args) == "hello\n\npic"


def test_gate_catches_webhook_tools():
    assert engine.is_outbound("connectors__discordbot__EXECUTE_WEBHOOK")
    assert not engine.is_outbound("read_file")
