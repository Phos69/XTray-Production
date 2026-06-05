using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace XTray.Tray.Backend;

internal sealed class JsonRpcClient : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> _pending = new();
    private Process? _process;
    private StreamWriter? _stdin;
    private Task? _stdoutTask;
    private Task? _stderrTask;
    private bool _disposed;

    public JsonRpcClient()
    {
        Start();
    }

    public bool IsRunning => _process is { HasExited: false };

    public async Task<JsonElement> CallAsync(
        string method,
        object? parameters = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default
    )
    {
        ThrowIfDisposed();
        if (!IsRunning)
        {
            await RestartAsync(cancellationToken);
        }

        var id = Guid.NewGuid().ToString("N");
        var completion = new TaskCompletionSource<JsonElement>(
            TaskCreationOptions.RunContinuationsAsynchronously
        );
        if (!_pending.TryAdd(id, completion))
        {
            throw new InvalidOperationException("Could not register JSON-RPC request.");
        }

        var payload = JsonSerializer.Serialize(
            new RpcRequest(id, method, parameters ?? new Dictionary<string, object>()),
            JsonOptions
        );

        try
        {
            await _writeLock.WaitAsync(cancellationToken);
            try
            {
                if (_stdin is null)
                {
                    throw new InvalidOperationException("The XTray backend is not writable.");
                }
                await _stdin.WriteLineAsync(payload.AsMemory(), cancellationToken);
                await _stdin.FlushAsync(cancellationToken);
            }
            finally
            {
                _writeLock.Release();
            }

            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken
            );
            timeoutCts.CancelAfter(timeout ?? TimeSpan.FromSeconds(20));
            return await completion.Task.WaitAsync(timeoutCts.Token);
        }
        catch
        {
            _pending.TryRemove(id, out _);
            throw;
        }
    }

    public async Task<T?> CallAsync<T>(
        string method,
        object? parameters = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default
    )
    {
        var element = await CallAsync(method, parameters, timeout, cancellationToken);
        if (typeof(T) == typeof(JsonElement))
        {
            return (T)(object)element;
        }
        return element.Deserialize<T>(JsonOptions);
    }

    public async Task RestartAsync(CancellationToken cancellationToken = default)
    {
        Stop();
        Start();
        await CallAsync(
            "app.health",
            timeout: TimeSpan.FromSeconds(10),
            cancellationToken: cancellationToken
        );
    }

    private void Start()
    {
        var command = BackendLocator.ResolveJsonRpc();
        _process = BackendLocator.StartProcess(command, redirect: true);
        _stdin = _process.StandardInput;
        _stdin.AutoFlush = true;
        _stdoutTask = Task.Run(() => ReadStdoutAsync(_process));
        _stderrTask = Task.Run(() => ReadStderrAsync(_process));
    }

    private async Task ReadStdoutAsync(Process process)
    {
        try
        {
            while (!process.HasExited)
            {
                var line = await process.StandardOutput.ReadLineAsync();
                if (line is null)
                {
                    break;
                }
                HandleResponse(line);
            }
        }
        catch (Exception ex)
        {
            FailPending(ex);
        }
        finally
        {
            FailPending(new InvalidOperationException("The XTray backend stopped."));
        }
    }

    private async Task ReadStderrAsync(Process process)
    {
        try
        {
            while (!process.HasExited)
            {
                var line = await process.StandardError.ReadLineAsync();
                if (line is null)
                {
                    break;
                }
                Debug.WriteLine("[XTray.Backend] " + line);
            }
        }
        catch
        {
            // Stderr is diagnostic-only.
        }
    }

    private void HandleResponse(string line)
    {
        RpcResponse? response;
        try
        {
            response = JsonSerializer.Deserialize<RpcResponse>(line, JsonOptions);
        }
        catch (JsonException ex)
        {
            FailPending(ex);
            return;
        }

        if (response?.Id is null)
        {
            return;
        }
        if (!_pending.TryRemove(response.Id, out var completion))
        {
            return;
        }
        if (!response.Ok)
        {
            completion.TrySetException(
                new InvalidOperationException(response.Error?.Message ?? "Backend error")
            );
            return;
        }
        completion.TrySetResult(response.Result.Clone());
    }

    private void FailPending(Exception exception)
    {
        foreach (var id in _pending.Keys)
        {
            if (_pending.TryRemove(id, out var completion))
            {
                completion.TrySetException(exception);
            }
        }
    }

    private void Stop()
    {
        try
        {
            _stdin?.Dispose();
        }
        catch
        {
        }
        try
        {
            if (_process is { HasExited: false })
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
        try
        {
            _process?.Dispose();
        }
        catch
        {
        }
        _stdin = null;
        _process = null;
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(JsonRpcClient));
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        Stop();
        _writeLock.Dispose();
    }

    private sealed record RpcRequest(
        [property: JsonPropertyName("id")] string Id,
        [property: JsonPropertyName("method")] string Method,
        [property: JsonPropertyName("params")] object Params
    );

    private sealed class RpcResponse
    {
        [JsonPropertyName("id")]
        public string? Id { get; set; }

        [JsonPropertyName("ok")]
        public bool Ok { get; set; }

        [JsonPropertyName("result")]
        public JsonElement Result { get; set; }

        [JsonPropertyName("error")]
        public RpcError? Error { get; set; }
    }

    private sealed class RpcError
    {
        [JsonPropertyName("message")]
        public string? Message { get; set; }
    }
}
