"""Run:  python -m unittest discover -s tests -v   (from the mvp/ folder)"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sagarakshak import ed25519, geo, models  # noqa: E402
from sagarakshak.agents import regional_advisory  # noqa: E402
from sagarakshak.data import DataLayer  # noqa: E402
from sagarakshak.orchestrator import handle  # noqa: E402
from sagarakshak.verifier import verify_one  # noqa: E402

BOAT = (9.56, 79.37)


class Geo(unittest.TestCase):
    def test_haversine_one_degree_lat(self):
        self.assertAlmostEqual(geo.haversine_km(9, 79, 10, 79), 111.2, delta=0.2)

    def test_sides_of_imbl(self):
        self.assertEqual(geo.side(9.56, 79.30), "IN")
        self.assertEqual(geo.side(9.56, 79.60), "LK")
        self.assertEqual(geo.side(9.385, 79.52), "LK")   # Kachchatheevu lies on the Sri Lankan side

    def test_distance_to_imbl_matches_side_switch(self):
        km, near = geo.dist_to_imbl_km(*BOAT)
        self.assertTrue(3 < km < 8, km)
        self.assertAlmostEqual(geo.dist_to_imbl_km(*near)[0], 0, delta=0.01)

    def test_land_mask(self):
        self.assertTrue(geo.is_land(9.29, 79.30))    # Rameswaram island
        self.assertTrue(geo.is_land(9.2, 80.4))      # northern Sri Lanka
        self.assertFalse(geo.is_land(*BOAT))


class Ed25519(unittest.TestCase):
    def test_rfc8032_vector_1(self):
        sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
                            "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertEqual(ed25519.public_key(sk), pk)
        self.assertEqual(ed25519.sign(sk, b""), sig)
        self.assertTrue(ed25519.verify(pk, b"", sig))

    def test_rfc8032_vector_2(self):
        sk = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
        pk = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        sig = bytes.fromhex("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
        self.assertEqual(ed25519.public_key(sk), pk)
        self.assertEqual(ed25519.sign(sk, b"\x72"), sig)

    def test_tamper_fails(self):
        seed = bytes(range(32))
        pk = ed25519.public_key(seed)
        sig = ed25519.sign(seed, b"imbl:79.3767")
        self.assertFalse(ed25519.verify(pk, b"imbl:79.5767", sig))


class Science(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dl = DataLayer()
        cls.adv = regional_advisory(cls.dl)

    def test_rk4_uniform_flow_is_exact(self):
        class Uniform:            # 0.5 m/s due east, no wind
            def fast(self, f, *_):
                return {"cu": 0.5, "cv": 0.0}.get(f, 0.0)
        tr, _ = models.rk4_track(Uniform(), 10.8, 80.5, 0, 2, dict(sc=1, rc=0, lw=0, rw=0))
        km = geo.haversine_km(10.8, 80.5, *tr[-1])
        self.assertAlmostEqual(km, 0.5 * 3.6 * 2, delta=0.05)

    def test_drift_is_deterministic_for_seed(self):
        a = models.drift_ensemble(self.dl, *BOAT, 0, 4, 10, 3)["stats"]
        b = models.drift_ensemble(self.dl, *BOAT, 0, 4, 10, 3)["stats"]
        self.assertEqual(a, b)

    def test_advisory_never_recommends_across_imbl(self):
        r = handle(self.dl, self.adv, "where is the nearest fishing zone?", *BOAT)
        for z in r["map"]["fish"]["zones"]:
            self.assertEqual(geo.side(z["lat"], z["lon"]), "IN")


class Verifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dl = DataLayer()
        cls.adv = regional_advisory(cls.dl)

    def ask(self, q, **kw):
        return handle(self.dl, self.adv, q, *BOAT, **kw)

    def test_normal_question_all_verified(self):
        r = self.ask("Is it safe to go out tomorrow morning, and where will the fish be?")
        self.assertTrue(r["claims"])
        self.assertTrue(all(c["status"] == "verified" for c in r["claims"]),
                        [(c["label"], c["reason"]) for c in r["claims"] if c["status"] != "verified"])

    def test_fabricated_input_blocked_at_provenance(self):
        r = self.ask("where is the nearest fishing zone?", fault="pfz")
        bad = [c for c in r["claims"] if c["status"] == "blocked"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["gate"], "provenance")

    def test_altered_value_blocked_at_reproduction(self):
        r = self.ask("Am I close to the border?")
        c = copy.deepcopy(next(c for c in r["claims"] if c["kind"] == "drift"))
        c["value"]["p_cross"] = 0.05          # agent understates the risk
        self.assertEqual(verify_one(self.dl, c)["gate"], "reproduction")

    def test_cloud_gap_withheld(self):
        r = self.ask("What is the chlorophyll at Kachchatheevu right now?")
        chl = next(c for c in r["claims"] if c["params"].get("field") == "chl")
        self.assertEqual((chl["status"], chl["gate"]), ("blocked", "coverage"))

    def test_unknown_claim_kind_is_unverifiable(self):
        c = {"id": "X", "kind": "vibes", "value": 1, "inputs": [], "params": {}}
        self.assertEqual(verify_one(self.dl, c)["status"], "blocked")

    def test_out_of_scope_refused_without_claims(self):
        r = self.ask("How many fish will there be next month?")
        self.assertEqual(r["claims"], [])
        self.assertEqual(r["sections"][0]["agent"], "refusal")

    def test_tamil_question_answered_in_tamil(self):
        r = self.ask("நாளை காலை கடலுக்குப் போகலாமா, மீன் எங்கே கிடைக்கும்?")
        self.assertEqual(r["understood"]["lang"], "ta")
        self.assertEqual(set(r["understood"]["intents"]), {"weather", "border", "fish"})
        self.assertRegex(r["speak"], "[஀-௿]")

    def test_telugu_question_answered_in_telugu(self):
        r = self.ask("రేపు ఉదయం సముద్రంలోకి వెళ్ళవచ్చా, చేపలు ఎక్కడ దొరుకుతాయి?")
        self.assertEqual(r["understood"]["lang"], "te")
        self.assertEqual(set(r["understood"]["intents"]), {"weather", "border", "fish"})
        self.assertEqual(r["understood"]["window"]["key"], "tomorrow_morning")
        self.assertRegex(r["speak"], "[ఀ-౿]")

    def test_code_mixed_questions(self):
        cases = {
            "border enta duram?": ("te", {"border"}),                                  # romanised Telugu + English
            "border evlo dooram?": ("ta", {"border"}),                                 # romanised Tamil + English
            "బోర్డర్ ఎంత దూరం?": ("te", {"border"}),                                    # English word, Telugu script
            "பார்டர் எவ்வளவு தூரம்?": ("ta", {"border"}),                              # English word, Tamil script
            "repu udayam sea ki vellocha? fish ekkada?": ("te", {"weather", "border", "fish"}),
            "naalai kaalai pogalama, meen enga kidaikum?": ("ta", {"weather", "border", "fish"}),
            "inga fishing yen kammi aayiduchu?": ("ta", {"diagnose"}),
            "రేపు weather ఎలా ఉంది? fish zone ఎక్కడ?": ("te", {"weather", "fish"}),
            "Am I close to the border?": ("en", {"border"}),                           # plain English stays English
        }
        for q, (lang, intents) in cases.items():
            r = self.ask(q, lang_hint="te")
            self.assertEqual((r["understood"]["lang"], set(r["understood"]["intents"])), (lang, intents), q)
        r = self.ask("border enta duram?")
        self.assertRegex(r["speak"], "[ఀ-౿]")                               # answered in Telugu
        self.assertEqual(self.ask("vache nela enni chepalu?")["sections"][0]["agent"], "refusal")

    def test_short_question_uses_selected_language(self):
        self.assertEqual(self.ask("border?", lang_hint="ta")["understood"]["lang"], "ta")
        self.assertEqual(self.ask("border?")["understood"]["lang"], "en")

    def test_telugu_refusal(self):
        r = self.ask("వచ్చే నెల ఎన్ని చేపలు దొరుకుతాయి?")
        self.assertEqual((r["claims"], r["sections"][0]["agent"]), ([], "refusal"))


if __name__ == "__main__":
    unittest.main()
