import json
import os
import re

html_path = r"H:\NEXEN\ui\mission_control.html"
with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update Header stats
content = content.replace(
    'DATASET: <strong class="text-pink-400">9,712 pairs (15.33 MB)</strong>',
    'DATASET: <strong class="text-pink-400">10,194 pairs (16.16 MB)</strong> <span class="text-slate-500">|</span> VAULT: <strong class="text-emerald-400">57,950 notes (CONNECTED)</strong>'
)

# 2. Load Workflows JSON
with open(r"H:\NEXEN\knowledge\master_workflows_registry.json", "r", encoding="utf-8") as f:
    wf_data = json.load(f)
workflows_json_str = json.dumps(wf_data["workflows"], indent=8)

# 3. Add Workflows, Focus, Clipper HTML before UGC tab
new_tabs_html = """
    <!-- ========================================== -->
    <!-- TAB: 🎬 WORKFLOWS & VIDEO SOURCES -->
    <!-- ========================================== -->
    <div x-show="currentTab === 'workflows'" class="space-y-6">
      <div class="bg-slate-900 p-6 rounded-2xl border border-slate-800 flex justify-between items-center">
        <div>
          <h2 class="text-xl font-black text-white flex items-center space-x-2">
            <span>🎬</span>
            <span>Master Workflows, Video Sources & Production Prompts</span>
          </h2>
          <p class="text-slate-400 text-sm mt-1">
            Every revenue workflow linked directly to the video/course it came from. Click video links to relearn, copy prompts to generate, or execute directly.
          </p>
        </div>
        <span class="text-xs font-mono bg-pink-500/20 text-pink-400 px-3 py-1.5 rounded-xl border border-pink-500/30">
          12 PROVEN WORKFLOWS
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <template x-for="wf in workflowsList" :key="wf.id">
          <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col justify-between hover:border-pink-500/50 transition">
            <div>
              <div class="flex justify-between items-start mb-2">
                <span class="text-xs font-mono font-bold text-pink-400 uppercase tracking-wider" x-text="wf.category"></span>
                <span class="text-xs font-mono bg-slate-800 text-slate-400 px-2 py-0.5 rounded" x-text="wf.id"></span>
              </div>
              <h3 class="text-base font-bold text-white mb-1" x-text="wf.title"></h3>
              
              <!-- Source Video Link -->
              <div class="mb-3 p-2.5 rounded-xl bg-slate-950 border border-slate-800/80 flex items-center justify-between text-xs">
                <div class="truncate pr-2">
                  <span class="text-slate-400 font-mono">Source: </span>
                  <strong class="text-emerald-400" x-text="wf.creator"></strong>
                  <span class="text-slate-500">&bull;</span>
                  <span class="text-slate-300" x-text="wf.source_video_title"></span>
                </div>
                <a :href="wf.source_url" target="_blank" class="shrink-0 bg-pink-600/30 hover:bg-pink-600 text-pink-300 hover:text-white px-2.5 py-1 rounded text-[11px] font-bold transition">
                  Open Video ↗
                </a>
              </div>

              <!-- How It Earns -->
              <div class="mb-3 text-xs bg-purple-950/40 border border-purple-800/50 p-2.5 rounded-xl text-purple-200">
                <strong>💰 Monetization: </strong><span x-text="wf.how_it_earns"></span>
              </div>

              <!-- How to Relearn Steps -->
              <div class="mb-3 text-xs text-slate-300 space-y-1">
                <strong class="text-slate-400 font-mono text-[11px] uppercase block mb-1">Execution Steps:</strong>
                <template x-for="(step, sIdx) in wf.how_to_do" :key="sIdx">
                  <div class="text-[11px] text-slate-400 leading-relaxed" x-text="step"></div>
                </template>
              </div>

              <!-- Prompt Box -->
              <div class="mb-3">
                <span class="text-[11px] font-mono text-slate-400 uppercase block mb-1">Production Video / Image Prompt:</span>
                <p class="text-xs text-slate-300 bg-slate-950 p-3 rounded-xl border border-slate-800/80 font-mono leading-relaxed select-all" x-text="wf.prompt"></p>
              </div>
            </div>

            <div class="pt-3 border-t border-slate-800/80 flex space-x-2">
              <button @click="copyText(wf.prompt, 'Prompt copied for ' + wf.title)" 
                      class="flex-1 bg-pink-600 hover:bg-pink-500 text-white font-bold py-2 px-3 rounded-xl text-xs transition flex items-center justify-center space-x-1.5">
                <span>📋</span>
                <span>Copy Prompt</span>
              </button>
              <button @click="copyText(wf.exec_command, 'CLI command copied for ' + wf.title)" 
                      class="bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-mono py-2 px-3 rounded-xl text-xs transition">
                Copy CLI
              </button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- TAB: 🎯 NEXEN DAILY FOCUS -->
    <!-- ========================================== -->
    <div x-show="currentTab === 'focus'" class="space-y-6">
      <div class="bg-slate-900 p-6 rounded-2xl border border-slate-800">
        <h2 class="text-xl font-black text-white flex items-center space-x-2">
          <span>🎯</span>
          <span>NEXEN Daily Focus & Priority Radar</span>
        </h2>
        <p class="text-slate-400 text-sm mt-1">
          Canonical daily operational focus extracted directly from <code>H:\\NEXEN\\handoffs\\NEXEN-DAILY-FOCUS-20260930.md</code> and live tickets.
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div class="bg-rose-950/40 border border-rose-800/60 rounded-2xl p-5 space-y-3">
          <span class="text-xs font-mono font-bold text-rose-400 uppercase">PRIORITY ZERO &bull; FOCUS #151</span>
          <h3 class="text-base font-bold text-white">Benefits & Housing Stability</h3>
          <p class="text-xs text-slate-300 leading-relaxed">
            Fill household/income/benefit/rent fields in BenefitApplier. 25-minute outreach block. Confirm last-job dates and wage verification. Zero downtime on survival.
          </p>
          <div class="pt-2">
            <code class="text-[11px] text-rose-300 bg-slate-950 p-2 rounded block font-mono">H:\\NEXEN\\apps\\BenefitApplier</code>
          </div>
        </div>

        <div class="bg-blue-950/40 border border-blue-800/60 rounded-2xl p-5 space-y-3">
          <span class="text-xs font-mono font-bold text-blue-400 uppercase">CONTROLLER &bull; TASK #142</span>
          <h3 class="text-base font-bold text-white">V3 Live Controller & Revenue Gates</h3>
          <p class="text-xs text-slate-300 leading-relaxed">
            Reconcile Packet106 executable acceptance. Keep STOP preserved until verified production canary. Four-lane helper checkout PASS.
          </p>
          <div class="pt-2">
            <code class="text-[11px] text-blue-300 bg-slate-950 p-2 rounded block font-mono">H:\\NEXEN\\v1\\app\\data\\nexen.db</code>
          </div>
        </div>

        <div class="bg-emerald-950/40 border border-emerald-800/60 rounded-2xl p-5 space-y-3">
          <span class="text-xs font-mono font-bold text-emerald-400 uppercase">REVENUE FIRST</span>
          <h3 class="text-base font-bold text-white">Fastest Dollar Lanes</h3>
          <p class="text-xs text-slate-300 leading-relaxed">
            1. Post 7 ready AI-model posts natively.<br>
            2. $100 n8n automation service proposals.<br>
            3. Whop Content Rewards clipping.<br>
            4. TikTok Shop seller product tags.
          </p>
          <div class="pt-2">
            <code class="text-[11px] text-emerald-300 bg-slate-950 p-2 rounded block font-mono">H:\\NEXEN\\posts\\ai-models</code>
          </div>
        </div>
      </div>

      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <h3 class="text-sm font-mono font-bold text-pink-400 uppercase mb-3">Live Daily Focus Document</h3>
        <pre class="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs text-slate-300 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-96 custom-scroll" x-text="dailyFocusText"></pre>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- TAB: ✂️ SMART VIRAL CLIPPER & HEATMAP -->
    <!-- ========================================== -->
    <div x-show="currentTab === 'clipper'" class="space-y-6" x-data="{ clipperInput: 'H:\\\\NEXEN\\\\videos\\\\sample.mp4', clipCount: 3, isClipping: false }">
      <div class="bg-slate-900 p-6 rounded-2xl border border-slate-800">
        <h2 class="text-xl font-black text-white flex items-center space-x-2">
          <span>✂️</span>
          <span>Smart Viral Clipper & Retention Heatmap Engine</span>
        </h2>
        <p class="text-slate-400 text-sm mt-1">
          Engineered to maximize Whop rewards ($1-$5 CPM) and short-form retention with word-by-word bouncing yellow captions and anti-ban video re-encoding.
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <h3 class="text-sm font-mono font-bold text-pink-400 uppercase">1. Clipper Configuration</h3>
          <div class="space-y-3 text-xs">
            <div>
              <label class="block text-slate-400 mb-1 font-mono">Input Video File Path:</label>
              <input type="text" x-model="clipperInput" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white font-mono focus:border-pink-500 focus:outline-none">
            </div>
            <div>
              <label class="block text-slate-400 mb-1 font-mono">Number of Viral Clips to Cut:</label>
              <input type="number" x-model="clipCount" min="1" max="10" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white font-mono focus:border-pink-500 focus:outline-none">
            </div>
          </div>

          <div class="pt-2">
            <button @click="copyText('python H:\\\\NEXEN\\\\clipping\\\\smart_viral_clipper.py --input \"' + clipperInput + '\" --clips ' + clipCount, 'Clipper command copied!'); isClipping = true;"
                    class="w-full bg-gradient-to-r from-pink-600 to-purple-600 hover:from-pink-500 hover:to-purple-500 text-white font-black py-3 rounded-xl text-sm transition flex items-center justify-center space-x-2 shadow-lg shadow-pink-600/30">
              <span>⚡</span>
              <span>RUN SMART CLIPPER & GENERATE SUBTITLES</span>
            </button>
          </div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <h3 class="text-sm font-mono font-bold text-emerald-400 uppercase">2. Retention Heatmap & Anti-Ban Architecture</h3>
          <ul class="text-xs text-slate-300 space-y-2.5 leading-relaxed">
            <li class="flex items-start space-x-2">
              <span class="text-emerald-400 font-bold">&bull;</span>
              <span><strong>0.0s - 1.5s Hook Snapping:</strong> Clips automatically start on speech word cues to eliminate empty intro dead space.</span>
            </li>
            <li class="flex items-start space-x-2">
              <span class="text-emerald-400 font-bold">&bull;</span>
              <span><strong>18s - 35s Viral Duration:</strong> Proven duration window for maximum 70%+ completion rate on TikTok & Reels algorithms.</span>
            </li>
            <li class="flex items-start space-x-2">
              <span class="text-emerald-400 font-bold">&bull;</span>
              <span><strong>Dynamic Bouncing Subtitles:</strong> Electric Yellow (#FFEE00) highlight, 110% scale pop, Arial Black 68pt centered above UI buttons.</span>
            </li>
            <li class="flex items-start space-x-2">
              <span class="text-emerald-400 font-bold">&bull;</span>
              <span><strong>Anti-Ban Hash Jitter:</strong> Strips original metadata (-map_metadata -1) and injects micro-noise to defeat duplicate video bans.</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
"""

content = content.replace("<!-- TAB 1: AI UGC ADS ON CLOUD GPU -->", new_tabs_html + "\n    <!-- TAB 1: AI UGC ADS ON CLOUD GPU -->")

# 4. Update Tabs list in JS
old_tabs_js = """tabs: [
          { id: 'ugc', name: 'AI UGC Ads', icon: '✨' },"""

new_tabs_js = """tabs: [
          { id: 'workflows', name: 'Workflows & Video Sources', icon: '🎬' },
          { id: 'focus', name: 'NEXEN Daily Focus', icon: '🎯' },
          { id: 'clipper', name: 'Smart Viral Clipper', icon: '✂️' },
          { id: 'ugc', name: 'AI UGC Ads', icon: '✨' },"""

content = content.replace(old_tabs_js, new_tabs_js)

# 5. Add workflowsList and dailyFocusText to Alpine data
alpine_hook = "currentTab: 'workflows',\n        toastMessage: '',\n        dailyFocusText: 'Loading Daily Focus...',\n        workflowsList: " + workflows_json_str + ",\n"
content = content.replace("currentTab: 'ugc',\n        toastMessage: '',\n", alpine_hook)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated mission_control.html with Workflows, Focus, and Clipper tabs successfully!")
