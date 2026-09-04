using System.Runtime.InteropServices;
using System.Text;

namespace DqxClarity.Launcher.Services;

public sealed class GameChatInputService
{
    public const int MaxChars = 40;

    private const int SwRestore = 9;
    private const uint AsfwAny = uint.MaxValue;
    private const int GwlExstyle = -20;
    private const int WsExToolwindow = 0x00000080;
    private const uint InputKeyboard = 1;
    private const uint KeyeventfKeyup = 0x0002;
    private const ushort VkControl = 0x11;
    private const ushort VkV = 0x56;

    public bool ActivateAndPaste(int pid, out string error)
    {
        error = "DQX window was not found.";
        var window = FindBestTopLevelWindowForPid(pid);
        if (window == IntPtr.Zero)
            return false;
        if (IsIconic(window))
            ShowWindow(window, SwRestore);

        AllowSetForegroundWindow(AsfwAny);
        BringWindowToTop(window);
        SetForegroundWindow(window);
        Thread.Sleep(75);
        if (GetForegroundWindow() != window)
        {
            error = "Windows did not allow focusing DQX. No input was sent.";
            return false;
        }
        var inputs = new[]
        {
            KeyInput(VkControl, false),
            KeyInput(VkV, false),
            KeyInput(VkV, true),
            KeyInput(VkControl, true),
        };
        var sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<INPUT>());
        if (sent != inputs.Length)
        {
            var code = Marshal.GetLastWin32Error();
            // Release keys if Windows accepted only part of the sequence.
            if (sent > 0)
                SendInput(2, [KeyInput(VkV, true), KeyInput(VkControl, true)], Marshal.SizeOf<INPUT>());
            error = $"Windows rejected the input ({sent}/4 events, error {code}). Check that DQX and dqxclarity use the same administrator level.";
            return false;
        }
        error = "";
        return true;
    }

    private static INPUT KeyInput(ushort key, bool keyUp) => new()
    {
        type = InputKeyboard,
        U = new INPUTUNION
        {
            ki = new KEYBDINPUT
            {
                wVk = key,
                dwFlags = keyUp ? KeyeventfKeyup : 0,
            },
        },
    };

    private static IntPtr FindBestTopLevelWindowForPid(int pid)
    {
        var best = IntPtr.Zero;
        long bestScore = long.MinValue;
        EnumWindows((window, _) =>
        {
            if (!IsWindowVisible(window))
                return true;
            GetWindowThreadProcessId(window, out var windowPid);
            if (windowPid != pid || IsToolWindow(window) || !GetWindowRect(window, out var rect))
                return true;

            var area = (long)Math.Max(0, rect.Right - rect.Left) * Math.Max(0, rect.Bottom - rect.Top);
            if (area <= 0)
                return true;
            var className = GetClassName(window);
            var score = area + (GetWindowTextLength(window) > 0 ? 5_000_000 : 0);
            if (className.Contains("IME", StringComparison.OrdinalIgnoreCase))
                score -= 50_000_000;
            if (score > bestScore)
            {
                bestScore = score;
                best = window;
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }

    private static bool IsToolWindow(IntPtr window) =>
        ((uint)GetWindowLongPtr(window, GwlExstyle).ToInt64() & WsExToolwindow) != 0;

    private static string GetClassName(IntPtr window)
    {
        var name = new StringBuilder(256);
        GetClassNameW(window, name, name.Capacity);
        return name.ToString();
    }

    private delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);

    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] private static extern bool AllowSetForegroundWindow(uint processId);
    [DllImport("user32.dll")] private static extern bool BringWindowToTop(IntPtr window);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out int processId);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextLength(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassNameW(IntPtr window, StringBuilder name, int maxCount);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetWindowLongPtr(IntPtr window, int index);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint count, INPUT[] inputs, int size);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT { public uint type; public INPUTUNION U; }

    [StructLayout(LayoutKind.Explicit)]
    private struct INPUTUNION
    {
        [FieldOffset(0)] public KEYBDINPUT ki;
        // INPUT's union must include its largest member even for keyboard-only
        // calls: otherwise cbSize is 32 instead of 40 on x64 and SendInput fails.
        [FieldOffset(0)] public MOUSEINPUT mi;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MOUSEINPUT
    {
        public int dx, dy;
        public uint mouseData, dwFlags, time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }
}
