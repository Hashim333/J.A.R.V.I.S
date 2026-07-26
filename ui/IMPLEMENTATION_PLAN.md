# Visual Comparison & Implementation Plan: IMAGE A → IMAGE B

## Current Issues Identified

### 1. Left Sidebar / Nav
- **Current**: Tiny NavRail (48px) with text chars ("○", "□", "△"), no real icons
- **Target**: Full sidebar with JARVIS logo, proper SVG icons, navigation labels, glass effect, orange highlights, rounded corners
- **Action**: Replace NavRail with full SidebarMenu integrated as permanent rail

### 2. AI Core (Highest Priority)
- **Current**: 
  - 1-2 static concentric rings
  - No hexagonal texture
  - 1 thin orbit ring (barely visible)
  - Simple glow rectangles
  - No orbiting particles/lights
  - No energy pulses
- **Target**: 
  - Large glowing AI Core with multiple concentric rotating rings
  - Hexagonal inner texture
  - Particle emitters
  - Bloom + orange volumetric glow
  - Energy pulses
  - Tiny orbiting lights
  - Subtle depth + orange reflections
- **Action**: Complete rewrite of AiCore.qml

### 3. Right Panels
- **Current**: Thin right panel with just "JARVIS / AI ASSISTANT" text
- **Target**: 
  - AI Core States panel
  - Quick Status cards (CPU, RAM, GPU, Battery)
  - Voice Visualization
- **Action**: Complete rewrite of right panel in main.qml

### 4. Bottom Section
- **Current**: Text list in bottom bar ("ADAPTIVE UI", "REAL-TIME VOICE", etc.)
- **Target**: 
  - Always Accessible
  - Chrome Preview
  - VS Code Preview  
  - Floating Orb Preview
  - Taskbar Preview
  - Voice Visualization
- **Action**: Complete rewrite of bottom panel

### 5. Particles
- **Current**: 200 particles, simple behavior
- **Target**: High density, float, orbit, fade, pulse, react to voice/state
- **Action**: Rewrite ParticleField.qml with higher density

### 6. Lighting
- **Target**: soft bloom, orange halo, ambient glow, panel reflections, deep shadows
- **Action**: Add bloom overlay, stronger glow gradients

### 7. Icons
- **Current**: Text characters
- **Target**: Professional SVG icons
- **Action**: Add SVG icon paths

### 8. Typography
- **Target**: Match font family, weight, letter spacing, alignment
- **Action**: Standardize typography

### 9. Animations
- **Target**: Mode-specific: idle (slow breathing), listening (blue transition), thinking (fast rotation), speaking (wave-synchronized)
- **Action**: Implement mode-driven animation system

## Implementation Order
1. AiCore.qml - Complete rewrite (highest priority)
2. ParticleField.qml - Higher density, mode reactivity
3. main.qml - Full layout rewrite for left sidebar, right panels, bottom section
4. VoiceWaveform.qml - Enhanced waveform
5. NavRail.qml - Enhanced with real icons
6. SidebarMenu.qml - Enhanced glass effect
7. InfoCards.qml - Enhanced styling