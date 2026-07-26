# JARVIS Desktop UI — Complete Implementation Specification

> **Source of Truth:** Official JARVIS Desktop UI Reference (IMAGE B)
> **Status:** v1.0 — Reverse Engineered from Reference
> **Author:** Design Analysis Team
> **Target Platform:** PySide6 / Qt6 / QML Desktop Application
> **Resolution Base:** 1920 × 1080 (16:9)

---

## Table of Contents

1. [Layout Hierarchy](#1-layout-hierarchy)
2. [Grid System](#2-grid-system)
3. [Panel Dimensions](#3-panel-dimensions)
4. [Sidebar Specification](#4-sidebar-specification)
5. [AI Core Specification](#5-ai-core-specification)
6. [Right Panel Specification](#6-right-panel-specification)
7. [Bottom Section Specification](#7-bottom-section-specification)
8. [Top Bar Specification](#8-top-bar-specification)
9. [Padding & Margins](#9-padding--margins)
10. [Border Radius](#10-border-radius)
11. [Glassmorphism Settings](#11-glassmorphism-settings)
12. [Shadow & Glow Settings](#12-shadow--glow-settings)
13. [Particle System Specification](#13-particle-system-specification)
14. [Ring Construction](#14-ring-construction)
15. [Typography](#15-typography)
16. [Color Palette](#16-color-palette)
17. [Animation Specification](#17-animation-specification)
18. [Component Hierarchy & Z-Index](#18-component-hierarchy--z-index)
19. [Window Behavior](#19-window-behavior)
20. [Responsive Behavior](#20-responsive-behavior)
21. [Icon System](#21-icon-system)
22. [Implementation Checklist](#22-implementation-checklist)

---

## 1. Layout Hierarchy

```
┌─────────────────────────────────────────────────────────────────────┐
│  TOP BAR (28px)           ┌──────────────────┐  ┌───────────────┐  │
│  Clock | Date             │   WINDOW CTLS   │  │  −  □  ✕      │  │
├──────┬───────────────────────────────────────────┬────────────────┤
│      │                                           │                │
│      │                                           │   ┌────────┐  │
│      │         CENTER AREA                       │   │CORE    │  │
│ LEFT │         ┌──────────────────────┐          │   │STATE   │  │
│ SIDE │         │    PARTICLE FIELD    │          │ R │        │  │
│ BAR  │         │                      │          │ I │┌──────┐│  │
│      │         │    ┌──────────┐      │          │ G ││CPU   ││  │
│ 200px│         │    │  AI CORE  │      │          │ H ││RAM   ││  │
│      │         │    │ (rotating)│      │          │ T ││GPU   ││  │
│      │         │    └──────────┘      │          │   │└──────┘│  │
│      │         │    Mode Label        │          │ P │        │  │
│      │         │    Voice Waveform    │          │ A │┌──────┐│  │
│      │         │    Subtitle Panel    │          │ N ││TASK  ││  │
│      │         │                      │          │ E │└──────┘│  │
│      │         └──────────────────────┘          │ L │        │  │
│      │                                           │   │        │  │
│      │                                           │   └────────┘  │
├──────┴───────────────────────────────────────────┴────────────────┤
│  BOTTOM SECTION (64px)                                            │
│  [Preview Cards ← → Voice Waveform Mini]                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Layout Regions (Proportions)

| Region | Width % | Height % | Description |
|--------|---------|----------|-------------|
| Top Bar | 100% | 2.6% | Clock, date, window controls |
| Left Sidebar | 10.4% | 91.5% | Branding, navigation, status |
| Center Area | 65.6% | 91.5% | AI Core, particles, waveform, subtitle |
| Right Panel | 12.5% | 91.5% | Core state, status cards, task |
| Bottom Section | 100% | 5.9% | Preview cards, voice mini |
| Left Border Divider | 1px | — | Orange accent between sidebar + center |
| Right Border Divider | 1px | — | Orange accent between center + right panel |

---

## 2. Grid System

### Vertical Grid (1080px base)

| # | Position | Element |
|---|----------|---------|
| 1 | y=0 to y=1 | Top orange accent line |
| 2 | y=1 to y=2 | Secondary top accent line |
| 3 | y=2 to y=28 | Top bar (clock, date, controls) |
| 4 | y=28 to y=1012 | Main content area |
| 5 | y=1012 to y=1076 | Bottom section |
| 6 | y=1076 to y=1080 | (edge) |

### Horizontal Grid (1920px base)

| # | Position | Element |
|---|----------|---------|
| 1 | x=0 to x=200 | Left Sidebar |
| 2 | x=200 to x=201 | Border divider |
| 3 | x=201 to x=1441 | Center Area |
| 4 | x=1441 to x=1442 | Border divider |
| 5 | x=1442 to x=1682 | Right Panel |
| 6 | x=1682 to x=1920 | (right margin) |

### Core Center Position

AI Core center is positioned at:
- **X:** 50% of Center Area width + 200px (sidebar offset)
- **Y:** 50% of total viewport height − 20px (slight upward bias)

---

## 3. Panel Dimensions

### Fixed & Relative Sizes (1920×1080)

| Element | Width | Height | Notes |
|---------|-------|--------|-------|
| Total Window | 1920px | 1080px | Fullscreen |
| Top Bar | 1920px | 28px | — |
| Left Sidebar | 200px | 1012px | Content area height |
| Center Area | 1441px−201px = 1240px | 1012px | From sidebar edge to right panel |
| Right Panel | 240px | 1012px | — |
| Bottom Section | 1920px | 64px | — |
| AI Core | 260px × 260px | — | Center of center area |
| Core Hotspot | 36px × 36px | — | White center dot |
| Core Inner Glow | 83px × 83px | — | Orange gradient sphere |
| Outer Corona | 624px × 624px | — | Faint ambient glow |
| Ring 1 | 221px diameter | 1.2px | Outer orbit ring |
| Ring 2 | 169px diameter | 0.8px | Inner counter-rotating ring |
| Ring 3 | 195px diameter | 0.6px | Listening mode ring (blue) |
| Ring 4 | 117px diameter | 1.0px | Innermost bright ring |
| Pulse Ring 1 | 91px → 338px | 1.0px | Expanding ring animation |
| Pulse Ring 2 | 91px → 338px | 0.6px | Secondary pulse (delayed) |
| Mode Label | Auto | 14px | Text below core |
| Voice Waveform | 400px × 60px | — | Center, below mode label |
| Subtitle Panel | 500px × 40px | — | Below waveform |

---

## 4. Sidebar Specification

### Structure

```
┌──────────────────────┐
│  ┌──┐                │  ← topMargin: 20px
│  │J │ JARVIS         │     Logo area (60px height)
│  └──┘ AI ASSISTANT   │
│──────────────────────│  ← divider at y=90px
│                      │
│  ◉ Conversation      │  ← active: orange accent
│  ▦ Memory             │
│  ⚙ Automation        │
│  ◈ Files              │
│  ⚡ Settings          │
│                      │
│                      │
│  Status              │  ← bottom: 16px from edge
│  ● Net  ● Mic  ● Spk │
└──────────────────────┘
```

### Dimensions

| Element | Value |
|---------|-------|
| Panel Width | 200px |
| Panel Color | rgba(8, 6, 5, 0.85) |
| Right Border | 1px, rgba(255, 140, 26, 0.08) |
| Logo Padding Left | 20px |
| Logo Icon Size | 32px × 32px |
| Logo Icon Radius | 8px |
| Logo Icon Color | rgba(255, 140, 26, 0.12) bg, #ff8c1a text |
| Logo Icon Border | 1px, rgba(255, 140, 26, 0.15) |
| JARVIS Text Left | 64px from left edge |
| JARVIS Font Size | 16px |
| JARVIS Letter Spacing | 3px |
| AI ASSISTANT Font Size | 8px |
| AI ASSISTANT Letter Spacing | 4px |
| Divider | 1px, rgba(255, 140, 26, 0.06), 20px margins |
| Nav Item Height | 40px |
| Nav Item Radius | 8px |
| Nav Item Left Margin | 12px |
| Nav Item Right Margin | 12px |
| Nav Item Hover BG | rgba(255, 140, 26, 0.08) |
| Nav Item Active Indicator | 3px wide, #ff8c1a, left side |
| Nav Icon Size | 14px |
| Nav Label Size | 12px |
| Nav Label Letter Spacing | 1px |
| Status Section Bottom | 16px from panel bottom |
| Status Dot Size | 5px |
| Status Label Size | 8px |
| Status Font | Consolas |
| Active Dot Color (Net) | #00ff88 |
| Active Dot Color (Mic) | #33aaff |
| Active Dot Color (Spk) | #ff8c1a |
| Inactive Dot Color | #333333 |

### Color States

| State | Background | Icon Color | Label Color |
|-------|-----------|------------|-------------|
| Default (inactive) | transparent | #665544 | #776655 |
| Hover | rgba(255,140,26,0.08) | #cc9966 | #aa9988 |
| Active | rgba(255,140,26,0.08) | #ff8c1a | #e8d5c4 |

---

## 5. AI Core Specification

### Layer Stack (bottom to top)

```
Layer 0: Outermost Ambient Corona
  └─ Size: 624px × 624px (2.4× parent)
  └─ Opacity: glow × 0.15
  └─ Gradient: coreColor(0.15) → coreColor(0.04) → transparent
  └─ Animation: pulsing with glow oscillation

Layer 1: Outer Glow Ring
  └─ Size: 416px × 416px (1.6× parent)
  └─ Opacity: glow × 0.5
  └─ Gradient: coreColor(0.3) → coreColor(0.06) → transparent

Layer 2: Mid Glow Ring
  └─ Size: 286px × 286px (1.1× parent)
  └─ Opacity: glow × 0.6
  └─ Gradient: coreColor(0.5) → coreColor(0.08) → transparent

Layer 3: Outer Orbit Ring (Ring 1)
  └─ Size: 221px × 221px (0.85× parent)
  └─ Border: 1.2px, rgba(coreColor, 0.2 × glow)
  └─ Rotation: 12s/cycle (idle), 4s (speaking), 2.5s (thinking)
  └─ Direction: clockwise

Layer 4: Inner Orbit Ring (Ring 2)
  └─ Size: 169px × 169px (0.65× parent)
  └─ Border: 0.8px, rgba(coreColor, 0.25 × glow)
  └─ Rotation: counter-clockwise, 1.3× speed of Ring 1

Layer 5: Listening Ring (Ring 3)
  └─ Size: 195px × 195px (0.75× parent)
  └─ Border: 0.6px, rgba(51, 170, 255, 0.15 × glow)
  └─ Visible: only in "listening" mode
  └─ Rotation: 4s/cycle

Layer 6: Innermost Ring (Ring 4)
  └─ Size: 117px × 117px (0.45× parent)
  └─ Border: 1.0px, rgba(coreColor, 0.35 × glow)
  └─ Rotation: 0.7× speed of Ring 1
  └─ Inner sub-ring: 0.82× size, 0.4px border

Layer 7: Hexagonal Texture
  └─ Size: 125px × 125px (0.48× parent)
  └─ Rendering: Canvas 2D
  └─ Hex radius: 4.5% of texture size
  └─ Line color: rgba(coreColor, 0.5)
  └─ Line width: 0.5px
  └─ Opacity: 0.12 + 0.08 × glow

Layer 8: Inner Glow Sphere (Core Hotspot)
  └─ Size: 83px × 83px (0.32× parent)
  └─ Gradient: lighter(coreColor, 1.6) → coreColor → darker(coreColor, 1.3) → #100500
  └─ Opacity: 0.9 × (0.8 + 0.2 × pulse)

Layer 9: Bright Center Hotspot
  └─ Size: 36px × 36px (0.14× parent)
  └─ Gradient: #ffffff → lighter(coreColor, 1.4) → transparent
  └─ Opacity: 0.65 × (0.8 + 0.2 × pulse)

Layer 10: Upper-Left Glare
  └─ Size: 130px × 130px (0.5× parent)
  └─ Gradient: rgba(255,217,102, 0.35×glow) → rgba(coreColor, 0.1) → transparent
  └─ Opacity: glow × 0.55

Layer 11: Bottom-Right Reflection
  └─ Size: 91px × 91px (0.35× parent)
  └─ Gradient: transparent → rgba(coreColor, 0.12×glow)
  └─ Opacity: glow × 0.3

Layer 12: Expanding Pulse Ring 1
  └─ Initial size: 91px (0.35× parent)
  └─ Final size: 338px (1.3× parent)
  └─ Border: 1.0px, rgba(coreColor, glow × 0.35)
  └─ Duration: 2200ms expand, 600ms pause
  └─ Opacity: 0.4 → 0.0 during expansion

Layer 13: Expanding Pulse Ring 2
  └─ Same as Pulse Ring 1 but 1100ms delay
  └─ Border: 0.6px, rgba(coreColor, glow × 0.20)

Layer 14: Orbiting Lights (Outer Set, 6)
  └─ Orbit radii: 20%, 27%, 34%, 41%, 48%, 55% of parent
  └─ Dot size: 2-4px
  └─ Color: lighter(coreColor, 1.3)
  └─ Opacity: 0.4-0.8 pulsing
  └─ Direction: alternating per light
  └─ Speed: varies (0.5-1.5× base)

Layer 15: Orbiting Lights (Inner Set, 4)
  └─ Orbit radii: 12%, 16%, 20%, 24% of parent
  └─ Dot size: 1.5-3px
  └─ Color: #ffffff
  └─ Opacity: 0.5-0.8 pulsing faster
  └─ Direction: alternating, 1.5× speed
```

### Core Color by Mode

| Mode | Core Color | Hex | Glow Target |
|------|-----------|-----|-------------|
| Idle | Orange | #ff8c1a | 0.45 |
| Listening | Blue | #33aaff | 0.65 |
| Thinking | Gold | #ffd700 | 0.55 |
| Speaking | Orange | #ff8c1a | 0.60 |
| Error | Red | #ff3355 | 0.70 |
| Offline | Gray | #444444 | 0.15 |

---

## 6. Right Panel Specification

### Structure

```
┌──────────────────────────┐
│ JARVIS                   │  ← 18px top, 18px left
│ AI ASSISTANT             │  ← 42px top, 20px left
│──────────────────────────│  ← divider at 70px
│ CORE STATE               │  ← 84px top, 18px left
│ ┌──────────────────────┐ │
│ │ ● Idle    [ElevenLabs]│ │  ← 100px top, 16px margins
│ │   Qwen 2.5 3B        │ │     52px height, 8px radius
│ └──────────────────────┘ │
│ QUICK STATUS             │  ← 168px top, 18px left
│ ┌──────────────────────┐ │
│ │ CPU       45% [██░░░]│ │  ← 184px top
│ │ RAM       67% [████░]│ │     40px height, 6px spacing
│ │ GPU       23% [██░░░]│ │
│ └──────────────────────┘ │
│                          │
│ ┌──────────────────────┐ │
│ │ CURRENT TASK         │ │  ← bottom: 16px
│ │ "Processing..."      │ │     40px height (when visible)
│ └──────────────────────┘ │
└──────────────────────────┘
```

### Dimensions

| Element | Value |
|---------|-------|
| Panel Width | 240px |
| Panel Color | rgba(8, 6, 5, 0.85) |
| Left Border | 1px, rgba(255, 140, 26, 0.08) |
| JARVIS Header Size | 18px, bold, letter-spacing 3px |
| AI ASSISTANT Subtitle | 9px, letter-spacing 4px |
| Header Top Margin | 18px |
| Header Left Margin | 18px |
| Section Label Size | 7px, letter-spacing 3px |
| Core State Card Height | 52px |
| Core State Card Radius | 8px |
| Core State Card BG | rgba(255, 255, 255, 0.03) |
| Core State Card Border | 1px, rgba(255, 140, 26, 0.10) |
| State Dot Size | 8px |
| State Label Size | 11px, bold |
| Model Name Size | 8px, Consolas |
| Provider Badge Width | 60px |
| Provider Badge Height | 20px |
| Provider Badge Radius | 4px |
| Provider Badge BG | rgba(255, 140, 26, 0.06) |
| Provider Badge Text | 7px, Consolas |
| Status Card Height | 40px |
| Status Card Radius | 6px |
| Status Card Left Accent | 2px wide |
| Status Card Label Size | 7px |
| Status Card Value Size | 10px, DemiBold, Consolas |
| Progress Bar Width | 40px |
| Progress Bar Height | 3px |
| Progress Bar Radius | 1.5px |
| Task Panel Bottom Margin | 16px |
| Task Panel Border Radius | 6px |
| Task Label Size | 6px, letter-spacing 2px |
| Task Text Size | 9px, Consolas |

### Status Card Colors

| Card | Accent Color | Progress Color |
|------|-------------|----------------|
| CPU | #33aaff | #33aaff |
| RAM | #00ff88 | #00ff88 |
| GPU | #ffd700 | #ffd700 |

---

## 7. Bottom Section Specification

### Structure

```
┌──────────────────────────────────────────────────────────────────────┐
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│ │ ◉       │ │ ◈       │ │ ▣       │ │ ◎       │ │ ▬       │  │
│ │ ALWAYS  │ │ CHROME   │ │ VS CODE  │ │ FLOATING │ │ TASKBAR  │  │
│ │ACCESSIBLE│ │          │ │          │ │ ORB      │ │          │  │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                       ┌──────────┐ │
│                                                       │ VOICE    │ │
│                                                       │ WAVEFORM │ │
│                                                       │ ──────   │ │
│                                                       └──────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### Dimensions

| Element | Value |
|---------|-------|
| Section Height | 64px |
| Section Color | rgba(8, 6, 5, 0.9) |
| Top Border | 1px, rgba(255, 140, 26, 0.06) |
| Left Padding | 20px |
| Preview Card Width | 100px |
| Preview Card Height | 40px (48px − 8px padding) |
| Preview Card Radius | 6px |
| Preview Card Default BG | rgba(255, 255, 255, 0.02) |
| Preview Card Hover BG | rgba(255, 140, 26, 0.06) |
| Preview Card Default Border | 1px, rgba(255, 255, 255, 0.04) |
| Preview Card Hover Border | 1px, rgba(255, 140, 26, 0.10) |
| Preview Icon Size | 16px |
| Preview Label Size | 7px, letter-spacing 1px |
| Card Spacing | 20px |
| Voice Mini Section Width | 160px |
| Voice Mini Label Size | 6px, letter-spacing 2px |

### Preview Card Accent Colors

| Card | Accent Color |
|------|-------------|
| ALWAYS ACCESSIBLE | #ff8c1a |
| CHROME | #33aaff |
| VS CODE | #00ff88 |
| FLOATING ORB | #ffd700 |
| TASKBAR | #ff8c1a |

---

## 8. Top Bar Specification

### Structure

```
┌───────────────────────────────────────────────────────────┐
│ 14:30:25    Monday, July 24, 2026            [−] [□] [✕] │
└───────────────────────────────────────────────────────────┘
```

### Dimensions

| Element | Value |
|---------|-------|
| Bar Height | 28px |
| Clock Left Margin | 24px |
| Clock Size | 12px, Consolas |
| Clock Color | #cfc3ba, opacity 0.6 |
| Date Left Margin | 90px from left |
| Date Size | 8px, Segoe UI |
| Date Color | #8f837b, opacity 0.4 |
| Control Button Size | 22px × 22px, circular |
| Control Button Spacing | 14px |
| Control Button Right Margin | 16px |
| Control Button Default BG | transparent |
| Control Button Hover BG | rgba(255, 140, 26, 0.15) |
| Close Button Hover BG | rgba(255, 26, 26, 0.20) |
| Control Icon Color | rgba(255, 140, 26, 0.50) |
| Top Accent Line 1 | 1px, #57320B, opacity 0.85 |
| Top Accent Line 2 | 1px, #120b04, at y=1px |

---

## 9. Padding & Margins

### Unified Spacing System

| Token | Value | Usage |
|-------|-------|-------|
| space-4 | 4px | Between nav items, status rows |
| space-6 | 6px | Between status cards |
| space-8 | 8px | Inside cards, badge padding |
| space-10 | 10px | Between waveform bars |
| space-12 | 12px | Nav icon to label, card left accent |
| space-14 | 14px | Window control spacing |
| space-16 | 16px | Panel margins, card padding |
| space-18 | 18px | Header margins, section titles |
| space-20 | 20px | Logo padding, bottom section padding |
| space-24 | 24px | Clock left margin, section headers |
| space-28 | 28px | Top bar height |
| space-36 | 36px | Gap: core → waveform |
| space-40 | 40px | Preview card height, status card height |
| space-48 | 48px | Bottom preview card height |
| space-52 | 52px | Core state card height |
| space-60 | 60px | Logo area height |
| space-64 | 64px | Bottom section height |
| space-90 | 90px | Sidebar divider position |
| space-100 | 100px | Core state card top position |
| space-104 | 104px | Nav items top position |
| space-168 | 168px | Quick status top position |
| space-184 | 184px | Status cards top position |
| space-200 | 200px | Sidebar width |
| space-240 | 240px | Right panel width |
| space-260 | 260px | AI Core size |
| space-400 | 400px | Waveform width |
| space-500 | 500px | Subtitle panel width |

---

## 10. Border Radius

| Element | Radius | Notes |
|---------|--------|-------|
| Sidebar Logo Icon | 8px | Square with rounded corners |
| Nav Items | 8px | Full item rectangle |
| Active Indicator | 1.5px | Left bar indicator |
| Core State Card | 8px | Right panel cards |
| Status Cards | 6px | CPU/RAM/GPU cards |
| Provider Badge | 4px | Top-right badge |
| Progress Bar | 1.5px | Thin progress indicator |
| Subtitle Panel | 8px | Center subtitle box |
| Preview Cards | 6px | Bottom section cards |
| Task Panel | 6px | Bottom of right panel |
| Window Controls | 50% | Circular buttons |
| Pulse Rings | 50% | Expanding animated rings |
| AI Core Glow Layers | 50% | All circular glow elements |
| Orbiting Light Halos | 50% | Tiny glow around lights |

---

## 11. Glassmorphism Settings

### Sidebar

| Property | Value |
|----------|-------|
| Background | rgba(8, 6, 5, 0.85) |
| Blur | 16px (if available) |
| Border Right | 1px, rgba(255, 140, 26, 0.08) |
| No direct backdrop blur in QML | Use semi-transparent RGBA |

### Right Panel

| Property | Value |
|----------|-------|
| Background | rgba(8, 6, 5, 0.85) |
| Blur | 16px |
| Border Left | 1px, rgba(255, 140, 26, 0.08) |

### Bottom Section

| Property | Value |
|----------|-------|
| Background | rgba(8, 6, 5, 0.90) |
| Blur | 16px |
| Border Top | 1px, rgba(255, 140, 26, 0.06) |

### Subtitle Panel

| Property | Value |
|----------|-------|
| Background | rgba(5, 6, 7, 0.70) |
| Blur | 8px |
| Border | 1px, rgba(255, 140, 26, 0.12) |

### Status & Core Cards

| Property | Value |
|----------|-------|
| Background | rgba(255, 255, 255, 0.03) |
| Border | 1px, rgba(255, 140, 26, 0.06–0.10) |
| Left Accent | 2px solid accent color |

---

## 12. Shadow & Glow Settings

### AI Core Glow Layers

| Layer | Spread | Opacity | Falloff |
|-------|--------|---------|---------|
| Outermost Corona | 2.4× core | 0.15 × glow | Gradual to edge |
| Outer Glow Ring | 1.6× core | 0.5 × glow | Center to 35% |
| Mid Glow Ring | 1.1× core | 0.6 × glow | Center to 40% |
| Ring Glows | Ring width + 4px | 0.15 | Soft outer glow |
| Pulse Ring Glow | Expanding | 0.4 → 0.0 | Fades during expansion |

### Orbital Light Glow

| Property | Value |
|----------|-------|
| Glow Size | 3× dot diameter |
| Glow Border | 0.3px |
| Glow Color | rgba(coreColor, 0.15) |
| Max Opacity | 0.5 |

### Particle Glow

| Property | Value |
|----------|-------|
| Glow Radius | 2× particle size |
| Glow Opacity | particle opacity × 0.3 |
| Only for | opacity > 0.3 AND size > 1.5px |

### Drop Shadows (simulated via gradients)

All shadows are rendered using radial gradients rather than true CSS drop shadows, since QML's canvas rendering does not support native drop-shadow for Canvas-drawn elements.

---

## 13. Particle System Specification

### Core Parameters

| Parameter | Value |
|-----------|-------|
| Particle Count | 800 (configurable up to 3000) |
| Render Mode | Canvas 2D (GPU) |
| Frame Rate | 60 FPS |
| Update Interval | 16ms |

### Particle Properties

| Property | Range | Distribution |
|----------|-------|--------------|
| Initial X | 0 → canvas width | Uniform random |
| Initial Y | 0 → canvas height | Uniform random |
| Velocity X | −0.15 → +0.15 | Uniform random |
| Velocity Y | −0.15 → +0.15 | Uniform random |
| Size | 0.3px → 2.5px | Uniform random |
| Phase | 0 → 2π | Uniform random |
| Orbital Tendency | 0.2 → 1.0 | Uniform random |
| Layer | 0, 1, 2 (BG, Mid, FG) | Uniform random (33% each) |
| Brightness | 0.5 → 1.0 | Uniform random |

### Layer System

| Layer | Depth Opacity | Visual Depth |
|-------|--------------|--------------|
| 0 (BG) | 0.30× | Farthest, slowest response |
| 1 (Mid) | 0.65× | Middle depth |
| 2 (FG) | 1.00× | Closest, fastest response |

### Mode Behavior

#### Idle Mode
- **Movement:** Gentle drift in random directions
- **Convergence:** Very slow pull toward center (only when dist > 30% width)
- **Opacity:** 0.10–0.25, slow sinusoidal pulsing (0.4 Hz)
- **Color:** #ff7b00 (warm orange)
- **Size:** Base size, no modulation

#### Listening Mode
- **Movement:** Strong attraction to center + gentle orbital component
- **Opacity:** 0.20–0.55, faster pulsing (2.5 Hz)
- **Color:** Blue shift — mixes from orange → blue based on time
  - Formula: `blueMix = min(1.0, 0.3 + 0.7 × (0.5 + 0.5 × sin(t × 0.5)))`
  - R: 0.2 + 0.8 × (1 − blueMix)
  - G: 0.4 + 0.5 × (1 − blueMix)
  - B: 0.7 + 0.3 × blueMix
- **Size:** Base × (1.0 + 0.5 × modulation)

#### Thinking Mode
- **Movement:** Fast orbital motion + tight convergence
- **Opacity:** 0.15–0.50, fast pulsing (3.5 Hz)
- **Color:** #ffd700 (gold)
- **Size:** Base × (0.8 + 0.6 × modulation)

#### Speaking Mode
- **Movement:** Voice-driven radial waves (4 lobes)
  - Formula: `wave = sin(angle × 4 + t × 4 + energy × 8) × (0.2 + 0.8 × energy)`
- **Opacity:** 0.15 + brightness × 0.7 × modulation
- **Color:** Orange brightness scales with energy: `rgb(1.0, 0.5 + 0.3×energy, 0.0)`
- **Size:** Base × (0.8 + 1.2 × energy × modulation)

#### Error Mode
- **Movement:** Chaotic random bursts
- **Opacity:** 0.20–0.70 (random)
- **Color:** #ff3355 (red)
- **Size:** Base × (0.8 + 0.8 × random)

#### Offline Mode
- **Movement:** Almost still, very slow drift
- **Opacity:** 0.02–0.06
- **Color:** #666666 (gray)
- **Size:** Base size

### Particle Glow
- When opacity > 0.3 AND size > 1.5px: draw secondary circle at 2× radius with opacity × 0.3

---

## 14. Ring Construction

### Ring Rendering Method
All rings are rendered using QML `Rectangle` elements with `radius: width / 2` and `border.width` / `border.color` properties. No Canvas is used for rings (to maintain crisp anti-aliasing).

### Ring Parameters

| Ring | Diameter (×parent) | Border Width | Border Color | Rotation Speed | Direction |
|------|-------------------|-------------|--------------|----------------|-----------|
| Ring 1 (Outer) | 0.85× | 1.2px | rgba(coreColor, 0.20×glow) | 1.0× base | CW |
| Ring 2 (Inner) | 0.65× | 0.8px | rgba(coreColor, 0.25×glow) | 1.3× base | CCW |
| Ring 3 (Listening) | 0.75× | 0.6px | rgba(51,170,255, 0.15×glow) | Variable | CW |
| Ring 4 (Innermost) | 0.45× | 1.0px | rgba(coreColor, 0.35×glow) | 0.7× base | CW |
| Ring 4 Sub-ring | 0.82× of Ring 4 | 0.4px | rgba(coreColor, 0.12) | Same as Ring 4 | CW |
| Pulse Ring 1 | 0.35→1.3× | 1.0px | rgba(coreColor, 0.35×glow) | Expanding | N/A |
| Pulse Ring 2 | 0.35→1.3× | 0.6px | rgba(coreColor, 0.20×glow) | Expanding (delayed) | N/A |

### Rotation Speeds by Mode

| Mode | Ring 1 Duration | Ring 2 Duration | Ring 3 Duration | Ring 4 Duration |
|------|----------------|----------------|----------------|----------------|
| Idle | 12s | 9.2s | Hidden | 17.1s |
| Listening | 6s | 4.6s | 4s | 8.6s |
| Thinking | 2.5s | 1.9s | Hidden | 3.6s |
| Speaking | 4s | 3.1s | Hidden | 5.7s |

### Pulse Ring Animation

```
Pulse Ring 1 (continuous loop):
  [0ms → 2200ms]:    Width grows 0.35× → 1.3×, opacity 0.4 → 0.0
  [2200ms → 2800ms]: Pause (invisible)
  [2800ms]:          Reset to 0.35×, opacity 0.4 → repeat

Pulse Ring 2 (continuous loop, 1100ms delayed):
  [0ms → 1100ms]:    Invisible (paused)
  [1100ms → 3300ms]: Width grows 0.35× → 1.3×, opacity 0.3 → 0.0
  [3300ms → 3900ms]: Pause (invisible)
  [3900ms]:          Reset → repeat
```

---

## 15. Typography

### Font Family Hierarchy

| Usage | Primary Font | Fallback |
|-------|-------------|----------|
| UI Labels, Headings | Segoe UI | Arial, sans-serif |
| Data, Metrics, Status | Consolas | Courier New, monospace |
| Clock | Consolas | monospace |

### Font Sizes & Weights

| Element | Size | Weight | Letter Spacing | Font |
|---------|------|--------|----------------|------|
| JARVIS Brand (Sidebar) | 16px | Bold | 3px | Segoe UI |
| JARVIS Brand (Right Panel) | 18px | Bold | 3px | Segoe UI |
| AI ASSISTANT Subtitle | 8–9px | Normal | 4px | Segoe UI |
| Nav Item Label | 12px | Normal | 1px | Segoe UI |
| Nav Icon | 14px | Normal | Normal | Segoe UI |
| Section Title (CORE STATE) | 7px | Normal | 3px | Segoe UI |
| Section Title (QUICK STATUS) | 7px | Normal | 3px | Segoe UI |
| State Name | 11px | Bold | Normal | Segoe UI |
| Model Name | 8px | Normal | Normal | Consolas |
| Status Card Label | 7px | Normal | 1px | Segoe UI |
| Status Card Value | 10px | DemiBold | Normal | Consolas |
| Provider Badge | 7px | Normal | Normal | Consolas |
| Task Section Label | 6px | Normal | 2px | Segoe UI |
| Task Text | 9px | Normal | Normal | Consolas |
| Clock | 12px | Normal | Normal | Consolas |
| Date | 8px | Normal | Normal | Segoe UI |
| Mode Label | 10px | Bold | 4px | Segoe UI |
| Subtitle Text | 11px | Normal | Normal | Segoe UI |
| Preview Card Label | 7px | Normal | 1px | Segoe UI |
| Status Label (Sidebar) | 8px | Normal | 2px | Segoe UI |
| Status Dot Labels | 8px | Normal | Normal | Consolas |
| Voice Mini Label | 6px | Normal | 2px | Segoe UI |
| Window Controls | 10–14px | Bold | Normal | Segoe UI |

### Text Colors

| Usage | Color | Opacity |
|-------|-------|---------|
| Primary Brand Text | #e8d5c4 | 0.9 |
| Secondary Text | #e0d5ca | 1.0 |
| Tertiary Text | #998877 | 1.0 |
| Muted Text | #776655 | 1.0 |
| Dim Text | #665544 | 1.0 |
| Faint Text | #555544 | 1.0 |
| Orange Accent Text | #ff8c1a | variable |
| Subtitle Text | #e0c4a6 | 1.0 |
| Clock Text | #cfc3ba | 0.6 |
| Date Text | #8f837b | 0.4 |
| Status Value | #e0e0e0 | 1.0 |
| Badge Text | #aa8866 | 1.0 |

---

## 16. Color Palette

### Brand Colors

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| JARVIS Orange | #ff8c1a | rgb(255, 140, 26) | Primary accent, active states |
| JARVIS Orange Light | #ffa64d | rgb(255, 166, 77) | Hover states |
| JARVIS Orange Dark | #cc6600 | rgb(204, 102, 0) | Borders, muted accents |
| JARVIS Orange Dim | #57320B | rgb(87, 50, 11) | Top accent line |

### Mode Colors

| Name | Hex | RGB | Mode |
|------|-----|-----|------|
| Listening Blue | #33aaff | rgb(51, 170, 255) | Listening mode accent |
| Thinking Gold | #ffd700 | rgb(255, 215, 0) | Thinking mode accent |
| Speaking Orange | #ff8c1a | rgb(255, 140, 26) | Speaking mode accent |
| Error Red | #ff3355 | rgb(255, 51, 85) | Error mode accent |
| Offline Gray | #444444 | rgb(68, 68, 68) | Offline mode |

### Status Indicator Colors

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Online Green | #00ff88 | rgb(0, 255, 136) | Active status dots |
| Mic Blue | #33aaff | rgb(51, 170, 255) | Mic status |
| Speaker Orange | #ff8c1a | rgb(255, 140, 26) | Speaker status |
| Offline Dot | #333333 | rgb(51, 51, 51) | Inactive status |

### Background Colors

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Pure Black | #000000 | rgb(0, 0, 0) | Window background |
| Deep Space | #010101 | rgb(1, 1, 1) | Outer gradient |
| Dark Void | #030506 | rgb(3, 5, 6) | Mid gradient |
| Warm Dark | #0b0805 | rgb(11, 8, 5) | Center gradient |
| Panel Dark | rgba(8, 6, 5, 0.85) | — | Sidebar/panel backgrounds |
| Panel Darker | rgba(8, 6, 5, 0.90) | — | Bottom section |
| Card BG | rgba(255, 255, 255, 0.02–0.03) | — | Status/core cards |
| Subtitle BG | rgba(5, 6, 7, 0.70) | — | Subtitle box |
| Orange Glow | #4a2100 → transparent | — | Ambient glow field |
| Blue Glow (Listening) | #001a33 → transparent | — | Blue ambient glow |

### Gradient Definitions

#### Background Gradient (radial, center-biased)
```
Stop 0.0:  #0b0805  (warm center)
Stop 0.5:  #030506  (cool void)
Stop 1.0:  #010101  (deep space)
```

#### Orange Ambient Glow (radial)
```
Stop 0.0:  #4a2100  (dense orange)
Stop 0.4:  #160900  (faint orange)
Stop 1.0:  transparent
```

#### Blue Ambient Glow (radial, listening mode only)
```
Stop 0.0:  #001a33  (dense blue)
Stop 0.5:  #000d1a  (faint blue)
Stop 1.0:  transparent
```

---

## 17. Animation Specification

### Mode Transition Animations

| Transition | Property | Duration | Easing |
|-----------|----------|----------|--------|
| Core Color Change | Color | 500ms | OutCubic |
| Mode Label Fade | Opacity | 400ms | Linear |
| Waveform Fade | Opacity | 500ms | OutCubic |
| Subtitle Fade | Opacity | 500ms | Linear |
| Panel Opacity | Opacity | 300ms | Linear |
| Glow Intensity | Glow | 2400ms loop | InOutSine |
| Pulse Animation | Width/Height | 2200ms loop | InSine |
| Pulse Ring 2 | Width/Height | 2200ms + 1100ms delay | InSine |

### Continuous Animations

#### Idle Mode
- Core rotation: 12s/cycle (slow, calm)
- Breathing pulse: 3.2s cycle, scale 1.0 → 1.045
- Glow oscillation: 2.4s cycle, 0.35 → 0.55
- Particles: 0.4Hz sinusoidal

#### Listening Mode
- Core rotation: 6s/cycle (faster)
- Pulse: 900ms cycle, scale 1.0 → 1.18 → 1.0 + 300ms pause
- Blue listening ring: 4s/cycle
- Particles: 2.5Hz, blue shift
- Blue ambient glow: fade in 600ms

#### Thinking Mode
- Core rotation: 2.5s/cycle (very fast)
- Pulse: 650ms cycle, scale 1.0 → 1.08 → 1.0 + 150ms pause
- Particles: 3.5Hz, orbital motion
- Gold color transition

#### Speaking Mode
- Core rotation: 4s/cycle
- Pulse: 750ms cycle, scale 1.0 → 1.12 → 1.0
- Particles: 5Hz wave-synchronized
- Waveform: 8–10Hz bar animation

### Hover Animations

| Element | Property | Duration | Easing |
|---------|----------|----------|--------|
| Nav Items | Background color | 150ms | Linear |
| Nav Items | Text color | 150ms | Linear |
| Active Indicator | Opacity | 200ms | Linear |
| Preview Cards | Background color | 150ms | Linear |
| Preview Cards | Border color | 150ms | Linear |
| Window Controls | Background color | 150ms | Linear |
| Floating Orb | Width/Opacity | 300ms | OutCubic |

### Orb Animation (FloatingOrb)
- Scale breathing: 1.0 → 1.06, 1800ms cycle, InOutSine
- Outer glow: width 1.6× → 2.0× on hover, 300ms

---

## 18. Component Hierarchy & Z-Index

### Z-Index Stack (bottom to top)

```
Z=0:   Particle Field Canvas
Z=1:   AI Core (all layers)
Z=2:   Mode Label, Voice Waveform, Subtitle Panel
Z=3:   Left Sidebar, Right Panel (over content edges)
Z=4:   Bottom Section
Z=5:   Top Bar, Window Controls
Z=10:  Floating Orb Context Menu
Z=100: Orb Menu (when visible)
```

### QML Component Tree

```
Window "fullscreenWindow"
├── Background Rectangle (#000000)
│   ├── Ambient Gradient (radial)
│   ├── Orange Glow Field (radial)
│   └── Blue Ambient Field (listening mode only)
├── Top Accent Lines (2×)
├── Top Bar (Item)
│   ├── Clock (Text)
│   ├── Date (Text)
│   └── Window Controls (Row)
│       ├── Minimize Button (→ Floating Orb)
│       ├── Maximize Button
│       └── Close Button (→ Quit)
├── Main Content (Item)
│   ├── Left Sidebar (Rectangle)
│   │   ├── Right Border (1px)
│   │   ├── Logo Area (Item)
│   │   │   ├── Logo Icon (Rectangle + Text "J")
│   │   │   ├── JARVIS Text
│   │   │   └── AI ASSISTANT Subtitle
│   │   ├── Divider
│   │   ├── Navigation Column
│   │   │   └── NavItem Repeater
│   │   │       ├── Active Indicator
│   │   │       ├── Icon (Text)
│   │   │       ├── Label (Text)
│   │   │       └── MouseArea
│   │   └── Status Section (Column)
│   │       └── Status Dot Row (Repeater)
│   ├── Center Area (Item)
│   │   ├── ParticleField (Canvas)
│   │   ├── AiCore (Item)
│   │   │   ├── Outermost Corona (Rectangle)
│   │   │   ├── Outer Glow Ring (Rectangle)
│   │   │   ├── Mid Glow Ring (Rectangle)
│   │   │   ├── Ring 1-4 (Rectangles)
│   │   │   ├── Hex Texture (Canvas)
│   │   │   ├── Inner Glow Sphere (Rectangle)
│   │   │   ├── Core Hotspot (Rectangle)
│   │   │   ├── Upper Glare (Rectangle)
│   │   │   ├── Lower Reflection (Rectangle)
│   │   │   ├── Pulse Rings (Rectangles)
│   │   │   ├── Orbiting Lights Outer (Repeater)
│   │   │   └── Orbiting Lights Inner (Repeater)
│   │   ├── Mode Label (Text)
│   │   ├── VoiceWaveform (Item)
│   │   │   ├── Mic Waveform (Row of bars)
│   │   │   ├── Assistant Waveform (Row of bars)
│   │   │   └── Center Divider
│   │   └── Subtitle Panel (Rectangle)
│   │       └── Subtitle Text
│   └── Right Panel (Rectangle)
│       ├── Left Border (1px)
│       ├── JARVIS Header
│       ├── AI ASSISTANT Subtitle
│       ├── Divider
│       ├── CORE STATE Section
│       │   ├── Section Label
│       │   └── Core State Card
│       │       ├── State Dot
│       │       ├── State Name + Model
│       │       └── Provider Badge
│       ├── QUICK STATUS Section
│       │   ├── Section Label
│       │   └── Status Cards Column
│       │       └── StatusCard (CPU, RAM, GPU)
│       │           ├── Left Accent
│       │           ├── Label + Value
│       │           └── Progress Bar
│       └── Active Task Panel
│           ├── Task Label
│           └── Task Text
├── Bottom Section (Rectangle)
│   ├── Top Border
│   ├── Preview Cards (Row)
│   │   └── PreviewItem Repeater
│   │       ├── Icon
│   │       ├── Label
│   │       └── MouseArea
│   └── Voice Mini (Item)
│       ├── VoiceWaveform
│       └── VOICE Label
├── FloatingOrb (Window)
└── EdgeDock (Window)
```

---

## 19. Window Behavior

### Startup
1. Application launches in **Fullscreen mode** by default
2. QML engine loads `main.qml`
3. Window manager starts foreground polling after 3 seconds
4. Bridge connects to backend services
5. System tray icon created (if available)

### Mode Transitions

| Trigger | From | To | Animation |
|---------|------|----|-----------|
| Escape key | Fullscreen | Floating Orb | Instant |
| Minimize click | Fullscreen | Floating Orb | Instant |
| Double-click Orb | Floating Orb | Fullscreen | Instant |
| Fullscreen app detected | Fullscreen | Floating Orb | Background poll |
| Desktop detected | Floating Orb | Fullscreen | Background poll |
| Close click | Any | Quit | — |
| Tray double-click | Any | Fullscreen | — |
| Tray single-click | Any | Floating Orb | — |

### Floating Orb Behavior
- Always-on-top frameless window
- Draggable (left mouse)
- Double-click returns to fullscreen
- Right-click opens context menu
- Pulsing breathing animation
- Hover expands size + glow
- Color changes with mode

### Edge Dock Behavior
- Hover to expand (narrow → 260px wide)
- Supports 4 positions: left, right, top, bottom
- Auto-adjusts to screen edges

### System Tray
- Icon: orange circle (22×22px)
- Menu: Show JARVIS, Floating Orb, separator, Quit
- Left-click: toggle orb
- Double-click: fullscreen

---

## 20. Responsive Behavior

### Scaling Strategy

Base resolution: **1920 × 1080**

All dimensions are calculated using a scale factor `s`:

```
scaleW = currentWidth / 1920
scaleH = currentHeight / 1080
s = min(scaleW, scaleH)
```

All pixel dimensions are multiplied by `s` and rounded.

### Minimum Dimensions

| Element | Minimum |
|---------|---------|
| Sidebar Width | 160px |
| Right Panel Width | 200px |
| Bottom Bar Height | 50px |
| AI Core Size | 120px |

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Resolution < 1280×720 | Scale down proportionally, ensure minimum touch targets (40px) |
| Resolution > 3840×2160 | Scale up proportionally, cap core at 300px |
| Ultrawide (21:9) | Center area expands, sidebar/panels maintain width |
| 4:3 Aspect Ratio | Core size clamped, panels maintain proportion |

### Window Resize Handling
- Fullscreen mode: window covers entire screen, no resize
- Floating orb: fixed 90×90 window, user-draggable
- Edge dock: auto-positions based on edge setting

---

## 21. Icon System

### Icon Recommendations

All icons should be professional SVG glyphs, 14px rendered size, with consistent stroke weight.

| Section | Icon | Unicode Fallback | Description |
|---------|------|-----------------|-------------|
| Conversation | ◉ | U+25C9 | Filled circle with dot |
| Memory | ▦ | U+25A6 | Square with diagonal fill |
| Automation | ⚙ | U+2699 | Gear |
| Files | ◈ | U+25C8 | Diamond |
| Settings | ⚡ | U+26A1 | Lightning bolt |
| Always Accessible | ◉ | U+25C9 | Target/circle |
| Chrome | ◈ | U+25C8 | Browser icon |
| VS Code | ▣ | U+25A3 | Square with cross |
| Floating Orb | ◎ | U+25CE | Bullseye |
| Taskbar | ▬ | U+25AC | Horizontal bar |

### Window Control Icons

| Control | Unicode | Description |
|---------|---------|-------------|
| Minimize | − (U+2212) | Minus sign |
| Maximize | □ (U+25A1) | Empty square |
| Close | ✕ (U+2715) | Multiplication X |

### Logo Icon
- **Shape:** Rounded rectangle with "J" letterform
- **Dimensions:** 32×32px, 8px radius
- **Colors:** rgba(255,140,26,0.12) background, #ff8c1a "J" text

### Implementation Note
For production, replace all Unicode fallback characters with proper SVG files placed in `ui/assets/icons/`. Each SVG should be 24×24px viewport, with 14px effective glyph size, #ff8c1a stroke color (or inheriting parent color), and 1.5px stroke width.

---

## 22. Implementation Checklist

### Phase 1: Foundation
- [ ] Set up QML imports (QtQuick 2.15, QtQuick.Window 2.15, QtQuick.Controls 2.15)
- [ ] Configure QSurfaceFormat (4× MSAA, vsync)
- [ ] Create responsive scaling constants (refW=1920, refH=1080)
- [ ] Implement Bridge connections for all backend state
- [ ] Set up background layers (deep space + ambient glows)

### Phase 2: Layout
- [ ] Create top bar (clock, date, window controls)
- [ ] Create left sidebar (logo, nav items, status)
- [ ] Create center area container
- [ ] Create right panel (header, cards, task)
- [ ] Create bottom section (preview cards, voice mini)
- [ ] Add border dividers between all sections
- [ ] Verify responsive scaling works

### Phase 3: AI Core
- [ ] Draw outermost ambient corona
- [ ] Draw outer and mid glow rings
- [ ] Create 4 concentric rotating rings with correct properties
- [ ] Implement hex texture via Canvas
- [ ] Draw inner glow sphere and hotspot
- [ ] Add upper-left glare and lower-right reflection
- [ ] Create 2 expanding pulse rings with staggered timing
- [ ] Implement 10 orbiting lights (6 outer + 4 inner)
- [ ] Wire mode colors and speed changes
- [ ] Test all 6 mode animations

### Phase 4: Particle System
- [ ] Convert to Canvas rendering for performance
- [ ] Initialize 800 particles with correct distributions
- [ ] Implement 3-layer depth system
- [ ] Code idle drift behavior
- [ ] Code listening attraction + blue shift
- [ ] Code thinking orbital motion
- [ ] Code speaking wave synchronization
- [ ] Code error chaos and offline stillness
- [ ] Add mouse attraction
- [ ] Optimize for 60 FPS

### Phase 5: Voice Waveform
- [ ] Create 48-bar mic waveform (blue, top)
- [ ] Create 48-bar assistant waveform (orange, bottom)
- [ ] Add glow effects to bars
- [ ] Implement smooth target-following interpolation
- [ ] Add center divider line
- [ ] Wire mode-based cross-fading

### Phase 6: Right Panel Content
- [ ] Add Core State card with animated dot
- [ ] Add provider badge
- [ ] Create CPU/RAM/GPU status cards with progress bars
- [ ] Add accent colors per card
- [ ] Implement Active Task panel with toggle visibility

### Phase 7: Bottom Section
- [ ] Create 5 preview cards with hover effects
- [ ] Add mini voice waveform section
- [ ] Implement correct spacing and alignment

### Phase 8: Polish
- [ ] Add all transition animations
- [ ] Verify all mode transitions are smooth
- [ ] Test at 1920×1080 for perfect pixel alignment
- [ ] Test at other resolutions for scaling
- [ ] Verify Floating Orb behavior
- [ ] Verify system tray integration
- [ ] Performance profiling (target: 60 FPS)

### Phase 9: Final Validation
- [ ] Side-by-side comparison with IMAGE B
- [ ] Score each category out of 10:
  - Layout: ___/10
  - Typography: ___/10
  - Spacing: ___/10
  - Lighting: ___/10
  - Particles: ___/10
  - AI Core: ___/10
  - Icons: ___/10
  - Waveforms: ___/10
  - Panels: ___/10
  - Animations: ___/10
- [ ] Overall Similarity: ___/10
- [ ] Continue refining until ALL scores ≥ 9.5/10

---

*End of Specification Document — This document serves as the single source of truth for all UI implementation decisions. No deviations from this specification are permitted without documented design review.*