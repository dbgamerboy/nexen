;(function (root) {
  'use strict';

  const PROFILE_KEY = 'nexen.voice.profile';
  const DEFAULT_PROFILE_ID = 'classic-ironman';

  const PROFILE_DEFINITIONS = [
    {
      id: 'classic-ironman',
      label: 'Classic MARVIN Â· British voice',
      aliases: ['classic', 'classic ironman', 'ironman', 'british marvin', 'marvin classic'],
      localeHints: ['en-GB', 'en-gb', 'en-AU'],
      voiceHints: ['british', 'female', 'daniel', 'ryan', 'matilda', 'emma', 'zira', 'online', 'clara', 'harry', 'jane', 'lucy', 'male'],
      rate: 0.98,
      note: 'British-leaning English voices from your installed device.'
    },
    {
      id: 'british-marvin',
      label: 'MARVIN Â· British voice',
      aliases: ['british marvin', 'marvin british', 'marvin', 'uk marvin'],
      localeHints: ['en-GB', 'en-gb', 'en-AU'],
      voiceHints: ['british', 'english', 'daniel', 'ryan', 'oliver', 'lucy', 'james', 'matilda', 'mark'],
      rate: 0.98,
      note: 'British English preference, local only.'
    },
    {
      id: 'denzel-style',
      label: 'Denzel-style (deep local voice)',
      aliases: ['denzel', 'denzel style', 'denzel washington', 'denzel washington style'],
      localeHints: ['en-US', 'en-us'],
      voiceHints: ['male', 'deep', 'rich', 'david', 'mark', 'daniel', 'jeremy', 'ravi', 'james', 'brandon', 'matt'],
      rate: 0.96,
      note: 'No real clone; this maps to your nearest local deep male-style English voice.'
    },
    {
      id: 'samuel-l-jackson-style',
      label: 'Samuel L. Jackson-style (strong local voice)',
      aliases: ['samuel', 'samuel l jackson', 'samuel jackson', 'samuel l', 'jackson style'],
      localeHints: ['en-US', 'en-us'],
      voiceHints: ['male', 'bold', 'deep', 'mark', 'john', 'david', 'jeremy', 'matt', 'alex'],
      rate: 0.95,
      note: 'No real clone; this maps to your nearest local strong male English voice.'
    },
    {
      id: 'andrew-tate-style',
      label: 'Andrew Tate-style (assertive local voice)',
      aliases: ['andrew tate', 'andrew', 'tate', 'alpha style'],
      localeHints: ['en-US', 'en-us'],
      voiceHints: ['male', 'authoritative', 'mark', 'david', 'alex', 'rich', 'ravi', 'steve'],
      rate: 0.96,
      note: 'No real clone; this maps to your nearest local assertive male English voice.'
    },
    {
      id: 'alpha-male-strategies',
      label: 'Alpha Male strategies style (assertive local)',
      aliases: ['alpha male', 'alpha male strategies', 'alpha', 'strategies'],
      localeHints: ['en-US', 'en-gb', 'en-gb', 'en-CA'],
      voiceHints: ['male', 'deep', 'daniel', 'alex', 'john', 'rich', 'mark', 'ravi', 'david'],
      rate: 0.96,
      note: 'No real clone; this maps to your nearest local assertive male English voice.'
    }
  ];

  function normalize(value) {
    return String(value || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  const PROFILE_ALIAS_LOOKUP = Object.fromEntries(
    PROFILE_DEFINITIONS.flatMap(profile => profile.aliases.map(alias => [normalize(alias), profile.id]))
  );

  function getProfiles() {
    return PROFILE_DEFINITIONS.map(profile => ({
      id: profile.id,
      label: profile.label,
      aliases: [...profile.aliases],
      rate: profile.rate,
      note: profile.note,
    }));
  }

  function getProfile(profileId) {
    const normalized = normalize(profileId);
    if (!normalized) return getProfile(DEFAULT_PROFILE_ID);
    return PROFILE_DEFINITIONS.find(profile => profile.id === normalized || PROFILE_ALIAS_LOOKUP[normalized] === profile.id) || PROFILE_DEFINITIONS[0];
  }

  function matchProfile(value) {
    const text = normalize(value);
    if (!text) return DEFAULT_PROFILE_ID;
    if (PROFILE_ALIAS_LOOKUP[text]) return PROFILE_ALIAS_LOOKUP[text];
    const exact = PROFILE_DEFINITIONS.find(profile => profile.id === text || profile.aliases.some(alias => normalize(alias) === text));
    if (exact) return exact.id;
    for (const profile of PROFILE_DEFINITIONS) {
      if (profile.aliases.some(alias => text.includes(normalize(alias)))) return profile.id;
    }
    for (const profile of PROFILE_DEFINITIONS) {
      if (text.includes(profile.id.replace(/-/g, ' '))) return profile.id;
    }
    return DEFAULT_PROFILE_ID;
  }

  function readStoredProfile(host = root) {
    try {
      const stored = host.localStorage?.getItem(PROFILE_KEY);
      return normalize(stored);
    } catch { return null; }
  }

  function setStoredProfile(profileId, host = root) {
    const resolved = matchProfile(profileId);
    try {
      host.localStorage?.setItem(PROFILE_KEY, resolved);
    } catch {}
    if (typeof host.dispatchEvent === 'function') {
      try { host.dispatchEvent(new CustomEvent('nexen:voice-profile-changed', { detail: { profileId: resolved } })); } catch {}
    }
    return getProfile(resolved);
  }

  function currentProfile(host = root) {
    const candidate = readStoredProfile(host) || DEFAULT_PROFILE_ID;
    return getProfile(candidate);
  }

  function availableEnglishVoices(host = root) {
    const synth = host.speechSynthesis;
    if (!synth || typeof synth.getVoices !== 'function') return [];
    return synth.getVoices().filter(v => v && typeof v === 'object' && v.lang && /^en(?:-|$)/i.test(v.lang));
  }

  function scoreVoiceForProfile(voice, profile) {
    const name = normalize(voice.name);
    let score = 0;
    const lang = normalize(voice.lang);
    const profileLocales = (profile.localeHints || []).map(item => normalize(item));
    const hints = (profile.voiceHints || []).map(item => normalize(item));
    if (profileLocales.some(locale => lang === normalize(locale))) score += 16;
    if (/^en-?gb/.test(lang)) score += 8;
    if (/^en-?us/.test(lang)) score += 6;
    for (const hint of hints) {
      if (!hint) continue;
      if (name.includes(hint)) score += 2;
      if (normalize(voice.voiceURI).includes(hint)) score += 1;
    }
    if (voice.localService) score += 4;
    return score;
  }

  function pickVoice(profileId, host = root) {
    const voices = availableEnglishVoices(host);
    if (!voices.length) return null;
    const profile = getProfile(profileId);
    let best = null;
    let bestScore = Number.NEGATIVE_INFINITY;
    for (const voice of voices) {
      const value = scoreVoiceForProfile(voice, profile);
      if (value > bestScore) {
        bestScore = value;
        best = voice;
      }
    }
    return best || voices[0] || null;
  }

  function describeCurrentProfile(host = root) {
    const profile = currentProfile(host);
    const voice = pickVoice(profile.id, host);
    return {
      profile,
      voice,
      storageKey: PROFILE_KEY,
      options: getProfiles(),
    };
  }

  function profileLabel(profileId) {
    return getProfile(profileId).label;
  }

  function makeSpeechUtterance(text, profileId, host = root, extra = {}) {
    if (typeof SpeechSynthesisUtterance === 'undefined' || typeof host.speechSynthesis === 'undefined') return null;
    const profile = getProfile(profileId);
    const selected = pickVoice(profile.id, host);
    if (!selected) return null;
    const utterance = new SpeechSynthesisUtterance(String(text));
    utterance.voice = selected;
    utterance.lang = selected.lang || 'en-US';
    utterance.rate = typeof extra.rate === 'number' ? extra.rate : profile.rate;
    return utterance;
  }

  root.NexenVoiceProfiles = {
    PROFILE_KEY,
    getProfiles,
    matchProfile,
    getProfile,
    currentProfile,
    pickVoice,
    profileLabel,
    setCurrentProfile: setStoredProfile,
    describeCurrentProfile,
    makeSpeechUtterance,
    availableEnglishVoices,
  };
})(typeof window === 'undefined' ? (typeof self === 'undefined' ? {} : self) : window);

