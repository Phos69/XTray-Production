using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using WpfBrushes = System.Windows.Media.Brushes;
using WpfPoint = System.Windows.Point;

namespace XTray.Tray.UI;

internal static class TrayWindowChrome
{
    public const string ResizeGripTag = "xtray.resize-grip";
    private const int WmNcHitTest = 0x0084;
    private const int HtClient = 1;
    private const int HtLeft = 10;
    private const int HtRight = 11;
    private const int HtTop = 12;
    private const int HtTopLeft = 13;
    private const int HtTopRight = 14;
    private const int HtBottom = 15;
    private const int HtBottomLeft = 16;
    private const int HtBottomRight = 17;
    private const double ResizeBorder = 8;

    public static void EnableFramelessResize(Window window)
    {
        window.SourceInitialized += (_, _) =>
        {
            if (PresentationSource.FromVisual(window) is HwndSource source)
            {
                source.AddHook((IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled) =>
                {
                    if (msg != WmNcHitTest)
                    {
                        return IntPtr.Zero;
                    }
                    return HandleNcHitTest(window, lParam, ref handled);
                });
            }
        };
    }

    public static UIElement WithResizeGrip(UIElement content)
    {
        var frame = new Grid();
        frame.Children.Add(content);

        var grip = new Canvas
        {
            Width = 18,
            Height = 18,
            Tag = ResizeGripTag,
            HorizontalAlignment = System.Windows.HorizontalAlignment.Right,
            VerticalAlignment = System.Windows.VerticalAlignment.Bottom,
            Cursor = System.Windows.Input.Cursors.SizeNWSE,
            Opacity = 0.75,
            Margin = new Thickness(0, 0, 2, 2),
        };
        grip.Children.Add(GripLine(10, 16, 16, 10));
        grip.Children.Add(GripLine(6, 16, 16, 6));
        grip.Children.Add(GripLine(14, 16, 16, 14));
        System.Windows.Controls.Panel.SetZIndex(grip, 20);
        frame.Children.Add(grip);

        return frame;
    }

    private static IntPtr HandleNcHitTest(Window window, IntPtr lParam, ref bool handled)
    {
        handled = true;
        if (window.ResizeMode == ResizeMode.NoResize || window.WindowState == WindowState.Maximized)
        {
            return new IntPtr(HtClient);
        }

        var point = window.PointFromScreen(new WpfPoint(SignedLoWord(lParam), SignedHiWord(lParam)));
        var width = window.ActualWidth;
        var height = window.ActualHeight;
        if (width <= 0 || height <= 0)
        {
            return new IntPtr(HtClient);
        }

        var left = point.X >= 0 && point.X <= ResizeBorder;
        var right = point.X <= width && point.X >= width - ResizeBorder;
        var top = point.Y >= 0 && point.Y <= ResizeBorder;
        var bottom = point.Y <= height && point.Y >= height - ResizeBorder;

        if (top && left)
        {
            return new IntPtr(HtTopLeft);
        }
        if (top && right)
        {
            return new IntPtr(HtTopRight);
        }
        if (bottom && left)
        {
            return new IntPtr(HtBottomLeft);
        }
        if (bottom && right)
        {
            return new IntPtr(HtBottomRight);
        }
        if (left)
        {
            return new IntPtr(HtLeft);
        }
        if (right)
        {
            return new IntPtr(HtRight);
        }
        if (top)
        {
            return new IntPtr(HtTop);
        }
        if (bottom)
        {
            return new IntPtr(HtBottom);
        }
        return new IntPtr(HtClient);
    }

    private static Line GripLine(double x1, double y1, double x2, double y2) =>
        new()
        {
            X1 = x1,
            Y1 = y1,
            X2 = x2,
            Y2 = y2,
            Stroke = WpfBrushes.Gray,
            StrokeThickness = 1,
            SnapsToDevicePixels = true,
        };

    private static int SignedLoWord(IntPtr value) => unchecked((short)((long)value & 0xffff));

    private static int SignedHiWord(IntPtr value) => unchecked((short)(((long)value >> 16) & 0xffff));
}
