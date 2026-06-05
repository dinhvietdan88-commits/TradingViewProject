
# real_mouse_edit_alerts.ps1
# Dùng mouse thực để hover và click edit trên TradingView alerts
# Cần chạy với màn hình hiển thị TradingView

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class MouseHelper {
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, int dx, int dy, uint cButtons, uint dwExtraInfo);
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    public const uint MOUSEEVENTF_RIGHTUP = 0x0010;
    public static void Click(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(100);
        mouse_event(MOUSEEVENTF_LEFTDOWN, x, y, 0, 0);
        System.Threading.Thread.Sleep(50);
        mouse_event(MOUSEEVENTF_LEFTUP, x, y, 0, 0);
    }
    public static void RightClick(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(100);
        mouse_event(MOUSEEVENTF_RIGHTDOWN, x, y, 0, 0);
        System.Threading.Thread.Sleep(50);
        mouse_event(MOUSEEVENTF_RIGHTUP, x, y, 0, 0);
    }
    public static void Move(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(50);
    }
}
"@

function Sleep-Ms($ms) { Start-Sleep -Milliseconds $ms }

Write-Host "TradingView Alert Real Mouse Editor" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT: Do NOT move your mouse while this script runs!" -ForegroundColor Yellow
Write-Host "Starting in 3 seconds..." -ForegroundColor Yellow
Sleep-Ms 3000

# Screen coordinates (from TradingView Desktop window)
# Alerts panel is at right side of screen
# Row positions based on CDP measurements:
# - Panel starts at approximately screen X=1026
# - The "..." (more) button or click area is at right side of each row

# Alert rows Y positions (screen coordinates, adjust if window moved):
$alertRows = @(
    @{ Name = "Test3: A.007 + MIS v1 Combined";      RowY = 167; AlertId = 4800272820 },
    @{ Name = "Test02: A.007 + MIS v2 Combined";     RowY = 243; AlertId = 4800248169 },
    @{ Name = "Test01: A.007 strategy (Order Filler)"; RowY = 319; AlertId = 4800166430 }
)

# Alert panel right area X coordinates (where edit icons appear on hover)
$panelCenterX = 990  # Center of alert row text area
$editIconX    = 1140 # Where the edit/settings icon appears on hover

foreach ($alert in $alertRows) {
    Write-Host ""
    Write-Host "Processing: $($alert.Name)" -ForegroundColor Green

    # Step 1: Hover over the alert row to reveal buttons
    Write-Host "  Hovering at ($panelCenterX, $($alert.RowY))..." -ForegroundColor Gray
    [MouseHelper]::Move($panelCenterX, $alert.RowY)
    Sleep-Ms 600

    # Move slowly to the right to trigger hover state
    for ($x = $panelCenterX; $x -le $editIconX; $x += 10) {
        [MouseHelper]::Move($x, $alert.RowY)
        Sleep-Ms 30
    }
    Sleep-Ms 400

    # Step 2: Click the row's settings/edit button (right side)
    Write-Host "  Clicking edit icon at ($editIconX, $($alert.RowY))..." -ForegroundColor Gray
    [MouseHelper]::Click($editIconX, $alert.RowY)
    Sleep-Ms 1500

    # Check if dialog opened (take screenshot via CDP won't work here,
    # so just wait and proceed assuming it opened)
    Write-Host "  Dialog should be open now. Waiting..." -ForegroundColor Gray
    Sleep-Ms 500

    Write-Host "  Alert $($alert.Name) - manual step complete" -ForegroundColor Green
}

Write-Host ""
Write-Host "Script complete. Check TradingView for open dialogs." -ForegroundColor Cyan
