"""Language layer: understanding a spoken/typed question, and phrasing verified answers.

MVP: rule-based intent parsing plus hand-written English/Tamil/Telugu templates. The
production path swaps in AI4Bharat IndicASR + IndicTrans2 at the edges; the
orchestrator and agents only ever see the structured intent, so nothing else changes.
"""
import datetime as dt
import re

from .data import PLACES, PLACE_ALIASES

TAMIL = re.compile(r"[஀-௿]")
TELUGU = re.compile(r"[ఀ-౿]")
LANG_NAME = {"en": "English", "ta": "Tamil", "te": "Telugu"}

# Keywords in English and in Tamil/Telugu script. English ones match a word start
# ("fish" matches "fishing"); script ones match anywhere (Indic words take suffixes).
# Script lists include how speech recognition spells common English words
# ("బోర్డర్" = border), because fishers mix English into Telugu and Tamil.
KEYWORDS = {
    "unsupported_forecast": ["next month", "next year", "how many fish", "fish population", "2030",
                             "அடுத்த மாதம்", "அடுத்த ஆண்டு", "எவ்வளவு மீன்",
                             "వచ్చే నెల", "వచ్చే సంవత్సరం", "ఎన్ని చేపలు"],
    "unsupported_price": ["price", "market", "விலை", "சந்தை", "ధర", "మార్కెట్"],
    "diagnose": ["why", "worse", "decline", "dropped", "less fish", "fewer", "ஏன்", "குறைந்", "ఎందుకు", "తగ్గ"],
    "fish": ["fish", "catch", "zone", "pfz", "மீன்", "ஃபிஷ்", "பிஷ்", "ஜோன்", "చేప", "మత్స్య", "ఫిష్", "జోన్"],
    "where": ["where", "nearest", "எங்கே", "அருகில", "ఎక్కడ", "దగ్గరలో"],
    "weather": ["safe", "weather", "wave", "storm", "wind", "rain", "cyclone", "go out", "sea today",
                "பாதுகாப்", "வானிலை", "அலை", "புயல்", "காற்று", "போகலாமா", "செல்லலாமா", "மழை",
                "வெதர்", "சேஃப்", "சேப்", "ஸ்டார்ம்", "சைக்ளோன்", "விண்ட்", "வேவ்",
                "సురక్షిత", "వాతావరణ", "అల", "తుఫాను", "గాలి", "వర్షం", "వెళ్ళవచ్చా", "వెళ్లవచ్చా", "వెళ్ళొచ్చా",
                "వెదర్", "సేఫ్", "స్టార్మ్", "సైక్లోన్", "విండ్", "వేవ్"],
    "safety": ["safe", "go out", "பாதுகாப்", "போகலாமா", "செல்லலாமா", "சேஃப்", "சேப்",
               "సురక్షిత", "వెళ్ళవచ్చా", "వెళ్లవచ్చా", "వెళ్ళొచ్చా", "సేఫ్"],
    "border": ["border", "boundary", "imbl", "drift", "cross", "எல்லை", "பார்டர", "సరిహద్దు", "బోర్డర్"],
    "ocean": ["chlorophyll", "temperature", "sst", "plankton", "குளோரோபில்", "வெப்பநிலை", "டெம்பரேச்சர்",
              "క్లోరోఫిల్", "ఉష్ణోగ్రత", "టెంపరేచర్"],
    # "how far?" on its own is almost always about the border
    "distance": ["how far", "ఎంత దూరం", "எவ்வளவு தூரம்", "எவ்வளவு தொலைவு"],
}

# Telugu and Tamil typed in English letters ("border enta duram?"). Short words must
# match exactly; longer ones also match with suffixes ("chepa" → "chepalu").
ROMAN = {
    "te": {
        "unsupported_forecast": ["vache nela", "vachhe nela", "vachche nela", "enni chepalu"],
        "unsupported_price": ["dhara"],
        "diagnose": ["enduku", "takkuva", "taggindi", "tagginchi"],
        "fish": ["chepa", "chepalu", "matsya"],
        "where": ["ekkada"],
        "weather": ["vatavaranam", "vaatavaranam", "vathavaranam", "toofan", "tufan", "tufanu", "gaali", "gaalulu",
                    "alalu", "varsham", "vellocha", "vellacha", "vellavacha", "vellochha", "vellachha", "surakshit"],
        "safety": ["vellocha", "vellacha", "vellavacha", "vellochha", "vellachha", "surakshit"],
        "border": ["sarihaddu"],
        "ocean": ["ushnogratha", "ushnograta"],
        "distance": ["enta duram", "entha duram", "enta dooram", "entha dooram", "yenta duram", "entha dhooram"],
        "tomorrow": ["repu"], "morning": ["udayam", "podduna"], "evening": ["sayantram", "saayantram", "ratri", "raatri"],
    },
    "ta": {
        "unsupported_forecast": ["adutha maasam", "adutha masam", "evlo meen", "evvalavu meen"],
        "unsupported_price": ["vilai"],
        "diagnose": ["yen", "yaen", "kuranj", "koranj", "korainj", "kuraivu"],
        "fish": ["meen", "meenu", "meenpidi"],
        "where": ["enga", "engey", "engae", "enge"],
        "weather": ["vaanilai", "vanilai", "puyal", "kaathu", "kaatru", "alai", "alaigal", "mazhai",
                    "pogalama", "pogalaama", "pogalaamaa", "paadhukaap", "pathukaap"],
        "safety": ["pogalama", "pogalaama", "pogalaamaa", "paadhukaap", "pathukaap"],
        "border": ["ellai"],
        "ocean": ["veppanilai", "vepanilai"],
        "distance": ["evlo dooram", "evlo thooram", "evvalavu dooram", "evvalavu thooram", "evlo dhooram"],
        "tomorrow": ["naalai", "nalaiku", "naalaiku", "naalaikku"], "morning": ["kaalai", "kalaila", "kaalaila"],
        "evening": ["maalai", "iravu", "raathiri"],
    },
}

# Words that say "this is romanised Telugu / Tamil" even when the topic word is English.
MARKERS = {
    "te": ["enta", "entha", "yenta", "duram", "ekkada", "chepa", "repu", "udayam", "vellocha", "vellacha",
           "vellavacha", "enduku", "undi", "unnanu", "unnana", "unnava", "nenu", "emi", "ela", "sarihaddu",
           "gaali", "vatavaranam", "ippudu", "eeroju", "ivala", "takkuva", "taggindi", "vache", "enni",
           "dorukutayi", "dorukuthayi", "chala", "ledu", "avuna", "kada", "cheppu", "cheppandi", "ki", "lo"],
    "ta": ["evlo", "evvalavu", "enga", "engey", "engae", "meen", "meenu", "naalai", "nalaiku", "kaalai",
           "pogalama", "pogalaama", "yen", "yaen", "ellai", "iruku", "irukku", "irukka", "irukkum", "naan",
           "ippo", "inniku", "indru", "kuranj", "korainj", "kammi", "adutha", "maasam", "vaanilai", "puyal",
           "kaathu", "alai", "mazhai", "sollu", "sollunga", "enna", "epdi", "eppadi", "kidaikum", "kidaikkum",
           "thooram"],
}
# "ki", "lo" are too common to decide on their own; they only add weight.
WEAK = {"ki", "lo", "ela", "emi", "enna"}

_TOKEN = re.compile(r"[a-z]+|[஀-௿]+|[ఀ-౿]+")


def _roman_hit(tokens, low, k):
    if " " in k:
        return k in low
    return any(t == k or (len(k) >= 5 and t.startswith(k)) for t in tokens)


def _has(low, tokens, key, langs=("te", "ta")):
    for k in KEYWORDS.get(key, []):
        if k.isascii():
            if (" " in k and k in low) or any(t.startswith(k) for t in tokens):
                return True
        elif k in low:
            return True
    return any(_roman_hit(tokens, low, k) for lg in langs for k in ROMAN[lg].get(key, []))


def detect_language(text, tokens, hint=None):
    """(lang, reason). Script wins; otherwise romanised markers; otherwise the UI language
    for one- or two-word questions ("border?"); otherwise English."""
    ta, te = len(TAMIL.findall(text)), len(TELUGU.findall(text))
    if ta or te:
        return ("ta", "Tamil script") if ta >= te else ("te", "Telugu script")
    hits = {lg: [t for t in tokens if any(t == m or (len(m) >= 5 and t.startswith(m)) for m in MARKERS[lg])]
            for lg in MARKERS}
    score = {lg: sum(0.3 if t in WEAK else 1 for t in hs) for lg, hs in hits.items()}
    best = max(score, key=score.get)
    if score[best] >= 1 and score[best] > score["te" if best == "ta" else "ta"]:
        return best, f"romanised {LANG_NAME[best]} ({', '.join(dict.fromkeys(h for h in hits[best] if h not in WEAK))})"
    if hint in ("ta", "te") and len(tokens) <= 2:
        return hint, f"short question, using the selected language ({LANG_NAME[hint]})"
    return "en", "English"


def understand(text, issued, hint=None):
    low = text.lower().strip()
    tokens = _TOKEN.findall(low)
    lang, reason = detect_language(text, tokens, hint)
    place = None
    for name in PLACES:
        if name in low:
            place = name
    for alias, name in PLACE_ALIASES.items():
        if alias in low:
            place = name

    has = lambda key: _has(low, tokens, key)  # noqa: E731
    intents, unsupported = [], None
    if has("unsupported_forecast"):
        unsupported = "forecast"
    elif has("unsupported_price"):
        unsupported = "price"
    else:
        if has("weather"):
            intents.append("weather")
        if has("border") or has("safety"):
            intents.append("border")
        if has("diagnose"):
            intents.append("diagnose")
        if has("fish") and ("diagnose" not in intents or has("where")):
            intents.append("fish")
        if has("ocean"):
            intents.append("ocean")
        if not intents and has("distance"):
            intents.append("border")
    return {"lang": lang, "lang_reason": reason, "intents": intents, "unsupported": unsupported,
            "place": place, "window": time_window(low, issued, tokens)}


def time_window(low, issued, tokens=()):
    """Turn 'tomorrow morning' / 'நாளை காலை' / 'repu udayam' into hours after the data issue time."""
    def said(words, key):
        return any(w in low for w in words) or any(_roman_hit(tokens, low, k) for lg in ROMAN for k in ROMAN[lg][key])
    tomorrow = said(("tomorrow", "நாளை", "రేపు"), "tomorrow")
    morning = said(("morning", "காலை", "ఉదయం"), "morning")
    evening = said(("evening", "tonight", "மாலை", "இரவு", "సాయంత్రం", "రాత్రి"), "evening")
    day = issued.date() + dt.timedelta(days=1 if tomorrow else 0)

    def at(d, h):
        return dt.datetime.combine(d, dt.time(h), tzinfo=issued.tzinfo)

    if morning:
        start, end, key = at(day, 5), at(day, 10), "tomorrow_morning" if tomorrow else "morning"
    elif evening:
        start, end, key = at(day, 17), at(day, 22), "tomorrow_evening" if tomorrow else "evening"
    elif tomorrow:
        start, end, key = at(day, 5), at(day, 17), "tomorrow"
    else:
        start, end, key = issued, issued + dt.timedelta(hours=12), "next12"
    if end <= issued:            # asked for "morning" after it has passed: use tomorrow's
        start, end = start + dt.timedelta(days=1), end + dt.timedelta(days=1)
    t0 = max(0.0, (start - issued).total_seconds() / 3600)
    t1 = max(t0, (end - issued).total_seconds() / 3600)
    return {"key": key, "t0": round(t0, 2), "t1": round(t1, 2),
            "start": start.isoformat(), "end": end.isoformat()}


COMPASS = {
    "en": {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east",
           "S": "south", "SW": "south-west", "W": "west", "NW": "north-west"},
    "ta": {"N": "வடக்கு", "NE": "வடகிழக்கு", "E": "கிழக்கு", "SE": "தென்கிழக்கு",
           "S": "தெற்கு", "SW": "தென்மேற்கு", "W": "மேற்கு", "NW": "வடமேற்கு"},
    "te": {"N": "ఉత్తరం", "NE": "ఈశాన్యం", "E": "తూర్పు", "SE": "ఆగ్నేయం",
           "S": "దక్షిణం", "SW": "నైరుతి", "W": "పడమర", "NW": "వాయువ్యం"},
}

WHEN = {
    "en": {"next12": "Next 12 hours", "tomorrow_morning": "Tomorrow morning (05:00–10:00)",
           "morning": "This morning (05:00–10:00)", "tomorrow_evening": "Tomorrow evening (17:00–22:00)",
           "evening": "This evening (17:00–22:00)", "tomorrow": "Tomorrow (05:00–17:00)"},
    "ta": {"next12": "அடுத்த 12 மணி நேரம்", "tomorrow_morning": "நாளை காலை (05:00–10:00)",
           "morning": "இன்று காலை (05:00–10:00)", "tomorrow_evening": "நாளை மாலை (17:00–22:00)",
           "evening": "இன்று மாலை (17:00–22:00)", "tomorrow": "நாளை (05:00–17:00)"},
    "te": {"next12": "తదుపరి 12 గంటలు", "tomorrow_morning": "రేపు ఉదయం (05:00–10:00)",
           "morning": "ఈరోజు ఉదయం (05:00–10:00)", "tomorrow_evening": "రేపు సాయంత్రం (17:00–22:00)",
           "evening": "ఈరోజు సాయంత్రం (17:00–22:00)", "tomorrow": "రేపు (05:00–17:00)"},
}

DRIVER_LABEL = {
    "en": {"upwelling": "Upwelling (cold, nutrient-rich water rising)", "chl": "Chlorophyll (plankton)",
           "sst_anom": "Sea temperature", "rain": "Rainfall / river run-off", "effort": "Fishing pressure (boat-days)"},
    "ta": {"upwelling": "அடிநீர் எழுச்சி (குளிர்ந்த, சத்து நிறைந்த நீர் மேலே வருவது)",
           "chl": "குளோரோபில் (பிளாங்க்டன்)", "sst_anom": "கடல் வெப்பநிலை",
           "rain": "மழை / ஆற்று நீர்", "effort": "மீன்பிடி அழுத்தம் (படகு-நாட்கள்)"},
    "te": {"upwelling": "అప్‌వెల్లింగ్ (లోతు నుండి చల్లని, పోషకాలు ఉన్న నీరు పైకి రావడం)",
           "chl": "క్లోరోఫిల్ (ప్లాంక్టన్)", "sst_anom": "సముద్ర ఉష్ణోగ్రత",
           "rain": "వర్షం / నదీ ప్రవాహం", "effort": "చేపల వేట ఒత్తిడి (పడవ-రోజులు)"},
}

T = {
    "en": {
        "weather_ok": "{when}: sea looks workable — waves up to {hs} m, wind up to {wind} km/h, thunderstorm chance {ts}%.",
        "weather_warn": "{when}: go with care — waves up to {hs} m, wind up to {wind} km/h, thunderstorm chance {ts}%.",
        "weather_crit": "{when}: do not go out — waves up to {hs} m, wind up to {wind} km/h, thunderstorm chance {ts}%.",
        "weather_later": "Later, around {time}: thunderstorm chance rises to {ts}% and waves to {hs} m. Be back ashore by {back}.",
        "border_far": "You are {km} km from the border (IMBL). If your engine stopped, none of {n} drift scenarios cross it in the next {h} hours.",
        "border_risk": "You are {km} km from the border (IMBL). If your engine stopped, {p}% of {n} drift scenarios cross it within {h} hours — most likely {t10}–{t90} h from now.",
        "border_other": "Your position is on the Sri Lankan side of the IMBL. Head {bearing}° ({compass}) now.",
        "border_head": "To gain distance, steer {bearing}° ({compass}).",
        "fish_intro": "Best fishing zones near you (temperature front + plankton):",
        "fish_zone": "{id}: {km} km {compass} (bearing {bearing}°) — front {grad} °C/km, chlorophyll {chl} mg/m³.",
        "fish_excluded": "A stronger zone lies {km} km {compass}, but across the border. Not advised.",
        "fish_none": "No strong fishing zone within {range} km of you today.",
        "diag_intro": "Catch per boat-day in {sector} is {dir} {pct}% over the last {k} weeks. Likely causes, ranked by evidence:",
        "diag_item": "{rank}. {label} — {updown} than normal ({z} σ); {link} (r = {r}).",
        "diag_chain": "These fit one story: weaker upwelling → warmer surface water and less plankton → fewer fish.",
        "diag_effort": "Extra boats are not the main cause here, though they add pressure.",
        "diag_caveat": "This ranks evidence; it is not proof of cause.",
        "higher": "higher", "lower": "lower", "with": "moves with catch", "against": "moves against catch", "down": "down", "up": "up",
        "ocean_sst": "{place}: sea temperature {v} °C.",
        "ocean_chl": "{place}: chlorophyll {v} mg/m³.",
        "your_position": "Your position",
        "withheld": "{what}: withheld — {why}. Don't rely on a guess.",
        "why_cloud": "no valid satellite reading there today (cloud cover)",
        "why_fabricated": "the figure did not match the satellite record",
        "why_repro": "the figure could not be reproduced",
        "w_weather": "Sea-safety verdict", "w_zone": "Fishing zone {id}", "w_sst": "Sea temperature",
        "w_chl": "Chlorophyll", "w_border": "Border drift estimate", "w_diag": "Cause ranking",
        "unsupported": "I can't answer that from the data I have. {why} I won't guess.",
        "unsupported_forecast": "No dataset I use forecasts fish numbers a month ahead.",
        "unsupported_price": "I have no market-price data.",
        "clarify": "I can help with: where the fish are, whether the sea is safe, how close the border is, and why catch has changed. Try one of those.",
    },
    "ta": {
        "weather_ok": "{when}: கடல் நிலை சரி — அலை {hs} மீ வரை, காற்று மணிக்கு {wind} கி.மீ வரை, இடி-மழை வாய்ப்பு {ts}%.",
        "weather_warn": "{when}: கவனமாகச் செல்லுங்கள் — அலை {hs} மீ வரை, காற்று மணிக்கு {wind} கி.மீ வரை, இடி-மழை வாய்ப்பு {ts}%.",
        "weather_crit": "{when}: கடலுக்குச் செல்ல வேண்டாம் — அலை {hs} மீ வரை, காற்று மணிக்கு {wind} கி.மீ வரை, இடி-மழை வாய்ப்பு {ts}%.",
        "weather_later": "பின்னர், சுமார் {time} மணிக்கு: இடி-மழை வாய்ப்பு {ts}% ஆகவும், அலை {hs} மீ ஆகவும் உயரும். {back} மணிக்குள் கரை திரும்புங்கள்.",
        "border_far": "நீங்கள் எல்லையிலிருந்து (IMBL) {km} கி.மீ தொலைவில் இருக்கிறீர்கள். இயந்திரம் நின்றாலும், அடுத்த {h} மணி நேரத்தில் {n} கணிப்புகளில் எதுவும் எல்லையைத் தாண்டவில்லை.",
        "border_risk": "நீங்கள் எல்லையிலிருந்து (IMBL) {km} கி.மீ தொலைவில் இருக்கிறீர்கள். இயந்திரம் நின்றால், {n} கணிப்புகளில் {p}% படகு {h} மணி நேரத்துக்குள் எல்லையைத் தாண்டும் — பெரும்பாலும் இப்போதிலிருந்து {t10}–{t90} மணி நேரத்தில்.",
        "border_other": "நீங்கள் இலங்கைப் பக்கம் இருக்கிறீர்கள். உடனே {bearing}° ({compass}) திசையில் திரும்புங்கள்.",
        "border_head": "தூரத்தை அதிகரிக்க {bearing}° ({compass}) திசையில் செல்லுங்கள்.",
        "fish_intro": "உங்களுக்கு அருகிலுள்ள சிறந்த மீன்பிடி இடங்கள் (வெப்ப எல்லை + பிளாங்க்டன்):",
        "fish_zone": "{id}: {compass} திசையில் {km} கி.மீ (திசைக்கோணம் {bearing}°) — வெப்ப மாற்றம் {grad} °C/கி.மீ, குளோரோபில் {chl} மி.கி/மீ³.",
        "fish_excluded": "{compass} திசையில் {km} கி.மீ தொலைவில் இன்னும் வலுவான இடம் உள்ளது, ஆனால் அது எல்லைக்கு அப்பால். பரிந்துரைக்கவில்லை.",
        "fish_none": "இன்று உங்களிடமிருந்து {range} கி.மீ-க்குள் வலுவான மீன்பிடி இடம் இல்லை.",
        "diag_intro": "{sector} பகுதியில் கடந்த {k} வாரங்களில் ஒரு படகு-நாள் பிடிப்பு {pct}% {dir}. சான்றுகளின்படி சாத்தியமான காரணங்கள்:",
        "diag_item": "{rank}. {label} — இயல்பை விட {updown} ({z} σ); {link} (r = {r}).",
        "diag_chain": "இவை ஒரே கதையைச் சொல்கின்றன: அடிநீர் எழுச்சி குறைந்தது → மேற்பரப்பு நீர் சூடானது, பிளாங்க்டன் குறைந்தது → மீன் குறைந்தது.",
        "diag_effort": "கூடுதல் படகுகள் முக்கிய காரணம் அல்ல, ஆனால் அழுத்தத்தைக் கூட்டுகின்றன.",
        "diag_caveat": "இது சான்றுகளின் வரிசை மட்டுமே; காரணத்துக்கான உறுதியான நிரூபணம் அல்ல.",
        "higher": "அதிகம்", "lower": "குறைவு", "with": "பிடிப்புடன் சேர்ந்து மாறுகிறது", "against": "பிடிப்புக்கு எதிர்த்திசையில் மாறுகிறது", "down": "குறைந்துள்ளது", "up": "உயர்ந்துள்ளது",
        "ocean_sst": "{place}: கடல் வெப்பநிலை {v} °C.",
        "ocean_chl": "{place}: குளோரோபில் {v} மி.கி/மீ³.",
        "your_position": "உங்கள் இடம்",
        "withheld": "{what}: தரப்படவில்லை — {why}. ஊகத்தை நம்ப வேண்டாம்.",
        "why_cloud": "இன்று அங்கே சரியான செயற்கைக்கோள் அளவீடு இல்லை (மேகமூட்டம்)",
        "why_fabricated": "அந்த எண் செயற்கைக்கோள் பதிவுடன் பொருந்தவில்லை",
        "why_repro": "அந்த எண்ணை மீண்டும் கணக்கிட்டு உறுதிப்படுத்த முடியவில்லை",
        "w_weather": "கடல் பாதுகாப்பு முடிவு", "w_zone": "மீன்பிடி இடம் {id}", "w_sst": "கடல் வெப்பநிலை",
        "w_chl": "குளோரோபில்", "w_border": "எல்லை நகர்வுக் கணிப்பு", "w_diag": "காரண வரிசை",
        "unsupported": "என்னிடம் உள்ள தரவுகளைக் கொண்டு இதற்குப் பதில் சொல்ல முடியாது. {why} நான் ஊகிக்க மாட்டேன்.",
        "unsupported_forecast": "ஒரு மாதம் முன்பே மீன் எண்ணிக்கையைக் கணிக்கும் தரவு எதுவும் என்னிடம் இல்லை.",
        "unsupported_price": "என்னிடம் சந்தை விலைத் தரவு இல்லை.",
        "clarify": "நான் உதவக்கூடியவை: மீன் எங்கே, கடல் பாதுகாப்பா, எல்லை எவ்வளவு தூரம், பிடிப்பு ஏன் மாறியது. இவற்றில் ஒன்றைக் கேளுங்கள்.",
    },
    "te": {
        "weather_ok": "{when}: సముద్రం అనుకూలంగా ఉంది — అలలు {hs} మీ. వరకు, గాలి గంటకు {wind} కి.మీ. వరకు, ఉరుములతో కూడిన వర్షం అవకాశం {ts}%.",
        "weather_warn": "{when}: జాగ్రత్తగా వెళ్ళండి — అలలు {hs} మీ. వరకు, గాలి గంటకు {wind} కి.మీ. వరకు, ఉరుములతో కూడిన వర్షం అవకాశం {ts}%.",
        "weather_crit": "{when}: సముద్రంలోకి వెళ్ళవద్దు — అలలు {hs} మీ. వరకు, గాలి గంటకు {wind} కి.మీ. వరకు, ఉరుములతో కూడిన వర్షం అవకాశం {ts}%.",
        "weather_later": "తర్వాత, సుమారు {time} గంటలకు: ఉరుములతో కూడిన వర్షం అవకాశం {ts}%కి, అలలు {hs} మీ.కి పెరుగుతాయి. {back} లోపు ఒడ్డుకు తిరిగి రండి.",
        "border_far": "మీరు సరిహద్దు (IMBL) నుండి {km} కి.మీ. దూరంలో ఉన్నారు. ఇంజిన్ ఆగిపోయినా, తదుపరి {h} గంటల్లో {n} అంచనాల్లో ఏదీ సరిహద్దు దాటలేదు.",
        "border_risk": "మీరు సరిహద్దు (IMBL) నుండి {km} కి.మీ. దూరంలో ఉన్నారు. ఇంజిన్ ఆగిపోతే, {n} అంచనాల్లో {p}% లో పడవ {h} గంటల్లోపు సరిహద్దు దాటుతుంది — ఎక్కువగా ఇప్పటి నుండి {t10}–{t90} గంటల్లో.",
        "border_other": "మీరు శ్రీలంక వైపు ఉన్నారు. వెంటనే {bearing}° ({compass}) దిశలో తిరగండి.",
        "border_head": "దూరం పెంచుకోవడానికి {bearing}° ({compass}) దిశలో వెళ్ళండి.",
        "fish_intro": "మీకు దగ్గరలోని ఉత్తమ చేపల వేట ప్రాంతాలు (ఉష్ణోగ్రత సరిహద్దు + ప్లాంక్టన్):",
        "fish_zone": "{id}: {compass} దిశలో {km} కి.మీ. (దిశాకోణం {bearing}°) — ఉష్ణోగ్రత మార్పు {grad} °C/కి.మీ., క్లోరోఫిల్ {chl} మి.గ్రా/మీ³.",
        "fish_excluded": "{compass} దిశలో {km} కి.మీ. దూరంలో ఇంకా బలమైన ప్రాంతం ఉంది, కానీ అది సరిహద్దు అవతల ఉంది. సిఫార్సు చేయడం లేదు.",
        "fish_none": "ఈరోజు మీకు {range} కి.మీ. లోపల బలమైన చేపల వేట ప్రాంతం లేదు.",
        "diag_intro": "{sector} ప్రాంతంలో గత {k} వారాల్లో ఒక్కో పడవ-రోజు పట్టు {pct}% {dir}. ఆధారాల ప్రకారం సంభావ్య కారణాలు:",
        "diag_item": "{rank}. {label} — సాధారణం కంటే {updown} ({z} σ); {link} (r = {r}).",
        "diag_chain": "ఇవన్నీ ఒకే కథ చెబుతున్నాయి: లోతు నుండి చల్లని నీరు పైకి రావడం తగ్గింది → ఉపరితల నీరు వేడెక్కింది, ప్లాంక్టన్ తగ్గింది → చేపలు తగ్గాయి.",
        "diag_effort": "అదనపు పడవలు ప్రధాన కారణం కాదు, కానీ ఒత్తిడిని పెంచుతున్నాయి.",
        "diag_caveat": "ఇది ఆధారాల వరుస మాత్రమే; కారణానికి ఖచ్చితమైన రుజువు కాదు.",
        "higher": "ఎక్కువ", "lower": "తక్కువ", "with": "పట్టుతో పాటు మారుతోంది", "against": "పట్టుకు వ్యతిరేకంగా మారుతోంది",
        "down": "తగ్గింది", "up": "పెరిగింది",
        "ocean_sst": "{place}: సముద్ర ఉష్ణోగ్రత {v} °C.",
        "ocean_chl": "{place}: క్లోరోఫిల్ {v} మి.గ్రా/మీ³.",
        "your_position": "మీ స్థానం",
        "withheld": "{what}: ఇవ్వడం లేదు — {why}. ఊహపై ఆధారపడవద్దు.",
        "why_cloud": "ఈరోజు అక్కడ సరైన ఉపగ్రహ కొలత లేదు (మేఘాలు)",
        "why_fabricated": "ఆ సంఖ్య ఉపగ్రహ రికార్డుతో సరిపోలలేదు",
        "why_repro": "ఆ సంఖ్యను మళ్ళీ లెక్కించి నిర్ధారించలేకపోయాం",
        "w_weather": "సముద్ర భద్రత నిర్ణయం", "w_zone": "చేపల వేట ప్రాంతం {id}", "w_sst": "సముద్ర ఉష్ణోగ్రత",
        "w_chl": "క్లోరోఫిల్", "w_border": "సరిహద్దు కదలిక అంచనా", "w_diag": "కారణాల వరుస",
        "unsupported": "నా దగ్గర ఉన్న డేటాతో దీనికి సమాధానం చెప్పలేను. {why} నేను ఊహించను.",
        "unsupported_forecast": "ఒక నెల ముందే చేపల సంఖ్యను అంచనా వేసే డేటా నా దగ్గర లేదు.",
        "unsupported_price": "నా దగ్గర మార్కెట్ ధరల డేటా లేదు.",
        "clarify": "నేను సహాయం చేయగలిగేవి: చేపలు ఎక్కడ ఉన్నాయి, సముద్రం సురక్షితమా, సరిహద్దు ఎంత దూరం, పట్టు ఎందుకు మారింది. వీటిలో ఒకటి అడగండి.",
    },
}

PLACE_NAMES_TA = {
    "kachchatheevu": "கச்சத்தீவு", "rameswaram": "இராமேஸ்வரம்", "mandapam": "மண்டபம்", "pamban": "பாம்பன்",
    "dhanushkodi": "தனுஷ்கோடி", "nagapattinam": "நாகப்பட்டினம்", "tuticorin": "தூத்துக்குடி",
    "kottaipattinam": "கோட்டைப்பட்டினம்", "jegathapattinam": "ஜெகதாப்பட்டினம்", "kodiyakarai": "கோடியக்கரை",
}


PLACE_NAMES_TE = {
    "kachchatheevu": "కచ్చతీవు", "rameswaram": "రామేశ్వరం", "mandapam": "మండపం", "pamban": "పాంబన్",
    "dhanushkodi": "ధనుష్కోడి", "nagapattinam": "నాగపట్టినం", "tuticorin": "తూత్తుకుడి",
    "kottaipattinam": "కోట్టైపట్టినం", "jegathapattinam": "జగదాపట్టినం", "kodiyakarai": "కోడియక్కరై",
}
PLACE_NAMES = {"ta": PLACE_NAMES_TA, "te": PLACE_NAMES_TE}
SECTOR_NAME = {"ta": "பாக் விரிகுடா வடக்கு (கோட்டைப்பட்டினம் – ஜெகதாப்பட்டினம்)",
               "te": "పాక్ బే ఉత్తరం (కోట్టైపట్టినం – జగదాపట్టినం)"}


def sector_name(lang, default):
    return SECTOR_NAME.get(lang, default)


def place_name(place, lang):
    if place is None:
        return T[lang]["your_position"]
    return PLACE_NAMES.get(lang, {}).get(place, place.title())


def t(lang, key, **kw):
    return T[lang][key].format(**kw)


def why(lang, c):
    return T[lang]["why_cloud" if c.get("gate") == "coverage" else
                   "why_fabricated" if c.get("gate") == "provenance" else "why_repro"]
