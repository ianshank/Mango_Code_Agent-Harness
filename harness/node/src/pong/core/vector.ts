/**
 * Pure functional 2D Vector mathematics module.
 * Requirement Citations:
 * - R-PONG-CORE-2: Deterministic vector operations for 2D physical simulations
 * - C-PONG-GOV-9: High-precision immutable math operations conforming to governance standards
 */

import type { Vector2D } from './types.js';

export const Vector = {
  /**
   * Creates a new 2D vector.
   */
  create(x = 0, y = 0): Vector2D {
    const nx = Number.isFinite(x) ? (x === 0 ? 0 : x) : 0;
    const ny = Number.isFinite(y) ? (y === 0 ? 0 : y) : 0;
    return Object.freeze({ x: nx, y: ny });
  },

  /**
   * Adds two vectors.
   */
  add(a: Vector2D, b: Vector2D): Vector2D {
    const rx = a.x + b.x;
    const ry = a.y + b.y;
    return Object.freeze({
      x: rx === 0 ? 0 : rx,
      y: ry === 0 ? 0 : ry,
    });
  },

  /**
   * Subtracts vector b from vector a (a - b).
   */
  subtract(a: Vector2D, b: Vector2D): Vector2D {
    const rx = a.x - b.x;
    const ry = a.y - b.y;
    return Object.freeze({
      x: rx === 0 ? 0 : rx,
      y: ry === 0 ? 0 : ry,
    });
  },

  /**
   * Multiplies a vector by a scalar.
   */
  scale(v: Vector2D, scalar: number): Vector2D {
    if (!Number.isFinite(scalar)) {
      return Object.freeze({ x: 0, y: 0 });
    }
    const rx = v.x * scalar;
    const ry = v.y * scalar;
    return Object.freeze({
      x: rx === 0 ? 0 : rx,
      y: ry === 0 ? 0 : ry,
    });
  },

  /**
   * Calculates the dot product of two vectors.
   */
  dot(a: Vector2D, b: Vector2D): number {
    return a.x * b.x + a.y * b.y;
  },

  /**
   * Calculates the squared magnitude of a vector.
   */
  magnitudeSquared(v: Vector2D): number {
    return v.x * v.x + v.y * v.y;
  },

  /**
   * Calculates the Euclidean magnitude of a vector.
   */
  magnitude(v: Vector2D): number {
    return Math.sqrt(v.x * v.x + v.y * v.y);
  },

  /**
   * Normalizes a vector to unit length (magnitude = 1).
   */
  normalize(v: Vector2D): Vector2D {
    const mag = Math.sqrt(v.x * v.x + v.y * v.y);
    if (mag === 0 || !Number.isFinite(mag)) {
      return Object.freeze({ x: 0, y: 0 });
    }
    return Object.freeze({
      x: v.x / mag,
      y: v.y / mag,
    });
  },

  /**
   * Reflects an incident vector across a surface normal.
   * R = V - 2 * (V . N) * N
   */
  reflect(v: Vector2D, normal: Vector2D): Vector2D {
    const norm = Vector.normalize(normal);
    const dotProduct = Vector.dot(v, norm);
    return Object.freeze({
      x: v.x - 2 * dotProduct * norm.x,
      y: v.y - 2 * dotProduct * norm.y,
    });
  },

  /**
   * Computes Euclidean distance between two points.
   */
  distance(a: Vector2D, b: Vector2D): number {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  },

  /**
   * Clamps vector components between minimum and maximum bounds.
   */
  clamp(
    v: Vector2D,
    minX: number,
    maxX: number,
    minY: number,
    maxY: number,
  ): Vector2D {
    return Object.freeze({
      x: Math.max(minX, Math.min(maxX, v.x)),
      y: Math.max(minY, Math.min(maxY, v.y)),
    });
  },

  /**
   * Linear interpolation between two vectors.
   */
  lerp(a: Vector2D, b: Vector2D, t: number): Vector2D {
    const factor = Math.max(0, Math.min(1, t));
    return Object.freeze({
      x: a.x + (b.x - a.x) * factor,
      y: a.y + (b.y - a.y) * factor,
    });
  },

  /**
   * Creates a directional vector from angle in radians.
   */
  fromAngle(radians: number, length = 1): Vector2D {
    return Object.freeze({
      x: Math.cos(radians) * length,
      y: Math.sin(radians) * length,
    });
  },
};
