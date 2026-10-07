"""
Expanded Master Fine-Tuning & Knowledge Packager for NEXEN V3
Aggregates:
1. 05_goldmine_master_v2.jsonl (9,712 existing pairs)
2. Live Obsidian Vault (F:\\NEXEN_MEMORY) Studies:
   - Study - ai-girls-money.md (19 studies)
   - Study - biaheza-course.md (48 studies)
   - Study - clipping.md (16 studies)
   - Study - ai-models.md
   - AI-MODELS-PLAYBOOK.md
   - DROPSHIPPING-RESEARCH-EXECUTION-PLAYBOOK-2026-09-30.md
3. AI Girl Method (14 pages extracted)
4. Master 100 Prompts (H:\\NEXEN\\knowledge\\master_100_prompts.json)
5. Deep Modules on:
   - Viral TikTok Girls (What they did, what they talked about)
   - How to Clip Videos & Popular Clipping Software features (OpusClip, Submagic, CapCut) + Whop Clipper integration
   - AI Dropshipping Ads & Competitor Reverse Engineering
   - Platform Anomaly Detection, Bot Evasion & Anti-Ban Protocols
   - Viral YouTube Faceless Patterns (Tags, Titles, Thumbnails, High-RPM Niches)
"""

import json
import os
import re

OUTPUT_FILE = r"H:\NEXEN\models\heavy\datasets\05_goldmine_master_v3_supercharged.jsonl"
V2_FILE = r"H:\NEXEN\models\heavy\datasets\05_goldmine_master_v2.jsonl"
VAULT_BASE = r"F:\NEXEN_MEMORY"

pairs = []

# 1. Load V2 Pairs
if os.path.exists(V2_FILE):
    with open(V2_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    pairs.append(json.loads(line))
                except Exception:
                    pass
print(f"Loaded {len(pairs)} existing pairs from V2.")

def add_pair(instruction, output):
    pairs.append({
        "messages": [
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": output}
        ]
    })

# 2. Ingest Obsidian Studies
studies = [
    (r"10-Segments\01-money-n8n\study\Study - ai-girls-money.md", "AI Girls & Persona Monetization"),
    (r"10-Segments\01-money-n8n\study\Study - biaheza-course.md", "Biaheza Dropshipping Course"),
    (r"10-Segments\01-money-n8n\study\Study - clipping.md", "Whop & Viral Video Clipping"),
    (r"10-Segments\01-money-n8n\study\Study - ai-models.md", "AI Model Workflows & Renders")
]

for rel_path, topic_name in studies:
    full_path = os.path.join(VAULT_BASE, rel_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
            text = fp.read()
        
        # Split by ## headers
        sections = re.split(r"\n##\s+", text)
        for sec in sections[1:]:
            lines = sec.strip().split("\n")
            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if len(body) > 100:
                prompt = f"Explain the core strategy and breakdown of '{title}' from the {topic_name} study."
                add_pair(prompt, body)
        print(f"Ingested study: {topic_name}")

# 3. Deep Domain Module: Viral TikTok Girls (What did they do? What did they talk about?)
tiktok_girls_data = [
    (
        "What do viral girls on TikTok actually do visually to stop the scroll in under 1 second?",
        "Visual Hook Mechanics of Viral TikTok Girls:\n"
        "1. Immediate Eye-Contact & Proxemics: Starting 6-12 inches from the lens with direct gaze, leaning back or stepping into frame within 0.8 seconds. This creates instant intimacy.\n"
        "2. Micro-Movement Pattern Interrupts: Doing routine physical actions (adjusting a camera angle, tucking hair behind ear, swatching lip gloss, holding a coffee cup, unboxing) right at frame 0.\n"
        "3. Aesthetic Lighting & Depth: Soft diffused natural window light or high-CRI ring light with warm backlight and bokeh/shallow depth of field, making skin look radiant without looking like a synthetic filter.\n"
        "4. Dynamic Camera Shake / Handheld Realism: Avoiding sterile tripod shots; slight organic handheld motion triggers the brain's peer-to-peer authenticity radar.\n"
        "5. Visual Staging: Clean aesthetic bedroom, minimalist gym, luxury car interior, or modern kitchen vanity that signals lifestyle aspirational status."
    ),
    (
        "What do viral TikTok creators and AI personas actually talk about to keep 70%+ retention?",
        "Content & Scripting Formulas of Viral TikTok Creators:\n"
        "1. 'Storytime with Open Loop': 'I wasn't going to talk about this, but...' or 'The most unhinged thing happened today...' The core revelation is withheld until seconds 25-30.\n"
        "2. Polarizing Relatable Takes: 'Unpopular opinion, but guys who do X...' or 'Why does nobody talk about this unspoken rule?' Drives hundreds of comments debating the premise.\n"
        "3. 'Get Ready With Me' (GRWM) Confessionals: Narrating an emotionally charged or entertaining life anecdote while applying skincare/makeup. The dual stimuli (visual action + auditory story) spikes average watch time.\n"
        "4. The Insecurity/Pain Callout: 'If your jeans gap at the waist, stop scrolling' or 'How I fixed my texture in 3 days.' Pinpoints an acute problem immediately.\n"
        "5. Parasocial Intimacy Ladder: Sharing vulnerable thoughts, asking the audience for advice in the comments ('Should I wear outfit 1 or 2?'), creating genuine follower bonding."
    ),
    (
        "How is the AI Girl Fanvue/Unlockt/Subscription monetization funnel structured?",
        "AI Girl Subscription Funnel Architecture:\n"
        "Stage 1 - Top of Funnel (Free Traffic): TikTok, Instagram Reels, and YouTube Shorts posting 1-2 lifestyle/relatable clips daily. Strict SFW compliance with synthetic media tags.\n"
        "Stage 2 - Bridge Link-in-Bio: A clean mobile landing page (Beacons/Linktree/Custom Tailwind) highlighting lifestyle photos and a single clear VIP Community CTA.\n"
        "Stage 3 - Front-End Subscription: Fanvue or Unlockt portal ($9.99-$19.99/mo) providing access to exclusive daily high-res photosets, vlog voice notes, and direct messaging.\n"
        "Stage 4 - Automated DM Monetization: Automated chatbot persona programmed with memory, mirroring the fan's tone, leading to Pay-Per-View (PPV) unlocked drops ($25-$150 each).\n"
        "Stage 5 - High-Ticket Custom Requests: Exclusive custom voice greetings, personalized digital photo cards, and tipping rewards."
    )
]
for q, a in tiktok_girls_data:
    add_pair(q, a)

# 4. Deep Domain Module: How to Clip Videos & Popular Clipping Software Features
clipping_data = [
    (
        "What is the exact formula for 'How to clip videos' for maximum virality and high retention?",
        "The Definitive Viral Video Clipping Protocol:\n"
        "1. The 1.5-Second Hook Window: The first 45 frames must feature a high-voltage statement, shocking reaction, or provocative question. Never start with greetings or filler words.\n"
        "2. Optimal Clip Duration: 18 to 35 seconds. Clips under 15s don't build sufficient narrative depth; clips over 45s suffer dramatic retention drop-off on TikTok/Shorts.\n"
        "3. 9:16 Aspect Ratio Re-Framing: Auto-crop source horizontal 16:9 footage with face-tracking centered on the active speaker. For two-person podcasts, use a dynamic split-screen (top/bottom) stacked vertical layout.\n"
        "4. Dynamic Bouncing Captions: 1 to 3 words rendered per frame in large bold font (TheBoldFont, Montserrat, Komika Axis) with high-contrast yellow/green highlight on the spoken word, accompanied by animated pop-in emojis.\n"
        "5. Sound Design: Subtle 'whoosh' on scene transitions, gentle 'pop' on graphic overlays, and low-volume trending ambient background music (ducked -18dB under speech).\n"
        "6. Narrative Closure / Cliffhanger: End on a punchline, surprising conclusion, or an open loop that prompts viewers to rewatch or comment."
    ),
    (
        "What are the core features of popular clipping software like OpusClip, Submagic, and CapCut, and how do we code them?",
        "Popular Clipping Software Architecture & Features:\n"
        "1. AI Virality Scoring: Analyzes speech transcripts using NLP sentiment/hook models to identify segments with high emotional volatility, curiosity gaps, and memorable quotes.\n"
        "2. Active Speaker Auto-Reframing: Uses computer vision face detection (YOLO/MediaPipe) to track coordinates of the speaking subject and dynamically adjust the 9:16 crop box.\n"
        "3. Whisper-Powered Timed Transcription: Generates word-level timestamps (faster-whisper) to synchronize word-by-word highlighted subtitles.\n"
        "4. Auto B-Roll & Visual Inserts: Automatically queries stock footage/GIF APIs (Pexels, Giphy) based on transcript keywords to cut away every 2.5-3 seconds.\n"
        "5. Whop Content Rewards Integration: Automated submission pipeline that extracts video metadata, verifies view thresholds, and submits directly to Whop creator campaigns.\n"
        "Implementation in NEXEN: Built on `H:\\NEXEN\\clipping\\baseline_clipper.py` and `H:\\NEXEN\\tickets\\ticket_engine.py` using native FFmpeg, faster-whisper, and automated SRT generation."
    )
]
for q, a in clipping_data:
    add_pair(q, a)

# 5. Deep Domain Module: AI Dropshipping Ads & Competitor Reverse Engineering
dropship_data = [
    (
        "How do you reverse engineer competitor winning dropshipping ads using the Biaheza method?",
        "Competitor Ad Reverse-Engineering Workflow:\n"
        "1. Facebook Ad Library / TikTok Creative Center Mining: Filter by 'Active Ads', category 'All Ads', search terms: '50% off', 'free shipping', 'tiktok made me buy it', 'get yours now'.\n"
        "2. The 30-Day Longevity Filter: If an advertiser has kept an ad active for over 30 days, they are actively spending money on it and it is guaranteed profitable. Ignore ads running <7 days.\n"
        "3. Shopify Best-Seller Dork: Visit competitor store URL and append `/collections/all?sort_by=best-selling` to identify their top revenue-generating SKU.\n"
        "4. Hook & Script Deconstruction: Transcribe the competitor's first 3 seconds, the problem demonstration (sec 3-10), the solution feature (sec 10-20), and the call-to-action.\n"
        "5. Angle Differentiation: Replicate the successful structural skeleton, but film higher-resolution original footage, test 3 new hook angles, and price $2-$5 below or offer a 2-for-1 bundle."
    ),
    (
        "How do you script and produce a high-converting AI Dropshipping Video Ad?",
        "High-Converting AI Dropshipping Video Ad Structure (30 Seconds):\n"
        "Seconds 0-3 (The Pain Hook): 'Stop ruining your [Item/Body Part] with [Common Bad Product].'\n"
        "Seconds 3-8 (Agitation): Show visual frustration with the old way (poor fit, wasted money, painful routine).\n"
        "Seconds 8-15 (The AI Reveal): 'That's why over 20,000 people switched to [Product Name].' Hero shot of the product in action solving the problem.\n"
        "Seconds 15-22 (Feature Stack): 3 rapid-fire benefits: 'Zero waist gap, 4-way stretch denim, all-day comfort.' Use onscreen text badges.\n"
        "Seconds 22-26 (Social Proof): 'Over 4.8 stars from 1,200 verified reviews.' Show 5-star customer snippet.\n"
        "Seconds 26-30 (Urgency CTA): 'Get 50% off today only with free shipping. Click the link below before stock sells out.'"
    )
]
for q, a in dropship_data:
    add_pair(q, a)

# 6. Deep Domain Module: Anomaly Detection Model, Bot/AI Ban Reasons, & Detection Evasion
antiban_data = [
    (
        "Why do AI influencer accounts, bots, and automated posting tools get banned on TikTok, Instagram, and YouTube?",
        "Primary Root Causes of Platform Bans & Shadowbans:\n"
        "1. Identical Media Hashes (MD5/SHA256): Rendering and uploading the exact same video file across multiple accounts without re-encoding causes instant automated spam deduplication.\n"
        "2. Datacenter IP Leaks: Creating or managing accounts through obvious cloud hosting IPs (AWS, DigitalOcean, Hetzner, Vultr) rather than residential/4G mobile IPs.\n"
        "3. Unseasoned Fresh Account Posting: Uploading 5 videos immediately on a brand-new account created 10 minutes prior triggers automated bot detection.\n"
        "4. Bot-Like Deterministic Intervals: Posting at exact intervals (e.g., precisely every 60.000 minutes) without human jitter/variance.\n"
        "5. Missing Synthetic Media Disclosures: Failing to check the platform 'AI-generated content' toggle. Platforms use watermark classifiers (SynthID/C2PA); hidden AI media is penalized.\n"
        "6. High-Frequency Direct Messaging: Sending automated uninvited DMs with outbound URLs triggers aggressive spam tripwires.\n"
        "7. Device Fingerprint Clustering: Running multiple accounts inside a single browser instance with shared Canvas/WebGL/WebRTC fingerprints."
    ),
    (
        "How does NEXEN's Anomaly Detection & Evasion Model protect accounts and ensure 100% longevity?",
        "NEXEN Anti-Ban & Longevity Protocol:\n"
        "1. Video Hash Diversification (FFmpeg Micro-Jitter): Every rendered clip undergoes slight micro-adjustments: ±1% frame rate pitch, imperceptible crop (0.5%), randomized noise injection (`noise=alls=1:allf=t`), and full metadata stripping (`-map_metadata -1`).\n"
        "2. 3 to 7-Day Progressive Account Warming: Prior to posting, automated sessions execute authentic user actions: 20-30 minutes of niche video viewing, randomized scroll pauses, genuine likes, and follows of verified creators.\n"
        "3. Strict Volume Caps: Maximum 2 to 3 posts per day per account, separated by randomized dwell windows of 3 to 6 hours.\n"
        "4. Residential/Mobile Proxy Rotation: Ensuring each persona operates on a dedicated static residential IP with persistent browser cookies.\n"
        "5. Native Platform Disclosure: Automatically activating the native 'AI-generated content' switch on all platforms to remain in 100% regulatory and terms-of-service compliance.\n"
        "6. Human Approval Gates: Retaining an owner approval gate before any direct outreach or public posting goes live."
    )
]
for q, a in antiban_data:
    add_pair(q, a)

# 7. Deep Domain Module: Viral YouTube Faceless Patterns (Tags, Titles, Thumbnails, High-RPM)
youtube_data = [
    (
        "What patterns, titles, thumbnails, and tags drive 1M+ views in faceless YouTube channels?",
        "Viral YouTube Faceless Anatomy:\n"
        "1. Title Formulas (High CTR):\n"
        "   - The Disparity Hook: 'How a $0 Tool Outsmarted a $10 Billion Hedge Fund'\n"
        "   - The Warning/Urgency Hook: 'Why 99% of Dropshippers Will Go Broke in 2026'\n"
        "   - The Timeline Blueprint: 'How I Built a Faceless $10k/mo Channel in 48 Hours'\n"
        "2. Thumbnail Psychology (The 3-Element Rule):\n"
        "   - High Contrast Colors: Yellow/Green on Dark Navy or Deep Red.\n"
        "   - Maximum 3 Visual Elements: 1 emotional face or hero graphic, 1 contrasting comparison item, and 2-3 massive words max.\n"
        "   - Never Repeat Title Text in Thumbnail: Thumbnail generates the curiosity; title explains the promise.\n"
        "3. High-RPM Niches ($15-$40+ RPM):\n"
        "   - Personal Finance & Investing ($20-$45 RPM)\n"
        "   - Software & AI Automation ($18-$35 RPM)\n"
        "   - Real Estate & Business Case Studies ($15-$30 RPM)\n"
        "   - Luxury Lifestyle & Automotive ($12-$25 RPM)\n"
        "4. Retention Pacing (The 5-Second Reset):\n"
        "   - Introduce a visual change (b-roll, zoom, text pop, sound effect) every 3.5 to 5.0 seconds.\n"
        "   - Reset narrative tension every 2 minutes with a new revelation or mini-climax."
    )
]
for q, a in youtube_data:
    add_pair(q, a)

# 8. Ingest Master 100 Prompts
prompts_file = r"H:\NEXEN\knowledge\master_100_prompts.json"
if os.path.exists(prompts_file):
    with open(prompts_file, "r", encoding="utf-8") as fp:
        prompt_data = json.load(fp)
    for cat_key, prompt_list in prompt_data.get('categories', {}).items():
        for p in prompt_list:
            q = f"Provide the exact production-ready prompt and configuration for '{p.get('title')}' in category '{cat_key}'."
            a = f"ID: {p.get('id')}\nTitle: {p.get('title')}\nPersona/Target: {p.get('persona')}\nCategory: {cat_key}\n\nProduction Prompt:\n{p.get('prompt')}"
            add_pair(q, a)
    print(f"Ingested 100 Master Prompts from {prompts_file}")

# 9. Ingest 20-Arsenal Cards (New Open Source Capabilities & Repos)
arsenal_cards_dir = os.path.join(VAULT_BASE, r"20-Arsenal\cards")
if os.path.exists(arsenal_cards_dir):
    for f in os.listdir(arsenal_cards_dir):
        if f.endswith(".md"):
            p = os.path.join(arsenal_cards_dir, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                card_text = fp.read()
            q = f"What is the capability, architecture, and deployment instructions for Arsenal Tool '{f}'?"
            add_pair(q, card_text)
    print(f"Ingested Arsenal tool cards from {arsenal_cards_dir}")

# 10. Deep Module: Retention Heatmaps & Modern Caption Adding Software
retention_caption_data = [
    (
        "Explain the science of TikTok & YouTube Retention Heatmaps and how to hack 80%+ completion rate.",
        "Retention Heatmap Engineering:\n"
        "1. The 3-Second Drop Cliff: The steepest cliff in any short-form heatmap occurs between 0.0s and 3.0s (often losing 40-60% of cold viewers). Prevent this with an immediate visual movement, text hook with contrasting background, and no intro dead space.\n"
        "2. The Re-Engagement Valleys (Every 7 Seconds): Attention naturally decays every 5-7 seconds. Introduce a secondary stimulus (sound effect, punch zoom, b-roll overlay, or tone shift) precisely at 7s, 14s, 21s, and 28s to flatten the retention decay curve.\n"
        "3. Loop Optimization Spike: The final 1.5 seconds should visually and aurally bridge seamlessly back into the first frame (seamless audio loop or repeating sentence start). When viewers watch through 105-115%, the recommendation algorithm triggers viral exponential distribution.\n"
        "4. Heatmap Anomaly Detection: Spikes in the heatmap indicate re-watched moments (fast-moving text, shocking visuals, Easter eggs). Intentionally placing a 0.5s visual Easter egg forces viewers to replay."
    ),
    (
        "How do modern caption adding programs (Submagic, OpusClip, CapCut, AutoCut) format captions, and how is it implemented in NEXEN?",
        "State-of-the-Art Subtitle & Caption Architecture:\n"
        "1. Word-Level Timestamping: Leveraging faster-whisper with `word_timestamps=True` to extract millisecond-accurate start/end boundaries for every word.\n"
        "2. 1-to-3 Word Visual Chunks: Rendering max 2-3 words simultaneously on screen. Eye-tracking studies show paragraph blocks cause cognitive fatigue, while rapid word pops sustain high dopamine focus.\n"
        "3. Visual Hierarchy & Color Psychology:\n"
        "   - Primary Text: Heavy White (#FFFFFF) with 4px Black Outline (#000000) and subtle drop shadow.\n"
        "   - Spoken Word Highlight: Electric Yellow (#FFEE00) or Vibrant Neon Green (#00FF66) scaled 110% on the exact spoken millisecond.\n"
        "   - Auto-Emoji Triggers: Pairing sentiment/keywords ('money' -> 💰, 'fire' -> 🔥, 'stop' -> 🛑, 'shock' -> 😱) popping in synchronized with speech.\n"
        "4. Implementation in NEXEN Clipper: Powered by `H:\\NEXEN\\clipping\\smart_viral_clipper.py` with custom ASS/SRT formatting, center-safe zone positioning (y=1400px in 1080x1920 to avoid TikTok/Reels UI buttons)."
    )
]
for q, a in retention_caption_data:
    add_pair(q, a)

# Write to Output File
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    for item in pairs:
        out.write(json.dumps(item) + "\n")

print(f"\n=======================================================")
print(f"MASTER DATASET SUPERCHARGED GENERATION COMPLETE!")
print(f"Output File: {OUTPUT_FILE}")
print(f"Total Instruction Pairs: {len(pairs)}")
print(f"File Size: {os.path.getsize(OUTPUT_FILE) / (1024*1024):.2f} MB")
print(f"=======================================================\n")
