using System.Runtime.InteropServices;
using System.Windows.Input;
using System.Windows.Threading;

namespace XTray.Tray.Infrastructure;

internal sealed class GlobalHotkeyPoller : IDisposable
{
    private readonly DispatcherTimer _timer;
    private readonly Action _onPressed;
    private HotkeyDefinition? _definition;
    private bool _wasPressed;

    public GlobalHotkeyPoller(Action onPressed)
    {
        _onPressed = onPressed;
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(90) };
        _timer.Tick += (_, _) => Poll();
        _timer.Start();
    }

    public void Update(bool enabled, string sequence)
    {
        _definition = enabled ? HotkeyDefinition.Parse(sequence) : null;
        _wasPressed = false;
    }

    private void Poll()
    {
        if (_definition is null)
        {
            return;
        }
        var pressed = _definition.IsPressed();
        if (pressed && !_wasPressed)
        {
            _onPressed();
        }
        _wasPressed = pressed;
    }

    public void Dispose()
    {
        _timer.Stop();
    }

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int virtualKey);

    private sealed class HotkeyDefinition
    {
        private HotkeyDefinition(bool ctrl, bool alt, bool shift, bool win, int key)
        {
            Ctrl = ctrl;
            Alt = alt;
            Shift = shift;
            Win = win;
            Key = key;
        }

        private bool Ctrl { get; }

        private bool Alt { get; }

        private bool Shift { get; }

        private bool Win { get; }

        private int Key { get; }

        public static HotkeyDefinition? Parse(string sequence)
        {
            if (string.IsNullOrWhiteSpace(sequence))
            {
                return null;
            }

            var ctrl = false;
            var alt = false;
            var shift = false;
            var win = false;
            int? key = null;
            foreach (var rawPart in sequence.Split('+', StringSplitOptions.RemoveEmptyEntries))
            {
                var part = rawPart.Trim();
                switch (part.ToLowerInvariant())
                {
                    case "ctrl":
                    case "control":
                        ctrl = true;
                        break;
                    case "alt":
                        alt = true;
                        break;
                    case "shift":
                        shift = true;
                        break;
                    case "win":
                    case "windows":
                    case "super":
                        win = true;
                        break;
                    default:
                        key = VirtualKeyFromText(part);
                        break;
                }
            }

            return key is null ? null : new HotkeyDefinition(ctrl, alt, shift, win, key.Value);
        }

        public bool IsPressed()
        {
            return (!Ctrl || Down(0x11))
                && (!Alt || Down(0x12))
                && (!Shift || Down(0x10))
                && (!Win || Down(0x5B) || Down(0x5C))
                && Down(Key);
        }

        private static int? VirtualKeyFromText(string text)
        {
            if (text.Length == 1)
            {
                var ch = char.ToUpperInvariant(text[0]);
                if (ch is >= 'A' and <= 'Z')
                {
                    return ch;
                }
                if (ch is >= '0' and <= '9')
                {
                    return ch;
                }
            }
            if (Enum.TryParse<Key>(text, ignoreCase: true, out var key))
            {
                return KeyInterop.VirtualKeyFromKey(key);
            }
            if (
                text.StartsWith("F", StringComparison.OrdinalIgnoreCase)
                && int.TryParse(text[1..], out var functionKey)
                && functionKey is >= 1 and <= 24
            )
            {
                return 0x70 + functionKey - 1;
            }
            return null;
        }

        private static bool Down(int virtualKey)
        {
            return (GetAsyncKeyState(virtualKey) & 0x8000) != 0;
        }
    }
}
