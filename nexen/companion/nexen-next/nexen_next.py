"""NEXEN NEXT: one window. Next blocker banner on every tab, steps, Q1 to Q6, agent tracker (Claude, Codex, Antigravity),
live evidence (from Antigravity's NEXEN_LIVE_DASHBOARD), Road to Success (from Antigravity's ROAD_TO_SUCCESS),
MARVIN training, Desktop, status. Every button either does the thing or copies a ready prompt for an agent.
State: H:\\NEXEN-ENTERPRISE\\Apps\\NEXEN\\companion\\nexen-next\\state.json. No passwords are read or stored here."""
import datetime, glob, json, os, subprocess, sys, tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blocker as B

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = B.STATE
DESK = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
PY = r"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe"
MT = r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\companion\marvin-training"
DO = r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\companion\desktop-organizer"
PACKET = B.PACKET
SCRAPE_DIR = os.path.join(DESK, "Scrape_Results_3000_VIRAL")
DATASET_DIR = os.path.join(DESK, "NEXEN_MASTER_DATASETS")
AGENT_LOG = r"H:\NEXEN\logs\uncensored_agent.log"
VAULT = r"H:\NEXEN\obsidian\NEXEN-Recovered-20261005"

STEPS = [
    ("q", "1. Answer Q1 to Q6 (10 min)", "Unblocks the Curviana test, the first real money step. Use the Questions tab. Type 'default' to accept the default."),
    ("fiverr", "2. Finish and publish the Fiverr gig (30 min)", "Open Chrome with the Dione - Chrome shortcut, sign in to Fiverr. Finish requirements, FAQs, gallery. Publish. Screenshot the live page."),
    ("tiktok", "3. Cancel TikTok posts P03 and P05 (5 min)", "You rejected P02 to P07. Open TikTok scheduled posts and delete P03 and P05 from the schedule."),
    ("key", "4. Rotate the Ollama cloud key (5 min)", "It was pasted in chat Sept 30. Make a new key on the provider site. Never paste it into chat or files."),
    ("train", "5. Run MARVIN training (15 min)", "MARVIN training tab. Self-test, then Ask live MARVIN. Type the password in the console window, hidden."),
    ("agent", "6. Start ONE lead agent on Curviana", "Fresh Claude Code chat. Paste PROMPT A from file 06 in the packet. Chat title is a ticket ID."),
    ("f", "Later: F: drive disk check", "Close all agent chats, restart once. No dupeGuru, defrag or live CHKDSK on F:."),
    ("pc2", "Later: PC2 launch (optional)", "On PC2 only, double-click START-HIDDEN.vbs in coding-loop-v1. STOP-WORKER.vbs stops it."),
    ("assoc", "Later: Amazon Associates and persona handles", "Confirm approval and send tagged links (Q4). Say which personas have Instagram accounts (Q5)."),
    ("life", "Later: housing and unemployment (Q19, Q20)", "Tell the agent the exact deadline and your job or separation status. Nothing is submitted for you."),
]
QS = [
    ("Q1", "Which persona leads Curviana? (Sienna Rowe, Maya Vale, Jade Monroe)", "Sienna Rowe"),
    ("Q2", "Exact denim item first: supplier, price, sales link", "Agent proposes 3, you pick"),
    ("Q3", "Own stock, dropship or affiliate? Also Passion Homecare, LumiPaw", ""),
    ("Q4", "Amazon Associates approved? Your tagged links?", "Agent lists links from Chrome home page"),
    ("Q5", "Do the 5 personas have Instagram accounts? Handles?", "Agent drafts bios, no accounts created"),
    ("Q6", "Which V3 exe and source owns the Stat Center?", "Agent compares, you confirm"),
]
DONE = ["Upwork offer approved and visible: 250 / 450 / 650 USD", "Fiverr profile done, gig overview, tags, prices saved", "Old vault recovered: 58,162 notes in Obsidian",
        "Swarm audited, twelve roles approved, corrected worker staged (34 tests, not promoted)", "MARVIN practice 11 pass / 6 partial",
        "Desktop sorted into 15 folders (115 moves, verified)", "MARVIN heavy training module: 120 questions, selftest 618/618"]
OPEN = ["Revenue: $0 verified, no orders", "Fiverr gig not published", "Swarm: 192 queued jobs, zero receipts, gate is ticket 229",
        "Ingest stopped at 12,193 of 62,021, stays stopped", "291 of 318 tickets open", "V4 is a name and boundary, no code moved",
        "MARVIN training not yet run on live MARVIN", "OpenClaw (WSL) cannot reach Windows Ollama", "PC2 coding loop never confirmed run",
        "Global STOP and PAUSE_AUTONOMY are on"]
FOLDERS = [("00 START HERE", ""), ("01 NEXEN Apps - Open These", ""), ("02 AI and Coding Tools", ""), ("03 Media Music and Social Apps", ""),
           ("04 Google and Browser Links", ""), ("05 Reports and Status Notes", ""), ("06 Raw Chat Handoff Dumps", ""), ("07 Music Projects", ""),
           ("08 Installers and Packages", ""), ("09 Pictures and Clips", ""), ("10 Business Projects", ""), ("11 Private - Do Not Share", ""),
           ("12 Controller Tool (DS4Windows)", ""), ("13 Old Backups and Junk", ""), ("14 Duplicate Copies (identical, safe to delete)", "")]

RULES = ("Rules: read F:\\NEXEN_MEMORY\\00-Control\\AGENT-START-HERE.md and the last 40 lines of SESSION-LOG.md first. "
         "Global STOP and PAUSE_AUTONOMY stay on. No paid spend without a MARVIN approval (amount, purpose, provider, scope). "
         "Never put passwords, keys or PC2 details in files, prompts or logs. Done means a receipt: a file path, a hash or a screenshot saved to disk. "
         "Append a SESSION-LOG entry (Did, Receipts, Decisions, Blocked on, NEXT ACTION) and run knowledge_sync.py all before you stop. "
         "Label status honestly: tested on real input, synthetic only, or untested.")
PROMPTS = {
    "q": "Open H:\\NEXEN\\handoffs\\packet-20261005\\OWNER-ANSWERS-Q1-Q6.txt and 02-QUESTIONS-ALL-OF-THEM.txt. For every blank answer apply the stated default. Write the resolved answers into the vault Current Decisions with an ID and source. Then list what Curviana still needs from the owner. ",
    "fiverr": "Help the owner finish the Fiverr gig. Saved: profile, title, tags, prices 250/450/650. Left: requirements, FAQs, gallery, publish. Draft the requirements and FAQ text from H:\\NEXEN\\handoffs\\income-launch-20261003\\SERVICE-OFFER-APPROVAL.json for the owner to paste. The owner clicks publish. Verify with a saved screenshot of the live gig. ",
    "tiktok": "Check TikTok scheduled posts P03 and P05 (owner rejected P02 to P07). Prepare the exact cancel steps for the owner, then record a screenshot receipt that neither is scheduled. Do not publish or schedule anything. ",
    "key": "The Ollama cloud key was pasted in chat on Sept 30. Write a 5-step checklist for the owner to revoke it on the provider site and store a new one in Windows Credential Manager. Search the vault and H:\\NEXEN for files containing the old key pattern and list paths only, never the value. ",
    "train": "Run the MARVIN heavy training at H:\\NEXEN-ENTERPRISE\\Apps\\NEXEN\\companion\\marvin-training. Self-test first. The live run needs the owner password typed by the owner, so stop and ask the owner to type it in the console. Then read results\\LATEST-REPORT.md, list the 3 weakest categories and write a 10-line drill plan. ",
    "agent": "You are the ONE lead agent. Take PROMPT A from H:\\NEXEN\\handoffs\\packet-20261005\\06-PLAN-PROMPTS-AND-CLIENTS.txt and start the Curviana 7-day pilot using the owner's resolved Q1 to Q6 answers. Chat title must be a ticket ID. One owner per ticket. Take the lease before editing. ",
    "f": "Prepare the F: drive repair checklist. F_DRIVE_ALERT.txt says Windows queued a boot-time check. Do not run dupeGuru, defrag or live CHKDSK /f. List what must be closed first, what to verify after reboot, and the receipt path. ",
    "pc2": "Read %USERPROFILE%\\Desktop\\MARVIN\\Reports\\PC2-DO-THIS-NOW.txt. Check coding-loop-v1\\results after the owner launches it on PC2. Validate host, job identity, source and artifact hashes, baseline and tests before calling remote coding proven. ",
    "assoc": "Using the owner's Q4 and Q5 answers, list the Amazon tagged links found on the Chrome home page (paths and URLs only) and draft bios and handles for the five personas for review. Create no accounts. ",
    "life": "Read H:\\NEXEN\\apps\\BenefitApplier. Using the owner's Q19 and Q20 answers, put the urgent deadline first and prepare drafts for the owner's review. Submit nothing. Do not guess eligibility. ",
    "rent": "Rent is one month late (owner-reported in the Road to Success app). Read the packet, find the fastest verified cash path (Fiverr gig publish, Upwork leads, Curviana pilot), and rank steps by dollars and days to first payment. Include housing help resources from the benefits app. Make no promises of income and submit nothing without owner approval. ",
    "live": "Verify the live evidence: count files in Desktop\\Scrape_Results_3000_VIRAL, check Desktop\\NEXEN_MASTER_DATASETS exists, and tail H:\\NEXEN\\logs\\uncensored_agent.log. Report which scripts are really running (process list) and which claims in Road to Success are unverified. ",
}
GENERIC = "Read the last 40 lines of F:\\NEXEN_MEMORY\\00-Control\\SESSION-LOG.md, take the open NEXT ACTION, and do that one bounded task. "


def full(key):
    return PROMPTS.get(key, GENERIC) + RULES


def resume_prompt(agent):
    ag, _ = B.agents_latest(); e = ag.get(agent)
    last = (f"Your last logged entry: {e['title']}. Blocked on: {e['blocked']}. NEXT ACTION: {e['next']}." if e else "You have no entry in SESSION-LOG yet.")
    return f"You are {agent} on NEXEN. {last} Refresh file ownership before writing, then do the NEXT ACTION as one bounded packet. " + RULES


def load():
    return B.load_state()


def save(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(s, f, indent=1)
    os.replace(tmp, STATE)
    try:
        with open(os.path.join(PACKET, "OWNER-ANSWERS-Q1-Q6.txt"), "w", encoding="utf-8") as f:
            f.write(f"Owner answers saved {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n")
            for k, q, d in QS: f.write(f"{k}. {q}\n   ANSWER: {s['answers'].get(k, '') or '(blank)'}\n\n")
    except OSError: pass


def opn(path):
    if os.path.exists(path): os.startfile(path)
    else: messagebox.showwarning("Not found", path)


def console(cmd):
    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd], cwd=MT if os.path.isdir(MT) else None)


SCRAPE_DIRS = [SCRAPE_DIR] + [os.path.join(DESK, d) for d in ("1000_VIRAL_VIDEOS", "VIRAL_PATTERN_RESEARCH", "EXTRACTED_VIRAL_HOOKS")]


def live_numbers():
    n = sum(len(glob.glob(os.path.join(d, "*.json"))) for d in SCRAPE_DIRS if os.path.isdir(d))
    mb = 0.0
    if os.path.isdir(DATASET_DIR):
        for r, _d, fs in os.walk(DATASET_DIR):
            for x in fs:
                try: mb += os.path.getsize(os.path.join(r, x)) / 1048576
                except OSError: pass
    return n, mb


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NEXEN MISSION CONTROL"); self.geometry("1100x800"); self.configure(bg="#111")
        st = ttk.Style(self); st.theme_use("clam")
        st.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(10, 6))
        st.configure("TFrame", background="#fff"); st.configure("TLabel", background="#fff", font=("Segoe UI", 11))
        st.configure("TCheckbutton", background="#fff", font=("Segoe UI", 12, "bold")); st.configure("TButton", font=("Segoe UI", 10), padding=5)
        self.s = load(); self.vars = {}; self.cur = None; self.log_pos = 0
        self.banner = tk.Frame(self, bg="#c00"); self.banner.pack(fill="x", padx=6, pady=(6, 0))
        tk.Label(self.banner, text="NEXT BLOCKER", bg="#c00", fg="#fff", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(4, 0))
        self.btxt = tk.Label(self.banner, text="", bg="#c00", fg="#fff", font=("Segoe UI", 15, "bold"), wraplength=960, justify="left"); self.btxt.pack(anchor="w", padx=10)
        row = tk.Frame(self.banner, bg="#c00"); row.pack(anchor="w", padx=10, pady=6)
        for t, c in (("Open blocker", self.open_blocker), ("Copy agent prompt", self.copy_blocker_prompt), ("Mark done", self.done_blocker)):
            tk.Button(row, text=t, font=("Segoe UI", 11, "bold"), command=c).pack(side="left", padx=3)
        self.toast = tk.Label(row, text="", bg="#c00", fg="#fff", font=("Segoe UI", 10)); self.toast.pack(side="left", padx=10)
        self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True, padx=6, pady=6); self.tabs = {}
        for name, fn in (("Next steps", self.tab_steps), ("Questions Q1-Q6", self.tab_q), ("Agents tracker", self.tab_track), ("Live evidence", self.tab_live),
                         ("Road to success", self.tab_road), ("All tools", self.tab_all), ("Open ports", self.tab_ports), ("Everything coded", self.tab_code), ("Failure prevention", self.tab_prevent), ("MARVIN training", self.tab_train), ("Desktop", self.tab_desk), ("Status", self.tab_status)):
            f = ttk.Frame(self.nb, padding=12); self.nb.add(f, text=name); self.tabs[name] = f; fn(f)
        self.tick(); self.after(2000, self.auto)

    # ---- shared
    def say(self, t):
        self.toast.config(text=t); self.after(4500, lambda: self.toast.config(text=""))

    def copy(self, text, label="Prompt"):
        self.clipboard_clear(); self.clipboard_append(text); self.update(); self.say(f"{label} copied. Paste into Claude, Codex or Antigravity.")

    def go(self, target):
        if target.startswith("tab:"): self.nb.select(self.tabs[target[4:]])
        else: B.open_target(target)

    def refresh_banner(self):
        self.cur = B.next_blocker(self.s)
        self.btxt.config(text=self.cur[1] if self.cur else "None. Every step is ticked.")

    def open_blocker(self):
        if self.cur: self.go(self.cur[2])

    def copy_blocker_prompt(self):
        if self.cur: self.copy(full(self.cur[0]))

    def done_blocker(self):
        if not self.cur: return
        k = self.cur[0]; self.s["done"][k] = True
        if k in self.vars: self.vars[k].set(True)
        self.tick()

    def auto(self):
        try:
            self.refresh_live(); self.tail_log()
            self.n = getattr(self, "n", 0) + 1
            if self.n % 15 == 0: self.refresh_track(); self.refresh_banner()
        finally:
            self.after(2000, self.auto)

    def tick(self):
        self.s["done"] = {k: v.get() for k, v in self.vars.items()}; save(self.s)
        n = sum(self.s["done"].values()); nxt = next((t for k, t, _ in STEPS if not self.s["done"].get(k)), "All done")
        self.prog.config(text=f"{n} of {len(STEPS)} done.  NEXT: {nxt}"); self.refresh_banner()

    def buttons(self, parent, key, target=""):
        r = ttk.Frame(parent); r.pack(anchor="w", pady=2)
        if target: ttk.Button(r, text="Open", command=lambda: self.go(target)).pack(side="left", padx=2)
        ttk.Button(r, text="Copy agent prompt", command=lambda: self.copy(full(key))).pack(side="left", padx=2)
        return r

    # ---- tabs
    def tab_steps(self, f):
        self.prog = ttk.Label(f, font=("Segoe UI", 14, "bold")); self.prog.pack(anchor="w")
        ttk.Label(f, text="Do them in order. Tick when done. Saved automatically.").pack(anchor="w", pady=(0, 6))
        for key, title, why in STEPS:
            v = tk.BooleanVar(value=self.s["done"].get(key, False)); self.vars[key] = v
            box = ttk.Frame(f); box.pack(fill="x", pady=3)
            ttk.Checkbutton(box, text=title, variable=v, command=self.tick).pack(anchor="w")
            ttk.Label(box, text=why, wraplength=920, foreground="#444").pack(anchor="w", padx=26)
            tgt = next((o for kk, _t, o in B.ORDER if kk == key), "")
            self.buttons(box, key, tgt).pack_configure(padx=26)

    def tab_q(self, f):
        ttk.Label(f, text="Short answers are enough. Blank means use the default. Saved to the packet folder. No passwords or keys here.", wraplength=920).pack(anchor="w", pady=(0, 6))
        self.ent = {}
        for k, q, d in QS:
            ttk.Label(f, text=f"{k}. {q}", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(6, 0))
            ttk.Label(f, text=f"Default: {d or 'none, you answer'}", foreground="#666").pack(anchor="w")
            e = ttk.Entry(f, font=("Segoe UI", 11)); e.pack(fill="x"); e.insert(0, self.s["answers"].get(k, "")); self.ent[k] = e
            e.bind("<KeyRelease>", lambda _e: self.saveq())
        r = ttk.Frame(f); r.pack(anchor="w", pady=10)
        ttk.Button(r, text="Open full 22-question file", command=lambda: opn(os.path.join(PACKET, "02-QUESTIONS-ALL-OF-THEM.txt"))).pack(side="left", padx=2)
        ttk.Button(r, text="Copy agent prompt: resolve my answers", command=lambda: self.copy(full("q"))).pack(side="left", padx=2)

    def saveq(self):
        self.s["answers"] = {k: e.get() for k, e in self.ent.items()}; save(self.s)

    def tab_track(self, f):
        ttk.Label(f, text="What Claude, Codex and Antigravity last logged in SESSION-LOG. Refreshes every 30 seconds.", wraplength=920).pack(anchor="w", pady=(0, 6))
        self.tr = {}
        for a in ("Claude", "Codex", "Antigravity"):
            box = ttk.Frame(f); box.pack(fill="x", pady=5)
            ttk.Label(box, text=a, font=("Segoe UI", 13, "bold")).pack(anchor="w")
            lab = ttk.Label(box, text="", wraplength=920, justify="left"); lab.pack(anchor="w", padx=12)
            ttk.Button(box, text=f"Copy resume prompt for {a}", command=lambda a=a: self.copy(resume_prompt(a), a + " prompt")).pack(anchor="w", padx=12, pady=2)
            self.tr[a] = lab
        r = ttk.Frame(f); r.pack(anchor="w", pady=8)
        ttk.Button(r, text="Refresh now", command=self.refresh_track).pack(side="left", padx=2)
        ttk.Button(r, text="Open session log", command=lambda: B.open_target(B.LOG if os.path.exists(B.LOG) else B.LOG_ALT)).pack(side="left", padx=2)
        ttk.Button(r, text="Open coding status report", command=lambda: opn(os.path.join(DESK, "MARVIN", "Reports", "NEXEN-CODING-STATUS-LATEST.txt"))).pack(side="left", padx=2)
        self.refresh_track()

    def refresh_track(self):
        ag, _p = B.agents_latest()
        for a, lab in self.tr.items():
            e = ag.get(a)
            conv = B.v4_recent(a)
            tail = f"\nLast conversation (V4 connector): {conv}" if conv else ""
            lab.config(text=(f"{e['title']}\nBlocked on: {e['blocked']}\nNext: {e['next']}" + tail if e else
                             "No entry in SESSION-LOG. Paste the resume prompt so this agent logs its work there." + tail))

    def tab_prevent(self, f):
        ttk.Label(f, text="Intellect spine: live checks mapped to the 72 known failure classes, worst first. Each one has a fix prompt for an agent.", wraplength=920).pack(anchor="w", pady=(0, 6))
        r = ttk.Frame(f); r.pack(anchor="w")
        ttk.Button(r, text="Scan now", command=self.scan_prevent).pack(side="left", padx=2)
        self.pv_note = ttk.Label(r, text="Not scanned yet."); self.pv_note.pack(side="left", padx=8)
        self.pv_box = ttk.Frame(f); self.pv_box.pack(fill="both", expand=True, pady=6)
        self.after(1500, self.scan_prevent)

    def scan_prevent(self):
        import threading
        self.pv_note.config(text="Scanning (up to 10 s)...")
        box = []  # the worker only fills this list; Tk calls stay on the main thread
        def work():
            try:
                import prevent
                box.append(prevent.scan())
            except Exception as e:
                box.append(e)
        def poll():
            if box: self.show_prevent(box[0])
            else: self.after(300, poll)
        threading.Thread(target=work, daemon=True).start()
        self.after(300, poll)

    def show_prevent(self, rows):
        for w in self.pv_box.winfo_children(): w.destroy()
        if isinstance(rows, Exception):
            self.pv_note.config(text="Scan failed: %s" % type(rows).__name__); return
        import prevent
        bad = [x for x in rows if x["state"] != "ok"]
        self.pv_note.config(text="%d need attention, %d ok. %s" % (len(bad), len(rows) - len(bad), datetime.datetime.now().strftime("%H:%M:%S")))
        for x in rows:
            colour = {"bad": "#c00", "warn": "#b60"}.get(x["state"], "#080")
            box = ttk.Frame(self.pv_box); box.pack(fill="x", pady=2)
            tk.Label(box, text=x["state"].upper(), bg=colour, fg="#fff", width=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
            ttk.Label(box, text="%s  %s" % (x["detail"], ("[%s %s]" % (x["problem"], x["title"])) if x["problem"] else ""), wraplength=720).pack(side="left")
            if x["state"] != "ok" and x["steps"]:
                ttk.Button(box, text="Copy fix prompt", command=lambda x=x: self.copy(prevent.agent_prompt(x), "Fix prompt")).pack(side="right")

    def tab_live(self, f):
        ttk.Label(f, text="Live evidence (from Antigravity's dashboard, now inside this app). Counts update every 2 seconds.", wraplength=920).pack(anchor="w")
        self.sc = ttk.Label(f, font=("Consolas", 13, "bold")); self.sc.pack(anchor="w", pady=(8, 0))
        self.ds = ttk.Label(f, font=("Consolas", 13, "bold")); self.ds.pack(anchor="w")
        ttk.Label(f, text="Agent log (H:\\NEXEN\\logs\\uncensored_agent.log):").pack(anchor="w", pady=(8, 0))
        self.logbox = scrolledtext.ScrolledText(f, height=18, bg="#000", fg="#0f0", font=("Consolas", 10)); self.logbox.pack(fill="both", expand=True)
        r = ttk.Frame(f); r.pack(anchor="w", pady=6)
        ttk.Button(r, text="Open scrape folder", command=lambda: opn(SCRAPE_DIR)).pack(side="left", padx=2)
        ttk.Button(r, text="Open dataset folder", command=lambda: opn(DATASET_DIR)).pack(side="left", padx=2)
        ttk.Button(r, text="Copy agent prompt: verify what is really running", command=lambda: self.copy(full("live"))).pack(side="left", padx=2)
        self.refresh_live()

    def refresh_live(self):
        n, mb = live_numbers()
        self.sc.config(text=f"Scraped viral targets: {n}/3000" + ("" if n else "  (folder missing)"))
        self.ds.config(text=f"Dataset size: {mb:.2f} MB" + ("" if os.path.isdir(DATASET_DIR) else "  (NEXEN_MASTER_DATASETS not found, nothing to count yet)"))

    def tail_log(self):
        if not os.path.exists(AGENT_LOG):
            if self.log_pos == 0 and not self.logbox.get("1.0", "end").strip():
                self.logbox.insert("end", "No agent log yet. The uncensored agent has not written one. Nothing is claimed as running.\n")
            return
        try:
            size = os.path.getsize(AGENT_LOG)
            if size < self.log_pos: self.log_pos = 0
            with open(AGENT_LOG, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(max(self.log_pos, size - 20000) if self.log_pos == 0 else self.log_pos)
                data = fh.read(); self.log_pos = fh.tell()
            if data: self.logbox.insert("end", data); self.logbox.see("end")
        except OSError: pass

    def tab_road(self, f):
        ttk.Label(f, text="YOUR ROAD TO SUCCESS (from Antigravity's Life OS, merged)", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        box = tk.LabelFrame(f, text=" URGENT SURVIVAL METRICS ", fg="#c00", bg="#fff", font=("Segoe UI", 11, "bold")); box.pack(fill="x", pady=8, ipady=6)
        ttk.Label(box, text="Rent is 1 month late (owner-reported). Cash focus: Fiverr gig, Upwork leads, Curviana pilot. Verified revenue: $0.", font=("Segoe UI", 12, "bold"), foreground="#c00").pack(anchor="w", padx=8)
        self.buttons(box, "rent").pack_configure(padx=8)
        ttk.Label(f, text="WHAT IS ACTUALLY HAPPENING (checked live, not assumed)", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(10, 2))
        self.rl = ttk.Label(f, justify="left", wraplength=920, font=("Segoe UI", 11)); self.rl.pack(anchor="w", padx=8)
        ttk.Label(f, text="Antigravity's original list said brand identities are locked and a 7B sales model is training. No receipt for either was found, so they are shown as unverified.", wraplength=920, foreground="#8a5a00").pack(anchor="w", pady=8)
        r = ttk.Frame(f); r.pack(anchor="w")
        ttk.Button(r, text="Open Obsidian vault folder (past chats)", command=lambda: opn(VAULT)).pack(side="left", padx=2)
        ttk.Button(r, text="Open housing and benefits app folder", command=lambda: opn(r"H:\NEXEN\apps\BenefitApplier")).pack(side="left", padx=2)
        self.refresh_road(); self.after(10000, self.loop_road)

    def loop_road(self):
        self.refresh_road(); self.after(10000, self.loop_road)

    def refresh_road(self):
        n, mb = live_numbers()
        log_ok = os.path.exists(AGENT_LOG) and os.path.getsize(AGENT_LOG) > 100
        lines = [f"{'OK' if n >= 3000 else 'PARTIAL'}  Viral scrape files on disk: {n} of 3000",
                 f"{'OK' if os.path.isdir(DATASET_DIR) else 'MISSING'}  Master dataset folder (Desktop\\NEXEN_MASTER_DATASETS): {mb:.1f} MB",
                 f"{'OK' if log_ok else 'NO RECEIPT'}  Uncensored agent log with content (training claim): {'found' if log_ok else 'not found or empty'}",
                 "UNVERIFIED  Brand identities locked (Curviana, LumiPaw, Passion Homecare): no receipt found",
                 "UNVERIFIED  Rainmaker agent drafting Fiverr profiles: no receipt found",
                 f"{'OK' if os.path.isdir(VAULT) else 'MISSING'}  Obsidian recovered vault folder"]
        self.rl.config(text="\n".join(lines))

    def tab_all(self, f):
        V4 = r"H:\NEXEN-ENTERPRISE\Apps\NEXEN"
        canvas = tk.Canvas(f, bg="#fff", highlightthickness=0); sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas); inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw"); canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        review = ("Review this script line by line and report what it really does, which files and services it touches, "
                  "whether it conflicts with global STOP and PAUSE_AUTONOMY, and whether its output claims are backed by receipts. Do not run it. ")

        def head(t): ttk.Label(inner, text=t, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(12, 2))

        def row(title, note, buttons, color="#444"):
            b = ttk.Frame(inner); b.pack(fill="x", pady=3, anchor="w")
            ttk.Label(b, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
            ttk.Label(b, text=note, wraplength=900, foreground=color).pack(anchor="w", padx=10)
            r = ttk.Frame(b); r.pack(anchor="w", padx=10)
            for label, fn in buttons: ttk.Button(r, text=label, command=fn).pack(side="left", padx=2)

        def cnt(p):
            return sum(len(fs) for _r, _d, fs in os.walk(p)) if os.path.isdir(p) else 0

        head("NEXEN (the main app)")
        row("NEXEN app", "Engine on http://127.0.0.1:8794. Tracks, learns and connects every NEXEN piece. This app is one of its modules.",
            [("Open V4 in browser", lambda: B.open_target("http://127.0.0.1:8794/")), ("nexen status", lambda: console(f'"{V4}\\nexen.cmd" status & pause')),
             ("nexen doctor", lambda: console(f'"{V4}\\nexen.cmd" doctor & pause')), ("Open V4 folder", lambda: opn(V4)),
             ("Copy prompt: sync with V4", lambda: self.copy("Run nexen context 'NEXEN NEXT' --print and nexen status, then reconcile NEXEN NEXT tabs and modules\\companion-tools.json with what V4 reports. " + RULES))])
        head("Command center and folders")
        for name, p, note in (("NEXEN_COMMAND_CENTER", os.path.join(DESK, "NEXEN_COMMAND_CENTER"), "1_ACTION_REQUIRED, 2_MARVIN_DROPS, 3_CHECKLISTS, DONE. Contains a task shortcut named about FL Studio cracks: that is not legal software, skip it."),
                              ("READY_TO_POST_DROPSHIP", os.path.join(DESK, "READY_TO_POST_DROPSHIP"), "Nothing posts without your approval and the quality gate. TikTok P02 to P07 stay rejected."),
                              ("READY_TO_POST_MUSIC", os.path.join(DESK, "READY_TO_POST_MUSIC"), "Same rule: review, then approve."),
                              ("1000_VIRAL_VIDEOS (scrape output)", os.path.join(DESK, "1000_VIRAL_VIDEOS"), "Scraped metadata JSON, not videos you own. Research only."),
                              ("NEXEN_MASTER_DATASETS", DATASET_DIR, "Training data pile from other tabs. Check licenses before fine-tuning."),
                              ("VIRAL_PATTERN_RESEARCH", os.path.join(DESK, "VIRAL_PATTERN_RESEARCH"), ""), ("EXTRACTED_VIRAL_HOOKS", os.path.join(DESK, "EXTRACTED_VIRAL_HOOKS"), "Empty."),
                              ("HIGGSFIELD_OUTPUTS", os.path.join(DESK, "HIGGSFIELD_OUTPUTS"), "Empty. Higgsfield is ignored by your decision."),
                              ("REVERSE_ENGINEERED_ASSETS / REJECTED_TRASH", os.path.join(DESK, "REJECTED_TRASH"), "Empty.")):
            row(f"{name}  [{cnt(p)} files]", note, [("Open folder", lambda p=p: opn(p))], "#8a0000" if "cracks" in note else "#444")
        head("Antigravity scripts on your Desktop (review only, not run from here)")
        for fn_, verdict, color in (
                ("NEXEN_LIVE_DASHBOARD.py", "Merged into the Live evidence tab. Safe: reads counts and a log.", "#086b2a"),
                ("ROAD_TO_SUCCESS.py", "Merged into Road to success. Its status list was unverified, now live-checked.", "#086b2a"),
                ("NEXEN_THE_GOD_BUTTON.py", "Prints a banner. Not a working automation. Review before any use.", "#8a5a00"),
                ("NEXEN_V7_METAMORPHIC_CORE.py", "A simulation: it fakes a scraper failure and a 'heal'. It does not heal anything real.", "#8a5a00"),
                ("NEXEN_MASTER_BOOTLOADER.bat", "Would start 8 agents at once (loop, ripper, dropship factory, music promo). Blocked: global STOP and PAUSE_AUTONOMY are on. Needs your lift.", "#b00000"),
                ("INSTALL_NEXEN_V5_BRIDGE.bat", "Downloads ray, vllm, langgraph with pip and sets up PC2 over LAN. Needs your approval first.", "#b00000"),
                ("MARVIN_LATEST_BRIEFING.html", "Says 50 leads scraped and mouse telemetry logged. No receipt found for either. Treat as unverified.", "#8a5a00")):
            p = os.path.join(DESK, fn_)
            row(fn_, verdict, [("Review in Notepad", lambda p=p: subprocess.Popen(["notepad", p])), ("Copy review prompt", lambda p=p: self.copy(f"File: {p}. " + review + RULES))], color)
        head("Everything else in NEXEN NEXT")
        row("Tabs", "Next steps, Questions, Agents tracker, Live evidence, Road to success, MARVIN training, Desktop, Status. The red banner on top is always your next blocker.", [])

    # ---- open ports (live)
    KNOWN_PORTS = {5678: "n8n (main)", 5680: "n8n staging instance", 5681: "n8n staging (internal)", 8788: "NEXEN core / MARVIN (V3)", 8794: "NEXEN engine",
                   8795: "NEXEN (exe, likely V4 shell)", 8806: "Business review workspace", 11438: "Local OCR", 11434: "Ollama", 1234: "LM Studio proxy",
                   27124: "Obsidian local REST", 18789: "WSL relay (OpenClaw gateway path)", 3001: "node service (unidentified)", 11435: "ollama-proxy", 11436: "python service (unidentified)"}
    WEB_PORTS = {5678, 5680, 8788, 8794, 8795, 8806, 1234, 11434}
    SYSTEM_PROCS = {"svchost", "System", "lsass", "wininit", "services", "spoolsv", "jhi_service", "OVRServer_x64", "vmms", "WorkflowAppControl"}

    def tab_ports(self, f):
        ttk.Label(f, text="Every TCP port listening on this PC right now. Red = reachable from other machines, not just this PC.", wraplength=1000).pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=4)
        self.hide_sys = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Hide Windows system ports", variable=self.hide_sys, command=self.refresh_ports).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=6)
        ttk.Button(top, text="Open selected in browser", command=self.open_port).pack(side="left", padx=2)
        ttk.Button(top, text="Copy prompt: audit selected port", command=self.audit_port).pack(side="left", padx=2)
        self.pcount = ttk.Label(top, text=""); self.pcount.pack(side="left", padx=10)
        cols = ("port", "bind", "process", "what", "exposure")
        self.ptree = ttk.Treeview(f, columns=cols, show="headings", height=22)
        for c, w in zip(cols, (70, 170, 190, 330, 220)): self.ptree.heading(c, text=c.title()); self.ptree.column(c, width=w, anchor="w")
        self.ptree.tag_configure("net", foreground="#b00000"); self.ptree.pack(fill="both", expand=True)
        self.refresh_ports(); self.after(15000, self.loop_ports)

    def loop_ports(self):
        self.refresh_ports(); self.after(15000, self.loop_ports)

    def refresh_ports(self):
        ps = ("Get-NetTCPConnection -State Listen | ForEach-Object { $p=Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
              "'{0}|{1}|{2}|{3}' -f $_.LocalPort,$_.LocalAddress,$p.ProcessName,$_.OwningProcess } | Sort-Object -Unique")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=25, creationflags=0x08000000).stdout
        except Exception as e:  # noqa: BLE001
            self.pcount.config(text=f"scan failed: {e}"); return
        rows, seen = [], set()
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 4 or not parts[0].isdigit(): continue
            port, addr, proc = int(parts[0]), parts[1], parts[2] or "?"
            if (port, addr) in seen: continue
            seen.add((port, addr))
            if self.hide_sys.get() and proc in self.SYSTEM_PROCS: continue
            local = addr in ("127.0.0.1", "::1")
            expo = "this PC only" if local else ("ALL interfaces (LAN reachable)" if addr in ("0.0.0.0", "::") else f"network address {addr}")
            rows.append((port, addr, proc, self.KNOWN_PORTS.get(port, ""), expo, local))
        rows.sort(key=lambda r: (r[3] == "", r[0]))
        self.ptree.delete(*self.ptree.get_children())
        for r in rows: self.ptree.insert("", "end", values=r[:5], tags=(() if r[5] else ("net",)))
        self.pcount.config(text=f"{len(rows)} listening, {sum(1 for r in rows if not r[5])} reachable beyond this PC, {sum(1 for r in rows if r[3])} identified")

    def _sel_port(self):
        s = self.ptree.selection()
        return self.ptree.item(s[0], "values") if s else None

    def open_port(self):
        v = self._sel_port()
        if v: B.open_target(f"http://127.0.0.1:{v[0]}/")

    def audit_port(self):
        v = self._sel_port()
        if v: self.copy(f"Audit TCP port {v[0]} bound to {v[1]} by process {v[2]} ({v[3] or 'unidentified'}). Find its owner program and source, say whether it must be reachable beyond this PC, whether it needs a password, and how to bind it to 127.0.0.1 if not. Change nothing without owner approval. " + RULES)

    # ---- everything coded (from the Button Box inventory in the vault)
    INVENTORY = [os.path.join(DESK, "05 Reports and Status Notes", "NEXEN-BUTTON-BOX-ALL-SOFTWARE.txt"), r"H:\NEXEN\handoffs\business-operations-20261004\NEXEN-BUTTON-BOX-ALL-SOFTWARE.txt"]

    def load_inventory(self):
        import re
        for p in self.INVENTORY:
            if os.path.exists(p):
                txt = open(p, encoding="utf-8", errors="replace").read(); break
        else: return [], None
        items = []
        for blk in re.split(r"\n(?=\d{4}\. )", txt):
            m = re.match(r"(\d{4})\. (.+?) \[(.+?)\]\s*\n\s*(.+)\n\s*(.+)\n?\s*(.*)", blk)
            if m: items.append({"id": m.group(1), "title": m.group(2), "cat": m.group(3), "path": m.group(4).strip(), "status": m.group(5).strip(), "what": m.group(6).strip()})
        return items, p

    def tab_code(self, f):
        self.inv, src = self.load_inventory()
        ttk.Label(f, text=f"Everything coded and installed, from the vault Button Box inventory: {len(self.inv)} entries. Source: {src or 'NOT FOUND'}. A source file is not proof of a working app; the Exists column is checked live.", wraplength=1040).pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=4)
        ttk.Label(top, text="Search:").pack(side="left"); self.q = tk.StringVar(); e = ttk.Entry(top, textvariable=self.q, width=34); e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda _e: self.fill_code())
        ttk.Button(top, text="Open folder", command=lambda: self.code_act("folder")).pack(side="left", padx=2)
        ttk.Button(top, text="Review in Notepad", command=lambda: self.code_act("review")).pack(side="left", padx=2)
        ttk.Button(top, text="Copy prompt: test this one", command=lambda: self.code_act("prompt")).pack(side="left", padx=2)
        self.ccount = ttk.Label(top, text=""); self.ccount.pack(side="left", padx=10)
        cols = ("id", "cat", "title", "exists", "status")
        self.ctree = ttk.Treeview(f, columns=cols, show="headings", height=22)
        for c, w in zip(cols, (55, 110, 420, 60, 380)): self.ctree.heading(c, text=c.title()); self.ctree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.ctree.yview); self.ctree.configure(yscrollcommand=sb.set)
        self.ctree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y"); self.fill_code()

    def fill_code(self):
        q = self.q.get().lower(); self.ctree.delete(*self.ctree.get_children()); n = ok = 0
        for it in self.inv:
            if q and q not in (it["title"] + it["cat"] + it["path"] + it["status"]).lower(): continue
            ex = os.path.exists(it["path"]); n += 1; ok += ex
            self.ctree.insert("", "end", iid=it["id"], values=(it["id"], it["cat"], it["title"], "yes" if ex else "NO", it["status"]))
        self.ccount.config(text=f"{n} shown, {ok} exist on disk")

    def code_act(self, what):
        s = self.ctree.selection()
        if not s: return
        it = next(i for i in self.inv if i["id"] == s[0]); p = it["path"]
        if what == "folder": opn(p if os.path.isdir(p) else os.path.dirname(p))
        elif what == "review": subprocess.Popen(["notepad", p]) if os.path.isfile(p) else messagebox.showinfo("Not a file", p)
        else: self.copy(f"Test this NEXEN program: {it['title']} [{it['cat']}] at {p}. Status in inventory: {it['status']}. Read the source, run its tests or one bounded real-input run, check the actual output file, and report tested on real input, synthetic only or untested with a receipt. Do not start background services while STOP is on. " + RULES)

    def tab_train(self, f):
        ttk.Label(f, text="120 heavy questions. Live runs ask the MARVIN password in the console window, hidden, never saved.", wraplength=920).pack(anchor="w", pady=(0, 6))
        for text, cmd in (("1  Self-test (no password)", f'"{PY}" marvin_train.py selftest'),
                          ("2  Ask live MARVIN all 120", f'"{PY}" marvin_train.py run --target marvin && "{PY}" marvin_train.py report'),
                          ("3  Only the brutal ones (difficulty 5)", f'"{PY}" marvin_train.py run --target marvin --min-diff 5 && "{PY}" marvin_train.py report'),
                          ("4  Re-ask only last failures", f'"{PY}" marvin_train.py run --target marvin --ids-file results\\drill-ids.txt && "{PY}" marvin_train.py report'),
                          ("5  Make fine-tune files", f'"{PY}" marvin_train.py sft && "{PY}" marvin_train.py dpo')):
            ttk.Button(f, text=text, command=lambda c=cmd: console(c)).pack(anchor="w", pady=3)
        for t, p in (("Open latest report", "results\\LATEST-REPORT.md"), ("Read the questions", "questions\\QUESTIONS.md"), ("Read the answer key", "questions\\ANSWER-KEY.md")):
            ttk.Button(f, text=t, command=lambda p=p: opn(os.path.join(MT, p))).pack(anchor="w", pady=3)
        ttk.Button(f, text="Copy agent prompt: run training and write the drill plan", command=lambda: self.copy(full("train"))).pack(anchor="w", pady=3)

    def tab_desk(self, f):
        ttk.Label(f, text="Click a folder to open it. Nothing was deleted.", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        g = ttk.Frame(f); g.pack(fill="x", pady=6)
        for i, (n, _d) in enumerate(FOLDERS):
            ttk.Button(g, text=n, width=46, command=lambda n=n: opn(os.path.join(DESK, n))).grid(row=i // 2, column=i % 2, sticky="w", padx=3, pady=2)
        ttk.Label(f, text="Left on the Desktop on purpose: AHK.AHK, MARVIN, scraper output, chat export, VM, NEXEN Deliverables.", wraplength=920).pack(anchor="w", pady=6)
        r = ttk.Frame(f); r.pack(anchor="w")
        ttk.Button(r, text="Open MAP", command=lambda: opn(os.path.join(DESK, "00 START HERE", "MAP.txt"))).pack(side="left", padx=3)
        ttk.Button(r, text="Sort new files", command=lambda: console(f'"{PY}" "{DO}\\organize_desktop.py" apply')).pack(side="left", padx=3)
        ttk.Button(r, text="UNDO the clean-up", command=lambda: messagebox.askyesno("Undo", "Put every file back where it was?") and console(f'"{PY}" "{DO}\\organize_desktop.py" undo ALL')).pack(side="left", padx=3)
        ttk.Button(r, text="Copy prompt: agent sorts new files", command=lambda: self.copy("Run H:\\NEXEN-ENTERPRISE\\Apps\\NEXEN\\companion\\desktop-organizer\\organize_desktop.py plan, review the unsorted list, add known names to EXACT, then apply. Never delete. " + RULES)).pack(side="left", padx=3)
        ttk.Button(r, text="Open CLEAN.pdf", command=lambda: opn(os.path.join(DESK, "CLEAN.pdf"))).pack(side="left", padx=3)

    def tab_status(self, f):
        for title, items in (("DONE", DONE), ("NOT DONE", OPEN)):
            ttk.Label(f, text=title, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(6, 2))
            for i in items: ttk.Label(f, text="  - " + i).pack(anchor="w")
        ttk.Label(f, text="Dated Oct 5 2026 from vault logs. Revenue is $0 verified.", foreground="#666").pack(anchor="w", pady=8)
        r = ttk.Frame(f); r.pack(anchor="w")
        ttk.Button(r, text="Open session log", command=lambda: B.open_target(B.LOG if os.path.exists(B.LOG) else B.LOG_ALT)).pack(side="left", padx=2)
        ttk.Button(r, text="Copy agent prompt: re-verify this status", command=lambda: self.copy("Re-verify each DONE and NOT DONE line in H:\\NEXEN-ENTERPRISE\\Apps\\NEXEN\\companion\\nexen-next\\nexen_next.py against live files, nexen.db (read only) and SESSION-LOG. Update the lists with receipts. " + RULES)).pack(side="left", padx=2)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        s = load(); s["answers"]["Q1"] = "t"; save(s); s["answers"]["Q1"] = ""; save(s)
        ok = all(k in PROMPTS for k, _, _ in STEPS) and "rent" in PROMPTS and "live" in PROMPTS
        print("state ok", len(STEPS), len(QS), "prompts", ok, "live", live_numbers()); print(B.summary_text())
        sys.exit(0 if ok else 1)
    App().mainloop()
