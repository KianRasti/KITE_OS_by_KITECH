-- KITE_OS™ Hyprland Lua Configuration — Built by KITech (https://kian.kitech.info)
-- Target: HP EliteBook Folio 9480m (Haswell ULT + Intel HD 4400) & VMware/QEMU VMs

local mainMod = "SUPER"
local terminal = "sh -c 'command -v foot >/dev/null 2>&1 && exec foot || exec kitty'"
local fileManager = "sh -c 'command -v thunar >/dev/null 2>&1 && exec thunar || exec dolphin'"

-- 1. Core Compositor, Glass Blur (HD 4400 2-pass Dual-Kawase budget) & VFR
hl.config({
    general = {
        gaps_in = 6,
        gaps_out = 10,
        border_size = 1,
        layout = "dwindle",
        resize_on_border = true,
        allow_tearing = false,
        col = {
            active_border = "rgba(FFFFFF59) rgba(38BDF866) 45deg",
            inactive_border = "rgba(FFFFFF22)",
        },
    },
    decoration = {
        rounding = 12,
        active_opacity = 0.92,
        inactive_opacity = 0.85,
        blur = {
            enabled = true,
            size = 6,
            passes = 2,
            new_optimizations = true,
            xray = true,
            ignore_opacity = true,
            noise = 0.0117,
            contrast = 0.95,
            brightness = 1.0,
            vibrancy = 0.1696,
        },
        shadow = {
            enabled = true,
            range = 18,
            render_power = 3,
            color = "rgba(00000044)",
        },
    },
    animations = {
        enabled = true,
    },
    input = {
        kb_layout = "us",
        follow_mouse = 1,
        float_switch_override_focus = 2,
        sensitivity = 0,
        touchpad = {
            natural_scroll = false,
            tap_to_click = true,
            drag_lock = false,
            disable_while_typing = true,
        },
    },
    dwindle = {
        pseudotile = true,
        preserve_split = true,
    },
    master = {
        new_status = "master",
    },
    misc = {
        vfr = true,
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
        force_default_wallpaper = 0,
        background_color = "0x0B1120",
        mouse_move_enables_dpms = true,
        key_press_enables_dpms = true,
        focus_on_activate = true,
    },
})

-- 2. Helper for safe dispatcher binding across Hyprland 0.55+ revisions
local function safe_bind(combo, fn_factory)
    local ok, action = pcall(fn_factory)
    if ok and action ~= nil then
        pcall(hl.bind, combo, action)
    end
end

local function exec_action(cmd)
    return function()
        if hl.dsp and hl.dsp.exec_cmd then
            return hl.dsp.exec_cmd(cmd)
        elseif hl.dsp and hl.dsp.exec then
            return hl.dsp.exec(cmd)
        end
        return nil
    end
end

-- 3. Core KITE_OS Apps & Terminal (foot with kitty fallback)
safe_bind(mainMod .. " + RETURN", exec_action(terminal))
safe_bind(mainMod .. " + Q", exec_action(terminal))
safe_bind(mainMod .. " + T", exec_action(terminal))
safe_bind(mainMod .. " + E", exec_action(fileManager))
safe_bind(mainMod .. " + I", exec_action("kite-settings"))

-- 4. Window & Session Controls
safe_bind("ALT + F4", function() return hl.dsp.window.close() end)
safe_bind(mainMod .. " + C", function() return hl.dsp.window.close() end)
safe_bind(mainMod .. " + F", function() return hl.dsp.window.float({ action = "toggle" }) end)
safe_bind(mainMod .. " + SHIFT + M", function() return hl.dsp.exit() end)

-- 5. Hardware Fn Volume & Brightness Controls (HP Folio 9480m)
safe_bind("XF86AudioRaiseVolume", exec_action("wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+"))
safe_bind("XF86AudioLowerVolume", exec_action("wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%-"))
safe_bind("XF86AudioMute", exec_action("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"))
safe_bind("XF86MonBrightnessUp", exec_action("brightnessctl set 5%+"))
safe_bind("XF86MonBrightnessDown", exec_action("brightnessctl set 5%-"))

-- 6. Workspace Switching (1-4)
for i = 1, 4 do
    safe_bind(mainMod .. " + " .. tostring(i), function()
        if hl.dsp and hl.dsp.workspace and hl.dsp.workspace.switch then
            return hl.dsp.workspace.switch(i)
        end
        return nil
    end)
end

-- 7. Autostart DBus environment & Quickshell Glass UI (complemented by kite-session watchdog)
if hl.on then
    pcall(hl.on, "hyprland.start", function()
        if hl.dispatch then
            local ok, act = pcall(exec_action("dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP"))
            if ok and act then pcall(hl.dispatch, act) end
        end
    end)
end
