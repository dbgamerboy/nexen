// NEXEN.exe: thin shell. Starts the Python engine, opens the app window, keeps the engine alive,
// and restarts it when an update writes restart.flag. All real code lives in engine/ and ui/, so
// updates never need this exe rebuilt.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

static class NexenV4Launcher
{
    const string Home = @"H:\NEXEN-ENTERPRISE";
    static readonly string AppDir = Path.GetDirectoryName(Application.ExecutablePath);
    static readonly string DataDir = Path.Combine(Home, "Data", "V4");
    static readonly string Python = @"H:\NEXEN_RUNTIME\python-recovery\Scripts\pythonw.exe";
    static int Port = 8794;
    static Process Engine;
    static NotifyIcon Tray;
    static volatile bool Quit;
    static readonly System.Collections.Generic.List<DateTime> Restarts = new System.Collections.Generic.List<DateTime>();

    [STAThread]
    static void Main(string[] args)
    {
        bool created;
        using (var mutex = new Mutex(true, "Global\\NEXEN-Launcher", out created))
        {
            if (!created) { OpenWindow(); return; }   // already running: just show the window
            Directory.CreateDirectory(DataDir);
            string envPort = Environment.GetEnvironmentVariable("NEXEN_PORT");
            if (!string.IsNullOrEmpty(envPort)) int.TryParse(envPort, out Port);
            Application.EnableVisualStyles();
            Tray = new NotifyIcon { Icon = SystemIcons.Application, Visible = true, Text = "NEXEN" };
            var menu = new ContextMenuStrip();
            menu.Items.Add("Open NEXEN", null, (s, e) => OpenWindow());
            menu.Items.Add("Restart engine", null, (s, e) => StartEngine(true));
            menu.Items.Add("Open app folder", null, (s, e) => Process.Start("explorer.exe", AppDir));
            menu.Items.Add("Quit (stops engine)", null, (s, e) => { Quit = true; StopEngine(); Tray.Visible = false; Application.Exit(); });
            Tray.ContextMenuStrip = menu;
            Tray.DoubleClick += (s, e) => OpenWindow();

            StartEngine(false);
            var watcher = new Thread(Supervise) { IsBackground = true };
            watcher.Start();
            if (Array.IndexOf(args, "--no-window") < 0) OpenWindow();
            Application.Run();
        }
    }

    static bool Healthy()
    {
        try
        {
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + Port + "/api/health");
            req.Timeout = 2500;
            using (var resp = (HttpWebResponse)req.GetResponse()) return (int)resp.StatusCode == 200;
        }
        catch { return false; }
    }

    static void StartEngine(bool force)
    {
        if (!force && Healthy()) return;      // an engine is already serving (started by someone else)
        StopEngine();
        string py = File.Exists(Python) ? Python : "pythonw.exe";
        var psi = new ProcessStartInfo(py, "-X utf8 \"" + Path.Combine(AppDir, "run.py") + "\" serve --port " + Port)
        {
            WorkingDirectory = AppDir, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
        };
        psi.EnvironmentVariables["NEXEN_APP"] = AppDir;
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try { Engine = Process.Start(psi); }
        catch (Exception ex) { Tray.ShowBalloonTip(5000, "NEXEN", "Could not start engine: " + ex.Message, ToolTipIcon.Error); }
    }

    static void StopEngine()
    {
        try { if (Engine != null && !Engine.HasExited) { Engine.Kill(); Engine.WaitForExit(3000); } } catch { }
        Engine = null;
    }

    static void Supervise()
    {
        string flag = Path.Combine(DataDir, "restart.flag");
        DateTime lastStart = DateTime.Now;
        while (!Quit)
        {
            Thread.Sleep(5000);
            try
            {
                if (File.Exists(flag)) { File.Delete(flag); StartEngine(true); lastStart = DateTime.Now; continue; }
                if ((DateTime.Now - lastStart).TotalSeconds < 25) continue;   // grace period while the engine boots
                if (!Healthy())
                {
                    Restarts.RemoveAll(t => (DateTime.Now - t).TotalMinutes > 10);
                    if (Restarts.Count < 5) { Restarts.Add(DateTime.Now); StartEngine(true); }
                }
            }
            catch { }
        }
    }

    static void OpenWindow()
    {
        string url = "http://127.0.0.1:" + Port + "/";
        for (int i = 0; i < 40 && !Healthy(); i++) Thread.Sleep(750);   // wait up to 30 s for the engine
        string[] edges = {
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe" };
        foreach (var edge in edges)
        {
            if (!File.Exists(edge)) continue;
            Process.Start(edge, "--app=" + url + " --user-data-dir=\"" + Path.Combine(DataDir, "edge-profile") + "\" --no-first-run");
            return;
        }
        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }
}
