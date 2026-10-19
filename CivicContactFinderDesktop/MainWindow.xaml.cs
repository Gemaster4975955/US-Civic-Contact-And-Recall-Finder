using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Windows;

namespace CivicContactFinderDesktop;

public partial class MainWindow : Window
{
    private const string AppUrl = "http://127.0.0.1:5001/";
    private readonly string _repoRoot;
    private readonly string _pythonAppPath;
    private Process? _pythonProcess;

    public MainWindow()
    {
        InitializeComponent();

        var projectDir = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", ".."));
        _repoRoot = Directory.Exists(Path.Combine(projectDir, "civic_contact_finder"))
            ? projectDir
            : Directory.GetParent(projectDir)?.FullName ?? projectDir;

        _pythonAppPath = Path.Combine(_repoRoot, "civic_contact_finder");
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            StatusText.Text = "Preparing the civic directory service…";
            await EnsurePythonAppIsReadyAsync();
            await Browser.EnsureCoreWebView2Async();
            Browser.Source = new Uri(AppUrl);
            StatusText.Text = "U.S. Civic Contact Finder is ready";
        }
        catch (Exception ex)
        {
            StatusText.Text = "The desktop app could not start the civic service.";
            Browser.NavigateToString($"<html><body style='font-family:sans-serif;padding:24px;color:#222'><h1>App startup failed</h1><p>{System.Net.WebUtility.HtmlEncode(ex.Message)}</p><p>Check that Python 3 and the civic_contact_finder requirements are installed and that the local service can start.</p></body></html>");
        }
    }

    private async Task EnsurePythonAppIsReadyAsync()
    {
        var pythonExe = ResolvePythonExecutable();
        if (string.IsNullOrWhiteSpace(pythonExe))
        {
            throw new InvalidOperationException("Python 3 was not found on this machine. Install Python 3 to run the civic finder.");
        }

        await EnsurePythonDependenciesAsync(pythonExe);
        StartPythonApp(pythonExe);
        await WaitForServiceAsync();
    }

    private string ResolvePythonExecutable()
    {
        var localVenvPython = Path.Combine(_pythonAppPath, ".venv", "Scripts", "python.exe");
        if (File.Exists(localVenvPython))
        {
            return localVenvPython;
        }

        foreach (var candidate in new[] { "python", "py", "python3" })
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = candidate,
                    Arguments = "--version",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };

                using var process = Process.Start(psi);
                if (process is null)
                {
                    continue;
                }

                process.WaitForExit(5000);
                if (process.ExitCode == 0)
                {
                    return candidate;
                }
            }
            catch
            {
                // Ignore and continue to the next candidate.
            }
        }

        return string.Empty;
    }

    private async Task EnsurePythonDependenciesAsync(string pythonExecutable)
    {
        var requirementsPath = Path.Combine(_pythonAppPath, "requirements.txt");
        if (!File.Exists(requirementsPath))
        {
            throw new InvalidOperationException("The civic_contact_finder requirements.txt file could not be found.");
        }

        var checkScript = "import flask, requests, waitress; print('ready')";
        var checkProcess = Process.Start(new ProcessStartInfo
        {
            FileName = pythonExecutable,
            Arguments = $"-c \"{checkScript}\"",
            WorkingDirectory = _pythonAppPath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        });

        if (checkProcess is not null)
        {
            var output = await checkProcess.StandardOutput.ReadToEndAsync();
            var error = await checkProcess.StandardError.ReadToEndAsync();
            await checkProcess.WaitForExitAsync();
            if (checkProcess.ExitCode == 0 && output.Contains("ready", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (!string.IsNullOrWhiteSpace(error))
            {
                // continue to install below.
            }
        }

        using var installProcess = Process.Start(new ProcessStartInfo
        {
            FileName = pythonExecutable,
            Arguments = "-m pip install -r requirements.txt",
            WorkingDirectory = _pythonAppPath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        });

        if (installProcess is null)
        {
            throw new InvalidOperationException("Unable to start the Python package installer.");
        }

        var installOutput = await installProcess.StandardOutput.ReadToEndAsync();
        var installErrors = await installProcess.StandardError.ReadToEndAsync();
        await installProcess.WaitForExitAsync();

        if (installProcess.ExitCode != 0)
        {
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(installErrors) ? installOutput.Trim() : installErrors.Trim());
        }
    }

    private void StartPythonApp(string pythonExecutable)
    {
        if (!Directory.Exists(_pythonAppPath))
        {
            throw new InvalidOperationException("The civic_contact_finder app folder was not found.");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonExecutable,
            Arguments = "app.py",
            WorkingDirectory = _pythonAppPath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        _pythonProcess = Process.Start(startInfo);
        if (_pythonProcess is null)
        {
            throw new InvalidOperationException("The civic_contact_finder app could not be started.");
        }
    }

    private async Task WaitForServiceAsync()
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                using var response = await client.GetAsync(AppUrl + "healthz");
                if (response.IsSuccessStatusCode)
                {
                    return;
                }
            }
            catch
            {
                // The Flask service may still be starting.
            }

            await Task.Delay(500);
        }

        throw new TimeoutException("The civic_contact_finder service did not start within 30 seconds.");
    }

    private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
    {
        if (_pythonProcess is not null && !_pythonProcess.HasExited)
        {
            try
            {
                _pythonProcess.Kill(entireProcessTree: true);
                _pythonProcess.WaitForExit(5000);
            }
            catch
            {
                // Ignore shutdown exceptions.
            }
        }
    }
}