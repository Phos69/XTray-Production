using System.Threading;

namespace XTray.Tray.Infrastructure;

internal sealed class SingleInstanceGuard : IDisposable
{
    private readonly Mutex _mutex = new(false, @"Local\XTray.NativeTray");
    private bool _hasHandle;

    public bool TryAcquire()
    {
        try
        {
            _hasHandle = _mutex.WaitOne(TimeSpan.Zero, false);
            return _hasHandle;
        }
        catch (AbandonedMutexException)
        {
            _hasHandle = true;
            return true;
        }
    }

    public void Dispose()
    {
        if (_hasHandle)
        {
            _mutex.ReleaseMutex();
            _hasHandle = false;
        }
        _mutex.Dispose();
    }
}
