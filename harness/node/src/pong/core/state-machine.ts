/**
 * Deterministic Finite State Machine and Score Management.
 * Requirement Citations:
 * - R-PONG-STATE-3: Finite state machine lifecycle, transitions, and deterministic score tracking
 * - C-PONG-GOV-9: Conformance to reliable state mutation contracts
 */

import type { GameStatePhase, ScoreState, GameConfig } from './types.js';

export class StateMachine {
  private currentPhase: GameStatePhase = 'MENU';
  private scoreState: ScoreState;
  private readonly config: GameConfig;

  constructor(config: GameConfig) {
    this.config = config;
    this.scoreState = Object.freeze({
      player1: 0,
      player2: 0,
      maxScore: config.maxScore,
      winner: null,
      rallyCount: 0,
      totalRallies: 0,
    });
  }

  /**
   * Retrieves current phase.
   */
  get phase(): GameStatePhase {
    return this.currentPhase;
  }

  /**
   * Retrieves current score state snapshot.
   */
  get score(): Readonly<ScoreState> {
    return this.scoreState;
  }

  /**
   * Starts a fresh match.
   */
  startMatch(): void {
    this.scoreState = Object.freeze({
      player1: 0,
      player2: 0,
      maxScore: this.config.maxScore,
      winner: null,
      rallyCount: 0,
      totalRallies: 0,
    });
    this.currentPhase = 'SERVING';
  }

  /**
   * Begins active gameplay rally.
   */
  startRally(): void {
    if (this.currentPhase === 'SERVING' || this.currentPhase === 'MENU') {
      this.currentPhase = 'PLAYING';
    }
  }

  /**
   * Toggles game pause state.
   */
  togglePause(): boolean {
    if (this.currentPhase === 'PLAYING') {
      this.currentPhase = 'PAUSED';
      return true;
    }
    if (this.currentPhase === 'PAUSED') {
      this.currentPhase = 'PLAYING';
      return false;
    }
    return false;
  }

  /**
   * Increments current rally hit count.
   */
  incrementRally(): void {
    if (this.currentPhase === 'PLAYING') {
      this.scoreState = Object.freeze({
        ...this.scoreState,
        rallyCount: this.scoreState.rallyCount + 1,
        totalRallies: this.scoreState.totalRallies + 1,
      });
    }
  }

  /**
   * Records a point for the specified player.
   */
  recordPoint(scoringPlayer: 'player1' | 'player2'): {
    winner: 'player1' | 'player2' | null;
    gameOver: boolean;
  } {
    const p1Score =
      scoringPlayer === 'player1'
        ? this.scoreState.player1 + 1
        : this.scoreState.player1;
    const p2Score =
      scoringPlayer === 'player2'
        ? this.scoreState.player2 + 1
        : this.scoreState.player2;

    const isP1Winner = p1Score >= this.config.maxScore;
    const isP2Winner = p2Score >= this.config.maxScore;
    const winner: 'player1' | 'player2' | null = isP1Winner
      ? 'player1'
      : isP2Winner
        ? 'player2'
        : null;

    this.scoreState = Object.freeze({
      ...this.scoreState,
      player1: p1Score,
      player2: p2Score,
      winner,
      rallyCount: 0,
    });

    if (winner !== null) {
      this.currentPhase = 'GAME_OVER';
      return { winner, gameOver: true };
    }

    this.currentPhase = 'ROUND_OVER';
    return { winner: null, gameOver: false };
  }

  /**
   * Prepares the next serve round.
   */
  prepareServe(): void {
    if (this.currentPhase === 'ROUND_OVER') {
      this.currentPhase = 'SERVING';
    }
  }

  /**
   * Resets the match state back to Menu.
   */
  resetToMenu(): void {
    this.currentPhase = 'MENU';
    this.scoreState = Object.freeze({
      player1: 0,
      player2: 0,
      maxScore: this.config.maxScore,
      winner: null,
      rallyCount: 0,
      totalRallies: 0,
    });
  }
}
