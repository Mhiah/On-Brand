from onbrand.rules import Profile, lint, mechanical_fix


def nimbus(**kw):
    base = dict(name="Nimbus", display_name="Nimbus Protocol", person="third",
                banned=["revolutionary", "game-changer", "LFG"], preferred={"NIMBUS": "Nimbus"},
                packs=["crypto"], max_chars=280, max_hashtags=1, max_emojis=1, max_exclamations=0)
    base.update(kw)
    return Profile(**base)


def details(text, profile=None):
    return [v.detail for v in lint(text, profile or nimbus()).violations]


def test_clean_copy_passes():
    v = lint("Nimbus Protocol shipped its audit today. The team published the full report.", nimbus())
    assert v.passed and v.score == 100 and not v.violations


def test_first_person_in_third_person_brand():
    v = lint("We just shipped our audit.", nimbus())
    assert not v.passed and v.violations[0].rule == "person"


def test_banned_and_spelling():
    d = details("NIMBUS is a revolutionary bridge.")
    assert any("banned word 'revolutionary'" in x for x in d)
    assert any("'NIMBUS' should be 'Nimbus'" in x for x in d)


def test_banned_word_needs_whole_word():
    assert not any("banned" in x for x in details("The evolutionary path of Nimbus Protocol."))


def test_crypto_pack():
    d = details("Nimbus Protocol: guaranteed returns of 20% APY, risk-free.")
    assert any("guaranteed returns" in x for x in d)
    assert any("no risk" in x for x in d)
    assert any("NFA" in x for x in d)
    ok = details("Nimbus Protocol staking is live. Rewards vary. NFA, DYOR.")
    assert not any(x for x in ok if "Crypto" in x)


def test_multiplier_vs_speed():
    assert any("multiple" in x for x in details("Nimbus Protocol could 100x."))
    assert not any("multiple" in x for x in details("Nimbus Protocol is 10x faster."))


def test_limits():
    d = details("Nimbus Protocol!!! " + "#a #b " + "x" * 300)
    assert any("characters" in x for x in d)
    assert any("hashtags" in x for x in d)
    assert any("exclamation" in x for x in d)


def test_required_phrase():
    p = nimbus(required=["#NimbusMainnet"])
    assert any("missing required" in x for x in details("Nimbus Protocol is live.", p))


def test_mechanical_fix():
    assert mechanical_fix("NIMBUS is live", nimbus()) == "Nimbus is live"


def test_brief_mentions_rules():
    b = nimbus().brief()
    assert "THIRD person" in b and "revolutionary" in b and "NFA" in b


def test_crypto_flags_promised_return_rate():
    from onbrand.rules import Profile, lint
    p = Profile(name="n", display_name="N", packs=["crypto"])
    bad = lint("Nimbus Protocol's staking program offers 50% returns. NFA.", p)
    assert any("specific return rate" in v.detail for v in bad.violations)
    ok = lint("Nimbus Protocol has launched staking. Returns are not guaranteed. NFA.", p)
    assert not any("specific return rate" in v.detail for v in ok.violations)
