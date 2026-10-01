# SAGARAKSHAK — MVP demo

A working agentic marine-advisory system for SIH PS 26176. A fisher asks a question in
English or Tamil; an orchestrator splits it across specialist agents that run in parallel;
a verifier re-reads the source data and recomputes every number before anything is said;
the answer comes back in the fisher's language with its evidence. Offline, the phone keeps
warning from a signed safety packet. Catch reports flow back and score the advisory.

## Run

```
cd mvp
python server.py            # Python 3.10+, standard library only — no pip install
```
Open http://localhost:8000. Signature checks in the browser need a recent Chrome, Edge,
Firefox or Safari (WebCrypto Ed25519).

### Mixed languages

Each message is answered in its own language, so one chat can switch freely. Within a
message, the language is decided in this order:
1. **Script:** any Telugu or Tamil letters → that language, even with English words
   mixed in ("రేపు weather ఎలా ఉంది?").
2. **Romanised words:** Telugu or Tamil typed in English letters ("border enta
   duram?" → Telugu; "border evlo dooram?" → Tamil).
3. **One- or two-word questions** ("border?") → the language selected in the top bar.
4. **Otherwise** → English.

Topic keywords include romanised Telugu/Tamil and the way speech recognition spells
English words in Indic script (బోర్డర్, பார்டர் = border). The Agents tab shows the
detected language and the reason. Word lists are in `sagarakshak/lang.py` (`KEYWORDS`,
`ROMAN`, `MARKERS`).

### Voice (speak in, hear back)

- **Speaking in:** tap the mic (or press **M**) and speak. The mic listens in the
  language picked in the top bar (English, தமிழ் or తెలుగు). You'll see a live transcript, then
  the question is sent and the answer is read aloud. Requires Chrome or Edge, microphone
  permission for the page, and internet: both browsers send the audio to their online
  speech service. A real phone at sea would need on-device speech recognition.
- **Hearing Tamil and Telugu answers:** the app looks for a voice in this order:
  1. A voice for that language in the browser. Edge has built-in "Natural" Tamil and
     Telugu voices (online).
  2. A voice for that language installed in Windows, used either by the browser or through
     `POST /api/tts`, which synthesises with Windows' own speech engine.

  The label next to "Try asking" shows which voice is in use for the selected language.
- **Telugu:** Windows has no Telugu text-to-speech voice to install, so spoken Telugu
  answers need Microsoft Edge. In Chrome, Telugu answers are shown but not spoken.
- **Installing the Windows Tamil voice:** Settings → Time & language → Speech → Manage
  voices → Add voices → Tamil. Or, from an admin PowerShell:
  `Add-WindowsCapability -Online -Name "Language.TextToSpeech~~~ta-IN~0.0.1.0"`.
  Restart the browser afterwards so it picks up the new voice.

Tests: `python -m unittest discover -s tests -v`. The 17 tests include the RFC 8032
Ed25519 vectors, an RK4 exactness check, and each verifier gate.

## Five-minute demo script

1. **The PS's first question.** Tap *"Is it safe to go out tomorrow morning, and where will
   the fish be?"* One question fans out to three agents at once. You get a sea-state verdict
   (plus the afternoon thunderstorm warning), the border risk as a **drift cone** rather than
   fake precision, and three fishing zones. A stronger zone across the IMBL is named and
   *not* advised.
2. **Show the evidence.** Open the **Evidence** tab. Every number lists the exact grid cells
   it came from and what the verifier recomputed. **Agents** shows the parallel DAG with timings.
3. **The doctor, not the thermometer.** *"Why has fishing gotten worse here?"* The system ranks
   causes (weak upwelling → less plankton → fewer fish) with z-scores and correlations,
   and states that ranking evidence is not proof of cause.
4. **It refuses to guess.** *Chlorophyll at Kachchatheevu*: that spot is under cloud, so the
   value is withheld. *Fish next month*: no dataset supports it, so the system refuses.
5. **Catch a lying agent.** Turn on **Inject agent fault**, then ask for the nearest fishing
   zone. The agent cites a chlorophyll value the satellite never recorded. The verifier
   blocks that zone at the provenance gate, and it turns violet on the map.
6. **Tamil.** Switch the language to தமிழ் and tap the first preset. The same pipeline
   answers in Tamil.
7. **Lose signal.** Turn **Signal** off and ask anything. The phone answers from its signed
   packet. **Simulate engine failure** makes the boat drift on-device, with a caution alert
   at 5 km and a critical alert at 2 km (audio, vibration, voice). **Tamper with packet**
   moves the border; the signature check fails and the phone rejects the packet.
8. **The reply envelope.** Open **Loop** and send a catch report. It is scored against
   today's advisory (in-zone or not). Its water temperature becomes a satellite-SST
   validation point. The lift and RMSE figures are what you'd show NRSC.

## What is real and what is sample data

| Part | Status |
|---|---|
| Orchestrator, parallel agents, verifier gates, composer | Real, working code |
| RK4 drift ensemble (40 members, perturbed current, wind leeway) | Real, working code |
| PFZ scoring (SST-front gradient + chlorophyll) | Real method, sample inputs |
| Diagnosis (anomaly z-scores × correlation, physical-sign check) | Real method, sample inputs |
| IMBL coordinates | From the 1974/76 agreements, rounded; **verify before operational use** |
| Ed25519 signing (pure Python) and browser verification (WebCrypto) | Real |
| Ocean and weather fields, the 52-week series, seed catch reports | **Sample data**, generated deterministically per day and labelled as sample throughout the UI |
| English/Tamil | Hand-written templates + rule-based intent parsing |
| Speech | Browser Web Speech API. Tamil text-to-speech works only if the device has a Tamil voice installed |

## Where the production pieces plug in

- **Data:** `sagarakshak/data.py`. Replace `_build` with NetCDF loaders for MOSDAC SST and
  OCM-3 chlorophyll, INCOIS HOOFS currents and waves, and IMD winds and nowcasts, on the
  same grid. Each field already records which product it stands in for.
- **Language:** `sagarakshak/lang.py`. Put IndicASR and IndicTrans2 at the edges. Agents only
  ever see the structured intent.
- **Planner:** `lang.understand` is rule-based. An LLM planner can replace it, but claims
  still go through the same verifier, so the gate doesn't depend on trusting the LLM.
- **Delivery:** `sagarakshak/packet.py` is about 7 KB of JSON. A GEMINI broadcast would need
  a binary encoding and a smaller grid.

## Layout

```
server.py                 HTTP API + static files (stdlib)
sagarakshak/
  data.py                 gridded fields + series, provenance on every value
  agents.py               fish / weather / border / ocean / diagnosis agents
  models.py               PFZ score, RK4 ensemble, statistics (shared by agents and verifier)
  verifier.py             provenance -> coverage -> reproduction gates
  orchestrator.py         understand -> plan -> parallel agents -> verify -> compose
  lang.py                 intent + time parsing, English/Tamil templates
  packet.py, ed25519.py   signed offline packet
  tts.py                  speech through the host's Windows voices (fallback for Tamil)
  feedback.py             catch reports, PFZ lift, SST bias/RMSE
static/                   Leaflet web client
data/                     created on first run: signing key, catch reports
tests/test_core.py
```
