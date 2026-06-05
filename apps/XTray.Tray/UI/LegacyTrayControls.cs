using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using XTray.Tray.Backend;
using Button = System.Windows.Controls.Button;
using ButtonBase = System.Windows.Controls.Primitives.ButtonBase;
using Control = System.Windows.Controls.Control;
using Cursors = System.Windows.Input.Cursors;
using FontFamily = System.Windows.Media.FontFamily;
using HorizontalAlignment = System.Windows.HorizontalAlignment;
using MessageBox = System.Windows.MessageBox;
using MouseEventArgs = System.Windows.Input.MouseEventArgs;
using Orientation = System.Windows.Controls.Orientation;
using Point = System.Windows.Point;
using Size = System.Windows.Size;

namespace XTray.Tray.UI;

internal static class LegacyTrayControls
{
    public static TextBlock Text(
        string text,
        TrayThemePalette theme,
        double size = 13,
        FontWeight? weight = null,
        string? color = null
    )
    {
        return new TextBlock
        {
            Text = text,
            FontSize = size,
            FontWeight = weight ?? FontWeights.Normal,
            Foreground = theme.Brush(color ?? theme.Text),
            TextWrapping = TextWrapping.Wrap,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 1, 0, 1),
        };
    }

    public static Button IconButton(
        TrayAction action,
        TrayThemePalette theme,
        TrayIconCache icons,
        Func<Task> handler,
        string? iconColor = null,
        bool enabled = true,
        bool active = false,
        double width = 32,
        double height = 30
    )
    {
        var button = new Button
        {
            Width = width,
            Height = height,
            MinWidth = width,
            MinHeight = height,
            Padding = new Thickness(0),
            ToolTip = action.Label,
            IsEnabled = enabled,
            Cursor = Cursors.Hand,
            Focusable = false,
            Content = icons.Icon(
                action.Icon,
                iconColor ?? theme.AccentText,
                Math.Min(20, Math.Max(16, height - 10)),
                action.FallbackLabel
            ),
        };
        ApplyButtonStyle(
            button,
            theme,
            active ? theme.Accent : theme.AccentPressed,
            theme.AccentText,
            active ? theme.Accent : theme.AccentPressed,
            theme.Accent,
            theme.AccentPressed
        );
        button.Click += async (_, _) => await RunGuardedAsync(handler);
        return button;
    }

    public static Button TextButton(
        string text,
        TrayThemePalette theme,
        Func<Task> handler,
        bool enabled = true,
        string? role = null,
        double minWidth = 76
    )
    {
        var button = new Button
        {
            Content = text,
            IsEnabled = enabled,
            MinWidth = minWidth,
            MinHeight = theme.ControlHeight,
            Padding = new Thickness(10, 4, 10, 4),
            Margin = new Thickness(0),
            Cursor = Cursors.Hand,
            Focusable = false,
        };
        var bg = role switch
        {
            "primary" => theme.Accent,
            "success" => theme.Success,
            "warning" => theme.Warning,
            _ => theme.Control,
        };
        var fg = role switch
        {
            "primary" => theme.AccentText,
            "success" => theme.SuccessText,
            "warning" => theme.WarningText,
            _ => theme.Text,
        };
        ApplyButtonStyle(button, theme, bg, fg, bg, theme.ControlHover, theme.ControlPressed);
        button.Click += async (_, _) => await RunGuardedAsync(handler);
        return button;
    }

    public static Button IconTextButton(
        string text,
        string icon,
        string iconColor,
        TrayThemePalette theme,
        TrayIconCache icons,
        Func<Task> handler,
        bool enabled = true,
        string? role = null
    )
    {
        var stack = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            VerticalAlignment = VerticalAlignment.Center,
        };
        stack.Children.Add(icons.Icon(icon, iconColor, 18, text[..Math.Min(1, text.Length)]));
        stack.Children.Add(new TextBlock
        {
            Text = text,
            Margin = new Thickness(6, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Center,
        });
        var button = TextButton("", theme, handler, enabled, role);
        button.Content = stack;
        return button;
    }

    public static Button Faceplate(
        string title,
        string detail,
        string state,
        string icon,
        TrayThemePalette theme,
        TrayIconCache icons,
        Func<Task> handler,
        bool enabled = true,
        bool compact = false
    )
    {
        var foreground = theme.FaceplateTextFor(state);
        var stack = new StackPanel
        {
            Orientation = Orientation.Vertical,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        };
        if (!string.IsNullOrWhiteSpace(icon))
        {
            stack.Children.Add(icons.Icon(icon, foreground, compact ? 18 : 24, title[..Math.Min(1, title.Length)]));
        }
        stack.Children.Add(new TextBlock
        {
            Text = title,
            TextAlignment = TextAlignment.Center,
            Foreground = theme.Brush(foreground),
            FontWeight = FontWeights.SemiBold,
            FontSize = compact ? 11 : 12,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(2, 2, 2, 0),
        });
        if (!string.IsNullOrWhiteSpace(detail))
        {
            stack.Children.Add(new TextBlock
            {
                Text = detail,
                TextAlignment = TextAlignment.Center,
                Foreground = theme.Brush(foreground),
                FontSize = 11,
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(2, 0, 2, 0),
            });
        }
        var button = new Button
        {
            Content = stack,
            MinHeight = compact ? 56 : 66,
            MinWidth = 84,
            Padding = new Thickness(4),
            IsEnabled = enabled,
            ToolTip = string.IsNullOrWhiteSpace(detail) ? title : $"{title}: {detail}",
            Cursor = Cursors.Hand,
            Focusable = false,
        };
        ApplyButtonStyle(
            button,
            theme,
            theme.FaceplateBackgroundFor(state),
            foreground,
            state == "primary" ? theme.FaceplatePrimaryBorder : theme.FaceplateBackgroundFor(state),
            theme.RowSurfaceHover,
            theme.ControlPressed
        );
        button.Click += async (_, _) => await RunGuardedAsync(handler);
        return button;
    }

    public static Border Row(TrayThemePalette theme, UIElement content)
    {
        return new Border
        {
            Background = theme.Brush(theme.RowSurface),
            BorderBrush = theme.SubtleBorderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(theme.RadiusMedium),
            Padding = new Thickness(8),
            Margin = new Thickness(0, 0, 0, 8),
            Child = content,
        };
    }

    public static UniformGrid FaceplateGrid(int columns)
    {
        return new UniformGrid
        {
            Columns = Math.Max(1, columns),
            Margin = new Thickness(0, 0, 0, 6),
        };
    }

    public static Expander Section(
        string title,
        TrayAction action,
        TrayThemePalette theme,
        TrayIconCache icons,
        bool expanded = true
    )
    {
        var header = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            VerticalAlignment = VerticalAlignment.Center,
        };
        header.Children.Add(icons.Icon(action.Icon, theme.Text, 18, action.FallbackLabel));
        header.Children.Add(new TextBlock
        {
            Text = title,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(6, 0, 0, 0),
            Foreground = theme.TextBrush,
        });
        var expander = new Expander
        {
            Header = header,
            IsExpanded = expanded,
            Margin = new Thickness(0, 0, 0, 8),
            Foreground = theme.TextBrush,
        };
        return expander;
    }

    public static ScrollViewer Scroll(UIElement content)
    {
        return new ScrollViewer
        {
            Content = content,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            Padding = new Thickness(0),
        };
    }

    public static void ApplyButtonStyle(
        Button button,
        TrayThemePalette theme,
        string background,
        string foreground,
        string border,
        string hover,
        string pressed
    )
    {
        var style = new Style(typeof(Button));
        style.Setters.Add(new Setter(Control.BackgroundProperty, theme.Brush(background)));
        style.Setters.Add(new Setter(Control.ForegroundProperty, theme.Brush(foreground)));
        style.Setters.Add(new Setter(Control.BorderBrushProperty, theme.Brush(border)));
        style.Setters.Add(new Setter(Control.BorderThicknessProperty, new Thickness(1)));
        style.Setters.Add(new Setter(Control.FontFamilyProperty, new FontFamily("Segoe UI Variable, Segoe UI")));
        style.Setters.Add(new Setter(Control.FontWeightProperty, FontWeights.SemiBold));
        style.Setters.Add(new Setter(Control.TemplateProperty, ButtonTemplate(theme.RadiusSmall)));
        style.Triggers.Add(new Trigger
        {
            Property = UIElement.IsMouseOverProperty,
            Value = true,
            Setters =
            {
                new Setter(Control.BackgroundProperty, theme.Brush(hover)),
                new Setter(Control.BorderBrushProperty, theme.Brush(hover)),
            },
        });
        style.Triggers.Add(new Trigger
        {
            Property = ButtonBase.IsPressedProperty,
            Value = true,
            Setters =
            {
                new Setter(Control.BackgroundProperty, theme.Brush(pressed)),
                new Setter(Control.BorderBrushProperty, theme.Brush(pressed)),
            },
        });
        style.Triggers.Add(new Trigger
        {
            Property = UIElement.IsEnabledProperty,
            Value = false,
            Setters =
            {
                new Setter(Control.BackgroundProperty, theme.ControlPressedBrush),
                new Setter(Control.BorderBrushProperty, theme.SubtleBorderBrush),
                new Setter(Control.ForegroundProperty, theme.MutedBrush),
            },
        });
        button.Style = style;
    }

    private static ControlTemplate ButtonTemplate(int radius)
    {
        var border = new FrameworkElementFactory(typeof(Border));
        border.SetValue(Border.CornerRadiusProperty, new CornerRadius(radius));
        border.SetBinding(Border.BackgroundProperty, new System.Windows.Data.Binding("Background") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.SetBinding(Border.BorderBrushProperty, new System.Windows.Data.Binding("BorderBrush") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.SetBinding(Border.BorderThicknessProperty, new System.Windows.Data.Binding("BorderThickness") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        var presenter = new FrameworkElementFactory(typeof(ContentPresenter));
        presenter.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center);
        presenter.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
        presenter.SetBinding(FrameworkElement.MarginProperty, new System.Windows.Data.Binding("Padding") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.AppendChild(presenter);
        return new ControlTemplate(typeof(Button)) { VisualTree = border };
    }

    private static async Task RunGuardedAsync(Func<Task> handler)
    {
        try
        {
            await handler();
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "XTray", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }
}

internal sealed class VolumeFillBar : FrameworkElement
{
    private bool _pressed;
    private int _value;

    public event EventHandler<int>? ValueCommitted;

    public int Value
    {
        get => _value;
        set
        {
            var next = Math.Clamp(value, 0, 100);
            if (_value == next)
            {
                return;
            }
            _value = next;
            InvalidateVisual();
        }
    }

    public TrayThemePalette Theme { get; set; } = TrayThemePalette.FromSettings(default);

    protected override Size MeasureOverride(Size availableSize)
    {
        return new Size(Math.Max(72, availableSize.Width), 22);
    }

    protected override void OnRender(DrawingContext drawingContext)
    {
        var rect = new Rect(0, 0, ActualWidth, ActualHeight);
        var radius = ActualHeight / 2;
        drawingContext.DrawRoundedRectangle(Theme.Brush(Theme.SubtleBorder), null, rect, radius, radius);
        var fill = new Rect(0, 0, ActualWidth * Value / 100.0, ActualHeight);
        if (fill.Width > 0)
        {
            drawingContext.DrawRoundedRectangle(
                IsEnabled ? Theme.AccentBrush : Theme.MutedBrush,
                null,
                fill,
                radius,
                radius
            );
        }
    }

    protected override void OnMouseDown(MouseButtonEventArgs e)
    {
        if (!IsEnabled)
        {
            return;
        }
        CaptureMouse();
        _pressed = true;
        SetFromPoint(e.GetPosition(this));
        e.Handled = true;
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        if (_pressed)
        {
            SetFromPoint(e.GetPosition(this));
        }
    }

    protected override void OnMouseUp(MouseButtonEventArgs e)
    {
        if (!_pressed)
        {
            return;
        }
        _pressed = false;
        ReleaseMouseCapture();
        SetFromPoint(e.GetPosition(this));
        ValueCommitted?.Invoke(this, Value);
        e.Handled = true;
    }

    private void SetFromPoint(Point point)
    {
        var width = Math.Max(1, ActualWidth);
        Value = (int)Math.Round(Math.Clamp(point.X / width, 0.0, 1.0) * 100);
    }
}
