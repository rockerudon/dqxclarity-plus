using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using DqxClarity.Launcher.Models;

namespace DqxClarity.Launcher.Services;

public class ProcessService
{
    private const string ChatTranslationPrefix = "DQCX_CHAT_TRANSLATION::";
    private const string OutgoingTranslationPrefix = "DQCX_OUTGOING_TRANSLATION::";
    private Process? _child;
    private Process? _outgoingTranslator;
    private string? _pythonPath;
    private string? _appDir;
    private bool _userStopped;
    private readonly object _lock = new();
    private readonly SemaphoreSlim _outgoingWriteLock = new(1, 1);

    private static readonly Regex AnsiRegex =
        new(@"\x1b\[([0-9;]*)m", RegexOptions.Compiled);

    private static readonly Dictionary<int, string> AnsiColors = new()
    {
        [30] = "#595959", [31] = "#CC0000", [32] = "#4E9A06", [33] = "#C4A000",
        [34] = "#3465A4", [35] = "#75507B", [36] = "#06989A", [37] = "#D3D7CF",
        [90] = "#555753", [91] = "#EF2929", [92] = "#8AE234", [93] = "#FCE94F",
        [94] = "#729FCF", [95] = "#AD7FA8", [96] = "#34E2E2", [97] = "#EEEEEC",
    };

    private static (string PlainText, IReadOnlyList<AnsiRun> Runs) ParseAnsi(string s)
    {
        var runs = new List<AnsiRun>();
        string? currentColor = null;
        int pos = 0;

        foreach (Match m in AnsiRegex.Matches(s))
        {
            if (m.Index > pos)
                runs.Add(new AnsiRun(s[pos..m.Index], currentColor));

            pos = m.Index + m.Length;

            var codes = m.Groups[1].Value;
            if (string.IsNullOrEmpty(codes))
            {
                currentColor = null;
            }
            else
            {
                foreach (var part in codes.Split(';'))
                {
                    if (int.TryParse(part, out int code))
                    {
                        if (code == 0) currentColor = null;
                        else if (AnsiColors.TryGetValue(code, out var hex)) currentColor = hex;
                    }
                }
            }
        }

        if (pos < s.Length)
            runs.Add(new AnsiRun(s[pos..], currentColor));

        var plain = runs.Count > 0 ? string.Concat(runs.Select(r => r.Text)) : s;
        return (plain, runs);
    }

    public event Action<LogLine>? LogLine;
    public event Action<ChatTranslation>? ChatTranslationReceived;
    public event Action<bool>? ProcessExited; // bool = wasError

    private bool TryPublishChatTranslation(string line)
    {
        if (!line.StartsWith(ChatTranslationPrefix, StringComparison.Ordinal))
            return false;

        try
        {
            var chat = JsonSerializer.Deserialize<ChatTranslation>(line[ChatTranslationPrefix.Length..]);
            if (chat != null && (!string.IsNullOrWhiteSpace(chat.Translation)
                                 || !string.IsNullOrWhiteSpace(chat.Source)))
                ChatTranslationReceived?.Invoke(chat);
        }
        catch (JsonException)
        {
            // A malformed internal event should remain visible for diagnosis.
            return false;
        }
        return true;
    }

    private static string ExeDir()
    {
        var exe = Environment.ProcessPath ?? throw new Exception("Cannot determine executable path");
        return Path.GetDirectoryName(exe) ?? throw new Exception("Cannot determine executable directory");
    }

    private static string FindAppDir(string exeDir)
    {
        var dir = exeDir;
        for (int i = 0; i < 4; i++)
        {
            if (File.Exists(Path.Combine(dir, "main.py")))
                return Path.GetFullPath(dir);
            dir = Path.Combine(dir, "..");
        }
        return Path.GetFullPath(Path.Combine(exeDir, ".."));
    }

    private Process CreateOutgoingTranslator()
    {
        string pythonPath;
        string appDir;
        lock (_lock)
        {
            if (string.IsNullOrEmpty(_pythonPath) || string.IsNullOrEmpty(_appDir))
                throw new InvalidOperationException("dqxclarity must be running before chat can be translated.");
            pythonPath = _pythonPath;
            appDir = _appDir;
        }

        var psi = new ProcessStartInfo(pythonPath, "-m chat_translate")
        {
            WorkingDirectory = appDir,
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // Encoding.UTF8 emits a BOM through the redirected StreamWriter.
            // JSON-lines consumers expect the first byte to be `{`.
            StandardInputEncoding = new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        psi.Environment["PYTHONUTF8"] = "1";
        psi.Environment["PYTHONWARNINGS"] = "ignore::UserWarning";
        return new Process { StartInfo = psi };
    }

    public async Task<OutgoingChatTranslation> TranslateOutgoingChatAsync(string text)
    {
        var source = (text ?? "").Trim();
        if (source.Length == 0)
            return new OutgoingChatTranslation { Error = "Type a message first." };

        var id = Guid.NewGuid().ToString("N");
        Process? proc = null;

        await _outgoingWriteLock.WaitAsync();
        try
        {
            proc = CreateOutgoingTranslator();
            lock (_lock)
                _outgoingTranslator = proc;

            proc.Start();
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            var request = JsonSerializer.Serialize(new { Id = id, Text = source });
            await proc.StandardInput.WriteLineAsync(request);
            proc.StandardInput.Close();

            var stdout = await stdoutTask.WaitAsync(TimeSpan.FromSeconds(90));
            await proc.WaitForExitAsync();
            await stderrTask;

            foreach (var rawLine in stdout.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries).Reverse())
            {
                var line = rawLine.TrimStart('\uFEFF');
                if (!line.StartsWith(OutgoingTranslationPrefix, StringComparison.Ordinal))
                    continue;
                var response = JsonSerializer.Deserialize<OutgoingChatTranslation>(
                    line[OutgoingTranslationPrefix.Length..]);
                if (response != null)
                    return response;
            }
            return new OutgoingChatTranslation { Id = id, Error = "The chat translator returned no response." };
        }
        catch (TimeoutException)
        {
            try
            {
                if (proc is { HasExited: false })
                    proc.Kill(entireProcessTree: true);
            }
            catch { }
            return new OutgoingChatTranslation { Id = id, Error = "Chat translation timed out." };
        }
        finally
        {
            lock (_lock)
            {
                if (ReferenceEquals(_outgoingTranslator, proc))
                    _outgoingTranslator = null;
            }
            proc?.Dispose();
            _outgoingWriteLock.Release();
        }
    }

    private void StopOutgoingTranslator()
    {
        Process? proc;
        lock (_lock)
        {
            proc = _outgoingTranslator;
            _outgoingTranslator = null;
        }
        try
        {
            if (proc is { HasExited: false })
                proc.Kill(entireProcessTree: true);
        }
        catch { }
    }

    public void Launch(IEnumerable<string> args)
    {
        var dir = ExeDir();
        var python = Path.Combine(dir, "venv", "Scripts", "python.exe");

        if (!File.Exists(python))
            throw new FileNotFoundException("Python executable not found in venv. Please run setup first.");

        var appDir = FindAppDir(dir);
        var argList = string.Join(" ", args.Select(a => $"\"{a}\""));
        var psi = new ProcessStartInfo(python, $"-m main {argList}")
        {
            WorkingDirectory = appDir,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding  = System.Text.Encoding.UTF8,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        psi.Environment["PYTHONUTF8"] = "1";
        psi.Environment["PYTHONWARNINGS"] = "ignore::UserWarning";

        var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };

        proc.OutputDataReceived += (_, e) =>
        {
            if (e.Data != null)
            {
                if (TryPublishChatTranslation(e.Data))
                    return;
                var (text, runs) = ParseAnsi(e.Data);
                LogLine?.Invoke(new LogLine { Level = "info", Text = text, Runs = runs });
            }
        };
        proc.ErrorDataReceived += (_, e) =>
        {
            if (e.Data != null)
            {
                var (text, runs) = ParseAnsi(e.Data);
                LogLine?.Invoke(new LogLine { Level = "error", Text = text, Runs = runs });
            }
        };
        proc.Exited += (_, _) =>
        {
            bool wasUser;
            lock (_lock)
            {
                _child = null;
                wasUser = _userStopped;
                _userStopped = false;
            }
            StopOutgoingTranslator();
            if (!wasUser)
            {
                LogLine?.Invoke(new LogLine { Level = "info", Text = "-- process exited --" });
                var isError = proc.ExitCode != 0;
                ProcessExited?.Invoke(isError);
            }
        };

        lock (_lock)
        {
            _child = proc;
            _pythonPath = python;
            _appDir = appDir;
            _userStopped = false;
        }

        proc.Start();
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();
    }

    public void Stop()
    {
        Process? proc;
        lock (_lock)
        {
            proc = _child;
            if (proc == null) return;
            _userStopped = true;
        }

        try
        {
            var psi = new ProcessStartInfo("taskkill", $"/PID {proc.Id} /T /F")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
            };
            Process.Start(psi)?.WaitForExit();
        }
        catch { }

        StopOutgoingTranslator();

        ProcessExited?.Invoke(false);
    }

    public bool IsRunning()
    {
        lock (_lock) return _child != null;
    }
}
