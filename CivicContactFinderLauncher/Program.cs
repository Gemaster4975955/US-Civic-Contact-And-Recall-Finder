using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

class Program
{
    private const string AppUrl = "http://127.0.0.1:5001/";
    static async Task<int> Main(string[] args)
    {
        try
        {
            var repo = LocateRepoRoot();
            var appDir = Path.Combine(repo, "civic_contact_finder");
            if (!Directory.Exists(appDir))
            {
                Console.Error.WriteLine("Could not find civic_contact_finder folder.");
                return 2;
            }

            var python = ResolvePython(appDir);
            if (string.IsNullOrEmpty(python))
            {
                Console.Error.WriteLine("Python 3 not found. Install Python 3 or create .venv in the civic_contact_finder folder.");
                return 3;
            }

            await EnsureDependencies(python, appDir);
            var process = StartPython(python, appDir);
            try
            {
                await WaitForHealthz();
                OpenBrowser(AppUrl);
                Console.WriteLine("Civic Contact Finder is running; press Ctrl+C to stop.");
                await process.WaitForExitAsync();
                return process.ExitCode;
            }
            finally
            {
                if (!process.HasExited)
                {
                    try { process.Kill(entireProcessTree: true); } catch { }
                }
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }

    static string LocateRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        // Walk up to find civic_contact_finder
        var current = new DirectoryInfo(dir);
        for (int i = 0; i < 6 && current != null; i++)
        {
            var candidate = Path.Combine(current.FullName, "civic_contact_finder");
            if (Directory.Exists(candidate)) return current.FullName;
            current = current.Parent;
        }
        // fallback to base dir
        return Directory.GetCurrentDirectory();
    }

    static string ResolvePython(string appDir)
    {
        // Prefer a bundled python directory next to the launcher: ./python/python.exe (Windows) or ./python/bin/python (Unix)
        var repo = Directory.GetParent(appDir)?.FullName ?? AppContext.BaseDirectory;
        var bundledWindows = Path.Combine(AppContext.BaseDirectory, "python", "python.exe");
        var bundledUnix = Path.Combine(AppContext.BaseDirectory, "python", "bin", "python");
        if (File.Exists(bundledWindows)) return bundledWindows;
        if (File.Exists(bundledUnix)) return bundledUnix;

        // Also check a top-level python/ next to the repo root (for portable distributions)
        var repoBundledWin = Path.Combine(repo, "python", "python.exe");
        var repoBundledUnix = Path.Combine(repo, "python", "bin", "python");
        if (File.Exists(repoBundledWin)) return repoBundledWin;
        if (File.Exists(repoBundledUnix)) return repoBundledUnix;

        // Fallback to a local virtualenv inside the app directory
        var venv = Path.Combine(appDir, ".venv", RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "Scripts" : "bin", RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "python.exe" : "python");
        if (File.Exists(venv)) return venv;

        // Finally probe the system PATH for python executables
        foreach (var name in new[] { "python", "python3", "py" })
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = name,
                    Arguments = "--version",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                using var p = Process.Start(psi);
                if (p == null) continue;
                p.WaitForExit(3000);
                if (p.ExitCode == 0) return name;
            }
            catch { }
        }
        return string.Empty;
    }

    static async Task EnsureDependencies(string python, string appDir)
    {
        var req = Path.Combine(appDir, "requirements.txt");
        if (!File.Exists(req)) return;
        // Quick check: try to import flask
        var check = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-c \"import flask, requests, waitress; print('ready')\"",
            WorkingDirectory = appDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        try
        {
            using var p = Process.Start(check);
            if (p != null)
            {
                var outp = await p.StandardOutput.ReadToEndAsync();
                var err = await p.StandardError.ReadToEndAsync();
                await p.WaitForExitAsync();
                if (p.ExitCode == 0 && outp.IndexOf("ready", StringComparison.OrdinalIgnoreCase) >= 0) return;
            }
        }
        catch { }

        Console.WriteLine("Installing Python dependencies (pip install -r requirements.txt)...");
        var install = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-m pip install -r requirements.txt",
            WorkingDirectory = appDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        using var ip = Process.Start(install);
        if (ip == null) throw new InvalidOperationException("Could not start pip installer.");
        var so = await ip.StandardOutput.ReadToEndAsync();
        var se = await ip.StandardError.ReadToEndAsync();
        await ip.WaitForExitAsync();
        if (ip.ExitCode != 0) throw new InvalidOperationException(se.Length > 0 ? se : so);
    }

    static Process StartPython(string python, string appDir)
    {
        var start = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "app.py",
            WorkingDirectory = appDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        var p = Process.Start(start) ?? throw new InvalidOperationException("Failed to start python process.");
        _ = Task.Run(async () =>
        {
            try
            {
                await foreach (var line in ReadLinesAsync(p))
                {
                    Console.WriteLine(line);
                }
            }
            catch { }
        });
        return p;
    }

    static async IAsyncEnumerable<string> ReadLinesAsync(Process process)
    {
        var sr = process.StandardOutput;
        string? line;
        while ((line = await sr.ReadLineAsync()) is not null)
        {
            yield return line;
        }
    }

    static async Task WaitForHealthz()
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                using var r = await client.GetAsync(AppUrl + "healthz");
                if (r.IsSuccessStatusCode) return;
            }
            catch { }
            await Task.Delay(500);
        }
        throw new TimeoutException("Service did not start in time.");
    }

    static void OpenBrowser(string url)
    {
        try
        {
            if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            {
                Process.Start(new ProcessStartInfo("cmd", $"/c start {url}") { CreateNoWindow = true });
            }
            else if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
            {
                Process.Start("xdg-open", url);
            }
            else if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            {
                Process.Start("open", url);
            }
            else
            {
                Console.WriteLine("Open this URL in your browser: " + url);
            }
        }
        catch
        {
            Console.WriteLine("Open this URL in your browser: " + url);
        }
    }
}
