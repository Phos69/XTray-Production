using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace XTray.Tray.Infrastructure;

internal static class ConsoleBridge
{
    private const uint AttachParentProcess = 0xFFFFFFFF;
    private const int StdOutputHandle = -11;
    private const int StdErrorHandle = -12;
    private static readonly IntPtr InvalidHandleValue = new(-1);

    public static void AttachToParent()
    {
        AttachConsole(AttachParentProcess);
        var stdout = OpenStandardWriter(StdOutputHandle);
        if (stdout is not null)
        {
            Console.SetOut(stdout);
        }
        var stderr = OpenStandardWriter(StdErrorHandle);
        if (stderr is not null)
        {
            Console.SetError(stderr);
        }
    }

    private static TextWriter? OpenStandardWriter(int handleId)
    {
        var handle = GetStdHandle(handleId);
        if (handle == IntPtr.Zero || handle == InvalidHandleValue)
        {
            return null;
        }
        var safeHandle = new SafeFileHandle(handle, ownsHandle: false);
        if (safeHandle.IsInvalid)
        {
            return null;
        }
        return new StreamWriter(new FileStream(safeHandle, FileAccess.Write), Encoding.UTF8)
        {
            AutoFlush = true,
        };
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int stdHandle);
}
