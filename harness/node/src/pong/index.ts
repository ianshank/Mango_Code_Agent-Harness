/**
 * Unified Public Library Export for Pong Engine.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Dynamic config interfaces & factory
 * - R-PONG-CORE-2: 2D vector & physics simulation exports
 * - R-PONG-STATE-3: State machine exports
 * - R-PONG-INPUT-4: Input manager & drivers
 * - R-PONG-AI-5: Predictive AI opponent controller
 * - R-PONG-AUDIO-6: Audio manager & synthesis drivers
 * - R-PONG-RENDER-7: Multi-target renderers (Canvas, Terminal, Null)
 * - R-PONG-LOOP-8: Fixed-timestep accumulator loop
 * - C-PONG-GOV-9: Complete governance conformance
 */

// Core
export * from './core/types.js';
export * from './core/vector.js';
export * from './core/config.js';
export * from './core/physics.js';
export * from './core/state-machine.js';
export * from './core/game-engine.js';

// Input
export * from './input/types.js';
export * from './input/input-manager.js';
export * from './input/keyboard-driver.js';

// AI
export * from './ai/types.js';
export * from './ai/ai-opponent.js';

// Audio
export * from './audio/types.js';
export * from './audio/audio-manager.js';
export * from './audio/web-audio-driver.js';
export * from './audio/null-audio-driver.js';

// Render
export * from './render/types.js';
export * from './render/canvas-renderer.js';
export * from './render/terminal-renderer.js';
export * from './render/null-renderer.js';

// Loop
export * from './loop/game-loop.js';
