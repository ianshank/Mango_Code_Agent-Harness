/**
 * Finite State Machine Unit Tests.
 * Requirement Citations:
 * - R-PONG-STATE-3: State transitions, score counting, and match termination
 * - C-PONG-GOV-9: Deterministic state management
 */

import { describe, it, expect } from 'vitest';
import { StateMachine } from '../../../src/pong/core/state-machine.js';
import { createGameConfig } from '../../../src/pong/core/config.js';

describe('State Machine & Score Lifecycle (R-PONG-STATE-3)', () => {
  const config = createGameConfig('classic', { maxScore: 3 });

  it('initializes in MENU state with zeroed scores', () => {
    const sm = new StateMachine(config);
    expect(sm.phase).toBe('MENU');
    expect(sm.score).toEqual({
      player1: 0,
      player2: 0,
      maxScore: 3,
      winner: null,
      rallyCount: 0,
      totalRallies: 0,
    });
  });

  it('transitions from MENU to SERVING to PLAYING', () => {
    const sm = new StateMachine(config);
    sm.startMatch();
    expect(sm.phase).toBe('SERVING');

    sm.startRally();
    expect(sm.phase).toBe('PLAYING');
  });

  it('handles pause and resume toggle correctly', () => {
    const sm = new StateMachine(config);
    sm.startMatch();
    sm.startRally();
    expect(sm.phase).toBe('PLAYING');

    const paused = sm.togglePause();
    expect(paused).toBe(true);
    expect(sm.phase).toBe('PAUSED');

    const resumed = sm.togglePause();
    expect(resumed).toBe(false);
    expect(sm.phase).toBe('PLAYING');
  });

  it('tracks rally increments during active gameplay', () => {
    const sm = new StateMachine(config);
    sm.startMatch();
    sm.startRally();

    sm.incrementRally();
    sm.incrementRally();
    expect(sm.score.rallyCount).toBe(2);
    expect(sm.score.totalRallies).toBe(2);
  });

  it('records points and transitions to GAME_OVER on match victory', () => {
    const sm = new StateMachine(config);
    sm.startMatch();
    sm.startRally();

    // Point 1
    const pt1 = sm.recordPoint('player1');
    expect(pt1.gameOver).toBe(false);
    expect(sm.phase).toBe('ROUND_OVER');
    expect(sm.score.player1).toBe(1);

    sm.prepareServe();
    expect(sm.phase).toBe('SERVING');
    sm.startRally();

    // Point 2
    sm.recordPoint('player1');
    sm.prepareServe();
    sm.startRally();

    // Point 3 -> Victory
    const pt3 = sm.recordPoint('player1');
    expect(pt3.gameOver).toBe(true);
    expect(pt3.winner).toBe('player1');
    expect(sm.phase).toBe('GAME_OVER');
    expect(sm.score.winner).toBe('player1');
  });

  it('resets state cleanly back to MENU', () => {
    const sm = new StateMachine(config);
    sm.startMatch();
    sm.startRally();
    sm.recordPoint('player2');

    sm.resetToMenu();
    expect(sm.phase).toBe('MENU');
    expect(sm.score.player2).toBe(0);
  });
});
