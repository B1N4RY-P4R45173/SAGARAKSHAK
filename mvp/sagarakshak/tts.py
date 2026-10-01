"""Text-to-speech through the host's Windows voices (WinRT / OneCore).

Browsers only expose some system voices (Chrome on Windows sees the legacy SAPI
"Desktop" voices only), so a Tamil voice installed in Windows is invisible to it.
This module synthesises speech with Windows.Media.SpeechSynthesis via PowerShell and
returns WAV bytes the page can play. In the field this role is played by the phone's
own on-device TTS; here the demo laptop stands in for the phone.
"""
import hashlib
import os
import subprocess
import sys
import tempfile

_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$lang = $args[0]; $inFile = $args[1]; $outFile = $args[2]
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($inFile -eq 'LIST') { $all | ForEach-Object { $_.Language + '|' + $_.DisplayName }; exit 0 }
$voice = $all | Where-Object { $_.Language -eq $lang } | Select-Object -First 1
if (-not $voice) { $voice = $all | Where-Object { $_.Language -like ($lang.Split('-')[0] + '*') } | Select-Object -First 1 }
if (-not $voice) { [Console]::Error.WriteLine('NOVOICE'); exit 3 }
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$synth.Voice = $voice
$synth.Options.SpeakingRate = 0.95
$text = [IO.File]::ReadAllText($inFile, [Text.Encoding]::UTF8)
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($synth.SynthesizeTextToStreamAsync($text)))
$null = $task.Wait(-1)
$src = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($task.Result)
$dst = [IO.File]::Create($outFile); $src.CopyTo($dst); $dst.Close()
"""

LOCALE = {"ta": "ta-IN", "te": "te-IN", "en": "en-IN"}
_cache = {}


class NoVoice(Exception):
    pass


def available():
    return sys.platform == "win32"


def _run(args, timeout=60):
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
        f.write(_PS)
        script = f.name
    try:
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *args],
                              capture_output=True, timeout=timeout)
    finally:
        os.unlink(script)


def voices():
    """[(locale, name)] of Windows voices this host can speak with."""
    if not available():
        return []
    r = _run(["xx", "LIST", "none"], timeout=30)
    out = r.stdout.decode("utf-8", "replace").splitlines()
    return [tuple(line.split("|", 1)) for line in out if "|" in line]


def synth(text, lang):
    """WAV bytes for text, spoken by a Windows voice for lang ('ta' / 'te' / 'en')."""
    if not available():
        raise NoVoice("server TTS needs Windows")
    locale = LOCALE.get(lang, "en-IN")
    key = hashlib.sha1(f"{locale}|{text}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    fd_in, path_in = tempfile.mkstemp(suffix=".txt")
    fd_out, path_out = tempfile.mkstemp(suffix=".wav")
    os.close(fd_out)
    try:
        with os.fdopen(fd_in, "w", encoding="utf-8") as f:
            f.write(text)
        r = _run([locale, path_in, path_out])
        if r.returncode == 3:
            raise NoVoice(f"no Windows voice installed for {locale}")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace")[-400:])
        with open(path_out, "rb") as f:
            wav = f.read()
    finally:
        for p in (path_in, path_out):
            try:
                os.unlink(p)
            except OSError:
                pass
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = wav
    return wav
