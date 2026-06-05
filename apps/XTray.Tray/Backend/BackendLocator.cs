using System.Diagnostics;
using System.IO;
using System.Text;

namespace XTray.Tray.Backend;

internal sealed record BackendCommand(
    string FileName,
    string Arguments,
    string WorkingDirectory,
    IReadOnlyDictionary<string, string> Environment
);

internal static class BackendLocator
{
    private const string BackendExeName = "XTray.Backend.exe";

    public static BackendCommand ResolveJsonRpc()
    {
        return Resolve("--jsonrpc");
    }

    public static int RunCli(string[] args)
    {
        var command = Resolve(QuoteArguments(args));
        using var process = StartCliProcess(command);
        var stdoutTask = ForwardAsync(process.StandardOutput, Console.Out);
        var stderrTask = ForwardAsync(process.StandardError, Console.Error);
        process.WaitForExit();
        Task.WaitAll(new[] { stdoutTask, stderrTask }, TimeSpan.FromSeconds(5));
        return process.ExitCode;
    }

    public static Process StartProcess(BackendCommand command, bool redirect)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = command.FileName,
            Arguments = command.Arguments,
            WorkingDirectory = command.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = redirect,
            RedirectStandardOutput = redirect,
            RedirectStandardError = redirect,
        };
        foreach (var (key, value) in command.Environment)
        {
            startInfo.Environment[key] = value;
        }

        return Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start the XTray backend.");
    }

    private static Process StartCliProcess(BackendCommand command)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = command.FileName,
            Arguments = command.Arguments,
            WorkingDirectory = command.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var (key, value) in command.Environment)
        {
            startInfo.Environment[key] = value;
        }

        return Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start the XTray backend.");
    }

    private static async Task ForwardAsync(TextReader reader, TextWriter writer)
    {
        try
        {
            var buffer = new char[4096];
            int count;
            while ((count = await reader.ReadAsync(buffer, 0, buffer.Length)) > 0)
            {
                await writer.WriteAsync(buffer.AsMemory(0, count));
                await writer.FlushAsync();
            }
        }
        catch
        {
            // Console forwarding is best-effort for silent installer tasks.
        }
    }

    private static BackendCommand Resolve(string arguments)
    {
        var baseDir = AppContext.BaseDirectory;
        var envBackend = Environment.GetEnvironmentVariable("XTRAY_BACKEND_EXE");
        if (!string.IsNullOrWhiteSpace(envBackend) && File.Exists(envBackend))
        {
            return new BackendCommand(
                envBackend,
                arguments,
                Path.GetDirectoryName(envBackend) ?? baseDir,
                new Dictionary<string, string>()
            );
        }

        var bundled = Path.Combine(baseDir, BackendExeName);
        if (File.Exists(bundled))
        {
            return new BackendCommand(
                bundled,
                arguments,
                baseDir,
                new Dictionary<string, string>()
            );
        }

        var repoRoot = FindRepoRoot(baseDir);
        if (repoRoot is not null)
        {
            var python = ResolvePython(repoRoot);
            var pythonArgs = $"-m xtray.backend_jsonrpc {arguments}".TrimEnd();
            return new BackendCommand(
                python,
                pythonArgs,
                repoRoot,
                PythonEnvironment(repoRoot)
            );
        }

        throw new FileNotFoundException(
            $"Could not find {BackendExeName}. Set XTRAY_BACKEND_EXE to the backend path."
        );
    }

    private static string? FindRepoRoot(string start)
    {
        var directory = new DirectoryInfo(start);
        while (directory is not null)
        {
            var candidate = Path.Combine(
                directory.FullName,
                "packages",
                "xtray",
                "xtray",
                "backend_jsonrpc.py"
            );
            if (File.Exists(candidate))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        return null;
    }

    private static string ResolvePython(string repoRoot)
    {
        var envPython = Environment.GetEnvironmentVariable("XTRAY_PYTHON");
        if (!string.IsNullOrWhiteSpace(envPython) && File.Exists(envPython))
        {
            return envPython;
        }

        var venvPython = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        if (File.Exists(venvPython))
        {
            return venvPython;
        }

        return "py.exe";
    }

    private static Dictionary<string, string> PythonEnvironment(string repoRoot)
    {
        var packageRoots = new[]
        {
            Path.Combine(repoRoot, "packages", "xtray"),
            Path.Combine(repoRoot, "packages", "computer_manager"),
            Path.Combine(repoRoot, "packages", "network_manager"),
            Path.Combine(repoRoot, "packages", "xtray_sync"),
        };
        var existingPythonPath = Environment.GetEnvironmentVariable("PYTHONPATH");
        var pythonPath = string.Join(Path.PathSeparator, packageRoots);
        if (!string.IsNullOrWhiteSpace(existingPythonPath))
        {
            pythonPath = pythonPath + Path.PathSeparator + existingPythonPath;
        }
        return new Dictionary<string, string> { ["PYTHONPATH"] = pythonPath };
    }

    private static string QuoteArguments(IEnumerable<string> args)
    {
        return string.Join(" ", args.Select(QuoteArgument));
    }

    private static string QuoteArgument(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "\"\"";
        }
        if (!value.Any(char.IsWhiteSpace) && !value.Contains('"'))
        {
            return value;
        }

        var builder = new StringBuilder();
        builder.Append('"');
        var backslashes = 0;
        foreach (var ch in value)
        {
            if (ch == '\\')
            {
                backslashes++;
                continue;
            }
            if (ch == '"')
            {
                builder.Append('\\', backslashes * 2 + 1);
                builder.Append(ch);
                backslashes = 0;
                continue;
            }
            builder.Append('\\', backslashes);
            builder.Append(ch);
            backslashes = 0;
        }
        builder.Append('\\', backslashes * 2);
        builder.Append('"');
        return builder.ToString();
    }
}
