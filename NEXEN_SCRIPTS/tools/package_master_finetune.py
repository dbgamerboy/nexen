import json
import os
import glob

output_file = r"H:\NEXEN\models\heavy\datasets\05_goldmine_master_v2.jsonl"
existing_file = r"H:\NEXEN\models\heavy\datasets\05_goldmine_training.jsonl"

pairs = []

# 1. Load existing pairs
if os.path.exists(existing_file):
    with open(existing_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    pairs.append(json.loads(line))
                except Exception:
                    pass
print(f"Loaded {len(pairs)} existing pairs from v1")

# 2. Package Biaheza Dropshipping Course Notes
bia_pairs = [
    (
        "What are Biaheza's 4 Moving Parts to get right with dropshipping?",
        "According to Biaheza's dropshipping guide, the 4 core pillars are:\n"
        "1. Product: Solves a problem or taps a passion, unique wow factor, not sold in local retail.\n"
        "2. Website: Clean, minimalist 1-product or niche Shopify store, high-res photos, video demos, reviews.\n"
        "3. Ad Copy: Pain-point driven, customer benefit focused, breaking text with visuals/GIFs.\n"
        "4. Marketing: TikTok organic & paid ads driving qualified attention.\n"
        "If any single pillar fails, the entire store fails to convert."
    ),
    (
        "Detail Biaheza's 9-factor checklist for validating a winning product.",
        "Biaheza's 9 Winning Product Factors:\n"
        "1. Solves a real problem (pain/insecurity) or taps high passion (pets/fitness).\n"
        "2. Difficult to find in retail stores (Walmart, Target).\n"
        "3. Immediate WOW factor stopping scrollers within 1.5 seconds.\n"
        "4. Broad household market appeal (not narrow micro-niches).\n"
        "5. Proven quality to minimize returns/chargebacks.\n"
        "6. Active competitor traction with ads running >3-4 weeks.\n"
        "7. Solid AliExpress order velocity (100-500+ verified orders).\n"
        "8. Healthy profit margins: buy <$10 sell $20-$25; buy $20 sell $50+.\n"
        "9. Practical everyday utility you or your network would actually buy."
    ),
    (
        "Explain Biaheza's ad discovery and competitor copying strategy.",
        "Biaheza's Competitor Ad Scraping Protocol:\n"
        "1. Search terms: 'amazon finds', 'tiktok made me buy it', 'amazon gadgets', 'shop now', 'free shipping'.\n"
        "2. Inspect top-selling SKUs using Shopify store dork: appending `/collections/all?sort_by=best-selling` to any Shopify URL.\n"
        "3. Verify longevity on Facebook Ad Library / TikTok Creative Center. If an ad has been running continuously for over 30 days, it is verifiably profitable.\n"
        "4. Replicate the winning visual structure, write tighter hook scripts, record higher-definition demos, and improve store UX."
    ),
    (
        "What is the difference between General, Niche, and Single-Product stores according to Biaheza?",
        "Store Strategy Hierarchy:\n"
        "1. General Stores: Broad inventory, lowest conversion rate, hard to establish trust against Amazon. Not recommended.\n"
        "2. Niche Stores: Cohesive brand catalog (Beauty, Fitness, Baby, Pets). Recommended testing ground to test 5-10 products rapidly with shared brand equity.\n"
        "3. Single-Product Stores: Highest conversion rate. Once a product proves profitability in the niche store, migrate it to a dedicated 1-product website with custom video/GIF demos, reviews, and high-margin upsells."
    )
]
for q, a in bia_pairs:
    pairs.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]})

# 3. Package AI Girl Method (Google Drive Asset)
ai_girl_pairs = [
    (
        "Summarize the 8 stages of the AI Girl Method for autonomous digital persona monetization.",
        "The 8 Stages of the AI Girl Method:\n"
        "Stage 1 - Opportunity Window: Loneliness and parasocial demand create high recurring cashflow; 80% net profit margins vs 40% in traditional agencies.\n"
        "Stage 2 - Business Model: AI persona built with consistent identity, short-form distribution (TikTok/IG Reels), funneling to subscription portals (Fanvue/OnlyFans).\n"
        "Stage 3 - Generation Pipeline: Photorealistic consistency using uncensored generation pipelines (Eromify/Alibaba cloud endpoints) to prevent policy bans.\n"
        "Stage 4 - Automation via Claude MCP: Utilizing Claude and browser automation (Manus) to orchestrate content planning, metadata generation, and scheduled publishing.\n"
        "Stage 5 - Motion Control: Leveraging video reference clips to transfer human viral dances/reactions directly to the AI persona via Image-to-Image first-frame alignment and motion models (Higgsfield/LivePortrait).\n"
        "Stage 6 - Account Warming: 3-7 day seasoning protocol (human-like scrolling, liking, commenting) before posting to achieve algorithmic trust and high initial distribution.\n"
        "Stage 7 - High-Converting Funnel: Link-in-bio bridge landing page leading to tiered subscriptions with automated DM nurture bots.\n"
        "Stage 8 - Monetization Streams: Monthly subscriptions ($1k-$15k/mo), locked Pay-Per-View drops ($2k-$20k/mo), custom requests, and conversational AI tipping."
    ),
    (
        "How does the Motion Transfer pipeline work for AI influencer creation?",
        "Motion Transfer Pipeline:\n"
        "Step 1: Identify trending viral movement/dance clip on TikTok or Instagram.\n"
        "Step 2: Extract frame 0 of the reference video.\n"
        "Step 3: Run Image-to-Image with the persona identity LoRA conditioned on frame 0 pose to generate an aligned persona keyframe.\n"
        "Step 4: Feed the keyframe and reference video into an AI motion model (Higgsfield / AnimateDiff / LivePortrait) to transfer natural motion onto the persona.\n"
        "Step 5: Apply facial reenactment and upscale to 1080x1920 60fps for distribution."
    )
]
for q, a in ai_girl_pairs:
    pairs.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]})

# 4. Package Social Media Strategy (Vicky Owens Podcast)
social_pairs = [
    (
        "What are the core principles of a scalable social media strategy for TikTok and Instagram?",
        "Social Media Growth Architecture:\n"
        "1. Content Pillars: Establish 3 distinct pillars (Authority/Education, Entertainment/Pattern-Interrupt, Conversion/Proof).\n"
        "2. Batch Production & Repurposing: Produce core assets in batches, slicing one high-signal demonstration into 5 distinct hook variations.\n"
        "3. Algorithmic Warming & Consistency: Post on a strict deterministic schedule without erratic volume spikes to train platform recommendation graphs.\n"
        "4. Brand Identity Alignment: Maintain visual consistency (color palette, typography, visual hook cadence) across all short-form touchpoints."
    )
]
for q, a in social_pairs:
    pairs.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]})

# 5. Package Reddit Scraper Pipelines (r/dropship, r/ecommerce, r/tiktokshop, r/UGCcreators)
reddit_pairs = [
    (
        "How should automated market scrapers monitor Reddit communities (r/dropship, r/tiktokshop, r/UGCcreators) for winning trends?",
        "Automated Community Sentiment & Trend Scraper Protocol:\n"
        "1. Target Subreddits: r/dropship, r/ecommerce, r/tiktokshop, r/UGCcreators, r/digitalmarketing.\n"
        "2. Extraction Rules: Pull top weekly posts with upvote ratio > 85% and comment count > 20.\n"
        "3. Keyword Filtering: Scan for terms like 'winning product', 'supplier issue', 'TikTok shop violation', 'hook fatigue', 'scaling past 10k'.\n"
        "4. Synthesis: Cluster trending pain points into product sourcing opportunities and script angles for UGC creative production."
    )
]
for q, a in reddit_pairs:
    pairs.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]})

# 6. Package Agenthusiast Blueprints & Education Files
edu_files = glob.glob(r"F:\05_AI\02_EDUCATION\**\*.md", recursive=True)
print(f"Found {len(edu_files)} markdown files in education")
for ef in edu_files:
    try:
        with open(ef, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if len(content.strip()) > 100:
            basename = os.path.basename(ef)
            pairs.append({
                "messages": [
                    {"role": "user", "content": f"Explain the architectural guidelines and best practices from {basename}."},
                    {"role": "assistant", "content": content[:3000]}
                ]
            })
    except Exception:
        pass

# 7. Package Neuroscience & Neuromarketing Principles
neuro_pairs = [
    (
        "How do neuroscience and neuromarketing principles drive TikTok hook retention curves?",
        "Neuromarketing Retention Framework:\n"
        "1. 1.5-Second Visual Pattern Interrupt: The reticular activating system (RAS) filters out predictable stimuli. High-velocity visual movement, unexpected sound effects, or abrupt text shifts reset dopamine expectations and halt the scroll.\n"
        "2. Dopamine Anticipation Loops: Construct open loops in seconds 0-3 (e.g., 'Never use this on your skin until you see this'). The brain seeks narrative closure, compelling the viewer to complete the video.\n"
        "3. Cognitive Friction Minimization: Product value propositions must be understood at an instinctive, sub-cortical level. Use visual demos and GIFs rather than complex explanatory text.\n"
        "4. Loss Aversion & Social Proof: Framing messages around avoiding a common pain point triggers stronger amygdala response than simple feature promotion."
    )
]
for q, a in neuro_pairs:
    pairs.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]})

# 8. Write master v2 dataset
with open(output_file, "w", encoding="utf-8") as f:
    for p in pairs:
        f.write(json.dumps(p) + "\n")

print(f"Successfully wrote {len(pairs)} fine-tuning pairs to {output_file}")
sz_mb = os.path.getsize(output_file) / (1024 * 1024)
print(f"Dataset size: {sz_mb:.2f} MB")
